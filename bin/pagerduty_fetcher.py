#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests",
# ]
# ///

"""PagerDuty のインシデント情報を OKF 形式で取得し Markdown ファイルに保存する。

■ 環境変数
  PAGERDUTY_TOKEN  PagerDuty API トークン（必須）

■ 使い方
  export PAGERDUTY_TOKEN=<token>

  uv run scripts/pagerduty_fetcher.py \\
    [--since 2024-01-01T00:00:00Z] [--until 2024-01-08T00:00:00Z] \\
    [--statuses triggered,acknowledged,resolved] [--services SVC1,SVC2] \\
    [-o .]
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pagerduty.com"
DEFAULT_STATUSES = ["triggered", "acknowledged", "resolved"]
FETCH_LIMIT = 100


def _make_session() -> requests.Session:
    token = os.getenv("PAGERDUTY_TOKEN")
    if not token:
        logger.error("環境変数 PAGERDUTY_TOKEN が設定されていません")
        sys.exit(1)
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Token token={token}",
            "Accept": "application/vnd.pagerduty+json;version=2",
        }
    )
    return session


def _fetch_all(session: requests.Session, path: str, key: str, params: dict | None = None) -> list[dict]:
    """ページネーションを処理してすべてのリソースを取得する。"""
    results = []
    offset = 0
    while True:
        resp = session.get(
            f"{BASE_URL}{path}",
            params={**(params or {}), "limit": FETCH_LIMIT, "offset": offset},
        )
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get(key, []))
        if not data.get("more", False):
            break
        offset += FETCH_LIMIT
    return results


def _fetch_incidents(
    session: requests.Session,
    since: str,
    until: str,
    statuses: list[str],
    service_ids: list[str] | None = None,
) -> list[dict]:
    params: dict = {
        "since": since,
        "until": until,
        "statuses[]": statuses,
    }
    if service_ids:
        params["service_ids[]"] = service_ids
    return _fetch_all(session, "/incidents", "incidents", params)


def _fetch_notes(session: requests.Session, incident_id: str) -> list[dict]:
    return _fetch_all(session, f"/incidents/{incident_id}/notes", "notes")


def _fetch_alerts(session: requests.Session, incident_id: str) -> list[dict]:
    return _fetch_all(session, f"/incidents/{incident_id}/alerts", "alerts")


def _fetch_incident_by_id(session: requests.Session, incident_id: str) -> dict:
    resp = session.get(f"{BASE_URL}/incidents/{incident_id}")
    resp.raise_for_status()
    return resp.json()["incident"]


def _build_frontmatter(fields: dict) -> str:
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _format_notes(notes: list[dict]) -> str:
    if not notes:
        return "_ノートなし_"
    lines = []
    for note in notes:
        created = note.get("created_at", "")
        user = note.get("user", {}).get("summary", "不明")
        content = note.get("content", "")
        lines.append(f"**{created}** ({user})\n\n{content}")
    return "\n\n---\n\n".join(lines)


def _format_alerts(alerts: list[dict]) -> str:
    if not alerts:
        return "_アラートなし_"
    lines = []
    for alert in alerts:
        severity = alert.get("severity", "")
        summary = alert.get("summary", "")
        status = alert.get("status", "")
        created = alert.get("created_at", "")
        body = alert.get("body", {})
        details = body.get("details", {}) if isinstance(body, dict) else {}
        detail_str = "\n".join(f"  - {k}: {v}" for k, v in details.items())
        lines.append(f"- **severity**: {severity} | **status**: {status} | **created**: {created}\n  {summary}\n{detail_str}")
    return "\n".join(lines)


def _write_incident(incident: dict, notes: list[dict], alerts: list[dict], output_dir: Path) -> None:
    incident_id = incident["id"]
    title = incident.get("title", "")
    description = (incident.get("description") or title)[:100]
    html_url = incident.get("html_url", "")
    status = incident.get("status", "")
    urgency = incident.get("urgency", "")
    created_at = incident.get("created_at", "")
    resolved_at = incident.get("resolved_at") or "-"
    updated_at = incident.get("updated_at", "")
    service = incident.get("service", {}).get("summary", "")

    frontmatter = _build_frontmatter(
        {
            "type": "PagerDuty Incident",
            "title": title,
            "description": description,
            "resource": html_url,
            "tags": f"[pagerduty, incident, {urgency}, {status}]",
            "timestamp": updated_at,
        }
    )

    body = (
        f"# 詳細\n\n"
        f"| フィールド | 値 |\n"
        f"|---|---|\n"
        f"| ステータス | {status} |\n"
        f"| 緊急度 | {urgency} |\n"
        f"| 発生時刻 | {created_at} |\n"
        f"| 解決時刻 | {resolved_at} |\n"
        f"| 担当サービス | {service} |\n\n"
        f"# ノート\n\n"
        f"{_format_notes(notes)}\n\n"
        f"# アラート\n\n"
        f"{_format_alerts(alerts)}\n"
    )

    file_path = output_dir / f"{incident_id}.md"
    file_path.write_text(frontmatter + "\n" + body, encoding="utf-8")
    logger.info(f"書き込み完了: {file_path}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="PagerDutyのインシデント情報をOKF形式でエクスポートする。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/pagerduty_fetcher.py --since 2024-01-01T00:00:00Z -o .\n"
            "  uv run scripts/pagerduty_fetcher.py --statuses resolved --services SVC1,SVC2\n"
            "  uv run scripts/pagerduty_fetcher.py --incident-ids Q0AX7D922G6IUR,ABCDEFG -o .\n"
        ),
    )
    parser.add_argument("--since", default=None, help="取得開始日時（ISO 8601）（デフォルト: 7日前。--incident-ids指定時は無視）")
    parser.add_argument("--until", default=None, help="取得終了日時（ISO 8601）（デフォルト: 現在。--incident-ids指定時は無視）")
    parser.add_argument(
        "--statuses",
        default=None,
        help=f"対象ステータス（カンマ区切り、デフォルト: {','.join(DEFAULT_STATUSES)}。--incident-ids指定時は無視）",
    )
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="OKF出力先ディレクトリ")
    parser.add_argument("--services", default=None, help="対象サービスID（カンマ区切り）。省略時は全サービス。--incident-ids指定時は無視")
    parser.add_argument(
        "--incident-ids",
        default=None,
        help="取得対象のインシデントID（カンマ区切りで複数指定可）。指定時は一覧取得系オプション(--since/--until/--statuses/--services)は無視される",
    )
    args = parser.parse_args()

    def comma_list(value: str) -> list[str]:
        return [s.strip() for s in value.split(",")]

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = _make_session()

    if args.incident_ids:
        ignored = [
            name
            for name, value in (
                ("--since", args.since),
                ("--until", args.until),
                ("--statuses", args.statuses),
                ("--services", args.services),
            )
            if value is not None
        ]
        if ignored:
            logger.warning(f"--incident-ids 指定時は次のオプションは無視されます: {', '.join(ignored)}")

        incident_ids = comma_list(args.incident_ids)
        logger.info(f"ピンポイント取得: {len(incident_ids)} 件のインシデントIDを指定")
        fetched = 0
        for incident_id in incident_ids:
            try:
                incident = _fetch_incident_by_id(session, incident_id)
            except requests.HTTPError as e:
                logger.warning(f"インシデント取得失敗: {incident_id}: {e}, スキップ")
                continue
            notes = _fetch_notes(session, incident_id)
            alerts = _fetch_alerts(session, incident_id)
            _write_incident(incident, notes, alerts, output_dir)
            fetched += 1
        logger.info(f"完了: {fetched}/{len(incident_ids)} 件取得, 出力先: {output_dir}")
        return

    now = datetime.now(timezone.utc)
    since = args.since or (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    until = args.until or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    statuses = comma_list(args.statuses) if args.statuses else DEFAULT_STATUSES
    service_ids = comma_list(args.services) if args.services else None

    logger.info(f"インシデント取得中: {since} ～ {until}, statuses={statuses}, services={service_ids or '全て'}")
    incidents = _fetch_incidents(session, since, until, statuses, service_ids)
    logger.info(f"{len(incidents)} 件のインシデントを取得")

    for incident in incidents:
        incident_id = incident["id"]
        notes = _fetch_notes(session, incident_id)
        alerts = _fetch_alerts(session, incident_id)
        _write_incident(incident, notes, alerts, output_dir)

    logger.info(f"完了: {output_dir}")


if __name__ == "__main__":
    main()
