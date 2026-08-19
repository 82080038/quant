#!/usr/bin/env bash
# Quant — Daily data fetch to quant DB
# Runs at 17:00 WIB (10:00 UTC) Mon-Fri after IDX close
# Uses FetchRegistry to determine what needs fetching, then yfinance → quant DB
#
# Cross-platform: works on Linux and Windows (Git Bash / WSL).
# On native Windows, use run_daily_fetch.ps1 instead.

set -e

# ── Cross-platform project dir detection ────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── OS-aware venv python path ───────────────────────────────────────────
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OS" == "Windows_NT" ]]; then
    PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"
else
    PYTHON="$PROJECT_DIR/.venv/bin/python3"
fi

LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/daily_fetch.log"

mkdir -p "$LOG_DIR"

echo "============================================" >> "$LOG_FILE"
echo "[$(date)] Quant daily fetch starting" >> "$LOG_FILE"

cd "$PROJECT_DIR"

# Use FetchRegistry to determine what needs fetching, then yfinance to fetch
$PYTHON scripts/fetch_daily.py >> "$LOG_FILE" 2>&1

echo "[$(date)] Quant daily fetch complete" >> "$LOG_FILE"
echo "============================================" >> "$LOG_FILE"
