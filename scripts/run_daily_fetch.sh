#!/usr/bin/env bash
# Quant — Daily data fetch to quant DB
# Runs at 17:00 WIB (10:00 UTC) Mon-Fri after IDX close
# Currently minimal: fetch EOD data via yfinance → quant DB
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

# TODO: Replace with quant's own fetch pipeline once built
# For now, fetch via yfinance directly into quant DB
$PYTHON -c "
import yfinance as yf
import psycopg2
import pandas as pd
from datetime import datetime, timedelta

conn = psycopg2.connect('postgresql://petrick:market_dev@localhost:5432/quant')
cur = conn.cursor()

# Get active IDX tickers
cur.execute(\"SELECT ticker FROM instruments WHERE is_active = TRUE AND asset_class = 'equity'\")
tickers = [r[0] for r in cur.fetchall()]
print(f'Fetching {len(tickers)} tickers...')

# Fetch in batches of 50
batch_size = 50
total_saved = 0
for i in range(0, len(tickers), batch_size):
    batch = tickers[i:i+batch_size]
    yf_tickers = ' '.join(batch)
    try:
        data = yf.download(yf_tickers, period='5d', interval='1d', group_by='ticker', progress=False)
        for ticker in batch:
            try:
                if len(batch) > 1:
                    df = data[ticker] if ticker in data else None
                else:
                    df = data
                if df is None or df.empty:
                    continue
                df = df.dropna(subset=['Close'])
                for idx, row in df.iterrows():
                    date = idx.date()
                    cur.execute('''
                        INSERT INTO stock_prices (ticker, date, open, high, low, close, volume, adj_close)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (ticker, date, as_of_date) DO UPDATE
                        SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                            close=EXCLUDED.close, volume=EXCLUDED.volume, adj_close=EXCLUDED.adj_close
                    ''', (ticker, date, float(row.get('Open', 0)), float(row.get('High', 0)),
                          float(row.get('Low', 0)), float(row.get('Close', 0)),
                          int(row.get('Volume', 0)) if pd.notna(row.get('Volume')) else None,
                          float(row.get('Adj Close', 0)) if pd.notna(row.get('Adj Close')) else None))
                    total_saved += 1
            except Exception as e:
                print(f'  Error {ticker}: {e}')
        conn.commit()
    except Exception as e:
        print(f'  Batch error: {e}')
        conn.rollback()
    print(f'  Batch {i//batch_size + 1}/{(len(tickers)-1)//batch_size + 1} done')

print(f'Total rows saved: {total_saved}')
cur.close()
conn.close()
" >> "$LOG_FILE" 2>&1

echo "[$(date)] Quant daily fetch complete" >> "$LOG_FILE"
echo "============================================" >> "$LOG_FILE"
