---
name: pr
description: >
  GitHubのPull RequestをMarkdown化してローカルに保存する。
  会話中にgithub.comやGitHub EnterpriseのPR URL（`.../pull/<番号>`形式）が含まれていたら、
  gh apiを使ってPR本文・レビュー履歴・レビューコメント（差分への行コメント）・Issueコメントを取得し保存する。
  「このPR見せて」「PRの内容まとめて」「このPRのコメント確認して」といった依頼でも必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# PullRequest Fetcher スキル

実際のPR取得・保存処理は `pr-fetcher` エージェントが担当する。このスキルは対象PRの特定と、エージェントへの委譲のみを行う。

## Step 1: 対象PRの特定

会話中のURLからPRを特定する。

- **PR URLが与えられた場合**: `https://<host>/<owner>/<repo>/pull/<number>` の形式からhost/owner/repo/numberを抽出する
  - `github.com` に加え、GitHub Enterprise（社内GHE等）のホストも対象
  - `/files`・`/commits` などの末尾パスや `#discussion_r...` のようなフラグメントが付いていても番号までを読み取れればよい
- **URLが無い場合**（`owner/repo#123` のような略記のみ等）: PRのフルURLをユーザーに確認する

## Step 2: pr-fetcher エージェントへの委譲

Task tool で `pr-fetcher` エージェントを呼び出し、Step 1で特定したPR URL（複数可）と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
