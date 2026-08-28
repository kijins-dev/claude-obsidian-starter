#!/usr/bin/env node
/**
 * SessionStart/UserPromptSubmitフック: セッションに分かりやすい名前を自動で付ける。
 *
 * 名前のないセッションに「フォルダ名 日付-時刻」を付け、
 * 最初の発言が来た時点で「フォルダ名: 話題」に付け替える。
 * 自分で付けた名前（/rename 等）は上書きしない。
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const MARKER_DIR = path.join(os.homedir(), '.claude', 'state', 'session-title');
const SNIPPET_MAX = 24;

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

function safeJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

/** MMDD-HHMM 形式のスタンプ（ロケールに依存しないよう自前で組み立てる） */
function autoStamp() {
  const now = new Date();
  const two = (n) => String(n).padStart(2, '0');
  return `${two(now.getMonth() + 1)}${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}`;
}

function emit(event, title) {
  process.stdout.write(
    JSON.stringify({ hookSpecificOutput: { hookEventName: event, sessionTitle: title } })
  );
}

function markerPath(sessionId) {
  return path.join(MARKER_DIR, String(sessionId).replace(/[^\w-]/g, '_').slice(0, 80));
}

/** 印を立てるだけ（以後このセッションの名前は変更しない） */
function markRenamed(sessionId) {
  if (!sessionId) return;
  try {
    fs.mkdirSync(MARKER_DIR, { recursive: true });
    fs.writeFileSync(markerPath(sessionId), String(Date.now()), 'utf8');
  } catch { /* ignore */ }
}

/** 30日以上前の印を掃除する（溜め続けないため） */
function cleanupMarkers() {
  try {
    const limit = Date.now() - 30 * 86400000;
    for (const name of fs.readdirSync(MARKER_DIR)) {
      const target = path.join(MARKER_DIR, name);
      try {
        if (fs.statSync(target).mtimeMs < limit) fs.unlinkSync(target);
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }
}

/** 1セッションにつき1回だけ発火させるための印 */
function alreadyRenamed(sessionId) {
  if (!sessionId) return false;
  try {
    fs.mkdirSync(MARKER_DIR, { recursive: true });
    if (fs.existsSync(markerPath(sessionId))) return true;
    cleanupMarkers();
    markRenamed(sessionId);
    return false;
  } catch {
    return false;
  }
}

(async () => {
  try {
    const input = safeJson(await readStdin()) || {};
    const event = input.hook_event_name || (input.prompt ? 'UserPromptSubmit' : 'SessionStart');
    const folder = path.basename(input.cwd || process.cwd()) || 'session';
    const title = input.session_title || '';

    if (event === 'SessionStart') {
      if (title) {
        // 手動で付いた名前は守る。この時点で印を立てておかないと、
        // session_titleが渡らないUserPromptSubmit側で上書きしてしまう
        markRenamed(input.session_id || input.sessionId);
        return;
      }
      emit('SessionStart', `${folder} ${autoStamp()}`);
      return;
    }

    // UserPromptSubmit: 最初の発言から話題名を付ける
    // 自動命名パターン（末尾が「MMDD-HHMM」）以外の名前が付いていたら触らない
    if (title && !/\s\d{4}-\d{4}$/.test(title)) return;

    let prompt = String(input.prompt || '');
    if (/^\s*[/!]/.test(prompt)) return; // スラッシュコマンドは話題にしない
    prompt = prompt.replace(/<[^>]*>/g, ' ').replace(/https?:\/\/\S+/g, ' ').replace(/\s+/g, ' ').trim();
    if (prompt.length < 6) return;

    // このイベントには session_title が渡らないため、印が無いと毎回上書きしてしまう
    if (alreadyRenamed(input.session_id || input.sessionId)) return;

    const snippet = prompt.length > SNIPPET_MAX ? prompt.slice(0, SNIPPET_MAX) + '…' : prompt;
    emit('UserPromptSubmit', `${folder}: ${snippet}`);
  } catch {
    /* 何が起きても本体を妨げない */
  }
})();
