---
name: presentation
description: >
  Googleプレゼンテーション(Google スライド)をPDF化してローカルに保存する。
  「このプレゼン資料をPDFで保存して」「Google SlidesをPDFにして」「このプレゼンテーションの内容を確認して」など、
  Google Presentation/SlidesのURL(https://docs.google.com/presentation)やプレゼンテーションIDが会話に出てきた場合は必ずこのスキルを使う。
allowed-tools: Task AskUserQuestion
---

# Presentation Fetcher スキル

実際のプレゼンテーション取得・保存処理は `presentation-fetcher` エージェントが担当する。このスキルは対象プレゼンテーションの特定と、エージェントへの委譲のみを行う。

## Step 1: 対象プレゼンテーションの特定

会話中のURLやIDからプレゼンテーションを特定する。

- **URLが与えられた場合**: `https://docs.google.com/presentation/d/<presentationId>/...` の形式からIDを抽出する（エージェントにURLをそのまま渡してもよい）
- **IDのみ与えられた場合**: そのまま使う
- **どちらも無い場合**: プレゼンテーションのURLまたはIDをユーザーに確認する

## Step 2: presentation-fetcher エージェントへの委譲

Task tool で `presentation-fetcher` エージェントを呼び出し、Step 1で特定したプレゼンテーションのURL/ID（複数可）と、会話から出力先ディレクトリの指定が読み取れていればそれも併せて伝える。

## Step 3: 結果報告

エージェントから返された保存先パス（または失敗理由）をユーザーに報告する。
