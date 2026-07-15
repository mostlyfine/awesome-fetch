#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
# ]
# ///

"""JIRA (Server/Data Center) をJQLで検索し、結果一覧を表示する。

デフォルトでは結果をMarkdownの表として標準出力に表示するのみでファイルには保存しない。
`-o`/`--output` を指定した場合のみ、OKF形式のMarkdownファイルとして保存する。

■ 取得経路(2段構え)
  1. MCP経路: claude.aiのAtlassian連携でClaudeが`searchJiraIssuesUsingJql`を呼んで
     取得したJSON({"issues": [...]})を `--mcp-json` で渡す(このスクリプトはネットワークアクセスしない)
  2. トークン経路: 環境変数 `JIRA_API_TOKEN` を使い、このスクリプトが直接JIRA REST API
     (`/rest/api/2/search`)を呼んで取得する

■ 環境変数
  JIRA_API_TOKEN  Personal Access Token（Bearer 認証、必須。トークン経路のみ）
  JIRA_URL        JIRA のベース URL（--url の省略時に使用）

■ 使い方
  export JIRA_API_TOKEN=<token>

  uv run scripts/jira_issue_search.py --jql "project = PROJ AND status = Open" \\
    [--fields summary,status] [--max-results 50] [-o <保存先ディレクトリ>]
  uv run scripts/jira_issue_search.py --jql "..." --mcp-json raw.json --url https://x.atlassian.net
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

API_PATH = "/rest/api/2"
DEFAULT_FIELDS = "summary,status,issuetype,assignee,updated"


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


def _search_issues(session: requests.Session, base_url: str, jql: str, fields: str, max_results: int, page_size: int = 100) -> list[dict]:
    """/rest/api/2/search を startAt/maxResults/total 方式でページングし、max_results件に達したら打ち切る。"""
    issues: list[dict] = []
    start_at = 0
    url = f"{base_url}{API_PATH}/search"
    while len(issues) < max_results:
        resp = session.get(
            url,
            params={
                "jql": jql,
                "fields": fields,
                "startAt": start_at,
                "maxResults": min(page_size, max_results - len(issues)),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("issues", [])
        issues.extend(batch)
        total = data.get("total", 0)
        start_at += len(batch)
        if not batch or start_at >= total:
            break
    return issues[:max_results]


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


def _format_results_table(issues: list[dict], base_url: str) -> str:
    if not issues:
        return "_該当0件_"
    lines = [
        "| Key | Summary | Status | Type | Assignee | Updated |",
        "|---|---|---|---|---|---|",
    ]
    for issue in issues:
        key = issue["key"]
        f = issue.get("fields", {})
        summary = f.get("summary", "")
        status = (f.get("status") or {}).get("name", "")
        issuetype = (f.get("issuetype") or {}).get("name", "")
        assignee = (f.get("assignee") or {}).get("displayName", "未割当")
        updated = f.get("updated", "")
        lines.append(f"| [{key}]({base_url}/browse/{key}) | {summary} | {status} | {issuetype} | {assignee} | {updated} |")
    return "\n".join(lines)


def _build_body(jql: str, issues: list[dict], base_url: str) -> str:
    return (
        f"# JQL検索結果\n\n"
        f"**JQL**: `{jql}`\n\n"
        f"**該当件数**: {len(issues)}件\n\n"
        f"{_format_results_table(issues, base_url)}\n"
    )


def _write_results(jql: str, issues: list[dict], base_url: str, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    frontmatter = _build_frontmatter(
        {
            "type": "JIRA Search",
            "title": jql,
            "description": f"JQL検索結果: {len(issues)}件",
            "resource": f"{base_url}/issues/?jql={requests.utils.quote(jql)}",
            "tags": "[jira, search]",
            "timestamp": datetime.now().isoformat(),
        }
    )

    file_path = output_dir / f"jira-search-{timestamp}.md"
    file_path.write_text(frontmatter + "\n" + _build_body(jql, issues, base_url), encoding="utf-8")
    return file_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="JIRA (Server/Data Center) をJQLで検索し、結果一覧を表示する（-o省略時は保存せず標準出力に表示のみ）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            '  uv run scripts/jira_issue_search.py --jql "project = PROJ AND status = Open"\n'
            '  uv run scripts/jira_issue_search.py --jql "assignee = currentUser()" --max-results 20 -o docs/jira\n'
        ),
    )
    parser.add_argument("--jql", required=True, help="検索に使うJQL文字列")
    parser.add_argument("--fields", default=DEFAULT_FIELDS, help=f"取得フィールド（カンマ区切り、デフォルト: {DEFAULT_FIELDS}）")
    parser.add_argument("--max-results", type=int, default=50, help="取得件数の上限（デフォルト: 50）")
    parser.add_argument("--url", default=None, help="JIRAのベースURL（省略時は環境変数 JIRA_URL）")
    parser.add_argument("-o", "--output", metavar="DIR", default=None, help="OKF出力先ディレクトリ（省略時はファイル保存せず標準出力に表示のみ）")
    parser.add_argument("--mcp-json", metavar="PATH", default=None, help="MCPツールで取得済みの検索結果JSON({issues: [...]})")
    args = parser.parse_args()

    base_url = _get_base_url(args.url)

    if args.mcp_json:
        raw_path = Path(args.mcp_json)
        try:
            data = json.loads(raw_path.read_text(encoding="utf-8"))
            issues = data.get("issues", [])[: args.max_results]
            raw_path.unlink(missing_ok=True)
        except json.JSONDecodeError as e:
            logger.error(f"検索失敗: {e}")
            sys.exit(1)
    else:
        session = _make_session()
        try:
            issues = _search_issues(session, base_url, args.jql, args.fields, args.max_results)
        except requests.HTTPError as e:
            logger.error(f"検索失敗: {e}")
            sys.exit(1)

    if args.output is None:
        print(_build_body(args.jql, issues, base_url))
        logger.info(f"完了: {len(issues)}件ヒット（表示のみ、未保存）")
    else:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = _write_results(args.jql, issues, base_url, output_dir)
        logger.info(f"書き込み完了: {file_path}")
        logger.info(f"完了: {len(issues)}件ヒット, 出力先: {file_path}")


if __name__ == "__main__":
    main()
