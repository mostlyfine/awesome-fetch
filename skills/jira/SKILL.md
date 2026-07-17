---
name: jira
description: >
  JIRA（Server/Data Center）のissueをMarkdown化してローカルに保存する。
  「JIRAのこのissue取得して」「PROJ-123の内容を見せて」「このJIRAチケットを要約して」
  issueキー（例: DEV-12802）やJIRAのissue URLが会話に出てきた場合は必ずこのスキルを使う。
  また「JIRAでこの条件のissueを検索して」「JQLで検索して」「プロジェクトXのオープンなissue一覧が欲しい」
  のようなJQLでの横断検索の依頼にも使う。
allowed-tools: Bash Write Read AskUserQuestion mcp__claude_ai_Atlassian__getAccessibleAtlassianResources mcp__claude_ai_Atlassian__getJiraIssue mcp__claude_ai_Atlassian__searchJiraIssuesUsingJql
---

# JIRA Fetcher スキル

issue取得とJQL検索の2つのワークフローを持ち、ユーザーの発言からどちらを実行するかを判断し、対象の特定から取得・保存（または一覧提示）までを一貫して行う。

## Step 1: 対象の特定

ユーザーの発言から、issue取得かJQL検索かを判定し、対象を特定する。

### issueキー・URLが読み取れる場合（issue取得）

- **issueキーが直接与えられた場合**（例: `DEV-12802`）: そのまま使う
- **issue URLが与えられた場合**: 末尾のissueキー部分を抽出する
  - 例: `https://your-domain.atlassian.net/browse/DEV-1234` → `DEV-1234`
- **どちらも無い場合**: issueキーまたはURLをユーザーに確認する

→ 特定できたら「ワークフローA: issue取得」に進む。

### 検索条件が読み取れる場合（JQL検索）

- ユーザーがJQLをそのまま指定した場合はそれを使う
- 自然文の条件（プロジェクト・ステータス・担当者・期間など）の場合は、それらからJQLを組み立てて提案し、実行前にユーザーに確認する
- 組み立て方が分からない場合は `${CLAUDE_PLUGIN_ROOT:-.}/skills/jira/references/jql-cheatsheet.md` を参照する
- 保存が必要か（デフォルトは非保存、一覧を提示するのみ）をユーザーの発言から判断する。「保存して」「ファイルにして」等の明示的な指示があれば保存要と判断する

→ 特定できたら「ワークフローB: issue検索（JQL）」に進む。

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

---

# ワークフローA: issue取得

`${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_fetcher.py` を使い、JIRA issueの詳細とコメントをOKF形式（frontmatter付き）のMarkdownとして保存する。

## Step A1: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、jiraの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/jira`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のjiraの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step A2: 取得経路の判定（MCP優先→トークンフォールバック）

1. まず引数なしで `getAccessibleAtlassianResources` を呼ぶ。成功し、対象issueのURL（またはベースURL）のホスト名と一致するサイトが結果に含まれれば claude.ai のAtlassian連携が使える → **MCP経路（Step A3-A）**。一致したサイトの `id`（cloudId）を控えておく
2. 失敗した場合、ツールが使えない場合、または一致するサイトが無い場合は、環境変数 `JIRA_API_TOKEN` の設定有無を確認する:
   ```bash
   echo "JIRA_API_TOKEN set: ${JIRA_API_TOKEN:+yes}"
   ```
   設定済みなら **トークン経路（Step A3-B）**
3. どちらも使えない場合、ユーザーに次のいずれかを依頼する:
   - claude.aiでAtlassian連携を有効化する（Settings > Connectors > Atlassian）。対象がAtlassian Cloud（`*.atlassian.net`）でない場合はこの経路は使えない
   - Personal Access Tokenを発行し `export JIRA_API_TOKEN=<token>` を実行する

ベースURLは `--url` 省略時 `JIRA_URL` 環境変数が使われる（MCP経路でもfrontmatterの`resource`用に必要）。

## Step A3-A: 実行（MCP経路）

対象issueキーごとに以下を繰り返す。

1. `getJiraIssue(cloudId=<Step A2で控えたcloudId>, issueIdOrKey=<ISSUE_KEY>)` を呼ぶ
2. 返ってきたJSON（Jira Cloud REST API v3形式のissue、`fields.description`はADF、コメントは`fields.comment.comments`に含まれる想定）をそのまま一時ファイル（`<output-dir>/.raw/<ISSUE_KEY>.json`）に `Write` する
3. 次のコマンドを実行する（スクリプトはネットワークアクセスせず、渡されたJSONを整形・保存する）:
   ```bash
   uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_fetcher.py <ISSUE_KEY> -o <output-dir> --mcp-json <tmp.json> --url <base-url>
   ```

## Step A3-B: 実行（トークン経路）

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_fetcher.py <ISSUE_KEY> [<ISSUE_KEY> ...] \
  -o <output-dir>
```

複数issueをまとめて取得したい場合はissueキーをスペース区切りで並べる（トークン経路のみ、MCP経路は1件ずつ実行する）。特定フィールドのみ欲しい場合は `--fields summary,status` のように指定する（省略時は全フィールド）。ベースURLを明示したい場合は `--url` を追加する。

## Step A4: 結果報告

コマンド出力の `書き込み完了: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。更新がなく処理がスキップされた場合は `更新なし: スキップ (<path>)` が出力されるため、その場合も既存ファイルのパスを報告する。取得に失敗した場合は失敗理由を報告する:
- MCP経路: Atlassian連携の認可状態、対象issueへのアクセス権限を疑う
- トークン経路: issueキー・権限・ネットワーク到達性を疑う

## 補足（issue取得）

- 出力先ディレクトリには `{ISSUE_KEY}.md`（issue本体）が生成される
- 出力Markdownの先頭には `type` / `title` / `resource`（issueのbrowse URL）/ `tags` / `timestamp` の frontmatter が自動で付与される
- description・コメント本文はADF（Atlassian Document Format）/プレーンテキストのいずれでも自動でプレーンテキストに変換される
- issueに更新がなければ処理をスキップする（既存ファイルはそのまま保持される）。更新があれば自動的に再取得・上書きされる。更新の有無に関わらず強制的に再取得・上書きしたい場合は `--force` を付与する
- MCP経路はAtlassian Cloud（`*.atlassian.net`）のみ対応。自社ホストのJIRA Server/Data Centerはトークン経路のみ利用できる

---

# ワークフローB: issue検索（JQL）

`${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_search.py` を使い、JQLでの検索結果一覧を表示する。個別issueの詳細本文は取得しない（一覧のみ）。

**デフォルトではファイルに保存せず、検索結果の一覧表をそのままユーザーに返すだけにする。保存するのは、ユーザーが「保存して」「ファイルにして」等と明示した場合のみ。**

## Step B1: JQLの組み立て

- Step 1でJQLがそのまま特定できた場合はそれを使う
- 自然文の条件（プロジェクト・ステータス・担当者・期間など）しか無い場合は、それらからJQLを組み立てて提案し、実行前にAskUserQuestionでユーザーに確認する
- 組み立て方が分からない場合は `${CLAUDE_PLUGIN_ROOT:-.}/skills/jira/references/jql-cheatsheet.md` を参照する

## Step B2: 取得経路の判定

ワークフローAのStep A2と同じ判定を行う（`getAccessibleAtlassianResources` によるcloudId解決→MCP経路、失敗時は `JIRA_API_TOKEN` / `JIRA_URL` を使うトークン経路）。

## Step B3: 実行

### MCP経路

1. `searchJiraIssuesUsingJql(cloudId=<Step B2で控えたcloudId>, jql=<JQL>, fields=<--fieldsに対応する値>, maxResults=<--max-resultsに対応する値>)` を呼ぶ
2. 返ってきたJSON（`{"issues": [...]}` 形式想定）をそのまま一時ファイル（`<output-dir-or-scratchpad>/.raw/jira-search.json`）に `Write` する
3. 次のコマンドを実行する:
   ```bash
   uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_search.py --jql "<JQL>" --mcp-json <tmp.json> --url <base-url>
   ```
   保存する場合は `-o <output-dir>` を追加する

### トークン経路

デフォルト（保存しない場合）は `-o` を付けずに実行する。

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_search.py --jql "<JQL>"
```

標準出力に表示されたMarkdownの表をそのままユーザーに返す。

保存指示がある場合のみ、Step A1と同じ手順（Claude Memoryの `fetcher_output_dirs.md` の `jira` 行を参照、未指定なら処理開始前にAskUserQuestionで確認し `docs/jira` を推奨デフォルトとして提示）で出力先を確認し、`-o <output-dir>` を付けて実行する。

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/jira_issue_search.py --jql "<JQL>" \
  -o <output-dir>
```

いずれの経路でも保存の要否判断は同じ（デフォルト非保存、ユーザーからの保存指示がある場合のみ保存）。

いずれの場合も、必要に応じて `--fields summary,status` のように取得フィールドを絞り込める（省略時は `summary,status,issuetype,assignee,updated`）。結果件数が多い場合は `--max-results <N>`（省略時50件）で上限を調整する。ベースURLを明示したい場合は `--url` を追加する。

## Step B4: 結果報告

- 保存しない場合: 標準出力の表とヒット件数をそのままユーザーに報告する
- 保存する場合: コマンド出力の `書き込み完了: <path>` からファイルパスとヒット件数を確認し、ユーザーに報告する

いずれの場合も、ヒットしたissueの詳細本文が必要な場合はissueキーを指定してワークフローAを実行するよう案内する。検索失敗のログが出た場合はJQLの構文・権限・ネットワーク到達性を疑い、その旨を失敗理由として報告する。

## 補足（検索）

- 保存時のファイル名は `jira-search-{YYYYMMDD-HHMMSS}.md`（同じJQLで再実行しても上書きされず履歴が残る）
- 結果には検索に使ったJQL・該当件数・`Key/Summary/Status/Type/Assignee/Updated` の一覧表が含まれる
