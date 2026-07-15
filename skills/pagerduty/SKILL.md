---
name: pagerduty
description: >
  PagerDutyのインシデント情報をMarkdown化してローカルに保存する。
  「PagerDutyのインシデント取得して」「直近の障害情報教えて」「PagerDutyの障害履歴をまとめて」など、
  PagerDutyのインシデント・障害情報の取得や要約が会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# PagerDuty Fetcher スキル

実際のインシデント取得・保存処理は `pagerduty-fetcher` エージェントが担当する。このスキルは取得条件の特定と、エージェントへの委譲のみを行う。

## Step 1: 取得条件の特定

ユーザーの発言から、インシデントID指定のピンポイント取得か、期間指定での一覧取得かを判定し、対象を特定する。

### インシデントURL・IDが読み取れる場合（ピンポイント取得）

- **インシデントURLが与えられた場合**: `https://<subdomain>.pagerduty.com/incidents/<incident_id>` の形式から末尾のインシデントIDを抽出する
- **インシデントIDが直接与えられた場合**（例: `Q0AX7D922G6IUR`）: そのまま使う
- 複数のURL/IDが与えられた場合はまとめて対象とする（`--incident-ids` にカンマ区切りで渡す）

### 期間指定での一覧取得の場合

ユーザーの発言から以下を抽出する。

- **取得期間**: `--since` / `--until`（ISO 8601）。省略時は直近7日間
- **ステータス**: `--statuses`（カンマ区切り）。省略時は `triggered,acknowledged,resolved`
- **対象サービス**: `--services`（サービスIDのカンマ区切り）。省略時は全サービス

## Step 2: pagerduty-fetcher エージェントへの委譲

Task tool で `pagerduty-fetcher` エージェントを呼び出し、Step 1で特定した取得条件と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
