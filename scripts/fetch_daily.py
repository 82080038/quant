"""Daily data fetch using FetchRegistry.

Reads the FetchRegistry to determine which instruments need fetching,
then uses yfinance to download and store OHLCV data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf
from sqlalchemy import text

from quant.core.db import get_db
from quant.core.pre_trade_guard import PreTradeGuard
from quant.core.session_orchestrator import GlobalSessionOrchestrator
from quant.data.fetch_registry import FetchRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    session = get_db()
    registry = FetchRegistry(session)

    # Pre-trade guard: skip if IDX market is on holiday
    guard = PreTradeGuard()
    today = date.today()
    if not guard.is_market_open("XIDX", today):
        guard.log_idle_mode("XIDX", today)
        logger.info("Skipping daily fetch — IDX market closed (holiday/weekend).")
        session.close()
        return

    # Session orchestrator: check if IDX is in session or post-market
    orch = GlobalSessionOrchestrator()
    now_utc = datetime.now(timezone.utc)
    status = orch.get_session_status("XIDX", now_utc)
    logger.info("IDX session status: %s (UTC %s / WIB %s)", status["status"], status["current_time_utc"], status["current_time_wib"])

    if status["status"] == "CLOSED":
        # Market closed but not holiday — still fetch (end-of-day data)
        logger.info("IDX market closed — fetching end-of-day data.")

    # Get all pending fetches across all data layers
    pending = registry.get_pending_fetches()
    logger.info("Pending fetches: %d instruments", len(pending))

    if not pending:
        # No pending — check if any are stale by time
        from datetime import datetime, UTC
        now = datetime.now(UTC)
        result = session.execute(text(
            "SELECT ticker, data_layer, fetch_frequency, last_fetch_at, next_fetch_at "
            "FROM instruments WHERE is_active = TRUE AND is_delisted = FALSE "
            "AND (next_fetch_at IS NULL OR next_fetch_at <= :now) "
            "ORDER BY data_layer, ticker"
        ), {"now": now})
        rows = result.fetchall()
        logger.info("Stale by time: %d instruments", len(rows))
        pending_tickers = [r[0] for r in rows]
    else:
        pending_tickers = [item.ticker for item in pending]

    if not pending_tickers:
        logger.info("Nothing to fetch — all instruments up to date")
        session.close()
        return

    logger.info("Fetching %d tickers via yfinance...", len(pending_tickers))

    batch_size = 50
    total_saved = 0
    errors = 0

    for i in range(0, len(pending_tickers), batch_size):
        batch = pending_tickers[i : i + batch_size]
        yf_tickers = " ".join(batch)
        try:
            data = yf.download(yf_tickers, period="5d", interval="1d", group_by="ticker", progress=False)
            for ticker in batch:
                try:
                    if len(batch) > 1:
                        df = data[ticker] if ticker in data else None
                    else:
                        df = data
                    if df is None or df.empty:
                        continue
                    df = df.dropna(subset=["Close"])
                    rows_saved = 0
                    for idx, row in df.iterrows():
                        row_date = idx.date()
                        session.execute(
                            text(
                                "INSERT INTO stock_prices (ticker, date, open, high, low, close, volume, adj_close, as_of_date) "
                                "VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :adj_close, :as_of) "
                                "ON CONFLICT (ticker, date, as_of_date) DO UPDATE "
                                "SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, "
                                "close=EXCLUDED.close, volume=EXCLUDED.volume, adj_close=EXCLUDED.adj_close"
                            ),
                            {
                                "ticker": ticker,
                                "date": row_date,
                                "open": float(row.get("Open", 0)),
                                "high": float(row.get("High", 0)),
                                "low": float(row.get("Low", 0)),
                                "close": float(row.get("Close", 0)),
                                "volume": int(row.get("Volume", 0)) if pd.notna(row.get("Volume")) else None,
                                "adj_close": float(row.get("Adj Close", 0)) if pd.notna(row.get("Adj Close")) else None,
                                "as_of": date.today(),
                            },
                        )
                        rows_saved += 1
                    total_saved += rows_saved
                    if rows_saved > 0:
                        registry.mark_fetched(ticker, rows=rows_saved)
                except Exception as e:
                    logger.warning("Error %s: %s", ticker, e)
                    registry.mark_failed(ticker, str(e))
                    errors += 1
            session.commit()
        except Exception as e:
            logger.error("Batch error: %s", e)
            session.rollback()
            errors += len(batch)
        logger.info("Batch %d/%d done", i // batch_size + 1, (len(pending_tickers) - 1) // batch_size + 1)

    logger.info("Total rows saved: %d, errors: %d", total_saved, errors)

    # Print fetch registry summary
    summary = registry.get_summary()
    print("\nFetch registry summary:")
    for layer, statuses in summary.items():
        print(f"  {layer}: {statuses}")

    session.close()


if __name__ == "__main__":
    main()
