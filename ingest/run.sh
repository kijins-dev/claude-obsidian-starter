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
fi

echo "=== obsidian-ingest finished at $(date) with exit code $EXIT_CODE ===" >> "$LOG_FILE"

# 30日より古いログを掃除する。
find "$LOG_DIR" -name "ingest-*.log" -mtime +30 -delete 2>/dev/null || true

exit "$EXIT_CODE"
