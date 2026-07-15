#!/usr/bin/env -S uv run # /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

"""GitHub Pull Requestの詳細・レビュー・コメントを gh api 経由で取得し、OKF形式のMarkdownファイルに保存する。

■ 前提
  gh CLI がインストール済み・認証済みであること（`gh auth status` で確認）
  GitHub Enterprise を使う場合は `gh auth login --hostname <host>` で事前にログインしておく

■ 使い方
  uv run scripts/pr_fetcher.py https://github.com/owner/repo/pull/123 \\
    [https://ghe.example.com/owner2/repo2/pull/45 ...] [-o .]
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')
_PR_URL_RE = re.compile(r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")


class GhApiError(Exception):
    pass


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def parse_pr_url(url: str) -> dict:
    m = _PR_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"PR URLとして解釈できません: {url}")
    return m.groupdict()


def _gh_api(host: str, path: str) -> object:
    cmd = ["gh", "api"]
    if host != "github.com":
        cmd += ["--hostname", host]
    cmd += [path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GhApiError(result.stderr.strip() or f"gh api 実行に失敗しました: {path}")
    return json.loads(result.stdout)


def _gh_api_paginated(host: str, path: str, per_page: int = 100) -> list[dict]:
    items: list[dict] = []
    page = 1
    sep = "&" if "?" in path else "?"
    while True:
        batch = _gh_api(host, f"{path}{sep}per_page={per_page}&page={page}")
        if not isinstance(batch, list):
            break
        items.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return items


def _fetch_pr(host: str, owner: str, repo: str, number: str) -> dict:
    return _gh_api(host, f"repos/{owner}/{repo}/pulls/{number}")


def _fetch_pr_details(host: str, owner: str, repo: str, number: str) -> dict:
    base = f"repos/{owner}/{repo}"
    return {
        "reviews": _gh_api_paginated(host, f"{base}/pulls/{number}/reviews"),
        "review_comments": _gh_api_paginated(host, f"{base}/pulls/{number}/comments"),
        "issue_comments": _gh_api_paginated(host, f"{base}/issues/{number}/comments"),
    }


def _build_frontmatter(fields: dict) -> str:
    """OKF形式のYAML frontmatterを生成する。文字列値はJSONエンコードしてコロン等の混入に耐える。"""
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, str):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _read_existing_timestamp(file_path: Path) -> str | None:
    if not file_path.exists():
        return None
    text = file_path.read_text(encoding="utf-8")
    m = re.search(r"^timestamp:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _should_skip(existing_timestamp: str | None, current_timestamp: str, force: bool) -> bool:
    if force:
        return False
    if existing_timestamp is None:
        return False
    return existing_timestamp == current_timestamp


def _pr_file_path(owner: str, repo: str, number: str, output_dir: Path) -> Path:
    return output_dir / f"{sanitize_filename(owner)}-{sanitize_filename(repo)}-{number}.md"


def _format_issue_comments(comments: list[dict]) -> str:
    if not comments:
        return "_コメントなし_"
    lines = []
    for c in comments:
        author = (c.get("user") or {}).get("login", "不明")
        created = c.get("created_at", "")
        body = (c.get("body") or "").strip()
        lines.append(f"**{created}** ({author})\n\n{body}")
    return "\n\n---\n\n".join(lines)


def _format_reviews(reviews: list[dict]) -> str:
    if not reviews:
        return "_レビューなし_"
    lines = []
    for r in reviews:
        author = (r.get("user") or {}).get("login", "不明")
        state = r.get("state", "")
        submitted = r.get("submitted_at", "")
        body = (r.get("body") or "").strip()
        header = f"**{submitted}** ({author}) — {state}"
        lines.append(f"{header}\n\n{body}" if body else header)
    return "\n\n---\n\n".join(lines)


def _format_review_comments(comments: list[dict]) -> str:
    if not comments:
        return "_レビューコメントなし_"
    lines = []
    for c in comments:
        author = (c.get("user") or {}).get("login", "不明")
        created = c.get("created_at", "")
        path = c.get("path", "")
        line = c.get("line") or c.get("original_line") or ""
        body = (c.get("body") or "").strip()
        lines.append(f"**{path}:{line}** — {created} ({author})\n\n{body}")
    return "\n\n---\n\n".join(lines)


def _write_pr(host: str, owner: str, repo: str, number: str, bundle: dict, output_dir: Path) -> Path:
    pr = bundle["pr"]
    title = pr.get("title", "")
    state = pr.get("state", "")
    merged = pr.get("merged", False)
    user = (pr.get("user") or {}).get("login", "")
    base_ref = (pr.get("base") or {}).get("ref", "")
    head_ref = (pr.get("head") or {}).get("ref", "")
    created_at = pr.get("created_at", "")
    updated_at = pr.get("updated_at", "")
    merged_at = pr.get("merged_at", "")
    html_url = pr.get("html_url", f"https://{host}/{owner}/{repo}/pull/{number}")
    additions = pr.get("additions", "")
    deletions = pr.get("deletions", "")
    changed_files = pr.get("changed_files", "")

    tags = ["github", "pr", state]
    if merged:
        tags.append("merged")

    frontmatter = _build_frontmatter(
        {
            "type": "GitHub PR",
            "title": f"{owner}/{repo}#{number}: {title}",
            "description": title[:100],
            "resource": html_url,
            "tags": f"[{', '.join(tags)}]",
            "timestamp": updated_at,
        }
    )

    body = (
        f"# 詳細\n\n"
        f"| フィールド | 値 |\n"
        f"|---|---|\n"
        f"| ステータス | {state}{' (merged)' if merged else ''} |\n"
        f"| 作成者 | {user} |\n"
        f"| ブランチ | {head_ref} -> {base_ref} |\n"
        f"| 変更 | +{additions} / -{deletions}（{changed_files} files） |\n"
        f"| 作成日時 | {created_at} |\n"
        f"| 更新日時 | {updated_at} |\n"
        f"| マージ日時 | {merged_at or '-'} |\n\n"
        f"# 説明\n\n"
        f"{(pr.get('body') or '').strip()}\n\n"
        f"# レビュー\n\n"
        f"{_format_reviews(bundle['reviews'])}\n\n"
        f"# レビューコメント（差分への行コメント）\n\n"
        f"{_format_review_comments(bundle['review_comments'])}\n\n"
        f"# コメント\n\n"
        f"{_format_issue_comments(bundle['issue_comments'])}\n"
    )

    file_path = _pr_file_path(owner, repo, number, output_dir)
    file_path.write_text(frontmatter + "\n" + body, encoding="utf-8")
    logger.info(f"書き込み完了: {file_path}")
    return file_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="GitHub Pull Requestの詳細・レビュー・コメントを gh api 経由で取得し、OKF形式のMarkdownとして保存する。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/pr_fetcher.py https://github.com/owner/repo/pull/123 -o .\n"
            "  uv run scripts/pr_fetcher.py https://ghe.example.com/owner/repo/pull/45\n"
        ),
    )
    parser.add_argument("pr_urls", nargs="+", metavar="PR_URL", help="取得対象のPR URL（複数指定可）")
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="OKF出力先ディレクトリ")
    parser.add_argument("--force", action="store_true", help="更新チェックをスキップし常に再取得・上書きする")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    fetched_urls = []
    for url in args.pr_urls:
        try:
            ref = parse_pr_url(url)
        except ValueError as e:
            logger.warning(f"{e}, スキップ")
            continue
        try:
            pr = _fetch_pr(ref["host"], ref["owner"], ref["repo"], ref["number"])
            file_path = _pr_file_path(ref["owner"], ref["repo"], ref["number"], output_dir)
            existing_timestamp = _read_existing_timestamp(file_path)
            current_timestamp = pr.get("updated_at", "")
            if _should_skip(existing_timestamp, current_timestamp, args.force):
                logger.info(f"更新なし: スキップ ({file_path})")
                fetched_urls.append(url)
                continue
            details = _fetch_pr_details(ref["host"], ref["owner"], ref["repo"], ref["number"])
            bundle = {"pr": pr, **details}
            _write_pr(ref["host"], ref["owner"], ref["repo"], ref["number"], bundle, output_dir)
            fetched_urls.append(url)
        except GhApiError as e:
            logger.warning(f"PR取得失敗: {url}: {e}, スキップ")

    logger.info(f"完了: {len(fetched_urls)}/{len(args.pr_urls)} 件取得, 出力先: {output_dir}")
    if len(fetched_urls) < len(args.pr_urls):
        sys.exit(1)


if __name__ == "__main__":
    main()
