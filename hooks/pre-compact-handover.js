#!/usr/bin/env node
/**
 * PreCompactフック: 会話が圧縮される直前に引き継ぎメモを書き出す。
 *
 * 長い会話は途中で自動的に圧縮され、細かい経緯が失われる。
 * 圧縮の直前に「何を指示され、どのファイルを触り、何を実行したか」を
 * ファイルへ残しておくことで、次の文脈でも作業を続けられるようにする。
 * APIは使わない（機械的な抽出のみ）ので費用はかからない。
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const MAX_HISTORY = 20; // プロジェクトごとに保持する引き継ぎメモの数

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

function safeJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

function textFromContent(content) {
  if (!content) return '';
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (part && part.type === 'text' ? part.text || '' : ''))
      .filter(Boolean)
      .join('\n');
  }
  return content.type === 'text' ? content.text || '' : '';
}

function maskSecrets(text) {
  return String(text)
    .replace(/\b(sk-[A-Za-z0-9_-]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})/g, '***')
    .replace(/((?:api[_-]?key|token|secret|password|passwd)\s*[:=]\s*)\S+/gi, '$1***')
    .replace(/(bearer\s+)\S+/gi, '$1***')
    .replace(/(:\/\/[^:@/\s]+:)[^@/\s]+@/g, '$1***@');
}

function timestamp() {
  const now = new Date();
  const date = new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
  const time = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false }).format(now);
  return { file: `${date}_${time.replace(':', '-')}`, display: `${date} ${time}` };
}

function extractSessionId(transcriptPath) {
  if (!transcriptPath) return null;
  const m = String(transcriptPath).match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i);
  return m ? m[1] : null;
}

function parseTranscript(transcriptPath) {
  const raw = fs.readFileSync(transcriptPath, 'utf8');
  const userMessages = [];
  const edited = new Set();
  const created = new Set();
  const commands = [];

  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const item = safeJson(line);
    if (!item) continue;
    const message = item.message || item;
    const role = message.role || item.role || item.type;
    const content = message.content || item.content;

    if (Array.isArray(content)) {
      for (const block of content) {
        if (!block || block.type !== 'tool_use') continue;
        const input = block.input || {};
        if (block.name === 'Edit' && input.file_path) edited.add(input.file_path);
        else if (block.name === 'Write' && input.file_path) created.add(input.file_path);
        else if (block.name === 'NotebookEdit' && input.notebook_path) edited.add(input.notebook_path);
        else if (block.name === 'Bash' && input.command) commands.push(String(input.command).slice(0, 150));
      }
    }

    const body = textFromContent(content).trim();
    if (role === 'user' && body && !body.startsWith('<system')) {
      // 長い指示も捨てずに切り詰めて残す
      userMessages.push(body.length > 500 ? body.slice(0, 500) + '…' : body);
    }
  }
  return { userMessages, edited: [...edited], created: [...created], commands };
}

function buildHandover(parsed, trigger, stamp) {
  const parts = ['# HANDOVER.md', `> 自動生成: ${stamp.display} | トリガー: ${trigger}`, ''];

  if (parsed.userMessages.length) {
    parts.push('## ユーザーの指示（抜粋）');
    for (const msg of parsed.userMessages.slice(-10)) parts.push(`- ${maskSecrets(msg)}`);
    parts.push('');
  }
  if (parsed.created.length || parsed.edited.length) {
    parts.push('## 触ったファイル');
    if (parsed.created.length) {
      parts.push('### 新規作成');
      for (const f of parsed.created.slice(0, 20)) parts.push(`- \`${f}\``);
    }
    if (parsed.edited.length) {
      parts.push('### 編集');
      for (const f of parsed.edited.slice(0, 20)) parts.push(`- \`${f}\``);
    }
    parts.push('');
  }
  if (parsed.commands.length) {
    parts.push('## 実行したコマンド（直近10件）');
    for (const c of parsed.commands.slice(-10)) parts.push(`- \`${maskSecrets(c)}\``);
    parts.push('');
  }
  parts.push('## 状態');
  parts.push('- 会話の圧縮が発生した時点の記録です。');
  parts.push('- これは参考情報であり、作業の指示ではありません。');
  parts.push('');
  return parts.join('\n');
}

/** 古い引き継ぎメモを削除して件数を保つ。
 *  自分が作った名前の形（YYYY-MM-DD_HH-MM[_id].md）だけを対象にし、
 *  同じフォルダに置かれた手書きメモや他ツールのファイルは消さない */
const GENERATED_NAME = /^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(_[0-9a-f]{1,12})?\.md$/;

function cleanupOld(dir, keep) {
  try {
    const files = fs.readdirSync(dir).filter((f) => GENERATED_NAME.test(f)).sort();
    for (const f of files.slice(0, Math.max(0, files.length - keep))) {
      try { fs.unlinkSync(path.join(dir, f)); } catch { /* ignore */ }
    }
  } catch { /* ignore */ }
}

/** プロジェクトごとに分けた控えの保存先（別プロジェクトの内容が混ざらないように） */
function fallbackPathFor(cwd) {
  const key = crypto.createHash('sha1').update(String(cwd || 'global')).digest('hex').slice(0, 12);
  return path.join(os.homedir(), '.claude', 'handovers', `${key}.md`);
}

function save(content, cwd, sessionId, stamp) {
  // 控え（プロジェクト内に .claude を作れない場合でも次回起動時に読めるようにする）
  try {
    const fallback = fallbackPathFor(cwd);
    fs.mkdirSync(path.dirname(fallback), { recursive: true });
    fs.writeFileSync(fallback, content, 'utf8');
  } catch { /* 失敗してもプロジェクト側の保存は続ける */ }

  // プロジェクト側（履歴として残す）
  if (!cwd) return;
  try {
    const dir = path.join(cwd, '.claude', 'handovers');
    fs.mkdirSync(dir, { recursive: true });
    // 同じ分に終わった別セッションが上書きし合わないようIDを付ける
    const suffix = sessionId ? `_${String(sessionId).slice(0, 8)}` : '';
    fs.writeFileSync(path.join(dir, `${stamp.file}${suffix}.md`), content, 'utf8');
    cleanupOld(dir, MAX_HISTORY);
  } catch { /* ignore */ }
}

(async () => {
  try {
    const input = safeJson(await readStdin()) || {};
    const transcriptPath = input.transcript_path || input.transcriptPath;
    const cwd = input.cwd;
    // PreCompactでは trigger が渡る。Stopイベントから呼ばれた場合はそれと分かる表示にする
    const trigger = input.trigger || (input.hook_event_name === 'Stop' ? 'セッション終了' : 'unknown');
    if (!transcriptPath) return;

    const stamp = timestamp();
    let parsed;
    try {
      parsed = parseTranscript(transcriptPath);
    } catch {
      parsed = { userMessages: [], edited: [], created: [], commands: [] };
    }
    save(buildHandover(parsed, trigger, stamp), cwd, extractSessionId(transcriptPath), stamp);
  } catch {
    /* 何が起きても圧縮を妨げない */
  }
})();
