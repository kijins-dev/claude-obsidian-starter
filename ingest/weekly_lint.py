#!/usr/bin/env python3
"""Obsidian Vaultを週次検査し、リンク切れ・孤児・重複タイトルを受信箱へ出力する。"""

from __future__ import annotations

import bisect
import os
import posixpath
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import DefaultDict
from urllib.parse import unquote


BASE_DIR = Path(__file__).resolve().parent
TARGET_DIRECTORIES = ("02_プロジェクト", "04_技術ドキュメント")
INBOX_DIRECTORY = "00_受信箱"
REPORT_PREFIX = "週次Lint_"
ARCHIVE_NAMES = {"archive", "archives", "アーカイブ"}
GRAPH_EXTENSIONS = {".md", ".canvas", ".base"}
EXPLICIT_NOTE_EXTENSIONS = {".md", ".canvas", ".base"}
EXCLUDE_DUP_NAMES = {
    "index",
    "readme",
    "設計判断ログ",
    "環境変数一覧",
    "00 プロジェクト概要",
    "プロジェクト概要",
    "概要",
}
WIKILINK_RE = re.compile(r"(?<!\\)!?\[\[([^\[\]\n]+)\]\]")
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)[^\n]*?(?<!`)\1(?!`)")


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


load_env(BASE_DIR / ".env")
VAULT = Path(os.environ["VAULT_PATH"]).expanduser()


@dataclass(frozen=True)
class Wikilink:
    source: Path
    line: int
    raw: str
    target: str
    same_note: bool


@dataclass(frozen=True)
class BrokenLink:
    source: Path
    line: int
    raw: str


@dataclass(frozen=True)
class DuplicateTitle:
    normalized_title: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class LintResult:
    broken_links: tuple[BrokenLink, ...]
    orphan_notes: tuple[Path, ...]
    duplicate_titles: tuple[DuplicateTitle, ...]
    scanned_notes: int
    ignored_numeric: int
    ignored_external: int
    ignored_text: int
    ignored_directory: int


def normalized_key(value: str) -> str:
    """リンク解決用に弱く正規化する。"""
    return unicodedata.normalize("NFC", value).casefold()


def normalized_title(value: str) -> str:
    """重複タイトル検出用に表記揺れを吸収する。"""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\s_\-‐‑‒–—―]+", " ", value).strip()


def is_archive_directory(name: str) -> bool:
    """アーカイブ扱いするフォルダ名か判定する。"""
    value = unicodedata.normalize("NFKC", name).casefold().strip()
    value = re.sub(r"^\d+[\s_.-]*", "", value)
    return value in ARCHIVE_NAMES


def iter_files(root: Path, exclude_archives: bool = False):
    """隠しフォルダを除いて安定順でファイルを列挙する。"""
    for current_root, directory_names, file_names in os.walk(str(root)):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not name.startswith(".") and not (exclude_archives and is_archive_directory(name))
        )
        for file_name in sorted(file_names):
            yield Path(current_root) / file_name


def iter_directories(root: Path):
    """隠しフォルダを除いて安定順でフォルダを列挙する。"""
    for current_root, directory_names, _ in os.walk(str(root)):
        directory_names[:] = sorted(name for name in directory_names if not name.startswith("."))
        for directory_name in directory_names:
            yield Path(current_root) / directory_name


def target_markdown_files(vault: Path) -> list[Path]:
    """検査対象フォルダ配下のMarkdownを集める。"""
    files: list[Path] = []
    for directory_name in TARGET_DIRECTORIES:
        root = vault / directory_name
        if not root.is_dir():
            continue
        files.extend(path for path in iter_files(root, exclude_archives=True) if path.suffix.lower() == ".md")
    return sorted(files, key=lambda path: normalized_key(path.as_posix()))


def mask_range(characters: list[str], start: int, end: int) -> None:
    """指定範囲を行番号を保ったまま空白化する。"""
    for index in range(start, end):
        if characters[index] not in ("\n", "\r"):
            characters[index] = " "


def mask_non_link_regions(text: str) -> str:
    """コードブロック・インラインコード・コメントを検索対象から外す。"""
    characters = list(text)
    offset = 0
    fence = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" \t")
        if fence:
            mask_range(characters, offset, offset + len(line))
            if re.match(re.escape(fence) + "{" + str(fence_length) + r",}[ \t]*(?:\r?\n)?$", stripped):
                fence = ""
        else:
            opening = re.match(r"(`{3,}|~{3,})", stripped)
            if opening:
                fence = opening.group(1)[0]
                fence_length = len(opening.group(1))
                mask_range(characters, offset, offset + len(line))
        offset += len(line)

    masked = "".join(characters)
    for opening, closing in (("<!--", "-->"), ("%%", "%%")):
        start = masked.find(opening)
        while start >= 0:
            end = masked.find(closing, start + len(opening))
            end = len(masked) if end < 0 else end + len(closing)
            mask_range(characters, start, end)
            masked = "".join(characters)
            start = masked.find(opening, end)
    for match in INLINE_CODE_RE.finditer(masked):
        mask_range(characters, match.start(), match.end())
    return "".join(characters)


def parse_wikilink(inner: str) -> tuple[str, bool]:
    """aliasとfragmentを外し、同一ノート参照かどうかも返す。"""
    link_part = inner.replace(r"\|", "|").split("|", 1)[0].strip()
    if not link_part or link_part.startswith("#") or link_part.startswith("^"):
        return "", True
    target = link_part.split("#", 1)[0].strip()
    return target, not target


def extract_wikilinks(path: Path) -> list[Wikilink]:
    """1ファイル内のwikilinkを行番号付きで抽出する。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    searchable = mask_non_link_regions(text)
    line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
    links: list[Wikilink] = []
    for match in WIKILINK_RE.finditer(searchable):
        target, same_note = parse_wikilink(match.group(1))
        links.append(Wikilink(path, bisect.bisect_right(line_starts, match.start()), text[match.start():match.end()], target, same_note))
    return links


def add_index(index: DefaultDict[str, set[Path]], key: str, path: Path) -> None:
    """索引へ正規化キーを追加する。"""
    index[normalized_key(key)].add(path)


def suffixes(relative_path: str):
    """パスの末尾一致候補を作る。"""
    parts = PurePosixPath(relative_path).parts
    for index in range(len(parts)):
        yield "/".join(parts[index:])


class VaultIndex:
    """Vault内ファイルをObsidianのwikilink解決用に索引化する。"""

    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self.full_exact: DefaultDict[str, set[Path]] = defaultdict(set)
        self.full_suffix: DefaultDict[str, set[Path]] = defaultdict(set)
        self.md_exact: DefaultDict[str, set[Path]] = defaultdict(set)
        self.md_suffix: DefaultDict[str, set[Path]] = defaultdict(set)
        self.text_exact: DefaultDict[str, set[Path]] = defaultdict(set)
        self.text_suffix: DefaultDict[str, set[Path]] = defaultdict(set)
        self.dir_exact: DefaultDict[str, set[Path]] = defaultdict(set)
        self.dir_suffix: DefaultDict[str, set[Path]] = defaultdict(set)
        for path in iter_files(vault):
            relative = path.relative_to(vault).as_posix()
            add_index(self.full_exact, relative, path)
            for suffix in suffixes(relative):
                add_index(self.full_suffix, suffix, path)
            if path.suffix.lower() in {".md", ".txt"}:
                without_ext = str(PurePosixPath(relative).with_suffix(""))
                exact = self.md_exact if path.suffix.lower() == ".md" else self.text_exact
                suffix_index = self.md_suffix if path.suffix.lower() == ".md" else self.text_suffix
                add_index(exact, without_ext, path)
                for suffix in suffixes(without_ext):
                    add_index(suffix_index, suffix, path)
        for path in iter_directories(vault):
            relative = path.relative_to(vault).as_posix()
            add_index(self.dir_exact, relative, path)
            for suffix in suffixes(relative):
                add_index(self.dir_suffix, suffix, path)

    def lookup(self, value: str, full_index: dict[str, set[Path]], note_index: dict[str, set[Path]]) -> set[Path]:
        """拡張子付き/なしの候補を索引から引く。"""
        suffix = PurePosixPath(value).suffix.lower()
        key = normalized_key(value)
        if suffix:
            matches = set(full_index.get(key, set()))
            if matches:
                return matches
            if suffix in EXPLICIT_NOTE_EXTENSIONS:
                return set()
        return set(note_index.get(key, set()))

    def resolve_indexed(self, target: str, source: Path, exact: dict[str, set[Path]], suffix_index: dict[str, set[Path]]) -> set[Path]:
        """任意の索引でリンク先を解決する。"""
        for variant in dict.fromkeys([target, unquote(target)]):
            value = unicodedata.normalize("NFC", variant.strip()).replace("\\", "/")
            if not value or value.startswith("/"):
                continue
            source_parent = str(PurePosixPath(source.relative_to(self.vault).as_posix()).parent)
            candidates = [value]
            if value.startswith("./") or value.startswith("../"):
                candidates = [posixpath.normpath(posixpath.join(source_parent, value))]
            elif "/" not in value:
                candidates.append(PurePosixPath(value).name)
            for candidate in candidates:
                if candidate.startswith("../"):
                    continue
                matches = set(exact.get(normalized_key(candidate), set())) or set(suffix_index.get(normalized_key(candidate), set()))
                if matches:
                    return matches
        return set()

    def resolve(self, target: str, source: Path) -> set[Path]:
        """Markdown/Canvas/Baseのリンク先を解決する。"""
        for variant in dict.fromkeys([target, unquote(target)]):
            value = unicodedata.normalize("NFC", variant.strip()).replace("\\", "/")
            if not value or value.startswith("/"):
                continue
            source_parent = str(PurePosixPath(source.relative_to(self.vault).as_posix()).parent)
            candidates = [value, posixpath.normpath(posixpath.join(source_parent, value))]
            if "/" not in value:
                candidates.append(PurePosixPath(value).name)
            for candidate in candidates:
                if candidate.startswith("../"):
                    continue
                matches = self.lookup(candidate, self.full_exact, self.md_exact) or self.lookup(candidate, self.full_suffix, self.md_suffix)
                if matches:
                    return matches
        return set()

    def resolve_text(self, target: str, source: Path) -> set[Path]:
        """同名テキストファイルを解決する。"""
        return self.resolve_indexed(target, source, self.text_exact, self.text_suffix)

    def resolve_directory(self, target: str, source: Path) -> set[Path]:
        """同名フォルダを解決する。"""
        return self.resolve_indexed(target, source, self.dir_exact, self.dir_suffix)

    def closest_match(self, matches: set[Path], source: Path) -> Path:
        """曖昧なリンク候補から近い1件を選ぶ。"""
        source_parts = source.parent.relative_to(self.vault).parts

        def sort_key(candidate: Path) -> tuple[int, str]:
            candidate_parts = candidate.parent.relative_to(self.vault).parts
            common = 0
            for left, right in zip(source_parts, candidate_parts):
                if normalized_key(left) != normalized_key(right):
                    break
                common += 1
            distance = len(source_parts) + len(candidate_parts) - (2 * common)
            return distance, normalized_key(candidate.relative_to(self.vault).as_posix())

        return min(matches, key=sort_key)


def is_numeric_footnote(target: str) -> bool:
    """数値脚注風のwikilinkを除外する。"""
    value = unicodedata.normalize("NFKC", target.strip())
    return value.isascii() and value.isdigit() and 1 <= len(value) <= 3


def is_external_path_reference(target: str) -> bool:
    """Vault外を指す参照を除外する。"""
    value = unquote(unicodedata.normalize("NFC", target.strip())).replace("\\", "/")
    return value.startswith("/") or value.startswith("../")


def find_duplicate_titles(target_notes: list[Path], vault: Path) -> tuple[DuplicateTitle, ...]:
    """同一タイトル候補を検出する。"""
    grouped: DefaultDict[str, list[Path]] = defaultdict(list)
    for path in target_notes:
        grouped[normalized_title(path.stem)].append(path.relative_to(vault))
    duplicates = []
    for title, paths in grouped.items():
        if len(paths) > 1 and title not in EXCLUDE_DUP_NAMES:
            duplicates.append(DuplicateTitle(title, tuple(sorted(paths, key=lambda item: normalized_key(item.as_posix())))))
    return tuple(sorted(duplicates, key=lambda item: normalized_key(item.normalized_title)))


def lint_vault(vault: Path) -> LintResult:
    """Vaultを検査し、検出結果を返す。"""
    if not vault.is_dir():
        raise FileNotFoundError(f"Vaultが見つかりません: {vault}")
    target_notes = target_markdown_files(vault)
    target_note_set = set(target_notes)
    index = VaultIndex(vault)
    broken_links: list[BrokenLink] = []
    outgoing: DefaultDict[Path, set[Path]] = defaultdict(set)
    incoming: DefaultDict[Path, set[Path]] = defaultdict(set)
    ignored_numeric = ignored_external = ignored_text = ignored_directory = 0
    # 孤児判定のincomingはVault全体（デイリーノート等含む）から集める。
    # リンク切れの報告対象は従来どおり対象フォルダのノートに限定する。
    all_notes = [
        path for path in sorted(vault.rglob("*.md"))
        if not any(part.startswith(".") for part in path.relative_to(vault).parts)
    ]
    for source in all_notes:
        is_target_source = source in target_note_set
        for link in extract_wikilinks(source):
            if link.same_note:
                continue
            matches = index.resolve(link.target, source)
            if not matches:
                if not is_target_source:
                    continue
                if is_numeric_footnote(link.target):
                    ignored_numeric += 1
                elif is_external_path_reference(link.target):
                    ignored_external += 1
                elif index.resolve_text(link.target, source):
                    ignored_text += 1
                elif index.resolve_directory(link.target, source):
                    ignored_directory += 1
                else:
                    broken_links.append(BrokenLink(source.relative_to(vault), link.line, link.raw))
                continue
            target = index.closest_match(matches, source)
            if target.suffix.lower() in GRAPH_EXTENSIONS and target != source:
                outgoing[source].add(target)
                if target in target_note_set:
                    incoming[target].add(source)
    orphan_notes = tuple(
        path.relative_to(vault)
        for path in target_notes
        if path.name.lower() != "index.md" and not outgoing.get(path) and not incoming.get(path)
    )
    return LintResult(
        tuple(sorted(broken_links, key=lambda item: (normalized_key(item.source.as_posix()), item.line, item.raw))),
        orphan_notes,
        find_duplicate_titles(target_notes, vault),
        len(target_notes),
        ignored_numeric,
        ignored_external,
        ignored_text,
        ignored_directory,
    )


def code_span(value: str) -> str:
    """Markdownのコードスパンとして安全に包む。"""
    fence = "`"
    while fence in value:
        fence += "`"
    return f"{fence}{value}{fence}"


def week_label(run_date: date) -> str:
    """レポート名用の週ラベルを返す。"""
    year, week, _ = run_date.isocalendar()
    return f"{year}-W{week:02d}"


def build_report(result: LintResult, run_date: date) -> tuple[str, str]:
    """検出結果をObsidian Markdownに整形する。"""
    label = week_label(run_date)
    lines = [
        "---",
        f'title: "週次Lint {label}"',
        f"generated: {run_date.isoformat()}",
        f'week: "{label}"',
        "ingested: true",
        "tags:",
        "  - weekly-lint",
        "---",
        "",
        f"# 週次Lint {label}",
        "",
        "> [!info] 検出専用レポート",
        "> ファイルの自動修正は行っていません。",
        "",
        "## サマリー",
        "",
        "| 項目 | 件数 |",
        "| --- | ---: |",
        f"| 対象ノート | {result.scanned_notes} |",
        f"| リンク切れwikilink | {len(result.broken_links)} |",
        f"| 孤児ノート | {len(result.orphan_notes)} |",
        f"| 重複タイトル候補 | {len(result.duplicate_titles)}グループ |",
        "",
        "## 除外した件数",
        "",
        f"- 純数字のwikilink: {result.ignored_numeric}件",
        f"- Vault外パス参照: {result.ignored_external}件",
        f"- 同名テキストファイル実在: {result.ignored_text}件",
        f"- 同名フォルダ実在: {result.ignored_directory}件",
        "",
        "## リンク切れwikilink",
        "",
    ]
    lines.extend(
        [f"- {code_span(f'{item.source.as_posix()}:{item.line}')} - {code_span(item.raw)}" for item in result.broken_links]
        or ["検出なし。"]
    )
    lines.extend(["", "## 孤児ノート", ""])
    lines.extend([f"- {code_span(path.as_posix())}" for path in result.orphan_notes] or ["検出なし。"])
    lines.extend(["", "## 重複タイトル候補", ""])
    if result.duplicate_titles:
        for duplicate in result.duplicate_titles:
            lines.append(f"### {code_span(duplicate.normalized_title)}")
            lines.extend(f"- {code_span(path.as_posix())}" for path in duplicate.paths)
            lines.append("")
    else:
        lines.append("検出なし。")
    lines.extend(["", "## 検査条件", "", "- 検出元: `02_プロジェクト/`、`04_技術ドキュメント/`", "- 除外: アーカイブディレクトリ", "- 自動修正: なし", ""])
    return label, "\n".join(lines)


def write_report(vault: Path, result: LintResult, run_date: date) -> Path:
    """受信箱へ週次Lintレポートを書き出す。"""
    label, content = build_report(result, run_date)
    inbox = vault / INBOX_DIRECTORY
    inbox.mkdir(parents=True, exist_ok=True)
    report_path = inbox / f"{REPORT_PREFIX}{label}.md"
    report_path.write_text(content, encoding="utf-8")
    return report_path


def main() -> int:
    """週次Lintを実行する。"""
    try:
        result = lint_vault(VAULT)
        report_path = write_report(VAULT, result, date.today())
    except Exception as error:
        print(f"[weekly_lint] ERROR: {error}", file=sys.stderr)
        return 1
    duplicate_files = sum(len(group.paths) for group in result.duplicate_titles)
    print(f"[weekly_lint] 出力: {report_path}")
    print(f"[weekly_lint] 対象ノート: {result.scanned_notes}件")
    print(f"[weekly_lint] リンク切れwikilink: {len(result.broken_links)}件")
    print(f"[weekly_lint] 孤児ノート: {len(result.orphan_notes)}件")
    print(f"[weekly_lint] 重複タイトル候補: {len(result.duplicate_titles)}グループ / {duplicate_files}ファイル")
    return 0


if __name__ == "__main__":
    sys.exit(main())
