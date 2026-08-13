#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
#   "markdownify==1.2.0",
# ]
# ///

"""Confluence ページを OKF 形式の Markdown ファイルとしてダウンロードする。

環境変数 `CONFLUENCE_API_TOKEN` を使い、このスクリプトが直接Confluence REST APIを
呼んで取得する(子ページ再帰取得に対応)。

■ 環境変数
  CONFLUENCE_API_TOKEN  API トークン（必須）
  CONFLUENCE_EMAIL      メールアドレス（Confluence Cloud の場合のみ必須）
  CONFLUENCE_URL        Confluence のベース URL（--url の省略時に使用）

■ 使い方
  export CONFLUENCE_API_TOKEN=<token>
  export CONFLUENCE_EMAIL=<email>   # Cloud の場合のみ

  uv run scripts/confluence_downloader.py \\
    --url https://your-domain.atlassian.net/wiki \\
    --page-id 123456789 [--page-id 987654321 ...] [--depth 2] [-o .] [--wait 0.5]
"""

import argparse
import base64
import datetime
import html as html_lib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
from markdownify import markdownify as md

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 30
MAX_DEPTH = 50

_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')
_PAGE_ID_RE = re.compile(r"pageId=(\d+)")
_PAGES_PATH_RE = re.compile(r"/pages/(\d+)")
_RI_PAGE_RE = re.compile(r"<ri:page\b([^>]*?)/>")
_RI_TITLE_RE = re.compile(r'ri:content-title="([^"]*)"')
_RI_SPACE_RE = re.compile(r'ri:space-key="([^"]*)"')
_FILENAME_PAGE_ID_RE = re.compile(r"_(\d+)\.md$")
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def _is_cloud(base_url: str) -> bool:
    return "atlassian.net" in base_url


def html_to_markdown(html: str) -> str:
    return md(html, heading_style="ATX", bullets="-")


def get_auth_headers(base_url: str, token: str, email: str | None = None) -> dict:
    if _is_cloud(base_url):
        if not email:
            raise ValueError("CONFLUENCE_EMAIL is required for Confluence Cloud (atlassian.net)")
        credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}
    return {"Authorization": f"Bearer {token}"}


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def _api_prefix(base_url: str) -> str:
    if not _is_cloud(base_url):
        return ""
    return "" if "/wiki" in base_url else "/wiki"


def _api_base(base_url: str) -> str:
    return f"{base_url}{_api_prefix(base_url)}/rest/api/content"


def _page_url(base_url: str, page_id: str) -> str:
    if _is_cloud(base_url):
        return f"{base_url}{_api_prefix(base_url)}/pages/{page_id}"
    return f"{base_url}/pages/viewpage.action?pageId={page_id}"


def format_confluence_timestamp(when: str) -> str:
    """Confluence の `version.when`（例: `2017-12-11T03:52:47.153Z`）をfrontmatter用の秒精度ISO8601に正規化する。

    ミリ秒有無に関わらず出力を安定させ、ページ内容が変わらない限り同じ文字列になるようにする
    （差分検出時に無意味なtimestamp差分が発生するのを防ぐため）。
    """
    parsed = datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def save_markdown(
    output_dir: str,
    title: str,
    page_id: str,
    content: str,
    base_url: str,
    references: list[str] | None = None,
    updated_at: str | None = None,
) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filename = f"{sanitize_filename(title)}_{sanitize_filename(page_id)}.md"
    filepath = output_path / filename
    if updated_at is not None:
        timestamp = format_confluence_timestamp(updated_at)
    else:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    refs_line = f"references: {json.dumps(references)}\n" if references else ""
    frontmatter = (
        "---\n"
        "type: Confluence Page\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        f"resource: {_page_url(base_url, page_id)}\n"
        f"timestamp: {timestamp}\n"
        f"{refs_line}"
        "---\n\n"
    )
    filepath.write_text(frontmatter + content, encoding="utf-8")
    return str(filepath)


def _find_page_ids(text: str) -> list[str]:
    return _PAGE_ID_RE.findall(text) + _PAGES_PATH_RE.findall(text)


def extract_page_ids(view_html: str, current_page_id: str) -> list[str]:
    ids = set(_find_page_ids(view_html))
    ids.discard(current_page_id)
    return sorted(ids)


def extract_storage_refs(storage_xml: str) -> list[tuple[str, str]]:
    """storage形式のXMLから<ri:page>要素の(space_key, title)ペアを抽出する。"""
    refs: set[tuple[str, str]] = set()
    for m in _RI_PAGE_RE.finditer(storage_xml):
        attrs = m.group(1)
        title_m = _RI_TITLE_RE.search(attrs)
        space_m = _RI_SPACE_RE.search(attrs)
        if title_m:
            title = html_lib.unescape(title_m.group(1))
            space = html_lib.unescape(space_m.group(1)) if space_m else ""
            refs.add((space, title))
    return list(refs)


def resolve_page_refs(
    session: requests.Session,
    base_url: str,
    refs: list[tuple[str, str]],
    current_page_id: str,
) -> list[str]:
    """(space_key, title)ペアをREST APIでページIDに解決する。"""
    ids: set[str] = set()
    url = _api_base(base_url)
    for space_key, title in refs:
        try:
            params: dict = {"title": title, "type": "page", "limit": 1}
            if space_key:
                params["spaceKey"] = space_key
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                ids.add(results[0]["id"])
        except requests.RequestException as exc:
            logger.debug("Failed to resolve ref (%s, %s): %s", space_key, title, exc)
    ids.discard(current_page_id)
    return sorted(ids)


def fetch_page(session: requests.Session, base_url: str, page_id: str) -> dict:
    url = f"{_api_base(base_url)}/{page_id}"
    response = session.get(url, params={"expand": "body.storage,body.view,version"}, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def fetch_children(session: requests.Session, base_url: str, page_id: str) -> list[dict]:
    url = f"{_api_base(base_url)}/{page_id}/child/page"
    children = []
    start = 0
    limit = 25
    while True:
        response = session.get(url, params={"start": start, "limit": limit}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        children.extend(results)
        if len(results) < limit:
            break
        start += limit
    return children


def _get_references(
    page: dict,
    session: requests.Session,
    base_url: str,
    page_id: str,
) -> list[str] | None:
    storage_refs = extract_storage_refs(page["body"]["storage"]["value"])
    if storage_refs:
        return resolve_page_refs(session, base_url, storage_refs, page_id) or None
    view_html = page.get("body", {}).get("view", {}).get("value", "")
    return extract_page_ids(view_html, page_id) or None


def process_page(
    session: requests.Session,
    base_url: str,
    page_id: str,
    output_dir: str,
    depth: int,
    stats: dict,
    wait: float = 0.0,
) -> None:
    try:
        page = fetch_page(session, base_url, page_id)
        title = page["title"]
        html = page["body"]["storage"]["value"]
        references = _get_references(page, session, base_url, page_id)
        markdown = html_to_markdown(html)
        updated_at = page.get("version", {}).get("when")
        if markdown.strip():
            path = save_markdown(output_dir, title, page_id, markdown, base_url, references, updated_at)
            logger.info(f"Saved: {path}")
            stats["saved"] += 1
        else:
            logger.info(f"Skipped (empty content): {page_id}")
        time.sleep(wait)

        if depth > 0:
            children = fetch_children(session, base_url, page_id)
            child_dir = str(Path(output_dir) / sanitize_filename(title))
            for child in children:
                process_page(session, base_url, child["id"], child_dir, depth - 1, stats, wait)
    except requests.HTTPError as e:
        logger.warning(f"Failed to fetch page {page_id}: {e}, skipping")
        stats["skipped"] += 1
    except requests.RequestException as e:
        logger.warning(f"Network error for page {page_id}: {e}, skipping")
        stats["skipped"] += 1


def _extract_page_id_from_url(url: str) -> str | None:
    ids = _find_page_ids(url)
    return ids[0] if ids else None


def _build_page_id_to_path(paths: list[Path]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for path in paths:
        m = _FILENAME_PAGE_ID_RE.search(path.name)
        if m:
            mapping[m.group(1)] = path
    return mapping


def relink_local_files(root_dir: str) -> int:
    """保存済みMarkdown本文中のConfluenceリンクのうち、ローカルにダウンロード済みのページを
    指すものを相対パスに張り替える。戻り値は張り替えた件数。
    """
    paths = list(Path(root_dir).rglob("*.md"))
    id_to_path = _build_page_id_to_path(paths)
    if not id_to_path:
        return 0

    relinked = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")

        def _replace(m: re.Match) -> str:
            nonlocal relinked
            label, url = m.group(1), m.group(2)
            page_id = _extract_page_id_from_url(url)
            target = id_to_path.get(page_id) if page_id else None
            if target is None or target == path:
                return m.group(0)
            relinked += 1
            return f"[{label}]({os.path.relpath(target, start=path.parent)})"

        new_text = _MD_LINK_RE.sub(_replace, text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
    return relinked


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Confluence ページを OKF 形式の Markdown ファイルとしてダウンロードする。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/confluence_downloader.py -u https://example.atlassian.net/wiki -p 123456 -o .\n"
            "  uv run scripts/confluence_downloader.py -p 123456 -d 2 -o .\n"
            "  uv run scripts/confluence_downloader.py -p 123456 -p 789012 -d 2 -o .\n"
        ),
    )
    parser.add_argument("-u", "--url", default=None, help="Confluence のベース URL（省略時は CONFLUENCE_URL 環境変数）")
    parser.add_argument(
        "-p", "--page-id", required=True, action="append", help="ダウンロード対象のページ ID（複数指定可）"
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=0,
        help=f"子ページの取得深さ（デフォルト: 0、上限: {MAX_DEPTH}）",
    )
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="出力先ディレクトリ")
    parser.add_argument(
        "-w",
        "--wait",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="ページ取得間の待機秒数（デフォルト: 1.0）",
    )
    args = parser.parse_args()

    if args.depth > MAX_DEPTH:
        logger.error(f"--depth は {MAX_DEPTH} 以下で指定してください（指定値: {args.depth}）")
        sys.exit(1)

    base_url = (args.url or os.environ.get("CONFLUENCE_URL", "")).rstrip("/")
    if base_url and "://" not in base_url:
        base_url = f"https://{base_url}"
    if not base_url:
        logger.error("--url または CONFLUENCE_URL 環境変数が必要です")
        sys.exit(1)

    stats = {"saved": 0, "skipped": 0}

    token = os.environ.get("CONFLUENCE_API_TOKEN", "")
    email = os.environ.get("CONFLUENCE_EMAIL", "")

    errors = []
    if not token:
        errors.append("CONFLUENCE_API_TOKEN が設定されていません")
    if _is_cloud(base_url) and not email:
        errors.append("Confluence Cloud では CONFLUENCE_EMAIL が必要です")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    headers = get_auth_headers(base_url, token, email)

    session = requests.Session()
    session.headers.update(headers)

    for page_id in args.page_id:
        logger.info(f"Fetching page: {page_id}")
        process_page(session, base_url, page_id, args.output, args.depth, stats, args.wait)

    logger.info(f"Done. {stats['saved']} pages saved, {stats['skipped']} skipped.")
    relinked = relink_local_files(args.output)
    logger.info(f"Relinked {relinked} links to local files.")


if __name__ == "__main__":
    main()
