# Claude Code × Obsidian スターターキット

Claude Code（AIコーディングエージェント）にObsidian Vaultを「外部記憶」として読み書きさせるための、
ルール・フック・自動整理スクリプトの一式です。

## これを入れると何ができるようになるか

- **会話が自動で日記になる**: Claude Codeの応答が終わるたびに、そのセッションの要約がデイリーノートへ自動で書き込まれる（同じセッションは同じブロックが更新され続ける）
- **技術メモが自動でwikiになる**: デイリーノート・Webクリップ・受信箱の未整理情報を、毎朝5時にAIがトピック別のwikiページへ整理する
- **Claude CodeがVaultを迷わず読める**: 「どのフォルダに何があるか」の地図をルールファイルで渡すので、過去の判断や知見をAIが参照しながら働ける
- **散らかりを毎週自動点検**: リンク切れ・孤立ノートを毎週月曜に検出してレポートする

ポイントは、**AIが賢いから読めるのではなく、地図とルールを渡してあるから読める**という設計です。

## 仕組み（3つの部品）

```
あなた ⇄ Claude Code
            │
            ├─ [1] ルールファイル …… Vaultの地図。どこに何を書き、どこを読むか
            ├─ [2] Stopフック ……… 会話終了のたびにデイリーノートへ自動記録（層1）
            └─ [3] 自動整理 ………… 毎朝5時に未整理情報をwiki化＋週次点検（層2）
                     ↓
                Obsidian Vault（ただのフォルダ。Obsidianを開いていなくても動く）
```

| 部品 | 実体 | 例えると |
|---|---|---|
| ルールファイル | `templates/rules/obsidian.md` | 新人向け社内マニュアル |
| Stopフック | `hooks/stop-daily-note.js`（応答終了ごとに発火） | 自動日報 |
| 自動整理 | `ingest/` 一式（launchdで毎朝実行） | 夜間の清掃員 |

## 必要なもの

- macOS（自動実行の仕組みにlaunchdを使うため。フックとルールだけならOS問わず）
- [Claude Code](https://claude.com/claude-code)（インストール済みであること）
- [Obsidian](https://obsidian.md/)（無料）
- Anthropic APIキー（要約とwiki生成に使用。[console.anthropic.com](https://console.anthropic.com/) で取得。目安: 毎日実行しても月数百円程度）
- Python 3.9以降（macOS標準の `/usr/bin/python3` でOK）＋ `/usr/bin/python3 -m pip install anthropic`
- Node.js 18以降（Stopフックの実行に使用。`node -v` で確認、なければ [nodejs.org](https://nodejs.org/) から）

## セットアップ（15〜30分）

### Step 1: Vaultにフォルダ構造を作る

`templates/vault-skeleton/` の中身を、あなたのObsidian Vaultへコピーします。
各フォルダの役割は `templates/vault-skeleton/README.md` を参照。

コピーするのは中の**フォルダ**だけでOKです（`README.md` はリポジトリ側の説明書なのでVaultに入れる必要はありません）。

すでに使っているVaultがある場合は、足りないフォルダだけ作れば大丈夫です。
**フォルダ名はスクリプト内に固定で書かれているため、まずはこの標準名のまま使うことを推奨します**
（どうしても変えたい場合は `ingest/ingest.py` と `hooks/stop-daily-note.js` 内のフォルダ名も揃えて書き換える必要があります）。

### Step 2: ルールファイルを置く

```bash
mkdir -p ~/.claude/rules
cp templates/rules/obsidian.md ~/.claude/rules/obsidian.md
```

コピーしたら `~/.claude/rules/obsidian.md` を開いて、**Vaultパスを自分の実際のパスに書き換えます**。

次に `~/.claude/CLAUDE.md`（なければ新規作成）へ、この1行を追記します:

```markdown
- Obsidian Vaultの読み書きは `~/.claude/rules/obsidian.md` に必ず従う
```

これだけでClaude CodeはVaultの地図を持った状態になります。

### Step 3: Stopフック（自動日報）を入れる

```bash
mkdir -p ~/.claude/hooks
cp hooks/stop-daily-note.js ~/.claude/hooks/
```

設定ファイル `~/.claude/obsidian-starter.json` を作ります:

```json
{
  "vaultPath": "/Users/あなた/Documents/あなたのVault",
  "anthropicApiKey": "sk-ant-..."
}
```

APIキーが入るファイルなので、自分以外に読めないよう権限を絞っておきます:

```bash
chmod 600 ~/.claude/obsidian-starter.json
```

最後に `~/.claude/settings.json` へフックを登録します（`hooks/settings-example.json` の内容を参考に、
既存のsettings.jsonがある場合は `hooks` セクションへマージしてください）。

> フックは失敗しても黙って終了する設計なので、設定ミスでClaude Codeが動かなくなることはありません。
> もしデイリーノートが書かれない場合は、settings.json内の `~` を絶対パス（`/Users/あなた/.claude/hooks/...`）に書き換えてみてください。

### Step 4: 自動整理（毎朝5時のwiki生成）を入れる

```bash
mkdir -p ~/claude-obsidian-starter
cp -r ingest ~/claude-obsidian-starter/
cd ~/claude-obsidian-starter/ingest
```

`.env` ファイルを作ります:

```
ANTHROPIC_API_KEY=sk-ant-...
VAULT_PATH=/Users/あなた/Documents/あなたのVault
```

こちらもAPIキーが入るので権限を絞ります: `chmod 600 .env`

手動で1回動かして動作確認:

```bash
/usr/bin/python3 -m pip install anthropic  # 必ずこのpython3に入れる（自動実行と同じPythonを使うため）
/usr/bin/python3 ingest.py
```

`04_技術ドキュメント/` にノートが生成されれば成功です（未整理の素材が無い日は何も起きません。
`00_受信箱/` に適当なメモを1枚置いてから試すとわかりやすいです）。

毎朝の自動実行を仕込みます:

```bash
# plist内の __STARTER_DIR__ を実際のパスに置換してからコピー
sed "s|__STARTER_DIR__|$HOME/claude-obsidian-starter|g" com.example.obsidian-ingest.plist \
  > ~/Library/LaunchAgents/com.example.obsidian-ingest.plist
launchctl load ~/Library/LaunchAgents/com.example.obsidian-ingest.plist
```

### Step 5: 動作確認

1. Claude Codeで何か短い作業をして会話を終える → Vaultの `01_01_デイリーノート/{今年}年/今日の日付.md` に要約ブロックができていれば **フックOK**
2. Claude Codeに「Obsidianの02_プロジェクトに今日の設計判断を記録して」と頼む → 正しいフォルダ・正しい書式で書けば **ルールOK**
3. 翌朝、`04_技術ドキュメント/` を確認 → 前日のメモが整理されていれば **自動整理OK**

## よくある質問

**Q. Obsidianアプリを起動していなくても動く？**
動きます。Vaultはただのフォルダで、全部品はファイルを直接読み書きします。Obsidianは「人間が読むときのビューア」です。

**Q. APIコストはどれくらい？**
Stopフックは応答終了ごとに1回の要約呼び出しが走りますが1回あたり1円未満、毎朝の自動整理は素材量によりますが月数百円程度が目安です。

**Q. 失敗に気づける？**
自動整理が失敗するとmacOSの通知が出ます。チャットツール（Slack等）への通知に差し替える方法は `docs/extensions.md` を参照。

**Q. Windowsでも使える？**
ルールファイルとフックはWindowsでも動きます（パスの書き換えは必要）。毎朝の自動実行（launchd）だけはタスクスケジューラ等への読み替えが必要です。

## 応用編

議事録の自動取り込み・用語集の自動更新・DBとの連携など、この土台の上に載せられる拡張の実例を
`docs/extensions.md` にまとめています。

## ライセンス

MIT License
