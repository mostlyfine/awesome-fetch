#!/usr/bin/env -S uv run # /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

"""GitHub Issueの詳細・コメントを gh api 経由で取得し、OKF形式のMarkdownファイルに保存する。

■ 前提
  gh CLI がインストール済み・認証済みであること（`gh auth status` で確認）
  GitHub Enterprise を使う場合は `gh auth login --hostname <host>` で事前にログインしておく

■ 使い方
  uv run scripts/issue_fetcher.py https://github.com/owner/repo/issues/123 \\
    [https://ghe.example.com/owner2/repo2/issues/45 ...] [-o .]
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
_ISSUE_URL_RE = re.compile(r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)")


class GhApiError(Exception):
    pass


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def parse_issue_url(url: str) -> dict:
    m = _ISSUE_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"Issue URLとして解釈できません: {url}")
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


def _fetch_issue(host: str, owner: str, repo: str, number: str) -> dict:
    return _gh_api(host, f"repos/{owner}/{repo}/issues/{number}")


def _fetch_issue_comments(host: str, owner: str, repo: str, number: str) -> list[dict]:
    return _gh_api_paginated(host, f"repos/{owner}/{repo}/issues/{number}/comments")


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


def _issue_file_path(owner: str, repo: str, number: str, output_dir: Path) -> Path:
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


def _write_issue(host: str, owner: str, repo: str, number: str, bundle: dict, output_dir: Path) -> Path:
    issue = bundle["issue"]
    title = issue.get("title", "")
    state = issue.get("state", "")
    state_reason = issue.get("state_reason", "")
    user = (issue.get("user") or {}).get("login", "")
    assignees = ", ".join((a or {}).get("login", "") for a in (issue.get("assignees") or [])) or "-"
    label_names = [(lbl or {}).get("name", "") for lbl in (issue.get("labels") or [])]
    labels = ", ".join(label_names) or "-"
    milestone = (issue.get("milestone") or {}).get("title", "") or "-"
    created_at = issue.get("created_at", "")
    updated_at = issue.get("updated_at", "")
    closed_at = issue.get("closed_at", "")
    html_url = issue.get("html_url", f"https://{host}/{owner}/{repo}/issues/{number}")

    tags = ["github", "issue", state]
    tags += [n for n in label_names if n]

    frontmatter = _build_frontmatter(
        {
            "type": "GitHub Issue",
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
        f"| ステータス | {state}{f' ({state_reason})' if state_reason else ''} |\n"
        f"| 作成者 | {user} |\n"
        f"| 担当者 | {assignees} |\n"
        f"| ラベル | {labels} |\n"
        f"| マイルストーン | {milestone} |\n"
        f"| 作成日時 | {created_at} |\n"
        f"| 更新日時 | {updated_at} |\n"
        f"| クローズ日時 | {closed_at or '-'} |\n\n"
        f"# 説明\n\n"
        f"{(issue.get('body') or '').strip()}\n\n"
        f"# コメント\n\n"
        f"{_format_issue_comments(bundle['comments'])}\n"
    )

    file_path = _issue_file_path(owner, repo, number, output_dir)
    file_path.write_text(frontmatter + "\n" + body, encoding="utf-8")
    logger.info(f"書き込み完了: {file_path}")
    return file_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="GitHub Issueの詳細・コメントを gh api 経由で取得し、OKF形式のMarkdownとして保存する。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/issue_fetcher.py https://github.com/owner/repo/issues/123 -o .\n"
            "  uv run scripts/issue_fetcher.py https://ghe.example.com/owner/repo/issues/45\n"
        ),
    )
    parser.add_argument("issue_urls", nargs="+", metavar="ISSUE_URL", help="取得対象のIssue URL（複数指定可）")
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="OKF出力先ディレクトリ")
    parser.add_argument("--force", action="store_true", help="更新チェックをスキップし常に再取得・上書きする")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    fetched_urls = []
    for url in args.issue_urls:
        try:
            ref = parse_issue_url(url)
        except ValueError as e:
            logger.warning(f"{e}, スキップ")
            continue
        try:
            issue = _fetch_issue(ref["host"], ref["owner"], ref["repo"], ref["number"])
            file_path = _issue_file_path(ref["owner"], ref["repo"], ref["number"], output_dir)
            existing_timestamp = _read_existing_timestamp(file_path)
            current_timestamp = issue.get("updated_at", "")
            if _should_skip(existing_timestamp, current_timestamp, args.force):
                logger.info(f"更新なし: スキップ ({file_path})")
                fetched_urls.append(url)
                continue
            comments = _fetch_issue_comments(ref["host"], ref["owner"], ref["repo"], ref["number"])
            bundle = {"issue": issue, "comments": comments}
            _write_issue(ref["host"], ref["owner"], ref["repo"], ref["number"], bundle, output_dir)
            fetched_urls.append(url)
        except GhApiError as e:
            logger.warning(f"Issue取得失敗: {url}: {e}, スキップ")

    logger.info(f"完了: {len(fetched_urls)}/{len(args.issue_urls)} 件取得, 出力先: {output_dir}")
    if len(fetched_urls) < len(args.issue_urls):
        sys.exit(1)


if __name__ == "__main__":
    main()
