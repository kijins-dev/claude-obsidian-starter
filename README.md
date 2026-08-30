# Claude Code × Obsidian スターターキット

Claude Code（AIコーディングエージェント）にObsidian Vaultを「外部記憶」として読み書きさせるための、
ルール・フック・自動整理スクリプトの一式です。

## これを入れると何ができるようになるか

- **会話が自動で日記になる**: Claude Codeの応答が終わるたびに、そのセッションの要約がデイリーノートへ自動で書き込まれる（同じセッションは同じブロックが更新され続ける）
- **記憶が途切れない**: 応答のたびに引き継ぎメモを最新化し、次のセッション開始時に自動で読み込ませる。会話をいつ閉じても続きから始められる
- **技術メモが自動でwikiになる**: デイリーノート・Webクリップ・受信箱の未整理情報を、毎朝AIがトピック別のwikiページへ整理する
- **日記が週次・月次にまとまる**: 毎週月曜に先週分、毎月1日に先月分の振り返りノートを自動生成する
- **散らばったwikiが束ねられる**: 同じテーマのノートが3本以上たまると「テーマ別まとめ」を自動で作る
- **Claude CodeがVaultを迷わず読める**: 「どのフォルダに何があるか」の地図をルールファイルで渡すので、過去の判断や知見をAIが参照しながら働ける
- **散らかりを毎週自動点検**: リンク切れ・孤立ノートを毎週月曜に検出してレポートする
- **セッションに名前が付く**: 履歴から目的の会話を探しやすくなる
- **リンクを渡すと中身を読んで解説してくれる**: YouTube・X・記事のURLを渡すと、実際に内容を取得して周辺情報まで補って解説し、Obsidianに残す

ポイントは、**AIが賢いから読めるのではなく、地図とルールを渡してあるから読める**という設計です。

## 一番ラクな導入方法（推奨）

このリポジトリのURLをClaude Codeに渡して、こう言うだけです:

```
このリポジトリの SETUP_FOR_AI.md どおりにセットアップして
```

導入前後で何が変わるかの説明 → セットアップ → 動作実演 → 完了報告まで、AIが自動で進めます。
あなたがやるのはVaultの場所を答えることと、APIキーを1つ取得して渡すことだけです。
手動で入れたい場合は、以下のセットアップ手順へ。

## 仕組み（3つの部品）

```
あなた ⇄ Claude Code
            │
            ├─ [1] ルールファイル …… Vaultの地図。どこに何を書き、どこを読むか
            ├─ [2] フック ………… 会話のたびに記録し、記憶を次へ引き継ぐ（層1）
            └─ [3] 自動整理 ……… 毎朝の整理と、週次・月次のまとめ（層2）
                     ↓
                Obsidian Vault（ただのフォルダ。Obsidianを開いていなくても動く）
```

| 部品 | 実体 | 例えると |
|---|---|---|
| ルールファイル | `templates/rules/obsidian.md` | 新人向け社内マニュアル |
| 日記フック | `hooks/stop-daily-note.js`（応答終了ごとに発火） | 自動日報 |
| 引き継ぎフック | `hooks/pre-compact-handover.js` / `hooks/session-start-context.js` | 前任者からの申し送り |
| 命名フック | `hooks/session-title.js` | 会話の背表紙 |
| 毎朝の整理 | `ingest/ingest.py`（毎朝5時） | 夜間の清掃員 |
| 週次・月次まとめ | `ingest/gen_weekly_note.py` / `gen_monthly_note.py` | 定例の振り返り |
| wikiの整頓 | `ingest/wiki_gardening.py` / `weekly_lint.py` | 図書室の司書 |
| 古い日記の片付け | `ingest/archive_daily_notes.py`（毎月1日） | 書庫への移動 |
| URLの解説 | `skills/explain-url/` + `tools/fetch_url.py` | 資料を読んでから説明する調査員 |

## 必要なもの

- macOS（自動実行の仕組みにlaunchdを使うため。フックとルールだけならOS問わず）
- [Claude Code](https://claude.com/claude-code)（インストール済みであること）
- [Obsidian](https://obsidian.md/)（無料）
- Python 3.9以降（macOS標準の `/usr/bin/python3` でOK）
- Node.js 18以降（フックの実行に使用。`node -v` で確認、なければ [nodejs.org](https://nodejs.org/) から）

**APIキーは不要です。** 要約やwiki生成は、すでにログイン済みのClaude Code（`claude -p`）を通して実行するため、
Claude Codeのサブスクリプション枠でそのまま動きます。追加の課金設定もキーの取得も要りません。
（APIキーを使いたい場合は後述の「APIキーを使う場合」を参照）

## セットアップ（15〜30分）

### Step 1: Vaultにフォルダ構造を作る

`templates/vault-skeleton/` の中身を、あなたのObsidian Vaultへコピーします。
各フォルダの役割は `templates/vault-skeleton/README.md` を参照。

コピーするのは中の**フォルダ**だけでOKです（`README.md` はリポジトリ側の説明書なのでVaultに入れる必要はありません）。

すでに使っているVaultがある場合は、足りないフォルダだけ作れば大丈夫です。
**フォルダ名はスクリプト内に固定で書かれているため、まずはこの標準名のまま使うことを推奨します**
（どうしても変えたい場合は `ingest/` の各スクリプトと `hooks/` のフック内に書かれたフォルダ名を、すべて揃えて書き換える必要があります）。

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

### Step 3: フック（自動日報・引き継ぎ・命名）を入れる

```bash
mkdir -p ~/.claude/hooks
cp hooks/*.js ~/.claude/hooks/
```

入るフックは4つです。

| ファイル | 役割 |
|---|---|
| `stop-daily-note.js` | 応答が終わるたびにデイリーノートへ要約を記録 |
| `pre-compact-handover.js` | 応答のたび＋会話圧縮の直前に引き継ぎメモを保存（API不要・無料・1秒未満） |
| `session-start-context.js` | セッション開始時に前回の引き継ぎを読み込ませる（API不要・無料） |
| `session-title.js` | セッションに「フォルダ名: 話題」の名前を付ける（API不要・無料） |

設定ファイル `~/.claude/obsidian-starter.json` を作ります（Vaultの場所を教えるだけです）:

```json
{
  "vaultPath": "/Users/あなた/Documents/あなたのVault"
}
```

最後に `~/.claude/settings.json` へフックを登録します。`hooks/settings-example.json` の
`hooks` の中身を、あなたの `settings.json` の `hooks` へ追記してください（`_comment` 行は不要です）。

**settings.json がまだ無い場合**はこれだけでOKです:

```bash
/usr/bin/python3 - <<'EOF'
import json, os, pathlib
src = json.load(open('hooks/settings-example.json'))
src.pop('_comment', None)
dst = pathlib.Path(os.path.expanduser('~/.claude/settings.json'))
data = json.loads(dst.read_text()) if dst.exists() else {}
hooks = data.setdefault('hooks', {})
for event, entries in src['hooks'].items():
    hooks.setdefault(event, []).extend(entries)   # 既存のフックは消さずに追記
dst.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print('登録しました')
EOF
```

登録後、設定ファイルが壊れていないか必ず確認します:

```bash
/usr/bin/python3 -m json.tool ~/.claude/settings.json > /dev/null && echo "設定OK"
```

> フックは失敗しても黙って終了する設計なので、設定ミスでClaude Codeが動かなくなることはありません。
> **裏を返すと、うまく動かないときも無言です。** デイリーノートが書かれない場合は、
> (1) `~/.claude/obsidian-starter.json` のVaultパスとAPIキー、(2) `node -v` が18以上か、
> (3) settings.json 内の `~` を絶対パス（`/Users/あなた/.claude/hooks/...`）に置き換える、の順に確認してください。

### Step 4: 自動整理（毎朝5時のwiki生成）を入れる

```bash
mkdir -p ~/claude-obsidian-starter
cp -r ingest ~/claude-obsidian-starter/
cd ~/claude-obsidian-starter/ingest
```

`.env` ファイルを作ります（こちらもVaultの場所だけ）:

```
VAULT_PATH=/Users/あなた/Documents/あなたのVault
```

手動で1回動かして動作確認:

```bash
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

1. Claude Codeで何か作業（ファイルを1つ以上編集する程度）をして会話を終える → Vaultの `01_01_デイリーノート/{今年}年/今日の日付.md` に要約ブロックができていれば **日記フックOK**
   （挨拶や一言だけのやりとりは、ノートを汚さないよう意図的に記録されません。ファイル変更が1つでもあるか、ツール操作2回以上か、発言3回以上のいずれかで記録されます）
2. セッションの名前が「フォルダ名: 話題」に変わっていれば **命名フックOK**
3. Claude Codeに「Obsidianの02_プロジェクトに今日の設計判断を記録して」と頼む → 正しいフォルダ・正しい書式で書けば **ルールOK**
4. 翌朝、`04_技術ドキュメント/` を確認 → 前日のメモが整理されていれば **自動整理OK**
5. 翌週、`01_02_ウィークリーノート/` に先週分のまとめができていれば **週次OK**
   （週次・月次・古い日記の片付けは毎朝試行し、生成済みならすぐスキップします。
   Macがスリープで月曜の実行を逃しても、翌日以降に自動で追いつきます。
   なお週次ノートは、その週にデイリーノートが4日分以上ないと作られません）

### Step 6: URLの解説機能を入れる（任意・おすすめ）

「このYouTube解説して」「この記事まとめて」と言うと、**実際に中身を取得してから**解説し、
Obsidianに保存してくれるようになります。

```bash
mkdir -p ~/.claude/skills
cp -r skills/explain-url ~/.claude/skills/
```

コピーしたら `~/.claude/skills/explain-url/SKILL.md` を開き、`<キットの配置先>` を
実際のパス（例: `~/claude-obsidian-starter`）に書き換えてください。

**対応と必要な準備**

| 対象 | 準備 | 費用 |
|---|---|---|
| 一般のWebページ・記事 | 不要 | 無料 |
| YouTube（字幕・概要欄） | yt-dlp の導入 | 無料 |
| X（旧Twitter）の投稿 | X APIのトークン | 有料プランが必要 |

**yt-dlp の導入（YouTube用・無料）**

```bash
brew install yt-dlp
# Homebrewを使っていない場合
/usr/bin/python3 -m pip install --user yt-dlp
```

導入したら、試しに動かしてみてください:

```bash
/usr/bin/python3 tools/fetch_url.py "https://www.youtube.com/watch?v=..." --max-chars 500
```

タイトルと字幕が表示されれば成功です。字幕が無い動画の場合はその旨が表示され、
概要欄とタイトルの範囲で解説されます。

### Xの投稿を読めるようにする（任意・有料）

Xは公開投稿の取得にも**有料プランのAPIトークン**が必要です（金額と条件は変わるため、
必ず公式で最新を確認してください）。無くてもYouTubeと記事は使えます。

1. [console.x.com](https://console.x.com/) にXアカウントでログインし、開発者アカウントを作る
   （利用規約に同意し、用途を記入します）
2. ダッシュボードで「New App」からアプリを作る
3. 発行される認証情報のうち **Bearer Token** を控える
   （**認証情報は一度しか表示されません。**その場でパスワード管理ツール等に保存してください）
4. トークンを環境変数として設定する:

```bash
echo 'export X_BEARER_TOKEN="ここにBearer Token"' >> ~/.zshrc
source ~/.zshrc
```

5. 動作確認:

```bash
/usr/bin/python3 tools/fetch_url.py "https://x.com/<ユーザー名>/status/<投稿ID>"
```

> トークンを設定しない場合、XのURLを渡すと「トークンが無いので本文を貼ってください」と
> 案内されます。貼り付ければ、そこから解説できます。

## よくある質問

**Q. Obsidianアプリを起動していなくても動く？**
動きます。Vaultはただのフォルダで、全部品はファイルを直接読み書きします。Obsidianは「人間が読むときのビューア」です。

**Q. お金はかかる？**
既定では**追加の費用はかかりません**。Claude Codeのサブスクリプション枠を使うためです。
ただし枠を消費するので、要約や整理の分だけ普段のコーディングに使える量は少し減ります。
引き継ぎ・命名の3フックはAIを使わないため、枠も消費しません。
日記フックは同じセッションでは5分間キャッシュを使うので、呼びすぎることはありません。

**Q. サブスク枠を使いたくない（別会計にしたい）**
APIキーを設定すれば、そちらが優先して使われます。「APIキーを使う場合」を参照してください。

**Q. APIへ何が送られる？**
処理ごとに異なります。**Vaultに機密情報を置いている場合は、この範囲を確認してから導入してください。**

| 処理 | 送られるもの |
|---|---|
| 日記フック | あなたの発言・変更ファイルのパス・最後の応答の冒頭。ツールの実行結果（コマンド出力）は送りません。APIキーらしき文字列は伏せ字にします |
| 毎朝の整理 | `Clippings/` `00_受信箱/` の未処理ノート本文と、デイリーノートのセッション記録**そのもの** |
| テーマ別まとめ | `04_技術ドキュメント/` のノート本文 |
| 週次・月次 | デイリーノート／週次ノートの本文 |
| 引き継ぎ・命名の3フック | 何も送りません（AIを使いません） |
| URLの解説 | 取得したページ・動画字幕・投稿の本文（解説を作るため） |

送信先はAnthropicです（Claude Code経由でもAPI経由でも同じ）。自動整理系はノート本文をそのまま送るため、伏せ字処理は行っていません。
見せたくないノートがある場合は、対象フォルダ（`00_受信箱` `04_技術ドキュメント` など）の外に置いてください。

**Q. 自分のノートが勝手に書き換わることはある？**
テーマ別まとめを作ったとき、束ねた元のノートの先頭に `consolidated_into: まとめノート名` という1行が追加されます（本文は変更しません）。
それ以外で既存ノートの中身を書き換えることはありません。事前に確認したい場合は `/usr/bin/python3 wiki_gardening.py --dry-run` で対象だけを表示できます。
古い日記の月別フォルダへの移動も、移動先に同名ファイルがある場合は上書きせずスキップします（`--dry-run` あり）。

**Q. 引き継ぎメモはどこに保存される？**
作業中のプロジェクトの `.claude/handovers/` と、プロジェクトごとに分けた `~/.claude/handovers/` の2箇所です。
プロジェクトをGitで管理している場合は、`.gitignore` に `.claude/handovers/` を追加しておくことをおすすめします。

**Q. 失敗に気づける？**
自動整理が失敗するとmacOSの通知が出ます。チャットツール（Slack等）への通知に差し替える方法は `docs/extensions.md` を参照。

**Q. Windowsでも使える？**
ルールファイルとフックはWindowsでも動きます（パスの書き換えは必要）。毎朝の自動実行（launchd）だけはタスクスケジューラ等への読み替えが必要です。

## APIキーを使う場合（任意）

サブスクリプション枠を消費したくない、または定時実行をより確実に動かしたい場合は、
Anthropic APIキーを設定できます。設定されていればそちらが優先して使われます。

1. [console.anthropic.com](https://console.anthropic.com/) でAPIキーを取得
2. `/usr/bin/python3 -m pip install anthropic` を実行
3. 設定に追記して、権限を絞る:
   - `~/.claude/obsidian-starter.json` に `"anthropicApiKey": "sk-ant-..."` を追加 → `chmod 600 ~/.claude/obsidian-starter.json`
   - `ingest/.env` に `ANTHROPIC_API_KEY=sk-ant-...` を追加 → `chmod 600 .env`

目安の費用は、毎日使って月数百円程度です。

> **定時実行についての注意**: `claude -p` はmacOSのキーチェーンからログイン情報を読みます。
> 通常のログイン状態なら毎朝の自動実行も動きますが、Macがログイン画面のままだと失敗することがあります。
> 確実に動かしたい場合はAPIキーの設定をおすすめします。

## 応用編

議事録の自動取り込み・用語集の自動更新・DBとの連携など、この土台の上に載せられる拡張の実例を
`docs/extensions.md` にまとめています。

## ライセンス

MIT License
