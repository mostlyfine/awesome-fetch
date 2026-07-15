# JQL (JIRA Query Language) チートシート

出典: [Atlassian公式 JQL cheat sheet](https://www.atlassian.com/software/jira/guides/jql/cheat-sheet)

issue検索でJQLを組み立てる際のリファレンス。自然文の検索条件（「プロジェクトXのオープンなissue」等）をJQLへ変換するときに参照する。

## 基本構文

JQLは `field operator value` を `AND`/`OR` などのキーワードで組み合わせて書く。

```
project = "Marketing Campaign" AND status = "In Progress"
```

- **Field（フィールド）**: 検索対象の項目（`project`, `status`, `assignee` など）
- **Operator（演算子）**: フィールドと値を関連付ける（`=`, `!=`, `<` など）
- **Value / Function（値・関数）**: 比較対象の値、または `currentUser()` のような関数
- **Keyword（キーワード）**: `AND` / `OR` / `ORDER BY` など複合条件・整列を指定する語

## よく使うフィールド

| フィールド | 意味 |
|---|---|
| `project` | プロジェクト（キーまたは名前） |
| `status` | issueのステータス（例: `Open`, `In Progress`, `Closed`） |
| `assignee` | 担当者 |
| `reporter` | 報告者 |
| `priority` | 優先度（例: `High`, `Medium`, `Low`） |
| `issuetype` | 課題タイプ（例: `Bug`, `Task`, `Story`） |
| `created` | 作成日時 |
| `updated` | 更新日時 |
| `duedate` | 期日 |
| `labels` | ラベル |
| `component` | コンポーネント |
| `fixVersion` | 対応バージョン |
| `text` | 概要・説明・コメントなどの全文検索 |

## 演算子

| 演算子 | 意味 |
|---|---|
| `=` | 完全一致（Exact match） |
| `!=` | 不一致（Not equal to） |
| `IN` | 指定リスト内のいずれかに一致 |
| `NOT IN` | 指定リストのいずれにも一致しない |
| `~` | 含む（Contains、テキスト検索向け） |
| `!~` | 含まない（Does not contain） |
| `<` / `>` | 未満 / より大きい |
| `<=` / `>=` | 以下 / 以上 |
| `IS` / `IS NOT` | 値が空（`EMPTY`/`NULL`）かどうかの判定など |
| `WAS` | 過去に特定の値を持っていたか |
| `CHANGED` | 指定期間内にフィールドが変更されたか |

## 論理演算子・キーワード

- `AND` — 全ての条件が真であること
- `OR` — いずれか1つ以上の条件が真であること
- `NOT` — 条件の否定
- `ORDER BY` — 結果の並び替え（`ASC`/`DESC` を指定可能）

## 主要な関数・相対日付

- `currentUser()` — 現在ログイン中のユーザー
- `now()` — 現在時刻
- `startOfDay()` / `endOfDay()` — 当日の開始／終了時刻
- `startOfWeek()` / `endOfWeek()` — 週の開始／終了
- `MEMBERSOF("group")` — 指定グループのメンバーで絞り込み
- 相対日付: `-7d`（7日前）, `-1w`（1週間前）, `-1M`（1ヶ月前）のように現在時刻からの相対値を指定できる

## 注意: `status` は英語名で指定する

JIRAインスタンスによっては、issueのstatus名がREST APIレスポンス上「対応中」「オープン」のように日本語（ローカライズされた表示名）で返る場合がある。この場合、`status` フィールドをJQLで絞り込む際にその日本語表示名（例: `status = "対応中"`）を使うと0件になることがある。JQLの内部インデックスは英語の標準ステータス名で保持されているため、英語名（例: `status = "In Progress"`）を使う必要がある。一般的な対応関係の例:

| 表示（日本語の例） | JQLで使う値 |
|---|---|
| 対応中 | `In Progress` |
| オープン | `Open` |
| クローズ | `Closed` |
| 解決済み | `Resolved` |

環境固有の独自ステータス（例: 「レビュー中」「保留」等）は英語の標準名に対応するとは限らないため、事前に `status = <id>`（`/rest/api/2/status` で調べられる数値のstatus ID）で絞り込む方が確実。日本語名をそのまま `status` に指定すると `400` エラー（「値 '...' はフィールド 'status' に存在しません」）になる。

## 実用サンプルクエリ

```
priority = High AND assignee = currentUser()
project = "Customer Support" AND duedate < now() AND status != Closed
created >= -7d ORDER BY created DESC
status WAS "Resolved" AND status = "Open"
status CHANGED AFTER -1w
assignee IN MEMBERSOF("developers")
component = "User Interface" OR component = "API"
status IN ("In Progress", "Under Review", "Testing")
```
