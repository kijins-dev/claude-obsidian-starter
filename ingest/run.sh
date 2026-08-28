#!/bin/bash
# Obsidian Ingestを実行する汎用ラッパー。
# スクリプト自身の場所を基準にするため、任意の場所へ配置できる。

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/ingest-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "$LOG_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

notify_failure() {
  local code="$1"
  osascript -e "display notification \"終了コード: $code。ログ: $LOG_FILE\" with title \"Obsidian Ingest 失敗\"" >/dev/null 2>&1 || true
}

echo "=== obsidian-ingest started at $(date) ===" >> "$LOG_FILE"

set +e
/usr/bin/python3 "$SCRIPT_DIR/ingest.py" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
  notify_failure "$EXIT_CODE"
fi

# 月曜日だけ週次Lintを実行する。失敗しても本体の終了コードは変えない。
if [ "$(date +%u)" = "1" ]; then
  echo "=== weekly lint started at $(date) ===" >> "$LOG_FILE"
  /usr/bin/python3 "$SCRIPT_DIR/weekly_lint.py" >> "$LOG_FILE" 2>&1 || {
    LINT_EXIT_CODE=$?
    echo "=== weekly lint failed with exit code $LINT_EXIT_CODE ===" >> "$LOG_FILE"
    notify_failure "weekly-lint-$LINT_EXIT_CODE"
    true
  }
  echo "=== weekly lint finished at $(date) ===" >> "$LOG_FILE"

  echo "=== wiki gardening started at $(date) ===" >> "$LOG_FILE"
  /usr/bin/python3 "$SCRIPT_DIR/wiki_gardening.py" >> "$LOG_FILE" 2>&1 || {
    GARDEN_EXIT_CODE=$?
    echo "=== wiki gardening failed with exit code $GARDEN_EXIT_CODE ===" >> "$LOG_FILE"
    notify_failure "wiki-gardening-$GARDEN_EXIT_CODE"
    true
  }
  echo "=== wiki gardening finished at $(date) ===" >> "$LOG_FILE"

fi

# 週次・月次ノートと古い日次ノートの片付けは毎日試行する。
# 生成済みならAPI呼び出し前にスキップするため無駄がなく、Macのスリープで
# 月曜や1日を逃しても翌日以降に自動で追いつく。
echo "=== weekly note started at $(date) ===" >> "$LOG_FILE"
/usr/bin/python3 "$SCRIPT_DIR/gen_weekly_note.py" >> "$LOG_FILE" 2>&1 || {
  WEEKLY_NOTE_EXIT_CODE=$?
  echo "=== weekly note failed with exit code $WEEKLY_NOTE_EXIT_CODE ===" >> "$LOG_FILE"
  notify_failure "weekly-note-$WEEKLY_NOTE_EXIT_CODE"
  true
}
echo "=== weekly note finished at $(date) ===" >> "$LOG_FILE"
echo "=== monthly note started at $(date) ===" >> "$LOG_FILE"
/usr/bin/python3 "$SCRIPT_DIR/gen_monthly_note.py" >> "$LOG_FILE" 2>&1 || {
  MONTHLY_NOTE_EXIT_CODE=$?
  echo "=== monthly note failed with exit code $MONTHLY_NOTE_EXIT_CODE ===" >> "$LOG_FILE"
  notify_failure "monthly-note-$MONTHLY_NOTE_EXIT_CODE"
  true
}
echo "=== monthly note finished at $(date) ===" >> "$LOG_FILE"
echo "=== daily archive started at $(date) ===" >> "$LOG_FILE"
/usr/bin/python3 "$SCRIPT_DIR/archive_daily_notes.py" >> "$LOG_FILE" 2>&1 || {
  ARCHIVE_EXIT_CODE=$?
  echo "=== daily archive failed with exit code $ARCHIVE_EXIT_CODE ===" >> "$LOG_FILE"
  notify_failure "daily-archive-$ARCHIVE_EXIT_CODE"
  true
}
echo "=== daily archive finished at $(date) ===" >> "$LOG_FILE"

echo "=== obsidian-ingest finished at $(date) with exit code $EXIT_CODE ===" >> "$LOG_FILE"

# 30日より古いログを掃除する。
find "$LOG_DIR" -name "ingest-*.log" -mtime +30 -delete 2>/dev/null || true

exit "$EXIT_CODE"
