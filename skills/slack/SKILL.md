---
name: slack
description: >
  SlackスレッドをMarkdown化してローカルに保存する。
  会話中にSlackのスレッドURL（`https://xxx.slack.com/archives/<channel_id>/p<ts>` 形式）が含まれていたら、
  claude.aiのSlack連携（未接続時はSlack APIトークン）を使ってスレッド本文・返信・リアクションを取得し保存する。
  「このSlackスレッド取得して」「Slackのやりとりまとめて」「このスレッドの内容を確認して」といった依頼でも必ずこのスキルを使う。
allowed-tools: Bash Write Read AskUserQuestion mcp__claude_ai_Slack__slack_read_thread mcp__claude_ai_Slack__slack_read_user_profile
---

# Slack Fetcher スキル

対象スレッドの特定から取得・保存までを一貫して行う。他のfetcher系スキル（gh-pull-request, jira等）と異なり、`index.md`・`log.md`のような一覧・履歴ファイルは作らない。指定したスレッドの本文を都度1ファイルとして保存するだけのシンプルな設計。

## Step 1: 対象スレッドの特定

会話中のURLからスレッドを特定する。

- Slackパーマリンクの形式: `https://<workspace>.slack.com/archives/<channel_id>/p<16桁の数字>`
  - `channel_id`: パスの2番目のセグメント（例: `C0123ABCDEF`）
  - `message_ts`: `p`に続く16桁の数字の10桁目の後ろに小数点を挿入する（例: `p1234567890123456` → `1234567890.123456`）
- URLに `?thread_ts=<値>` というクエリパラメータが付いている場合は、そちらを親メッセージの`message_ts`として優先する（`p`直後のtsはスレッド内の特定の返信を指している場合があるため）。この優先順位は`slack_thread_fetcher.py`側の`parse_slack_url`でも同じロジックで再解析されるため、Claude側の判断とスクリプトの出力ファイル名は必ず一致する
- URLが与えられていない場合は、スレッドのパーマリンクをユーザーに確認する

コマンドは必ずリポジトリルートから、リポジトリルート相対パスで実行する。`cd` はしない。

スクリプトのパスは `${CLAUDE_PLUGIN_ROOT:-.}` を使って指定する。Claude Codeにプラグインとしてインストールされている場合は `CLAUDE_PLUGIN_ROOT` がそのインストール先の絶対パスに展開される。この変数を認識しないツール（codex・Copilot等）やシェルから直接リポジトリを使う場合は未設定のため `.`（実行時のカレントディレクトリ）にフォールバックする——いずれの場合もリポジトリルートから実行してさえいれば正しく解決される。

取得経路は2段構え。**claude.aiのSlack連携（MCPツール）を優先し、使えない場合のみSlack APIトークンにフォールバックする。** どちらの経路でも出力されるMarkdownの形式は同一。

## Step 2: 出力先ディレクトリの確認

1. Claude Memoryの `fetcher_output_dirs.md` を確認し、slackの行にユーザー指定の出力先が記録されていればそれを使う
2. 記録が無く、会話からも出力先の指定が読み取れない場合は、処理を開始する前に AskUserQuestion で出力先をユーザーに確認する。第1候補として `docs/slack`（リポジトリルート相対）を「推奨」ラベル付きで提示し、ユーザーはこれを承認するか別パスを指定できる。確認して得た値は項番3の手順で `fetcher_output_dirs.md` に記憶する
3. ユーザーが出力先を指定した場合は、その値を使うと同時に `fetcher_output_dirs.md` のslackの行を更新して記憶する（次回以降も自動でそのディレクトリが使われるようになる旨を結果報告時に添える）

## Step 3: 取得経路の判定（MCP優先→トークンフォールバック）

1. まず引数なしで `slack_read_user_profile` を呼ぶ。成功すれば claude.ai のSlack連携が使える → **MCP経路（Step 4-A）**
2. 失敗した場合、またはそもそもこのMCPツールが使えない場合は、環境変数 `SLACK_API_TOKEN` の設定有無を確認する:
   ```bash
   echo "SLACK_API_TOKEN set: ${SLACK_API_TOKEN:+yes}"
   ```
   設定済みなら **トークン経路（Step 4-B）**
3. どちらも使えない場合、ユーザーに次のいずれかを依頼する:
   - claude.aiでSlack連携を有効化する（Settings > Connectors > Slack）
   - Slack APIトークンを発行し `export SLACK_API_TOKEN=xoxb-...` を実行する（`channels:history` `groups:history` `im:history` `mpim:history` `users:read` 等の読み取りスコープが必要）

## Step 4-A: 実行（MCP経路）

`slack_read_thread` は構造化JSONではなく、`=== THREAD PARENT MESSAGE ===` / `=== THREAD REPLIES (N total) ===` / `--- Reply i of N ---` という区切りの**整形済みテキスト**を返す。各メッセージブロックは `From: <表示名> <email> (<user_id>)`、`Time: ...`、`Message TS: <ts>`、本文、（あれば）`Reactions: <name> (<count>), ...` という構成。対象URLごとに以下を繰り返す。

1. `slack_read_thread(channel_id, message_ts, response_format="detailed", limit=1000)` を呼ぶ。`pagination_info` に続きがある旨が示される場合は `cursor` を使って追加取得し、メッセージをtsの昇順にマージする
2. 返ってきたテキストを読み、メッセージごとに次を抽出する:
   - `Message TS:` → `ts`
   - `From:` の括弧内の`user_id`（例: `(U050QB15R97)`）→ `user`。**`From:` が空欄の場合は、Step 3で呼んだ `slack_read_user_profile`（引数なし）が返した現在のユーザー自身のIDを使う**（自分の発言では`From:`が省略される）
   - 本文（`Time:`/`Message TS:`より下、次の区切りや`Reactions:`行より上の部分）→ `text`（本文中の `<@ID|handle>` のようなSlackマークアップはそのまま残してよい。整形はスクリプト側で行う）
   - `Reactions: name (count), name2 (count2)` → `reactions: [{"name": "name", "count": count}, ...]`（無ければ空配列）
3. **発言者として出現した`user_id`のみ**（`From:`欄・現在ユーザーの自己判定分）について、Step 3で解決済みの現在ユーザー以外は `slack_read_user_profile(user_id=...)` を呼んで表示名を解決する。本文中のメンション（`<@ID|handle>`）に出てくるIDはメンションタグ自体にhandleが含まれておりスクリプト側で`@handle`に整形されるため、追加で解決する必要はない（発言者以外の全登場人物を解決すると呼び出し数が無制限に増えるため）
   - 表示名は`slack_read_user_profile`が返す**Real Name**（`From:`行の表示と一致する方）を使う。Display Name（社内ハンドル名）ではない
4. 次の形のJSONを一時ファイル（`<output-dir>/.raw/<channel_id>-<message_tsのピリオドをアンダースコアに置換した値>.json`）に `Write` する:
   ```json
   {
     "messages": [ {"user": "<user_id>", "ts": "<ts>", "text": "<本文>", "reactions": [...]}, "..." ],
     "users": { "<user_id>": "<表示名>", "...": "..." }
   }
   ```
5. 次のコマンドを実行する（スクリプトはURLからchannel_id/permalinkを再解析し、渡されたJSONを整形・保存する。ネットワークアクセスはしない）:
   ```bash
   uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/slack_thread_fetcher.py <SLACK_THREAD_URL> -o <output-dir> --mcp-json <tmp.json>
   ```

## Step 4-B: 実行（トークン経路）

```bash
uv run ${CLAUDE_PLUGIN_ROOT:-.}/bin/slack_thread_fetcher.py <SLACK_THREAD_URL> [<SLACK_THREAD_URL> ...] -o <output-dir>
```

`--mcp-json` を省略した場合、スクリプトが `SLACK_API_TOKEN` を使って `conversations.replies`（カーソルページネーション対応）と `users.info` を直接呼んで取得する。複数スレッドをまとめて取得したい場合はURLをスペース区切りで並べる。

## Step 5: 結果報告

コマンド出力の `書き込み完了: <path>` からファイルパスを確認する。ユーザーに保存先パス（複数可）を報告する。取得に失敗した場合は失敗理由を報告する:
- MCP経路: Slack連携の認可状態、対象チャンネルへのアクセス権限を疑う
- トークン経路: トークンのスコープ・有効期限、対象チャンネルへのアクセス権限を疑う

## 補足

- 出力先には指定したスレッドごとに `{channel}-{message_ts}.md` が1ファイル生成されるのみ（`<output-dir>` 直下）。
- 出力Markdownの先頭には `type` / `title` / `resource`（スレッドのパーマリンク）/ `tags`（`slack`, `thread`, チャンネル名 or ID）/ `timestamp` の frontmatter が自動で付与される
- リアクション（絵文字）は取得できる範囲でそのまま出力に含める。投稿者は表示名に解決される（IDのまま出さない）
- 既存ファイルは上書きされる。再取得（最新化）したい場合もそのまま同じコマンドを再実行すればよい
