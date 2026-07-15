#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
#   "markdownify==1.2.0",
# ]
# ///

"""Confluence ページを OKF 形式の Markdown ファイルとしてダウンロードする。

■ 取得経路(2段構え)
  1. MCP経路: claude.aiのAtlassian連携でClaudeが`getConfluencePage`を呼んで取得した
     JSONを `--mcp-json` で渡す(このスクリプトはネットワークアクセスしない。指定ページ単体のみ、
     `--depth`による子ページ再帰取得は非対応)
  2. トークン経路: 環境変数 `CONFLUENCE_API_TOKEN` を使い、このスクリプトが直接Confluence
     REST APIを呼んで取得する(子ページ再帰取得に対応)

■ 環境変数
  CONFLUENCE_API_TOKEN  API トークン（必須。トークン経路のみ）
  CONFLUENCE_EMAIL      メールアドレス（Confluence Cloud の場合のみ必須。トークン経路のみ）
  CONFLUENCE_URL        Confluence のベース URL（--url の省略時に使用）

■ 使い方
  export CONFLUENCE_API_TOKEN=<token>
  export CONFLUENCE_EMAIL=<email>   # Cloud の場合のみ

  uv run scripts/confluence_downloader.py \\
    --url https://your-domain.atlassian.net/wiki \\
    --page-id 123456789 [--depth 2] [-o .] [--wait 0.5]
  uv run scripts/confluence_downloader.py \\
    --url https://your-domain.atlassian.net/wiki --page-id 123456789 --mcp-json raw.json -o .
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

_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')
_PAGE_ID_RE = re.compile(r"pageId=(\d+)")
_PAGES_PATH_RE = re.compile(r"/pages/(\d+)")
_RI_PAGE_RE = re.compile(r"<ri:page\b([^>]*?)/>")
_RI_TITLE_RE = re.compile(r'ri:content-title="([^"]*)"')
_RI_SPACE_RE = re.compile(r'ri:space-key="([^"]*)"')


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


def save_markdown(
    output_dir: str,
    title: str,
    page_id: str,
    content: str,
    base_url: str,
    references: list[str] | None = None,
) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filename = f"{sanitize_filename(title)}_{sanitize_filename(page_id)}.md"
    filepath = output_path / filename
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


def extract_page_ids(view_html: str, current_page_id: str) -> list[str]:
    ids = set(_PAGE_ID_RE.findall(view_html) + _PAGES_PATH_RE.findall(view_html))
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
            resp = session.get(url, params=params)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                ids.add(results[0]["id"])
        except requests.RequestException:
            pass
    ids.discard(current_page_id)
    return sorted(ids)


def fetch_page(session: requests.Session, base_url: str, page_id: str) -> dict:
    url = f"{_api_base(base_url)}/{page_id}"
    response = session.get(url, params={"expand": "body.storage,body.view"})
    response.raise_for_status()
    return response.json()


def fetch_children(session: requests.Session, base_url: str, page_id: str) -> list[dict]:
    url = f"{_api_base(base_url)}/{page_id}/child/page"
    children = []
    start = 0
    limit = 25
    while True:
        response = session.get(url, params={"start": start, "limit": limit})
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
        if markdown.strip():
            path = save_markdown(output_dir, title, page_id, markdown, base_url, references)
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


def process_page_from_mcp_json(mcp_json_path: str, page_id: str, output_dir: str, base_url: str, stats: dict) -> None:
    """MCPツール(`getConfluencePage`)が返したJSONから単一ページを保存する。子ページ再帰取得は非対応。"""
    try:
        page = json.loads(Path(mcp_json_path).read_text(encoding="utf-8"))
        title = page["title"]
        html = page["body"]["storage"]["value"]
    except (KeyError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to parse MCP JSON for page {page_id}: {e}, skipping")
        stats["skipped"] += 1
        return

    markdown = html_to_markdown(html)
    if markdown.strip():
        path = save_markdown(output_dir, title, page_id, markdown, base_url)
        logger.info(f"Saved: {path}")
        stats["saved"] += 1
    else:
        logger.info(f"Skipped (empty content): {page_id}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Confluence ページを OKF 形式の Markdown ファイルとしてダウンロードする。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/confluence_downloader.py --url https://example.atlassian.net/wiki --page-id 123456 -o .\n"
            "  uv run scripts/confluence_downloader.py --page-id 123456 --depth 2 -o .\n"
        ),
    )
    parser.add_argument("--url", default=None, help="Confluence のベース URL（省略時は CONFLUENCE_URL 環境変数）")
    parser.add_argument("--page-id", required=True, help="ダウンロード対象のページ ID")
    parser.add_argument("--depth", type=int, default=0, help="子ページの取得深さ（デフォルト: 0）")
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="出力先ディレクトリ")
    parser.add_argument(
        "--wait",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="ページ取得間の待機秒数（デフォルト: 1.0）",
    )
    parser.add_argument("--mcp-json", metavar="PATH", default=None, help="MCPツールで取得済みのページJSON。指定時は--depthを無視し指定ページ単体のみ処理する")
    args = parser.parse_args()

    base_url = (args.url or os.environ.get("CONFLUENCE_URL", "")).rstrip("/")
    if base_url and "://" not in base_url:
        base_url = f"https://{base_url}"
    if not base_url:
        logger.error("--url または CONFLUENCE_URL 環境変数が必要です")
        sys.exit(1)

    stats = {"saved": 0, "skipped": 0}

    if args.mcp_json:
        logger.info(f"Fetching page (MCP): {args.page_id}")
        process_page_from_mcp_json(args.mcp_json, args.page_id, args.output, base_url, stats)
        logger.info(f"Done. {stats['saved']} pages saved, {stats['skipped']} skipped.")
        return

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

    logger.info(f"Fetching page: {args.page_id}")
    process_page(session, base_url, args.page_id, args.output, args.depth, stats, args.wait)

    logger.info(f"Done. {stats['saved']} pages saved, {stats['skipped']} skipped.")


if __name__ == "__main__":
    main()
