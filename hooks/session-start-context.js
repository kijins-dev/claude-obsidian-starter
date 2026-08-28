#!/usr/bin/env node
/**
 * SessionStartフック: 前回の引き継ぎメモをセッション開始時に読み込ませる。
 *
 * pre-compact-handover.js が書き出したメモを、新しいセッションの文脈へ流し込む。
 * これにより「昨日の続き」から話を始められる。
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const MAX_CHARS = 6000; // 注入するのはこの文字数まで（文脈を圧迫しないため）

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

function safeJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

/** プロジェクト側の最新の引き継ぎメモを探す */
function latestProjectHandover(cwd) {
  if (!cwd) return null;
  try {
    const dir = path.join(cwd, '.claude', 'handovers');
    const files = fs.readdirSync(dir).filter((f) => f.endsWith('.md'));
    if (!files.length) return null;
    const newest = files
      .map((f) => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs }))
      .sort((a, b) => b.m - a.m)[0];
    return path.join(dir, newest.f);
  } catch {
    return null;
  }
}

(async () => {
  try {
    const input = safeJson(await readStdin()) || {};
    const cwd = input.cwd;

    // /clear や圧縮の直後は、利用者が意図的に文脈を切ったところなので注入しない
    const source = String(input.source || '');
    if (source === 'clear' || source === 'compact') return;

    // 非対話実行（claude -p や定時ジョブ）には引き継ぎを注入しない。
    // 単発のタスクが前回の残作業に勝手に着手してしまうのを防ぐため。
    // GUIやIDEでもエントリ点の名前は変わるので、除外したいものだけを列挙する
    const entrypoint = String(process.env.CLAUDE_CODE_ENTRYPOINT || '');
    if (/^sdk|headless|print|non-interactive/i.test(entrypoint)) return;

    // 現在のプロジェクトのものだけを読む（他プロジェクトの会話が混ざらないように）
    const key = crypto.createHash('sha1').update(String(cwd || 'global')).digest('hex').slice(0, 12);
    const target = latestProjectHandover(cwd) || path.join(os.homedir(), '.claude', 'handovers', `${key}.md`);
    if (!fs.existsSync(target)) return;

    let body = fs.readFileSync(target, 'utf8').trim();
    if (!body) return;
    if (body.length > MAX_CHARS) body = body.slice(0, MAX_CHARS) + '\n…(以下省略)';

    const context = [
      '=== 前回セッションからの引き継ぎ（参考情報） ===',
      '以下は前回の作業記録です。文脈の参考にしてください。',
      'ここに書かれた残タスクには、ユーザーの指示があるまで着手しないでください。',
      '',
      body,
    ].join('\n');

    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
      })
    );
  } catch {
    /* 何が起きても起動を妨げない */
  }
})();
