---
name: confluence
description: >
  ConfluenceのページをMarkdown化してローカルに保存する。
  「Confluenceのこのページ取得して」「このURLの内容をMarkdownにして」「Confluenceページをダウンロードして」
  「このConfluenceページの内容を要約して」など、confluence のURLやページIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Bash Write Read AskUserQuestion
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

## Step 3: 認証情報の確認

環境変数 `CONFLUENCE_API_TOKEN` の設定有無を確認する:
```bash
echo "CONFLUENCE_API_TOKEN set: ${CONFLUENCE_API_TOKEN:+yes} / CONFLUENCE_EMAIL set: ${CONFLUENCE_EMAIL:+yes}"
```
未設定の場合は、ユーザーにトークンを発行し `export CONFLUENCE_API_TOKEN=<token>` を実行するよう依頼する（Confluence Cloudの場合はさらに `export CONFLUENCE_EMAIL=<email>` も必要）。

ベースURLは `--url` 省略時 `CONFLUENCE_URL` 環境変数が使われる。

## Step 4: 実行

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/confluence_fetcher.py \
  --url https://your-domain.atlassian.net/ \
  --page-id <page-id> \
  -o <output-dir>
```

複数ページを取得したい場合は `--page-id`（`-p`）を繰り返し指定する。子ページも再帰的に取得したい場合は `--depth <N>` を追加する（デフォルトは0=指定ページのみ）。取得間隔を調整したい場合は `--wait <秒数>`（デフォルト1.0秒）。

## Step 5: 結果報告

コマンド出力の `Saved: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。取得に失敗した場合はページID・権限・ネットワーク到達性を疑う。

## 補足

- 出力Markdownの先頭には `type` / `title` / `resource`（元ページURL）/ `timestamp` / `references`（リンク先ページIDの一覧）の frontmatter が自動で付与される
- 既存ファイルは上書きされる。再取得（最新化）したい場合もそのまま同じコマンドを再実行すればよい
