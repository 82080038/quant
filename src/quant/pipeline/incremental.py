"""Incremental processing watermark helpers.

Provides bounded-load and checkpoint utilities so that pipeline modules
only process NEW data instead of recomputing from scratch.

Architecture (adapted from old market project):
  1. Check recompute_watermark for (ticker, table_name) → last_processed_date
  2. Load OHLCV data only from (last_processed_date - buffer_days) to latest
  3. Delete rows within max_horizon of watermark (for label recompute)
  4. Compute new rows
  5. Upsert watermark with new last_processed_date

References:
- https://cursa.app/en/page/maintaining-projections-with-incremental-and-replayable-processing
  "Incremental processing requires a durable record of how far the projection
   has processed. The checkpoint stores the last processed position."
- https://www.citusdata.com/blog/2018/06/14/scalable-incremental-data-aggregation/
  "Use a rollups table to track which events have been aggregated"
- Old market project: recompute_internal.py watermark functions
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)


def get_watermark(
    session,
    ticker: str,
    table_name: str,
) -> Optional[date]:
    """Get last-processed date from recompute_watermark.

    Uses composite primary key (ticker, table_name) for O(1) lookup.
    """
    result = session.execute(
        text("""
            SELECT last_processed_date FROM recompute_watermark
            WHERE ticker = :ticker AND table_name = :table_name
        """),
        {"ticker": ticker, "table_name": table_name},
    ).scalar_one_or_none()
    return result


def set_watermark(
    session,
    ticker: str,
    table_name: str,
    last_date: date,
    rows: int = 0,
) -> None:
    """Upsert watermark for a ticker+table.

    Atomic upsert via ON CONFLICT — no race conditions.
    """
    session.execute(
        text("""
            INSERT INTO recompute_watermark (ticker, table_name, last_processed_date, last_ohlcv_date, rows_processed, updated_at)
            VALUES (:ticker, :table_name, :last_date, :last_date, :rows, now())
            ON CONFLICT (ticker, table_name) DO UPDATE
            SET last_processed_date = EXCLUDED.last_processed_date,
                last_ohlcv_date = EXCLUDED.last_ohlcv_date,
                rows_processed = EXCLUDED.rows_processed,
                updated_at = EXCLUDED.updated_at
        """),
        {
            "ticker": ticker,
            "table_name": table_name,
            "last_date": last_date,
            "rows": rows,
        },
    )
    session.commit()


def get_watermark_fallback(
    session,
    ticker: str,
    table_name: str,
    fallback_date_col: str = "date",
) -> Optional[date]:
    """Get watermark with fallback to MAX(date) in target table.

    If recompute_watermark has no entry for this ticker+table,
    check the target table itself for the latest date.
    This handles the first incremental run gracefully.
    """
    wm = get_watermark(session, ticker, table_name)
    if wm is not None:
        return wm

    # Fallback: check MAX(date) in the target table
    try:
        result = session.execute(
            text(f"""
                SELECT MAX({fallback_date_col}) FROM {table_name}
                WHERE ticker = :ticker
            """),
            {"ticker": ticker},
        ).scalar_one_or_none()
        return result
    except Exception:
        return None


def load_ohlcv_since(
    session,
    ticker: str,
    since_date: Optional[date],
    buffer_days: int = 0,
) -> pd.DataFrame:
    """Load OHLCV data from (since_date - buffer_days) to latest.

    Bounded load for incremental recompute — only loads the data needed
    instead of full history. The buffer_days parameter adds extra lookback
    for indicators that need historical context (e.g. MA200 needs 200 days).

    Uses idx_stock_prices_ticker_date for fast range scan.
    """
    if since_date is None:
        # No watermark — load full history
        sql = text(
            "SELECT date, open, high, low, close, volume, adj_close "
            "FROM stock_prices WHERE ticker = :ticker ORDER BY date"
        )
        params = {"ticker": ticker}
    else:
        cutoff = since_date - timedelta(days=buffer_days)
        sql = text(
            "SELECT date, open, high, low, close, volume, adj_close "
            "FROM stock_prices WHERE ticker = :ticker AND date >= :cutoff "
            "ORDER BY date"
        )
        params = {"ticker": ticker, "cutoff": cutoff}

    df = pd.read_sql(sql, session.bind, params=params, index_col="date", parse_dates=["date"])
    if df.empty:
        return df

    # Dedup index
    if not df.index.is_unique:
        df = df[~df.index.duplicated(keep="last")]

    # Type conversion
    for col in ("open", "high", "low", "close", "adj_close"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    if "volume" in df.columns:
        df["volume"] = df["volume"].astype(int)

    return df


def is_computed(
    session,
    ticker: str,
    table_name: str,
    target_date: date,
) -> bool:
    """Check if a computation result already exists for a given date.

    Fast existence check using composite index — returns in <1ms.
    """
    try:
        result = session.execute(
            text(f"""
                SELECT 1 FROM {table_name}
                WHERE ticker = :ticker AND date = :date
                LIMIT 1
            """),
            {"ticker": ticker, "date": target_date},
        ).scalar_one_or_none()
        return result is not None
    except Exception:
        return False


def get_last_computed_date(
    session,
    ticker: str,
    table_name: str,
) -> Optional[date]:
    """Get the last computed date for a ticker in a target table.

    Used to determine if incremental processing can skip this ticker
    (if data is already up to date).
    """
    try:
        result = session.execute(
            text(f"""
                SELECT MAX(date) FROM {table_name}
                WHERE ticker = :ticker
            """),
            {"ticker": ticker},
        ).scalar_one_or_none()
        return result
    except Exception:
        return None


def get_stale_tickers(
    session,
    table_name: str,
    reference_date: Optional[date] = None,
) -> list[str]:
    """Get tickers whose data in target table is stale (behind stock_prices).

    Compares MAX(date) in stock_prices vs MAX(date) in target table.
    Returns tickers where stock_prices has newer data than the target.

    Uses idx_stock_prices_ticker_date for efficient MAX() per ticker.
    """
    if reference_date is None:
        reference_date = date.today()

    try:
        result = session.execute(
            text("""
                SELECT sp.ticker
                FROM (
                    SELECT ticker, MAX(date) as max_price_date
                    FROM stock_prices
                    GROUP BY ticker
                ) sp
                LEFT JOIN (
                    SELECT ticker, MAX(date) as max_computed_date
                    FROM """ + table_name + """
                    GROUP BY ticker
                ) t ON sp.ticker = t.ticker
                WHERE t.max_computed_date IS NULL
                   OR t.max_computed_date < sp.max_price_date
                ORDER BY sp.ticker
            """)
        ).fetchall()
        return [r[0] for r in result]
    except Exception as e:
        logger.warning("get_stale_tickers failed: %s", e)
        return []


def bulk_upsert(
    session,
    table_name: str,
    rows: list[dict],
    conflict_cols: list[str],
    batch_size: int = 5000,
) -> int:
    """Bulk upsert rows into a table with ON CONFLICT handling.

    Args:
        session: SQLAlchemy session.
        table_name: Target table.
        rows: List of dicts with column→value mappings.
        conflict_cols: Columns for ON CONFLICT clause.
        batch_size: Rows per batch for executemany.

    Returns:
        Number of rows upserted.
    """
    if not rows:
        return 0

    columns = list(rows[0].keys())
    col_list = ", ".join(columns)
    param_list = ", ".join(f":{c}" for c in columns)
    conflict_list = ", ".join(conflict_cols)
    update_list = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in conflict_cols)

    sql = text(f"""
        INSERT INTO {table_name} ({col_list})
        VALUES ({param_list})
        ON CONFLICT ({conflict_list}) DO UPDATE
        SET {update_list}
    """)

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        session.execute(sql, batch)
        total += len(batch)

    session.commit()
    return total
