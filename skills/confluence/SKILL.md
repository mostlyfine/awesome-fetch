---
name: confluence
description: >
  ConfluenceのページをMarkdown化してローカルに保存する。
  「Confluenceのこのページ取得して」「このURLの内容をMarkdownにして」「Confluenceページをダウンロードして」
  「このConfluenceページの内容を要約して」など、confluence のURLやページIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Bash Write Read AskUserQuestion mcp__claude_ai_Atlassian__getAccessibleAtlassianResources mcp__claude_ai_Atlassian__getConfluencePage
---

# Confluence Fetcher スキル

対象ページの特定から取得・保存までを一貫して行う。

## Step 1: 対象ページの特定

ユーザーの発言からページを特定する。

- **URLが与えられた場合**: URLからページIDを抽出する
  - Cloud形式: `.../pages/<pageId>/...` → 数字部分がID
  - 社内Confluence形式: `...viewpage.action?pageId=<pageId>` → `pageId=` の数字部分がID
- **ページIDのみ与えられた場合**: そのまま使う
- **どちらも無い場合**: ページURLまたはIDをユーザーに確認する

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

## Step 2: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、confluenceの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/confluence`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のconfluenceの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step 3: 取得経路の判定（MCP優先→トークンフォールバック）

1. まず引数なしで `getAccessibleAtlassianResources` を呼ぶ。成功し、対象ページのURL（またはベースURL）のホスト名と一致するサイトが結果に含まれれば claude.ai のAtlassian連携が使える → **MCP経路（Step 4-A）**。一致したサイトの `id`（cloudId）を控えておく
2. 失敗した場合、ツールが使えない場合、または一致するサイトが無い場合は、環境変数 `CONFLUENCE_API_TOKEN` の設定有無を確認する:
   ```bash
   echo "CONFLUENCE_API_TOKEN set: ${CONFLUENCE_API_TOKEN:+yes} / CONFLUENCE_EMAIL set: ${CONFLUENCE_EMAIL:+yes}"
   ```
   設定済みなら **トークン経路（Step 4-B）**
3. どちらも使えない場合、ユーザーに次のいずれかを依頼する:
   - claude.aiでAtlassian連携を有効化する（Settings > Connectors > Atlassian）。対象がAtlassian Cloud（`*.atlassian.net`）でない場合はこの経路は使えない
   - トークンを発行し `export CONFLUENCE_API_TOKEN=<token>` を実行する（Cloudの場合はさらに `export CONFLUENCE_EMAIL=<email>` も必要）

ベースURLは `--url` 省略時 `CONFLUENCE_URL` 環境変数が使われる（MCP経路でもfrontmatterの`resource`用に必要）。

## Step 4-A: 実行（MCP経路）

**MCP経路は指定ページ単体のみ対応。子ページの再帰取得（`--depth`）が必要な場合はStep 4-Bのトークン経路を使う。**

1. `getConfluencePage(cloudId=<Step 3で控えたcloudId>, pageId=<page-id>, body-format="storage")` を呼ぶ
2. 返ってきたJSON（`title`、`body.storage.value`等を含む想定）をそのまま一時ファイル（`<output-dir>/.raw/<page-id>.json`）に `Write` する
3. 次のコマンドを実行する（スクリプトはネットワークアクセスせず、渡されたJSONを整形・保存する）:
   ```bash
   uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/confluence_downloader.py \
     --url https://your-domain.atlassian.net/ \
     --page-id <page-id> \
     --mcp-json <tmp.json> \
     -o <output-dir>
   ```

## Step 4-B: 実行（トークン経路）

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/confluence_downloader.py \
  --url https://your-domain.atlassian.net/ \
  --page-id <page-id> \
  -o <output-dir>
```

子ページも再帰的に取得したい場合のみ `--depth <N>` を追加する（デフォルトは0=指定ページのみ）。取得間隔を調整したい場合は `--wait <秒数>`（デフォルト1.0秒）。

## Step 5: 結果報告

コマンド出力の `Saved: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。取得に失敗した場合は失敗理由を報告する:
- MCP経路: Atlassian連携の認可状態、対象ページへのアクセス権限を疑う
- トークン経路: ページID・権限・ネットワーク到達性を疑う

## 補足

- 出力Markdownの先頭には `type` / `title` / `resource`（元ページURL）/ `timestamp` / `references`（リンク先ページIDの一覧）の frontmatter が自動で付与される
- 既存ファイルは上書きされる。再取得（最新化）したい場合もそのまま同じコマンドを再実行すればよい
- MCP経路はAtlassian Cloud（`*.atlassian.net`）のみ対応かつ子ページ再帰取得非対応。自社ホストのConfluence Server/Data Center、または子ページの再帰取得が必要な場合はトークン経路を使う
