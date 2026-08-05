#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
#   "google-auth==2.35.0",
# ]
# ///

"""Google スプレッドシートの各シートをCSVファイルとしてダウンロードする。

■ 認証
  Application Default Credentials (ADC) を使用する。事前に以下を実行しておくこと。

    gcloud auth application-default login \\
      --scopes "https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly"

■ 使い方
  uv run scripts/google_sheets_fetcher.py <SPREADSHEET_URL_OR_ID> [<SPREADSHEET_URL_OR_ID> ...] \\
    [--sheets Sheet1,Sheet2] [-o docs/google-sheets]
"""

import argparse
import csv
import logging
import re
import sys
from pathlib import Path

import requests
from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.auth.transport.requests import AuthorizedSession

logger = logging.getLogger(__name__)

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')
_SPREADSHEET_ID_RE = re.compile(r"/d/([a-zA-Z0-9-_]+)")


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def extract_spreadsheet_id(url_or_id: str) -> str:
    match = _SPREADSHEET_ID_RE.search(url_or_id)
    return match.group(1) if match else url_or_id


def get_credentials():
    try:
        credentials, _ = google_auth_default()
    except DefaultCredentialsError as e:
        raise RuntimeError(
            "Application Default Credentials の取得に失敗しました。"
            '`gcloud auth application-default login --scopes '
            '"https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly"` '
            f"を実行してください: {e}"
        ) from e
    return credentials


def _api_get(session: requests.Session, spreadsheet_id: str, params: dict) -> dict:
    response = session.get(f"{SHEETS_API_BASE}/{spreadsheet_id}", params=params)
    response.raise_for_status()
    return response.json()


def fetch_spreadsheet_meta(session: requests.Session, spreadsheet_id: str) -> dict:
    return _api_get(
        session, spreadsheet_id, {"fields": "properties.title,sheets.properties(sheetId,title)"}
    )


def fetch_sheet_grid_data(session: requests.Session, spreadsheet_id: str, sheet_title: str) -> list[list[str]]:
    escaped_title = sheet_title.replace("'", "''")
    params = {
        "ranges": f"'{escaped_title}'",
        "fields": "sheets.data.rowData.values(formattedValue,effectiveFormat.textFormat.strikethrough)",
    }
    data = _api_get(session, spreadsheet_id, params)

    try:
        row_data = data["sheets"][0]["data"][0]["rowData"]
    except (KeyError, IndexError):
        row_data = []

    rows = []
    for row in row_data:
        row_values = []
        for cell in row.get("values", []):
            value = cell.get("formattedValue", "")
            strikethrough = cell.get("effectiveFormat", {}).get("textFormat", {}).get("strikethrough", False)
            row_values.append(f"~~{value}~~" if value and strikethrough else value)
        rows.append(row_values)

    while rows and not rows[-1]:
        rows.pop()
    return rows


def save_csv(output_dir: str, title: str, sheet_title: str, rows: list[list[str]]) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filename = f"{sanitize_filename(title)}_{sanitize_filename(sheet_title)}.csv"
    filepath = output_path / filename
    with filepath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return str(filepath)


def process_spreadsheet(
    session: requests.Session,
    url_or_id: str,
    output_dir: str,
    sheet_filter: set[str] | None,
) -> tuple[int, int]:
    saved = skipped = 0
    spreadsheet_id = extract_spreadsheet_id(url_or_id)
    try:
        meta = fetch_spreadsheet_meta(session, spreadsheet_id)
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        logger.warning(f"スプレッドシート取得失敗: {spreadsheet_id}: {e}: {body}, skipping")
        return saved, skipped + 1

    title = meta.get("properties", {}).get("title", spreadsheet_id)
    sheets = meta.get("sheets", [])

    for sheet in sheets:
        sheet_title = sheet.get("properties", {}).get("title", "")
        if sheet_filter and sheet_title not in sheet_filter:
            continue
        try:
            rows = fetch_sheet_grid_data(session, spreadsheet_id, sheet_title)
            path = save_csv(output_dir, title, sheet_title, rows)
            logger.info(f"書き込み完了: {path}")
            saved += 1
        except requests.HTTPError as e:
            logger.warning(f"シート取得失敗: {sheet_title}: {e}, skipping")
            skipped += 1

    return saved, skipped


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Google スプレッドシートの各シートをCSVファイルとしてダウンロードする。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run scripts/google_sheets_fetcher.py https://docs.google.com/spreadsheets/d/XXXX/edit -o .\n"
            "  uv run scripts/google_sheets_fetcher.py XXXX --sheets Sheet1,Sheet2\n"
        ),
    )
    parser.add_argument("spreadsheets", nargs="+", metavar="SPREADSHEET_URL_OR_ID", help="対象スプレッドシートのURLまたはID")
    parser.add_argument("--sheets", default=None, help="取得対象シート名のカンマ区切り（省略時は全シート）")
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="出力先ディレクトリ")
    args = parser.parse_args()

    sheet_filter = set(s.strip() for s in args.sheets.split(",")) if args.sheets else None

    try:
        credentials = get_credentials()
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    session = AuthorizedSession(credentials)

    stats = {"saved": 0, "skipped": 0}

    try:
        for url_or_id in args.spreadsheets:
            logger.info(f"Fetching spreadsheet: {url_or_id}")
            saved, skipped = process_spreadsheet(session, url_or_id, args.output, sheet_filter)
            stats["saved"] += saved
            stats["skipped"] += skipped
    except RefreshError as e:
        logger.error(f"ADCの認証が無効です。再ログインしてください: {e}")
        sys.exit(1)

    logger.info(f"Done. {stats['saved']} sheets saved, {stats['skipped']} skipped.")


if __name__ == "__main__":
    main()
