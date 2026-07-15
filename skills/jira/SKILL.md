---
name: jira
description: >
  JIRA（Server/Data Center）のissueをMarkdown化してローカルに保存する。
  「JIRAのこのissue取得して」「PROJ-123の内容を見せて」「このJIRAチケットを要約して」
  issueキー（例: DEV-12802）やJIRAのissue URLが会話に出てきた場合は必ずこのスキルを使う。
  また「JIRAでこの条件のissueを検索して」「JQLで検索して」「プロジェクトXのオープンなissue一覧が欲しい」
  のようなJQLでの横断検索の依頼にも使う。
allowed-tools: Task AskUserQuestion
---

# JIRA Fetcher スキル

実際のissue取得・JQL検索処理は `jira-fetcher` エージェントが担当する。このスキルは対象の特定と、エージェントへの委譲のみを行う。

## Step 1: 対象の特定

ユーザーの発言から、issue取得かJQL検索かを判定し、対象を特定する。

### issueキー・URLが読み取れる場合（issue取得）

- **issueキーが直接与えられた場合**（例: `DEV-12802`）: そのまま使う
- **issue URLが与えられた場合**: 末尾のissueキー部分を抽出する
  - 例: `https://your-domain.atlassian.net/browse/DEV-1234` → `DEV-1234`
- **どちらも無い場合**: issueキーまたはURLをユーザーに確認する

### 検索条件が読み取れる場合（JQL検索）

- ユーザーがJQLをそのまま指定した場合はそれを使う
- 自然文の条件（プロジェクト・ステータス・担当者・期間など）の場合は、それらからJQLを組み立てて提案し、実行前にユーザーに確認する
- 組み立て方が分からない場合は `${CLAUDE_PLUGIN_ROOT:-.}/skills/jira/references/jql-cheatsheet.md` を参照する
- 保存が必要か（デフォルトは非保存、一覧を提示するのみ）をユーザーの発言から判断する。「保存して」「ファイルにして」等の明示的な指示があれば保存要と判断する

## Step 2: jira-fetcher エージェントへの委譲

Task tool で `jira-fetcher` エージェントを呼び出し、Step 1で特定した内容（issueキー、またはJQLと保存要否）と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された結果（保存先パス、または検索結果の一覧表・ヒット件数、あるいは失敗理由）をユーザーに報告する。
