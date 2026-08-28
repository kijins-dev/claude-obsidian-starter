#!/usr/bin/env python3
"""完了月のデイリーノートを月別フォルダへ移動する。
当月と先月は残し、2か月以上前の厳格な日付ファイルだけを対象にする。
--dry-runでは移動せず、予定だけを表示する。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


@dataclass(frozen=True)
class ArchiveItem:
    source: Path
    destination: Path
    day: date


def load_env(path: Path) -> None:
    """簡易.envローダー。既存の環境変数を優先する。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def log(message: str) -> None:
    """時刻付きで標準出力へ記録する。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")


def error(message: str) -> int:
    """利用者が直せる形でエラーを表示する。"""
    log(f"エラー: {message}")
    return 1


def require_env() -> Path | None:
    """必須環境変数を確認する。"""
    load_env(BASE_DIR / ".env")
    vault = os.environ.get("VAULT_PATH")
    if not vault:
        error("VAULT_PATH が未設定です。ingest/.env に VAULT_PATH=/path/to/vault を設定してください。")
        return None
    return Path(vault).expanduser()


def month_index(day: date) -> int:
    """年月を比較しやすい整数にする。"""
    return day.year * 12 + day.month


def should_archive(day: date, today: date) -> bool:
    """当月と先月以外をアーカイブ対象にする。"""
    return month_index(day) <= month_index(today) - 2


def parse_note_date(path: Path) -> date | None:
    """厳格な日付ファイル名から日付を読む。"""
    if not DAILY_RE.fullmatch(path.name):
        return None
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def collect_candidates(vault: Path, today: date) -> list[ArchiveItem]:
    """年フォルダ直下の日次ノートだけを収集する。"""
    daily_root = vault / "01_01_デイリーノート"
    if not daily_root.is_dir():
        log(f"デイリーノートフォルダが見つかりません: {daily_root}")
        return []

    items: list[ArchiveItem] = []
    for year_dir in sorted(daily_root.glob("*年")):
        if not year_dir.is_dir():
            continue
        for path in sorted(year_dir.iterdir()):
            if not path.is_file():
                continue
            note_day = parse_note_date(path)
            if not note_day or not should_archive(note_day, today):
                continue
            destination = year_dir / f"{note_day.month}月" / path.name
            items.append(ArchiveItem(source=path, destination=destination, day=note_day))
    return items


def move_without_overwrite(item: ArchiveItem) -> bool:
    """移動先が存在しない場合だけ移動する。"""
    if item.destination.exists():
        log(f"移動先が既にあるためスキップ: {item.destination}")
        return False
    item.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(item.source), str(item.destination))
    return True


def run(dry_run: bool) -> int:
    """日次ノートの月別アーカイブを実行する。"""
    vault = require_env()
    if not vault:
        return 1
    items = collect_candidates(vault, date.today())
    log(f"アーカイブ候補: {len(items)}件")
    moved = 0
    skipped = 0
    for item in items:
        if dry_run:
            if item.destination.exists():
                log(f"dry-run skip existing: {item.source} -> {item.destination}")
                skipped += 1
            else:
                log(f"dry-run move: {item.source} -> {item.destination}")
            continue
        if move_without_overwrite(item):
            moved += 1
            log(f"移動: {item.source.name} -> {item.destination.parent.name}/")
        else:
            skipped += 1
    if dry_run:
        log(f"dry-run完了: 候補{len(items)}件、既存スキップ{skipped}件")
    else:
        log(f"アーカイブ完了: 移動{moved}件、スキップ{skipped}件")
    return 0


def main() -> int:
    """CLI入口。"""
    parser = argparse.ArgumentParser(description="古いデイリーノートを月別フォルダへ移動します。")
    parser.add_argument("--dry-run", action="store_true", help="移動せず、予定だけを表示します。")
    args = parser.parse_args()
    try:
        return run(dry_run=args.dry_run)
    except Exception as exc:
        return error(f"処理に失敗しました: {exc}")


if __name__ == "__main__":
    sys.exit(main())
