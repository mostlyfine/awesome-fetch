#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
# ]
# ///

"""JIRA (Server/Data Center) のissue詳細とコメントを取得し、OKF形式のMarkdownファイルに保存する。

■ 取得経路(2段構え)
  1. MCP経路: claude.aiのAtlassian連携でClaudeが`getJiraIssue`を呼んで取得したJSONを
     `--mcp-json` で渡す(このスクリプトはネットワークアクセスしない)
  2. トークン経路: 環境変数 `JIRA_API_TOKEN` を使い、このスクリプトが直接JIRA REST API
     (`/rest/api/2/issue/{key}`)を呼んで取得する

■ 環境変数
  JIRA_API_TOKEN  Personal Access Token（Bearer 認証、必須。トークン経路のみ）
  JIRA_URL        JIRA のベース URL（--url の省略時に使用）

■ 使い方
  export JIRA_API_TOKEN=<token>

  uv run scripts/jira_issue_fetcher.py PROJ-123 PROJ-124 \\
    [--fields summary,status] [-o .]
  uv run scripts/jira_issue_fetcher.py PROJ-123 --mcp-json raw.json --url https://x.atlassian.net -o .
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

API_PATH = "/rest/api/2"
_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')


def _make_session() -> requests.Session:
    token = os.getenv("JIRA_API_TOKEN")
    if not token:
        logger.error("環境変数 JIRA_API_TOKEN が設定されていません")
        sys.exit(1)
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    return session


def _get_base_url(cli_url: str | None) -> str:
    base_url = (cli_url or os.getenv("JIRA_URL", "")).rstrip("/")
    if not base_url:
        logger.error("--url または環境変数 JIRA_URL が必要です")
        sys.exit(1)
    if "://" not in base_url:
        base_url = f"https://{base_url}"
    return base_url


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def _adf_to_text(node: dict | list | str | None) -> str:
    """ADF (Atlassian Document Format) ノードを再帰的にプレーンテキストへ変換する。"""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    node_type = node.get("type")
    if node_type == "text":
        return node.get("text", "")
    text = "".join(_adf_to_text(c) for c in node.get("content", []))
    if node_type == "paragraph":
        return text + "\n\n"
    if node_type == "hardBreak":
        return "\n"
    return text


def _extract_text_field(raw: str | dict | None) -> str:
    """description/comment.body フィールドをプレーンテキストに正規化する（str/ADF 両対応）。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return _adf_to_text(raw).strip()


def _fetch_paginated(session: requests.Session, url: str, params: dict, item_key: str, page_size: int = 100) -> list[dict]:
    """startAt/maxResults/total 方式のオフセットページネーションを処理する。"""
    items: list[dict] = []
    start_at = 0
    while True:
        resp = session.get(url, params={**params, "startAt": start_at, "maxResults": page_size})
        resp.raise_for_status()
        data = resp.json()
        batch = data.get(item_key, [])
        items.extend(batch)
        total = data.get("total", 0)
        start_at += len(batch)
        if not batch or start_at >= total:
            break
    return items


def _fetch_issue(session: requests.Session, base_url: str, issue_key: str, fields: list[str] | None) -> dict:
    params = {"fields": ",".join(fields)} if fields else {}
    resp = session.get(f"{base_url}{API_PATH}/issue/{issue_key}", params=params)
    resp.raise_for_status()
    return resp.json()


def _fetch_comments(session: requests.Session, base_url: str, issue_key: str) -> list[dict]:
    return _fetch_paginated(session, f"{base_url}{API_PATH}/issue/{issue_key}/comment", {}, "comments")


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


def _issue_file_path(key: str, output_dir: Path) -> Path:
    return output_dir / f"{sanitize_filename(key)}.md"


def _format_comments(comments: list[dict]) -> str:
    if not comments:
        return "_コメントなし_"
    lines = []
    for comment in comments:
        created = comment.get("created", "")
        author = comment.get("author", {}).get("displayName", "不明")
        body = _extract_text_field(comment.get("body"))
        lines.append(f"**{created}** ({author})\n\n{body}")
    return "\n\n---\n\n".join(lines)


def _write_issue(issue: dict, comments: list[dict], base_url: str, output_dir: Path) -> None:
    key = issue["key"]
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    status = fields.get("status", {}).get("name", "")
    issuetype = fields.get("issuetype", {}).get("name", "")
    priority = (fields.get("priority") or {}).get("name", "")
    assignee = (fields.get("assignee") or {}).get("displayName", "未割当")
    reporter = (fields.get("reporter") or {}).get("displayName", "")
    labels = ", ".join(fields.get("labels", []))
    created = fields.get("created", "")
    updated = fields.get("updated", "")

    frontmatter = _build_frontmatter(
        {
            "type": "JIRA Issue",
            "title": f"{key}: {summary}",
            "description": summary[:100],
            "resource": f"{base_url}/browse/{key}",
            "tags": f"[jira, issue, {issuetype}, {status}]",
            "timestamp": updated,
        }
    )

    body = (
        f"# 詳細\n\n"
        f"| フィールド | 値 |\n"
        f"|---|---|\n"
        f"| ステータス | {status} |\n"
        f"| 種別 | {issuetype} |\n"
        f"| 優先度 | {priority} |\n"
        f"| 担当者 | {assignee} |\n"
        f"| 報告者 | {reporter} |\n"
        f"| ラベル | {labels} |\n"
        f"| 作成日時 | {created} |\n"
        f"| 更新日時 | {updated} |\n\n"
        f"# 説明\n\n"
        f"{_extract_text_field(fields.get('description'))}\n\n"
        f"# コメント\n\n"
        f"{_format_comments(comments)}\n"
    )

    file_path = _issue_file_path(key, output_dir)
    file_path.write_text(frontmatter + "\n" + body, encoding="utf-8")
    logger.info(f"書き込み完了: {file_path}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="JIRA (Server/Data Center) のissue詳細とコメントを取得し、OKF形式のMarkdownとして保存する。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/jira_issue_fetcher.py PROJ-123 -o .\n"
            "  uv run scripts/jira_issue_fetcher.py PROJ-123 PROJ-124 --fields summary,status\n"
        ),
    )
    parser.add_argument("issue_keys", nargs="+", metavar="ISSUE_KEY", help="取得対象のissueキー（複数指定可、例: PROJ-123 PROJ-124）")
    parser.add_argument("--fields", default=None, help="取得フィールド（カンマ区切り、省略時は全フィールド）")
    parser.add_argument("--url", default=None, help="JIRAのベースURL（省略時は環境変数 JIRA_URL）")
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="OKF出力先ディレクトリ")
    parser.add_argument("--force", action="store_true", help="更新チェックをスキップし常に再取得・上書きする")
    parser.add_argument("--mcp-json", metavar="PATH", default=None, help="MCPツールで取得済みのissue JSON。指定時はISSUE_KEYを1つだけ指定する")
    args = parser.parse_args()

    if args.mcp_json and len(args.issue_keys) != 1:
        parser.error("--mcp-json は ISSUE_KEY を1つだけ指定した場合のみ使用できます")

    base_url = _get_base_url(args.url)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.mcp_json:
        key = args.issue_keys[0]
        raw_path = Path(args.mcp_json)
        try:
            issue = json.loads(raw_path.read_text(encoding="utf-8"))
            file_path = _issue_file_path(key, output_dir)
            existing_timestamp = _read_existing_timestamp(file_path)
            current_timestamp = issue.get("fields", {}).get("updated", "")
            if _should_skip(existing_timestamp, current_timestamp, args.force):
                logger.info(f"更新なし: スキップ ({file_path})")
                raw_path.unlink(missing_ok=True)
                logger.info(f"完了: 1/1 件取得, 出力先: {output_dir}")
                return
            comments = issue.get("fields", {}).get("comment", {}).get("comments", [])
            _write_issue(issue, comments, base_url, output_dir)
            raw_path.unlink(missing_ok=True)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"issue取得失敗: {key}: {e}")
            sys.exit(1)
        logger.info(f"完了: 1/1 件取得, 出力先: {output_dir}")
        return

    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
    session = _make_session()

    fetched_keys = []
    for key in args.issue_keys:
        try:
            issue = _fetch_issue(session, base_url, key, fields)
            file_path = _issue_file_path(key, output_dir)
            existing_timestamp = _read_existing_timestamp(file_path)
            current_timestamp = issue.get("fields", {}).get("updated", "")
            if _should_skip(existing_timestamp, current_timestamp, args.force):
                logger.info(f"更新なし: スキップ ({file_path})")
                fetched_keys.append(key)
                continue
            comments = _fetch_comments(session, base_url, key)
            _write_issue(issue, comments, base_url, output_dir)
            fetched_keys.append(key)
        except requests.HTTPError as e:
            logger.warning(f"issue取得失敗: {key}: {e}, スキップ")

    logger.info(f"完了: {len(fetched_keys)}/{len(args.issue_keys)} 件取得, 出力先: {output_dir}")


if __name__ == "__main__":
    main()
