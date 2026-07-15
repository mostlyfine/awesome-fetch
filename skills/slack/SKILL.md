---
name: slack
description: >
  SlackスレッドをMarkdown化してローカルに保存する。
  会話中にSlackのスレッドURL（`https://xxx.slack.com/archives/<channel_id>/p<ts>` 形式）が含まれていたら、
  claude.aiのSlack連携（未接続時はSlack APIトークン）を使ってスレッド本文・返信・リアクションを取得し保存する。
  「このSlackスレッド取得して」「Slackのやりとりまとめて」「このスレッドの内容を確認して」といった依頼でも必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# Slack Fetcher スキル

実際のスレッド取得・保存処理は `slack-fetcher` エージェントが担当する。このスキルは対象スレッドの特定と、エージェントへの委譲のみを行う。他のfetcher系スキル（pr, jira等）と異なり、`index.md`・`log.md`のような一覧・履歴ファイルは作らない。指定したスレッドの本文を都度1ファイルとして保存するだけのシンプルな設計。

## Step 1: 対象スレッドの特定

会話中のURLからスレッドを特定する。

- Slackパーマリンクの形式: `https://<workspace>.slack.com/archives/<channel_id>/p<16桁の数字>`
  - `channel_id`: パスの2番目のセグメント（例: `C0123ABCDEF`）
  - `message_ts`: `p`に続く16桁の数字の10桁目の後ろに小数点を挿入する（例: `p1234567890123456` → `1234567890.123456`）
- URLに `?thread_ts=<値>` というクエリパラメータが付いている場合は、そちらを親メッセージの`message_ts`として優先する（`p`直後のtsはスレッド内の特定の返信を指している場合があるため）。この優先順位は`slack_thread_fetcher.py`側の`parse_slack_url`でも同じロジックで再解析されるため、Claude側の判断とスクリプトの出力ファイル名は必ず一致する
- URLが与えられていない場合は、スレッドのパーマリンクをユーザーに確認する

## Step 2: slack-fetcher エージェントへの委譲

Task tool で `slack-fetcher` エージェントを呼び出し、Step 1で特定したスレッドのパーマリンク（複数可）と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
