# AIエージェント向けセットアップ指示書

このファイルは、このリポジトリを渡されたAIエージェント（Claude Code等）が読む前提の実行指示書です。
ユーザーから「セットアップして」と言われたら、この手順を上から順に実行してください。
人間向けの背景説明は `README.md` にあります（手順が食い違う場合は本ファイルが優先）。

## 進め方の原則

- 各ステップの実行前に既存ファイルを確認し、**既存の設定・ファイルを上書きしない**（マージまたはスキップ）
- ユーザーに聞くのは「Vaultの場所」と「Anthropic APIキー」の2つだけ。それ以外は自動で進める
- 専門用語を使わず、「何ができるようになるか」で説明する

## Step 0: 導入前後の変化を先に説明する（必須）

セットアップ作業を始める前に、まず以下の表をユーザーに提示し、「この状態になります。進めてよいですか？」と1回だけ確認する:

| | 導入前 | 導入後 |
|---|---|---|
| 作業の記録 | 会話が終わると消える | 会話のたびにObsidianの日記へ自動記録される |
| メモの整理 | 散らかったまま | 毎朝5時にAIがトピック別のwikiへ自動整理 |
| AIの記憶 | 毎回ゼロから | AIがVaultの「地図」を持ち、過去の記録を参照しながら働く |
| 散らかりの監視 | 気づいたら手動 | 毎週月曜にリンク切れ・孤立ノートの点検レポートが届く |
| 費用 | — | Anthropic APIで月数百円程度 |

## Step 1: Vaultの場所を確定する

1. `~/Documents` `~/` 直下などからObsidian Vault（`.obsidian` フォルダを含むディレクトリ）を探す
2. 見つかった候補をユーザーに提示して選んでもらう。無ければ新規作成場所を聞く
3. 確定したパスを以後 `{VAULT}` とする

## Step 2: フォルダ構造を作る

`templates/vault-skeleton/` 内の**フォルダだけ**を `{VAULT}` へコピーする（README.mdファイルはコピーしない。既存フォルダはそのまま）:
`00_受信箱` `01_01_デイリーノート/{今年}年` `02_プロジェクト` `04_技術ドキュメント` `05_会議記録` `07_アーカイブ` `Clippings`

## Step 3: ルールファイル（Vaultの地図）を配置する

1. `templates/rules/obsidian.md` を `~/.claude/rules/obsidian.md` へコピー（既存があれば差分をユーザーに見せて確認）
2. コピー先のVaultパス行を `{VAULT}` の実パスに書き換える
3. `~/.claude/CLAUDE.md` に次の1行を追記（無ければ作成、既に同趣旨の行があればスキップ）:
   `- Obsidian Vaultの読み書きは ~/.claude/rules/obsidian.md に必ず従う`

## Step 4: APIキーを設定する

1. ユーザーに案内する: 「Anthropic APIキーが必要です。ブラウザで console.anthropic.com を開いてAPIキーを作成し、ここに貼り付けてください（sk-ant-で始まる文字列）」
2. 受け取ったキーで以下を作成し、両方 `chmod 600` する:
   - `~/.claude/obsidian-starter.json` → `{"vaultPath": "{VAULT}", "anthropicApiKey": "<キー>"}`
   - `<このリポジトリの配置先>/ingest/.env` → `ANTHROPIC_API_KEY=<キー>` と `VAULT_PATH={VAULT}` の2行
3. キーをチャットログ以外の場所（コミット・別ファイル）へ絶対に書かない

## Step 5: フックと自動実行を仕込む

1. `hooks/stop-daily-note.js` を `~/.claude/hooks/` へコピー
2. `~/.claude/settings.json` の `hooks.Stop` に `hooks/settings-example.json` の内容をマージ（既存のStopフックは残す。JSONが壊れていないことを `python3 -m json.tool` で検証）
3. `/usr/bin/python3 -m pip install anthropic` を実行
4. `ingest/com.example.obsidian-ingest.plist` の `__STARTER_DIR__` をリポジトリの絶対パスに置換して `~/Library/LaunchAgents/` へ配置し、`launchctl load` する

## Step 6: 動作実演（「入れた後」を見せる）

1. `{VAULT}/00_受信箱/` にサンプルメモ（何か技術的な内容を3行程度）を1枚作成する
2. `cd <リポジトリ>/ingest && /usr/bin/python3 ingest.py` を実行（数円のAPI費用が掛かる旨を一言添える）
3. `{VAULT}/04_技術ドキュメント/` に生成されたwikiページをユーザーに見せて「これが毎朝5時に自動で起きます」と説明する
4. フックの確認は「この会話が終わったあと、`01_01_デイリーノート/{今年}年/今日の日付.md` に要約が書かれます。次の会話で確認してみてください」と案内する

## Step 7: 完了報告（必須フォーマット）

最後に以下を報告する:

1. Step 0の表を再掲し「この状態になりました」
2. 実演で生成されたwikiページのパス
3. 明日の朝5時に自動で起きること
4. 最初の1週間のおすすめの使い方3つ:
   - 思いついたことを `00_受信箱/` にメモとして放り込む（翌朝整理される）
   - AIに「昨日何やったっけ？」と聞く（デイリーノートから答える）
   - 大きな作業をしたらAIに「Obsidianに記録して」と言う（`02_プロジェクト/` に記録される）

## トラブル時

- フックが書き込まない → `~/.claude/obsidian-starter.json` のパスとキーを確認。フックは失敗しても静かに終了する設計
- ingestが失敗する → `ingest/logs/` の最新ログを読む。APIキー・`VAULT_PATH` の設定ミスが大半
- launchdが動かない → `launchctl list | grep obsidian-ingest` で登録確認。手動実行（Step 6）が通るならパス置換ミスを疑う
