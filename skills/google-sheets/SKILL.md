---
name: google-sheets
description: >
  GoogleスプレッドシートのデータをCSV化してローカルに保存する。
  「このスプレッドシート取得して」「Google Sheetsのデータをcsvにして」「このシートの内容を確認して」など、
  Google SheetsのURL(https://docs.google.com/spreadsheets)やスプレッドシートIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Bash Read AskUserQuestion
---

# Google Sheets Fetcher スキル

対象スプレッドシートの特定から取得・保存までを一貫して行う。

## Step 1: 対象スプレッドシートの特定

会話中のURLやIDからスプレッドシートを特定する。

- **URLが与えられた場合**: `https://docs.google.com/spreadsheets/d/<spreadsheetId>/...` の形式からIDを抽出する
- **IDのみ与えられた場合**: そのまま使う
- **どちらも無い場合**: スプレッドシートのURLまたはIDをユーザーに確認する
- 特定シートのみ欲しい場合はシート名を確認する（省略時は全シート取得）

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

## Step 2: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、google-sheetsの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/google-sheets`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のgoogle-sheetsの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step 3: 認証情報の確認

スクリプトは Application Default Credentials (ADC) を使う（APIトークンのexportは不要）。

```bash
gcloud auth application-default print-access-token >/dev/null 2>&1 && echo "ADC set: yes" || echo "ADC set: no"
```

- `ADC set: no` の場合、ユーザーに以下の実行を依頼する

```bash
gcloud auth application-default login \
  --scopes "https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly"
```

ADCがあってもquota project（課金・クォータの計上先GCPプロジェクト）が未設定だと、Sheets APIへのアクセスが `PERMISSION_DENIED` (`SERVICE_DISABLED`) で拒否される。Claude Memoryの `google_sheets_fetcher_quota_project.md` に過去に動作確認済みのプロジェクトIDが記録されていれば候補として提示する（記録が無ければユーザーに尋ねる）。いずれの場合も、以下のコマンドはユーザー環境の認証設定を変更するため、実行前に毎回ユーザーの許可を得る。

```bash
gcloud auth application-default set-quota-project <PROJECT_ID>
```

そのプロジェクトでGoogle Sheets APIが有効化されていない場合は `SERVICE_DISABLED` エラーになるので、その場合は表示されるAPI有効化用URLをユーザーに共有する。動作確認できたプロジェクトIDは `google_sheets_fetcher_quota_project.md` に記録しておく（次回以降もコマンド実行前の確認自体は毎回行う）。

## Step 4: 実行

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/google_sheets_fetcher.py <SPREADSHEET_URL_OR_ID> [<SPREADSHEET_URL_OR_ID> ...] \
  [--sheets Sheet1,Sheet2] \
  -o <output-dir>
```

複数スプレッドシートをまとめて取得したい場合はURL/IDをスペース区切りで並べる。特定シートのみ欲しい場合は `--sheets` にシート名をカンマ区切りで指定する（省略時は全シート）。

## Step 5: 結果報告

コマンド出力の `書き込み完了: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。`スプレッドシート取得失敗` / `シート取得失敗` のログが出た場合は、URL・IDの形式、ADCの認証状態、対象スプレッドシートへのアクセス権限（閲覧権限があるGoogleアカウントでログインしているか）を疑い、その旨を失敗理由として報告する。

## 補足

- 出力先ディレクトリには `{title}_{sheetname}.csv`（シートごとに1ファイル）が生成される。`title` はスプレッドシートのタイトル、`sheetname` は各シート名（いずれもファイル名として使えない文字は `_` に置換）
- セルの値は表示形式のまま（FORMATTED_VALUE）取得する。数式は評価済みの値になる
- 取り消し線（strikethrough）が付いたセルは、値を `~~text~~` のようにMarkdown記法でラップして出力する（テーマや条件付き書式による見た目上の取り消し線も反映される。値が空のセルはラップされない）
- 既存ファイルは上書きされる。再取得（最新化）したい場合もそのまま同じコマンドを再実行すればよい
