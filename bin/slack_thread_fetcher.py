#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
# ]
# ///

"""Slackスレッド(親メッセージ+返信+リアクション)を取得し、OKF形式のMarkdownファイルに保存する。

■ 取得経路(2段構え)
  1. MCP経路: claude.aiのSlack連携でClaudeが`slack_read_thread`/`slack_read_user_profile`を
     呼んで取得したJSONを `--mcp-json` で渡す(このスクリプトはネットワークアクセスしない)
  2. トークン経路: 環境変数 `SLACK_API_TOKEN` を使い、このスクリプトが直接Slack Web API
     (`conversations.replies` / `users.info`)を呼んで取得する

■ 使い方
  uv run scripts/slack_thread_fetcher.py <SLACK_THREAD_URL> --mcp-json raw.json [-o .]
  uv run scripts/slack_thread_fetcher.py <SLACK_THREAD_URL> [<SLACK_THREAD_URL> ...] [-o .]
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"
_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')
_PERMALINK_RE = re.compile(r"^https?://[^/]+\.slack\.com/archives/(?P<channel_id>[A-Z0-9]+)/p(?P<ts_digits>\d+)")
_MRKDWN_RE = re.compile(r"<(?P<target>[^|>]+)(?:\|(?P<label>[^>]*))?>")


class SlackApiError(Exception):
    pass


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def parse_slack_url(url: str) -> dict:
    """SlackパーマリンクからchannelIdと親メッセージのtsを抽出する。

    `p<16桁digits>` はメッセージ個別のtsだが、`?thread_ts=...` が付いている場合は
    スレッド内の特定の返信を指している可能性があるため、そちらを親メッセージのtsとして優先する。
    """
    m = _PERMALINK_RE.match(url.strip())
    if not m:
        raise ValueError(f"Slackスレッドのパーマリンクとして解釈できません: {url}")

    query = parse_qs(urlsplit(url).query)
    thread_ts = query.get("thread_ts", [None])[0]
    if thread_ts:
        message_ts = thread_ts
    else:
        digits = m.group("ts_digits")
        message_ts = f"{digits[:-6]}.{digits[-6:]}"

    return {"channel_id": m.group("channel_id"), "message_ts": message_ts}


def _clean_slack_markup(text: str) -> str:
    """Slackのmrkdwn記法(`<@ID|handle>` `<#ID|name>` `<url|label>` `<url>`)を読みやすい形に変換する。"""

    def _replace(m: re.Match) -> str:
        target, label = m.group("target"), m.group("label")
        if target.startswith("@") or target.startswith("#"):
            return f"{target[0]}{label}" if label else target
        return f"[{label}]({target})" if label else target

    return _MRKDWN_RE.sub(_replace, text)


def normalize_messages(raw_messages: list[dict], user_map: dict[str, str]) -> list[dict]:
    """MCP/Web APIどちらの生メッセージ形式も共通の内部形式へ変換し、ts昇順に並べる。"""
    normalized = []
    for msg in raw_messages:
        user_id = msg.get("user") or msg.get("bot_id") or "unknown"
        normalized.append(
            {
                "ts": msg["ts"],
                "user_id": user_id,
                "display_name": user_map.get(user_id, user_id),
                "text": _clean_slack_markup((msg.get("text") or "").strip()),
                "reactions": msg.get("reactions") or [],
            }
        )
    return sorted(normalized, key=lambda m: float(m["ts"]))


def _format_reactions(reactions: list[dict]) -> str:
    if not reactions:
        return ""
    return " ".join(f":{r['name']}: x{r['count']}" for r in reactions)


def _format_message(msg: dict) -> str:
    iso_ts = datetime.fromtimestamp(float(msg["ts"]), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"**{iso_ts}** ({msg['display_name']})", "", msg["text"] or "_(本文なし)_"]
    reactions = _format_reactions(msg["reactions"])
    if reactions:
        lines += ["", reactions]
    return "\n".join(lines)


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


def write_thread(output_dir: Path, channel_id: str, permalink: str, messages: list[dict]) -> Path:
    parent = messages[0]
    replies = messages[1:]
    parent_iso = datetime.fromtimestamp(float(parent["ts"]), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    title_snippet = (parent["text"] or "")[:50].replace("\n", " ")
    frontmatter = _build_frontmatter(
        {
            "type": "Slack Thread",
            "title": f"#{channel_id}: {title_snippet}",
            "description": (parent["text"] or "")[:100],
            "resource": permalink,
            "tags": f"[slack, thread, {channel_id}]",
            "timestamp": parent_iso,
        }
    )

    replies_body = "\n\n---\n\n".join(_format_message(m) for m in replies) if replies else "_返信なし_"

    body = (
        f"# 詳細\n\n"
        f"| フィールド | 値 |\n"
        f"|---|---|\n"
        f"| チャンネル | {channel_id} |\n"
        f"| パーマリンク | {permalink} |\n"
        f"| 投稿者 | {parent['display_name']} |\n"
        f"| 返信数 | {len(replies)} |\n"
        f"| 投稿日時 | {parent_iso} |\n\n"
        f"# 親メッセージ\n\n"
        f"{_format_message(parent)}\n\n"
        f"# 返信\n\n"
        f"{replies_body}\n"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{sanitize_filename(channel_id)}-{parent['ts'].replace('.', '_')}.md"
    file_path = output_dir / file_name
    file_path.write_text(frontmatter + "\n" + body, encoding="utf-8")
    logger.info(f"書き込み完了: {file_path}")
    return file_path


def _make_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


def fetch_thread_via_api(session: requests.Session, channel_id: str, message_ts: str) -> list[dict]:
    messages: list[dict] = []
    cursor = None
    while True:
        params = {"channel": channel_id, "ts": message_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = session.get(f"{SLACK_API_BASE}/conversations.replies", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise SlackApiError(data.get("error", "unknown_error"))
        messages.extend(data.get("messages", []))
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    return messages


def resolve_users_via_api(session: requests.Session, user_ids: set[str]) -> dict[str, str]:
    result = {}
    for user_id in user_ids:
        resp = session.get(f"{SLACK_API_BASE}/users.info", params={"user": user_id}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            continue
        profile = data.get("user", {}).get("profile", {})
        result[user_id] = profile.get("display_name") or profile.get("real_name") or user_id
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Slackスレッドを取得し、OKF形式のMarkdownとして保存する。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/slack_thread_fetcher.py https://ws.slack.com/archives/C1/p123 --mcp-json raw.json\n"
            "  uv run scripts/slack_thread_fetcher.py https://ws.slack.com/archives/C1/p123 -o .\n"
        ),
    )
    parser.add_argument("thread_urls", nargs="+", metavar="SLACK_THREAD_URL", help="取得対象のSlackスレッドURL(複数指定可)")
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="OKF出力先ディレクトリ")
    parser.add_argument("--mcp-json", metavar="PATH", default=None, help="MCPツールで取得済みのJSON({messages, users})。指定時はURL1件のみ")
    args = parser.parse_args()

    if args.mcp_json and len(args.thread_urls) != 1:
        parser.error("--mcp-json は SLACK_THREAD_URL を1つだけ指定した場合のみ使用できます")

    output_dir = Path(args.output)

    if args.mcp_json:
        url = args.thread_urls[0]
        raw_path = Path(args.mcp_json)
        try:
            ref = parse_slack_url(url)
            data = json.loads(raw_path.read_text(encoding="utf-8"))
            messages = normalize_messages(data["messages"], data.get("users", {}))
            write_thread(output_dir, ref["channel_id"], url, messages)
            raw_path.unlink(missing_ok=True)
        except (ValueError, KeyError) as e:
            logger.warning(f"スレッド取得失敗: {url}: {e}")
            sys.exit(1)
        return

    token = os.getenv("SLACK_API_TOKEN")
    if not token:
        logger.error("環境変数 SLACK_API_TOKEN が設定されていません")
        sys.exit(1)
    session = _make_session(token)

    fetched = []
    for url in args.thread_urls:
        try:
            ref = parse_slack_url(url)
            raw_messages = fetch_thread_via_api(session, ref["channel_id"], ref["message_ts"])
            user_ids = {m.get("user") or m.get("bot_id") or "unknown" for m in raw_messages}
            user_map = resolve_users_via_api(session, user_ids)
            messages = normalize_messages(raw_messages, user_map)
            write_thread(output_dir, ref["channel_id"], url, messages)
            fetched.append(url)
        except (ValueError, SlackApiError, requests.HTTPError) as e:
            logger.warning(f"スレッド取得失敗: {url}: {e}, スキップ")

    logger.info(f"完了: {len(fetched)}/{len(args.thread_urls)} 件取得")
    if len(fetched) < len(args.thread_urls):
        sys.exit(1)


if __name__ == "__main__":
    main()
