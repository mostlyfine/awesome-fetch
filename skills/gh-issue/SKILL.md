---
name: gh-issue
description: >
  GitHubのIssueをMarkdown化してローカルに保存する。
  会話中にgithub.comやGitHub EnterpriseのIssue URL（`.../issues/<番号>`形式）が含まれていたら、
  gh apiを使ってIssue本文・ラベル・担当者・マイルストーン・コメントを取得し保存する。
  「このIssue見せて」「Issueの内容まとめて」「このIssueのコメント確認して」といった依頼でも必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# Issue Fetcher スキル

実際のIssue取得・保存処理は `gh-issue-fetcher` エージェントが担当する。このスキルは対象Issueの特定と、エージェントへの委譲のみを行う。

## Step 1: 対象Issueの特定

会話中のURLからIssueを特定する。

- **Issue URLが与えられた場合**: `https://<host>/<owner>/<repo>/issues/<number>` の形式からhost/owner/repo/numberを抽出する
  - `github.com` に加え、GitHub Enterprise（社内GHE等）のホストも対象
  - `#issuecomment-...` のようなフラグメントが付いていても番号までを読み取れればよい
- **URLが無い場合**（`owner/repo#123` のような略記のみ等）: IssueのフルURLをユーザーに確認する
- Pull Requestの URL（`.../pull/<番号>`）はこのスキルの対象外。pr を使う

## Step 2: gh-issue-fetcher エージェントへの委譲

Task tool で `gh-issue-fetcher` エージェントを呼び出し、Step 1で特定したIssue URL（複数可）と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
