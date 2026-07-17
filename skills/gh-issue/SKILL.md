---
name: gh-issue
description: >
  GitHubのIssueをMarkdown化してローカルに保存する。
  会話中にgithub.comやGitHub EnterpriseのIssue URL（`.../issues/<番号>`形式）が含まれていたら、
  gh apiを使ってIssue本文・ラベル・担当者・マイルストーン・コメントを取得し保存する。
  「このIssue見せて」「Issueの内容まとめて」「このIssueのコメント確認して」といった依頼でも必ずこのスキルを使う。
allowed-tools: Bash Read AskUserQuestion
---

# Issue Fetcher スキル

対象Issueの特定から取得・保存までを一貫して行う。

## Step 1: 対象Issueの特定

会話中のURLからIssueを特定する。

- **Issue URLが与えられた場合**: `https://<host>/<owner>/<repo>/issues/<number>` の形式からhost/owner/repo/numberを抽出する
  - `github.com` に加え、GitHub Enterprise（社内GHE等）のホストも対象
  - `#issuecomment-...` のようなフラグメントが付いていても番号までを読み取れればよい
- **URLが無い場合**（`owner/repo#123` のような略記のみ等）: IssueのフルURLをユーザーに確認する
- Pull Requestの URL（`.../pull/<番号>`）はこのスキルの対象外。pr を使う

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。取得には `gh api` を使うため、JIRA/Confluence/PagerDutyのfetcher系と違いAPIトークンの手動設定は不要（`gh auth login` 済みであればよい）。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

## Step 2: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、gh-issueの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/issue`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のgh-issueの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step 3: 認証情報の確認

gh CLI は `gh auth login` 済みであることが前提。

```bash
gh auth status
```

- `github.com` 以外のホスト（GitHub Enterprise）が対象の場合は `gh auth status --hostname <host>` で確認する
- 未ログインの場合は、ユーザーに `gh auth login`（GHEの場合は `gh auth login --hostname <host>`）の実行を依頼する

## Step 4: 実行

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/issue_fetcher.py <ISSUE_URL> [<ISSUE_URL> ...] \
  -o <output-dir>
```

複数Issueをまとめて取得したい場合はURLをスペース区切りで並べる。

## Step 5: 結果報告

コマンド出力の `書き込み完了: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。更新がなく処理がスキップされた場合は `更新なし: スキップ (<path>)` が出力されるため、その場合も既存ファイルのパスを報告する。`Issue取得失敗` のログが出た場合は、URLの形式・`gh auth status` の認証状態・リポジトリへのアクセス権限を疑い、その旨を失敗理由として報告する。

## 補足

- 出力先ディレクトリには `{owner}-{repo}-{number}.md`（Issue本体）が生成される
- 「コメント含む」を網羅するため、Issueに付いた全コメント（会話タブの発言）を取得する
- 出力Markdownの先頭には `type` / `title` / `resource`（Issueのhtml_url）/ `tags`（`github`, `issue`, state, および各ラベル名）/ `timestamp` の frontmatter が自動で付与される
- Issueに更新がなければ処理をスキップする（既存ファイルはそのまま保持される）。更新があれば自動的に再取得・上書きされる。更新の有無に関わらず強制的に再取得・上書きしたい場合は `--force` を付与する
