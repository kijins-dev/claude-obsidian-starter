#!/usr/bin/env node
// Claude CodeのStopフックから、セッション要約をObsidianデイリーノートへ追記する。
// 失敗してもClaude Code本体を止めないため、すべて黙ってexit 0にする。

const fs = require('fs');
const path = require('path');
const os = require('os');

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

function safeJson(text) {
  try { return JSON.parse(text); } catch { return null; }
}

function textFromContent(content) {
  // textブロックだけを拾う（tool_result等のツール出力を要約APIへ送らないため）
  if (!content) return '';
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.map((part) => {
      if (typeof part === 'string') return part;
      if (part && part.type === 'text') return part.text || '';
      return '';
    }).filter(Boolean).join('\n');
  }
  return content.type === 'text' ? (content.text || '') : '';
}

function readTranscript(transcriptPath, sessionId) {
  const text = fs.readFileSync(transcriptPath, 'utf8');
  const users = [];
  let lastAssistant = '';
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    const item = safeJson(line);
    if (!item) continue;
    const itemSession = item.session_id || item.sessionId || item.session_id_short;
    if (sessionId && itemSession && itemSession !== sessionId) continue;
    const message = item.message || item;
    const role = message.role || item.role || item.type;
    const body = textFromContent(message.content || item.content);
    if (!body.trim()) continue;
    if (role === 'user') users.push(body.trim());
    if (role === 'assistant') lastAssistant = body.trim();
  }
  return { users, lastAssistant };
}

async function summarize(apiKey, users, lastAssistant) {
  const source = [
    'ユーザー発言:',
    users.slice(-8).join('\n---\n'),
    '',
    '直近のアシスタント最終応答:',
    lastAssistant,
  ].join('\n').slice(-12000);
  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-sonnet-5',
      max_tokens: 500,
      messages: [{
        role: 'user',
        content: `次のClaude Codeセッションを日本語で3〜5行に要約してください。作業内容、成果、未完了事項があれば含めます。\n\n${source}`,
      }],
    }),
  });
  if (!response.ok) throw new Error('api failed');
  const data = await response.json();
  return textFromContent(data.content).trim();
}

function todayParts() {
  // en-CAロケールはYYYY-MM-DD形式を返す（ja-JPだと「2026年」等が混入しパスが壊れる）
  const now = new Date();
  const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
  const time = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false }).format(now);
  return { date, yearDir: `${date.slice(0, 4)}年`, time };
}

function upsertDailyNote(vaultPath, sessionId, summary) {
  const parts = todayParts();
  const dailyDir = path.join(vaultPath, '01_01_デイリーノート', parts.yearDir);
  const dailyPath = path.join(dailyDir, `${parts.date}.md`);
  fs.mkdirSync(dailyDir, { recursive: true });
  const start = `<!-- session: ${sessionId} -->`;
  const end = `<!-- /session: ${sessionId} -->`;
  const block = [
    start,
    `## Claude Code セッション ${parts.time}`,
    '',
    summary,
    '',
    end,
    '',
  ].join('\n');
  const current = fs.existsSync(dailyPath) ? fs.readFileSync(dailyPath, 'utf8') : '';
  const pattern = new RegExp(`${start.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s\\S]*?${end.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\n?`);
  // 置換文字列に$&等が含まれてもそのまま書けるよう関数置換にする
  const next = pattern.test(current) ? current.replace(pattern, () => block) : `${current.replace(/\s*$/, '')}\n\n${block}`;
  // 一時ファイル経由のatomic renameで、同時書き込み時の中途半端なファイルを防ぐ
  const tmpPath = `${dailyPath}.tmp-${process.pid}`;
  fs.writeFileSync(tmpPath, next.replace(/^\n+/, ''), 'utf8');
  fs.renameSync(tmpPath, dailyPath);
}

(async () => {
  try {
    const input = safeJson(await readStdin()) || {};
    const transcriptPath = input.transcript_path || input.transcriptPath;
    const sessionId = input.session_id || input.sessionId || path.basename(transcriptPath || '', path.extname(transcriptPath || ''));
    const configPath = path.join(os.homedir(), '.claude', 'obsidian-starter.json');
    if (!transcriptPath || !sessionId || !fs.existsSync(configPath)) return;
    const config = safeJson(fs.readFileSync(configPath, 'utf8')) || {};
    if (!config.vaultPath || !config.anthropicApiKey || !fs.existsSync(config.vaultPath)) return;
    const transcript = readTranscript(transcriptPath, sessionId);
    // Stop時点のtranscriptに最新応答が含まれない場合があるため、フック入力の値を優先する
    const lastAssistant = input.last_assistant_message || transcript.lastAssistant;
    if (!transcript.users.length && !lastAssistant) return;
    const summary = await summarize(config.anthropicApiKey, transcript.users, lastAssistant);
    if (summary) upsertDailyNote(config.vaultPath, sessionId, summary);
  } catch {}
})();
