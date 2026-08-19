# ──────────────────────────────────────────────────────────────────────
# Quant — Daily data fetch to quant DB (Windows PowerShell)
# Runs at 17:00 WIB (10:00 UTC) Mon-Fri after IDX close
# ──────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectDir "logs"
$LogFile = Join-Path $LogDir "daily_fetch.log"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

Add-Content -Path $LogFile -Value "============================================"
Add-Content -Path $LogFile -Value "[$(Get-Date)] Quant daily fetch starting"

Set-Location $ProjectDir

# TODO: Replace with quant's own fetch pipeline once built
# For now, fetch via yfinance directly into quant DB
$PyScript = @"
import yfinance as yf
import psycopg2
import pandas as pd
from datetime import datetime, timedelta

conn = psycopg2.connect('postgresql://petrick:market_dev@localhost:5432/quant')
cur = conn.cursor()

cur.execute("SELECT ticker FROM instruments WHERE is_active = TRUE AND asset_class = 'equity'")
tickers = [r[0] for r in cur.fetchall()]
print(f'Fetching {len(tickers)} tickers...')

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
"@

$output = & $Python -c $PyScript 2>&1
Add-Content -Path $LogFile -Value $output

Add-Content -Path $LogFile -Value "[$(Get-Date)] Quant daily fetch complete"
Add-Content -Path $LogFile -Value "============================================"
