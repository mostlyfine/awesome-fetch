---
name: pagerduty
description: >
  PagerDutyのインシデント情報をMarkdown化してローカルに保存する。
  「PagerDutyのインシデント取得して」「直近の障害情報教えて」「PagerDutyの障害履歴をまとめて」など、
  PagerDutyのインシデント・障害情報の取得や要約が会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Bash Read AskUserQuestion
---

# PagerDuty Fetcher スキル

取得条件の特定から取得・保存までを一貫して行う。

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

`--incident-ids` と一覧系オプション（`--since`/`--until`/`--statuses`/`--services`）は同時に指定しない。両方特定できた場合は `--incident-ids` を優先する（一覧系オプションは無視され、実行時に警告ログが出る）。

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

## Step 2: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、pagerdutyの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/pagerduty`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のpagerdutyの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step 3: 認証情報の確認

スクリプトは環境変数 `PAGERDUTY_TOKEN` を読む。

```bash
echo "PAGERDUTY_TOKEN set: ${PAGERDUTY_TOKEN:+yes}"
```

- 未設定なら、ユーザーにAPIトークンの発行元・値を尋ね、`export PAGERDUTY_TOKEN=<token>` を実行してもらう（トークン自体をログや出力に含めない）

## Step 4: 実行

一覧取得の場合:
```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/pagerduty_fetcher.py \
  [--since 2024-01-01T00:00:00Z] [--until 2024-01-08T00:00:00Z] \
  [--statuses triggered,acknowledged,resolved] [--services SVC1,SVC2] \
  [-o <output-dir>]
```

ピンポイント取得の場合:
```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/pagerduty_fetcher.py \
  --incident-ids <incident_id1>,<incident_id2> \
  [-o <output-dir>]
```

## Step 5: 結果報告

コマンド出力の `書き込み完了: <path>` および `完了: <output_dir>` からファイルパスを確認する。ユーザーに保存先パスを報告する。ピンポイント取得の場合、完了ログは `完了: {fetched}/{len(incident_ids)} 件取得, 出力先: {output_dir}` の形式になる。`fetched` にはIDが存在しない・権限がない等で取得自体に失敗したものは含まれないため、その件数は `len(incident_ids) - fetched` から分かる。一方、更新がなく `更新なし: スキップ (<path>)` としてスキップされたインシデントは `fetched` に含まれるため、完了ログの比率だけでは判別できない点に注意する。`HTTPError` 等のエラーが出た場合は、トークンの権限・日時フォーマット・ネットワーク到達性を疑い、その旨を失敗理由として報告する。

## 補足

- 出力先ディレクトリには `incidents/{incident_id}.md`（インシデント本体：ステータス・緊急度・発生/解決時刻・ノート・アラート詳細）が生成される
- インシデントに更新がなければ処理をスキップする（既存ファイルはそのまま保持される）。更新があれば自動的に再取得・上書きされる。更新の有無に関わらず強制的に再取得・上書きしたい場合は `--force` を付与する
- ピンポイント取得で指定したIDが存在しない・権限がない等の場合、そのIDはスキップされ警告ログが出るが、他のIDの取得は継続される
- インシデント一覧・単体インシデントの取得に限定される。サービス一覧・オンコールスケジュールなど他のPagerDutyリソースの取得はこのスキルの対象外
