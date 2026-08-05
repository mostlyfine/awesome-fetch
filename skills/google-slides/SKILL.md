---
name: google-slides
description: >
  Googleプレゼンテーション(Google スライド)をPDF化してローカルに保存する。
  「このプレゼン資料をPDFで保存して」「Google SlidesをPDFにして」「このプレゼンテーションの内容を確認して」など、
  Google Presentation/SlidesのURL(https://docs.google.com/presentation)やプレゼンテーションIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Bash Read AskUserQuestion mcp__claude_ai_Google_Drive__get_file_metadata mcp__claude_ai_Google_Drive__download_file_content
---

# Google Slides Fetcher スキル

対象プレゼンテーションの特定から取得・保存までを一貫して行う。

## Step 1: 対象プレゼンテーションの特定

会話中のURLやIDからプレゼンテーションを特定する。

- **URLが与えられた場合**: `https://docs.google.com/presentation/d/<presentationId>/...` の形式からIDを抽出する
- **IDのみ与えられた場合**: そのまま使う
- **どちらも無い場合**: プレゼンテーションのURLまたはIDをユーザーに確認する

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

取得経路は2段構え。**claude.aiのGoogle Driveコネクタ（MCPツール）を優先し、使えない場合のみADC経由の`google_slides_fetcher.py`にフォールバックする。**

## Step 2: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、google-slidesの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/google-slides`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のgoogle-slidesの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step 3: 取得経路の判定（MCP優先→ADCフォールバック）

1. 最初の1件について `mcp__claude_ai_Google_Drive__get_file_metadata`（`fileId`＝URL/IDから抽出したプレゼンテーションID）を呼ぶ。成功すれば claude.ai の Google Drive 連携が使える → **MCP経路（Step 4-A）**
2. 失敗した場合、またはそもそもこのMCPツールが使えない場合（コネクタ未接続、headless/cron実行、codex/Copilot等の他ハーネスから呼ばれている等）は **ADC経路（Step 4-B）** にフォールバックする

## Step 4-A: 実行（MCP経路）

セットアップ不要（claude.aiの認証をそのまま利用、ADC/gcloud/quota projectの設定は一切不要）。対象プレゼンテーションごとに以下を繰り返す。

1. Step 3で取得済みの`title`を使う（2件目以降は`get_file_metadata`を都度呼ぶ）
2. `mcp__claude_ai_Google_Drive__download_file_content` を `fileId` と `exportMimeType: "application/pdf"` で呼び出し、PDFのbase64コンテンツ(`content`フィールド)を取得する
   - レスポンスが大きく直接返らない場合、ツール結果は自動的に `{content, id, mimeType, title}` 形式のJSONファイルに保存され、そのパスが案内される。この場合はbase64文字列を自分のコンテキストに読み込まず、Bash経由で `jq -r '.content' <保存先パス> | base64 -d > <output-dir>/<title>.pdf` のように直接ファイルへデコード・保存する
   - レスポンスがそのまま返った場合は `content` の値をbase64デコードして同様に保存する
3. 個別のファイルで失敗した場合（`fileId`が見つからない、権限が無い等）はStep 4-Bへのフォールバックは行わず、失敗理由をそのまま結果報告に含める（MCP経路が選べる状況で個別ファイルが失敗した場合は、アクセス権限やID指定の誤りが原因であることが多く、経路を変えても解決しないため）

## Step 4-B: 実行（ADC経路）

MCP Google Driveコネクタが使えない環境向け。Application Default Credentials (ADC) を使う。

```bash
gcloud auth application-default print-access-token >/dev/null 2>&1 && echo "ADC set: yes" || echo "ADC set: no"
```

- `ADC set: no` の場合、ユーザーに以下の実行を依頼する

```bash
gcloud auth application-default login \
  --scopes "https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive.readonly"
```

ADCがあってもquota project（課金・クォータの計上先GCPプロジェクト）が未設定だと、Drive APIへのアクセスが `PERMISSION_DENIED` (`SERVICE_DISABLED`) で拒否される。Claude Memoryの `google_slides_fetcher_quota_project.md` に過去に動作確認済みのプロジェクトIDが記録されていれば候補として提示する（記録が無ければユーザーに尋ねる。Sheets APIとは別のAPIのため、`google_sheets_fetcher_quota_project.md` の値を流用する場合はGoogle Drive APIが同一プロジェクトで有効化済みか確認すること）。いずれの場合も、以下のコマンドはユーザー環境の認証設定を変更するため、実行前に毎回ユーザーの許可を得る。

```bash
gcloud auth application-default set-quota-project <PROJECT_ID>
```

そのプロジェクトでGoogle Drive APIが有効化されていない場合は `SERVICE_DISABLED` エラーになるので、その場合は表示されるAPI有効化用URLをユーザーに共有する。動作確認できたプロジェクトIDは `google_slides_fetcher_quota_project.md` に記録しておく（次回以降もコマンド実行前の確認自体は毎回行う）。

認証確認後、実行する:

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/google_slides_fetcher.py <PRESENTATION_URL_OR_ID> [<PRESENTATION_URL_OR_ID> ...] \
  -o <output-dir>
```

複数プレゼンテーションをまとめて取得したい場合はURL/IDをスペース区切りで並べる。

## Step 5: 結果報告

コマンド出力の `書き込み完了: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。取得に失敗した場合は失敗理由を報告する:
- MCP経路: ファイルID/URLの誤り、対象プレゼンテーションへのアクセス権限（閲覧権限があるGoogleアカウントでコネクタが認証されているか）を疑う
- ADC経路: URL・IDの形式、ADCの認証状態、対象プレゼンテーションへのアクセス権限、Drive APIのエクスポートサイズ上限（10MB）超過の可能性を疑う

## 補足

- 出力先ディレクトリには `{title}.pdf`（プレゼンテーションごとに1ファイル）が生成される。`title` はプレゼンテーションのタイトル（ファイル名として使えない文字は `_` に置換）
- 既存ファイルは上書きされる。再取得（最新化）したい場合もそのまま同じコマンドを再実行すればよい
