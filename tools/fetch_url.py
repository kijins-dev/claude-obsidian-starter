#!/usr/bin/env python3
"""URLの中身をテキストで取り出す。Claude Codeから呼ばれて解説の材料になる。

対応:
  YouTube … yt-dlp でタイトル・説明・字幕を取得（yt-dlpの導入が必要・無料）
  X        … X APIで投稿本文を取得（有料プランのトークンが必要・任意）
  その他   … ふつうのWebページを取得して本文だけを抜き出す（追加の導入は不要）

使い方:
  python3 fetch_url.py <URL>
  python3 fetch_url.py <URL> --max-chars 8000
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
DEFAULT_MAX_CHARS = 12000
# 字幕は優先順に1言語ずつ試す（複数同時に頼むと429で弾かれやすい）
SUBTITLE_LANGS = ("ja", "ja-orig", "ja.*", "en", "en.*")

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}


def fail(message: str) -> None:
    """理由を伝えて終了する。"""
    print(f"[取得失敗] {message}")
    sys.exit(1)


def detect_kind(url: str) -> str:
    """URLの種類を判定する。"""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host in YOUTUBE_HOSTS:
        return "youtube"
    if host in X_HOSTS:
        return "x"
    return "web"


# ------------------------------------------------------------------ YouTube

def find_yt_dlp() -> str | None:
    """yt-dlpの実体を探す。"""
    found = shutil.which("yt-dlp")
    if found:
        return found
    for candidate in ("~/.local/bin/yt-dlp", "/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"):
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return None


def srt_to_text(srt: str) -> str:
    """字幕ファイルから話し言葉だけを取り出す。"""
    lines: list[str] = []
    for line in srt.splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if lines and lines[-1] == line:  # 自動字幕は同じ行が続くことがある
            continue
        lines.append(line)
    return " ".join(lines)


def fetch_youtube(url: str, max_chars: int) -> str:
    """YouTubeのタイトル・説明・字幕を取り出す。"""
    binary = find_yt_dlp()
    if not binary:
        fail(
            "yt-dlp が見つかりません。次のどちらかで導入してください:\n"
            "  brew install yt-dlp\n"
            "  /usr/bin/python3 -m pip install --user yt-dlp"
        )

    meta_format = "%(title)s\t%(channel)s\t%(duration_string)s\t%(upload_date)s\t%(description)s"
    try:
        meta = subprocess.run(
            [binary, "--skip-download", "--no-warnings", "--print", meta_format, url],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        fail("yt-dlp が120秒以内に応答しませんでした。")
    if meta.returncode != 0:
        detail = (meta.stderr or "").strip().splitlines()
        fail(f"動画情報を取得できませんでした: {detail[-1][:200] if detail else '詳細不明'}")

    fields = (meta.stdout or "").strip().split("\t")
    title, channel, duration, upload, description = (fields + [""] * 5)[:5]

    parts = [
        "種類: YouTube動画",
        f"タイトル: {title}",
        f"チャンネル: {channel}",
        f"長さ: {duration}",
        f"公開日: {upload}",
        f"URL: {url}",
        "",
        "## 概要欄",
        (description or "(なし)")[:2000],
        "",
        "## 字幕",
    ]

    transcript = ""
    used_lang = ""
    with tempfile.TemporaryDirectory() as work:
        for lang in SUBTITLE_LANGS:
            result = subprocess.run(
                [binary, "--skip-download", "--no-warnings", "--write-subs", "--write-auto-subs",
                 "--sub-langs", lang, "--convert-subs", "srt", "-o", f"{work}/sub.%(ext)s", url],
                capture_output=True, text=True, timeout=180,
            )
            files = sorted(glob.glob(f"{work}/*.srt"))
            if files:
                transcript = srt_to_text(Path(files[0]).read_text(encoding="utf-8", errors="replace"))
                used_lang = Path(files[0]).stem.split(".", 1)[-1]
                if transcript.strip():
                    break
            if result.returncode != 0 and "429" in (result.stderr or ""):
                continue

    if transcript.strip():
        parts.append(f"（言語: {used_lang}）")
        parts.append(transcript[:max_chars])
    else:
        parts.append("(この動画には取得できる字幕がありませんでした。概要欄とタイトルから読み取れる範囲で解説してください)")
    return "\n".join(parts)


# ------------------------------------------------------------------ X（旧Twitter）

def fetch_x(url: str, max_chars: int) -> str:
    """Xの投稿本文を取得する。X APIの有料プランで発行したトークンが必要。"""
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        fail(
            "X_BEARER_TOKEN が設定されていません。Xの取得には有料プランのAPIトークンが必要です。\n"
            "設定手順は README の「Xの投稿を読めるようにする（任意・有料）」を参照してください。\n"
            "トークンが無い場合は、投稿の内容を貼り付けてもらえば解説できます。"
        )

    match = re.search(r"/status(?:es)?/(\d+)", url)
    if not match:
        fail("XのURLから投稿IDを読み取れませんでした。/status/ を含むURLを渡してください。")
    tweet_id = match.group(1)

    endpoint = (
        f"https://api.x.com/2/tweets/{tweet_id}"
        "?tweet.fields=created_at,note_tweet,public_metrics,conversation_id"
        "&expansions=author_id&user.fields=name,username"
    )
    request = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        hint = {401: "トークンが無効です。", 403: "このプランでは読み取れません（有料プランが必要）。",
                429: "レート制限に達しました。しばらく待ってください。"}.get(exc.code, "")
        fail(f"X APIがエラーを返しました（HTTP {exc.code}）。{hint}")
    except urllib.error.URLError as exc:
        fail(f"X APIへ接続できませんでした: {exc.reason}")

    tweet = data.get("data") or {}
    users = {u["id"]: u for u in (data.get("includes", {}).get("users") or [])}
    author = users.get(tweet.get("author_id"), {})
    # 長文投稿は note_tweet 側に全文が入る
    body = (tweet.get("note_tweet") or {}).get("text") or tweet.get("text") or ""
    metrics = tweet.get("public_metrics") or {}

    return "\n".join([
        "種類: Xの投稿",
        f"投稿者: {author.get('name', '不明')}（@{author.get('username', '不明')}）",
        f"投稿日時: {tweet.get('created_at', '不明')}",
        f"反応: いいね{metrics.get('like_count', '?')} / リポスト{metrics.get('retweet_count', '?')}",
        f"URL: {url}",
        "",
        "## 本文",
        body[:max_chars] or "(本文を取得できませんでした)",
    ])


# ------------------------------------------------------------------ 一般のWebページ

def html_to_text(raw: str) -> str:
    """HTMLから本文らしい部分だけを取り出す。"""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|aside)[^>]*>.*?</\1>", " ", raw)
    main = re.search(r"(?is)<(article|main)[^>]*>(.*?)</\1>", raw)
    body = main.group(2) if main else raw
    body = re.sub(r"(?i)<br\s*/?>", "\n", body)
    body = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", body)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
    text = re.sub(r"[ \t　]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch_web(url: str, max_chars: int) -> str:
    """一般のWebページを取得して本文を抜き出す。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        fail(f"ページを取得できませんでした（HTTP {exc.code}）。Claude CodeのWebFetchで再試行してください。")
    except urllib.error.URLError as exc:
        fail(f"ページへ接続できませんでした: {exc.reason}")

    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    title = html.unescape(title_match.group(1)).strip() if title_match else "(タイトル不明)"
    return "\n".join([
        "種類: Webページ",
        f"タイトル: {title}",
        f"URL: {url}",
        "",
        "## 本文",
        html_to_text(raw)[:max_chars] or "(本文を抽出できませんでした)",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description="URLの中身をテキストで取り出します。")
    parser.add_argument("url", help="YouTube / X / 一般Webページ のURL")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="本文の最大文字数")
    args = parser.parse_args()

    kind = detect_kind(args.url)
    if kind == "youtube":
        print(fetch_youtube(args.url, args.max_chars))
    elif kind == "x":
        print(fetch_x(args.url, args.max_chars))
    else:
        print(fetch_web(args.url, args.max_chars))
    return 0


if __name__ == "__main__":
    sys.exit(main())
