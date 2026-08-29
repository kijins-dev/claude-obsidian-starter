#!/usr/bin/env python3
"""AIへの問い合わせ口。2つの方式を自動で使い分ける。

1. Claude Code経由（既定・APIキー不要）
   `claude -p` を呼ぶ。Claude Codeのサブスクリプション枠で動くため、
   APIキーの取得も課金設定も要らない。
2. Anthropic API経由
   ANTHROPIC_API_KEY が設定されている場合はこちらを使う。
   定時実行を確実に動かしたい場合や、サブスク枠を消費したくない場合向け。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

MODEL = "claude-sonnet-5"
DEFAULT_TIMEOUT = 300

# claudeコマンドの探索先。launchdからの実行ではPATHが最小限になるため、
# よくある設置場所を明示的に見に行く
CLAUDE_CANDIDATES = (
    "~/.local/bin/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    "~/.claude/local/claude",
)


class AiError(RuntimeError):
    """AI呼び出しに失敗したことを表す。"""


def find_claude() -> str | None:
    """claudeコマンドの実体を探す。見つからなければNone。"""
    explicit = os.environ.get("CLAUDE_BIN")
    if explicit and Path(explicit).expanduser().exists():
        return str(Path(explicit).expanduser())
    found = shutil.which("claude")
    if found:
        return found
    for candidate in CLAUDE_CANDIDATES:
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return None


def _ask_via_claude_code(prompt: str, timeout: int) -> str:
    """claude -p で問い合わせる（サブスク枠・APIキー不要）。"""
    binary = find_claude()
    if not binary:
        raise AiError(
            "claudeコマンドが見つかりません。Claude Codeをインストールするか、"
            "ANTHROPIC_API_KEY を設定してください。"
        )
    # --setting-sources "" で利用者のフック設定を読み込ませない。
    # これが無いと、この呼び出し自体がフックを起動して無限に連鎖する
    command = [
        binary, "-p",
        "--model", MODEL,
        "--setting-sources", "",
        "--strict-mcp-config",
    ]
    env = dict(os.environ)
    # 認証はmacOSキーチェーンを使うため、この2つが無いとログイン状態を読めない
    env.setdefault("USER", os.environ.get("USER") or Path.home().name)
    env.setdefault("LOGNAME", env["USER"])
    try:
        result = subprocess.run(
            command, input=prompt, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired as exc:
        raise AiError(f"claudeコマンドが{timeout}秒以内に応答しませんでした。") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        hint = detail[0][:200] if detail else "詳細不明"
        if "login" in hint.lower():
            hint += "（ターミナルで claude を起動して /login を実行してください）"
        raise AiError(f"claudeコマンドが失敗しました: {hint}")
    return (result.stdout or "").strip()


def _ask_via_api(prompt: str, api_key: str, max_tokens: int) -> str:
    """Anthropic APIで問い合わせる。"""
    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise AiError(
            "anthropic パッケージが見つかりません。"
            "`/usr/bin/python3 -m pip install anthropic` を実行してください。"
        ) from exc
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
    )
    # 思考ブロック等が混ざっても落ちないよう、本文だけを連結する
    parts = [
        block.text
        for block in (getattr(response, "content", None) or [])
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "\n".join(parts).strip()


def ask(prompt: str, max_tokens: int = 4000, timeout: int = DEFAULT_TIMEOUT) -> str:
    """AIに問い合わせて本文テキストを返す。失敗時は AiError を投げる。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return _ask_via_api(prompt, api_key, max_tokens)
    return _ask_via_claude_code(prompt, timeout)


def backend_name() -> str:
    """今どちらの方式で動くかを返す（ログ表示用）。"""
    return "Anthropic API" if os.environ.get("ANTHROPIC_API_KEY") else "Claude Code（サブスク枠）"


def is_available() -> tuple[bool, str]:
    """呼び出せる状態かを確認する。(可否, 説明) を返す。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True, "Anthropic API を使います。"
    if find_claude():
        return True, "Claude Code（サブスク枠）を使います。APIキーは不要です。"
    return False, (
        "AIを呼び出せません。Claude Codeをインストールするか、"
        "ingest/.env に ANTHROPIC_API_KEY を設定してください。"
    )
