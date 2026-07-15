---
name: confluence
description: >
  ConfluenceのページをMarkdown化してローカルに保存する。
  「Confluenceのこのページ取得して」「このURLの内容をMarkdownにして」「Confluenceページをダウンロードして」
  「このConfluenceページの内容を要約して」など、confluence のURLやページIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# Confluence Fetcher スキル

実際のページ取得・保存処理は `confluence-fetcher` エージェントが担当する。このスキルは対象ページの特定と、エージェントへの委譲のみを行う。

## Step 1: 対象ページの特定

ユーザーの発言からページを特定する。

- **URLが与えられた場合**: URLからページIDを抽出する
  - Cloud形式: `.../pages/<pageId>/...` → 数字部分がID
  - 社内Confluence形式: `...viewpage.action?pageId=<pageId>` → `pageId=` の数字部分がID
- **ページIDのみ与えられた場合**: そのまま使う
- **どちらも無い場合**: ページURLまたはIDをユーザーに確認する

## Step 2: confluence-fetcher エージェントへの委譲

Task tool で `confluence-fetcher` エージェントを呼び出し、Step 1で特定したページID（またはURL）と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
