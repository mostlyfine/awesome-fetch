---
name: spreadsheet
description: >
  GoogleスプレッドシートのデータをCSV化してローカルに保存する。
  「このスプレッドシート取得して」「Google Sheetsのデータをcsvにして」「このシートの内容を確認して」など、
  Google SheetsのURL(https://docs.google.com/spreadsheets)やスプレッドシートIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# Spreadsheet Fetcher スキル

実際のスプレッドシート取得・保存処理は `spreadsheet-fetcher` エージェントが担当する。このスキルは対象スプレッドシートの特定と、エージェントへの委譲のみを行う。

## Step 1: 対象スプレッドシートの特定

会話中のURLやIDからスプレッドシートを特定する。

- **URLが与えられた場合**: `https://docs.google.com/spreadsheets/d/<spreadsheetId>/...` の形式からIDを抽出する（エージェントにURLをそのまま渡してもよい）
- **IDのみ与えられた場合**: そのまま使う
- **どちらも無い場合**: スプレッドシートのURLまたはIDをユーザーに確認する
- 特定シートのみ欲しい場合はシート名を確認する（省略時は全シート取得）

## Step 2: spreadsheet-fetcher エージェントへの委譲

Task tool で `spreadsheet-fetcher` エージェントを呼び出し、Step 1で特定したスプレッドシートのURL/ID（複数可）・シート名の絞り込みと、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
