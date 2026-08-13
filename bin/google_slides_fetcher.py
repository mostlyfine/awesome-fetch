#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests==2.32.3",
#   "google-auth==2.35.0",
# ]
# ///

"""Google プレゼンテーション(Google スライド)をPDFファイルとしてダウンロードする。

■ 認証
  Application Default Credentials (ADC) を使用する。事前に以下を実行しておくこと。

    gcloud auth application-default login \\
      --scopes "https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly"

■ 使い方
  uv run bin/google_slides_fetcher.py <PRESENTATION_URL_OR_ID> [<PRESENTATION_URL_OR_ID> ...] \\
    [-o docs/google-slides]
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import requests
from google.auth import default as google_auth_default
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.auth.transport.requests import AuthorizedSession

logger = logging.getLogger(__name__)

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"
_SANITIZE_RE = re.compile(r'[\\/:*?"<>|\s]+')
_PRESENTATION_ID_RE = re.compile(r"/presentation/d/([a-zA-Z0-9-_]+)")


def sanitize_filename(name: str) -> str:
    result = _SANITIZE_RE.sub("_", name).strip("_")
    return result or "untitled"


def extract_presentation_id(url_or_id: str) -> str:
    match = _PRESENTATION_ID_RE.search(url_or_id)
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


def fetch_presentation_title(session: requests.Session, presentation_id: str) -> str:
    response = session.get(f"{DRIVE_API_BASE}/{presentation_id}", params={"fields": "name"})
    response.raise_for_status()
    return response.json().get("name", presentation_id)


def fetch_presentation_pdf(session: requests.Session, presentation_id: str) -> bytes:
    response = session.get(
        f"{DRIVE_API_BASE}/{presentation_id}/export", params={"mimeType": "application/pdf"}
    )
    response.raise_for_status()
    return response.content


def save_pdf(output_dir: str, title: str, content: bytes) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filepath = output_path / f"{sanitize_filename(title)}.pdf"
    filepath.write_bytes(content)
    return str(filepath)


def process_presentation(session: requests.Session, url_or_id: str, output_dir: str) -> bool:
    presentation_id = extract_presentation_id(url_or_id)
    try:
        title = fetch_presentation_title(session, presentation_id)
        content = fetch_presentation_pdf(session, presentation_id)
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        logger.warning(f"プレゼンテーション取得失敗: {presentation_id}: {e}: {body}, skipping")
        return False

    path = save_pdf(output_dir, title, content)
    logger.info(f"書き込み完了: {path}")
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Google プレゼンテーション(Google スライド)をPDFファイルとしてダウンロードする。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例:\n"
            "  uv run bin/google_slides_fetcher.py https://docs.google.com/presentation/d/XXXX/edit -o .\n"
            "  uv run bin/google_slides_fetcher.py XXXX -o docs/google-slides\n"
        ),
    )
    parser.add_argument(
        "presentations", nargs="+", metavar="PRESENTATION_URL_OR_ID", help="対象プレゼンテーションのURLまたはID"
    )
    parser.add_argument("-o", "--output", metavar="DIR", default=".", help="出力先ディレクトリ")
    args = parser.parse_args()

    try:
        credentials = get_credentials()
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    session = AuthorizedSession(credentials)

    stats = {"saved": 0, "skipped": 0}

    try:
        for url_or_id in args.presentations:
            logger.info(f"Fetching presentation: {url_or_id}")
            if process_presentation(session, url_or_id, args.output):
                stats["saved"] += 1
            else:
                stats["skipped"] += 1
    except RefreshError as e:
        logger.error(f"ADCの認証が無効です。再ログインしてください: {e}")
        sys.exit(1)

    logger.info(f"Done. {stats['saved']} presentations saved, {stats['skipped']} skipped.")


if __name__ == "__main__":
    main()
