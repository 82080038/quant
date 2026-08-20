"""
FE Dashboard Cache Layer — Materialized State Cache for zero-wait FE reads.

This module provides:
- write_cache(): Store computed engine results into fe_dashboard_cache
- read_cache(): Retrieve ready data for FE consumption
- write_daily_state(): Save end-of-day portfolio state for incremental computing
- read_daily_state(): Load previous day's state for T+1 incremental computation
- mark_fe_ready(): Flip is_fe_ready flag after computation completes
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger("fe_cache")


def write_cache(
    cache_key: str,
    sim_date: date,
    data_type: str,
    payload: dict[str, Any],
    ticker: str | None = None,
    mark_ready: bool = True,
) -> None:
    """Write computed data to fe_dashboard_cache (upsert)."""
    session = get_db()
    try:
        session.execute(text("""
            INSERT INTO fe_dashboard_cache (cache_key, sim_date, ticker, data_type, payload, is_fe_ready, last_computed_at)
            VALUES (:cache_key, :sim_date, :ticker, :data_type, CAST(:payload AS JSONB), :is_fe_ready, NOW())
            ON CONFLICT (cache_key, sim_date, ticker, data_type)
            DO UPDATE SET payload = CAST(:payload AS JSONB), is_fe_ready = :is_fe_ready, last_computed_at = NOW()
        """), {
            "cache_key": cache_key,
            "sim_date": sim_date,
            "ticker": ticker,
            "data_type": data_type,
            "payload": json.dumps(payload, default=str),
            "is_fe_ready": mark_ready,
        })
        session.commit()
    except Exception as e:
        session.rollback()
        logger.debug("write_cache failed: %s", e)
    finally:
        session.close()


def read_cache(
    cache_key: str,
    sim_date: date,
    data_type: str | None = None,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Read FE-ready data from cache. Returns empty list if not ready."""
    session = get_db()
    try:
        query = """
            SELECT payload, sim_date, ticker, data_type, last_computed_at
            FROM fe_dashboard_cache
            WHERE cache_key = :cache_key
              AND sim_date <= :sim_date
              AND is_fe_ready = TRUE
        """
        params: dict[str, Any] = {"cache_key": cache_key, "sim_date": sim_date}
        if data_type:
            query += " AND data_type = :data_type"
            params["data_type"] = data_type
        if ticker:
            query += " AND ticker = :ticker"
            params["ticker"] = ticker
        query += " ORDER BY sim_date DESC LIMIT 100"
        rows = session.execute(text(query), params).fetchall()
        return [
            {
                "payload": r[0] if isinstance(r[0], dict) else json.loads(r[0]),
                "sim_date": str(r[1]),
                "ticker": r[2],
                "data_type": r[3],
                "last_computed_at": str(r[4]) if r[4] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.debug("read_cache failed: %s", e)
        return []
    finally:
        session.close()


def write_daily_state(
    sim_date: date,
    equity: float,
    cash: float,
    positions: dict[str, Any],
    fib_pivots: dict[str, Any] | None = None,
    correlation_weights: dict[str, Any] | None = None,
    regime: str = "unknown",
    active_cycles: int = 0,
    n_positions: int = 0,
    n_trades: int = 0,
    lookahead_violations: int = 0,
) -> None:
    """Save end-of-day state for incremental T+1 computing (upsert)."""
    session = get_db()
    try:
        session.execute(text("""
            INSERT INTO daily_portfolio_states
                (sim_date, equity, cash, positions, fib_pivots, correlation_weights,
                 regime, active_cycles, n_positions, n_trades, lookahead_violations,
                 is_fe_ready, last_computed_at)
            VALUES
                (:sim_date, :equity, :cash, CAST(:positions AS JSONB),
                 CAST(:fib_pivots AS JSONB), CAST(:correlation_weights AS JSONB),
                 :regime, :active_cycles, :n_positions, :n_trades, :lookahead_violations,
                 TRUE, NOW())
            ON CONFLICT (sim_date)
            DO UPDATE SET
                equity = :equity, cash = :cash,
                positions = CAST(:positions AS JSONB),
                fib_pivots = CAST(:fib_pivots AS JSONB),
                correlation_weights = CAST(:correlation_weights AS JSONB),
                regime = :regime, active_cycles = :active_cycles,
                n_positions = :n_positions, n_trades = :n_trades,
                lookahead_violations = :lookahead_violations,
                is_fe_ready = TRUE, last_computed_at = NOW()
        """), {
            "sim_date": sim_date,
            "equity": equity,
            "cash": cash,
            "positions": json.dumps(positions, default=str),
            "fib_pivots": json.dumps(fib_pivots or {}, default=str),
            "correlation_weights": json.dumps(correlation_weights or {}, default=str),
            "regime": regime,
            "active_cycles": active_cycles,
            "n_positions": n_positions,
            "n_trades": n_trades,
            "lookahead_violations": lookahead_violations,
        })
        session.commit()
    except Exception as e:
        session.rollback()
        logger.debug("write_daily_state failed: %s", e)
    finally:
        session.close()


def read_daily_state(sim_date: date) -> dict[str, Any] | None:
    """Load the most recent daily state at or before sim_date for incremental computing."""
    session = get_db()
    try:
        row = session.execute(text("""
            SELECT sim_date, equity, cash, positions, fib_pivots, correlation_weights,
                   regime, active_cycles, n_positions, n_trades, lookahead_violations
            FROM daily_portfolio_states
            WHERE sim_date <= :sim_date AND is_fe_ready = TRUE
            ORDER BY sim_date DESC LIMIT 1
        """), {"sim_date": sim_date}).fetchone()
        if not row:
            return None
        return {
            "sim_date": str(row[0]),
            "equity": float(row[1]),
            "cash": float(row[2]),
            "positions": row[3] if isinstance(row[3], dict) else json.loads(row[3]),
            "fib_pivots": row[4] if isinstance(row[4], dict) else json.loads(row[4]),
            "correlation_weights": row[5] if isinstance(row[5], dict) else json.loads(row[5]),
            "regime": row[6],
            "active_cycles": row[7],
            "n_positions": row[8],
            "n_trades": row[9],
            "lookahead_violations": row[10],
        }
    except Exception as e:
        logger.debug("read_daily_state failed: %s", e)
        return None
    finally:
        session.close()


def mark_fe_ready(table_name: str, sim_date: date, ticker: str | None = None) -> None:
    """Mark rows in an engine result table as FE-ready."""
    session = get_db()
    try:
        if ticker:
            session.execute(text(f"""
                UPDATE {table_name} SET is_fe_ready = TRUE, last_computed_at = NOW()
                WHERE date = :sim_date AND ticker = :ticker
            """), {"sim_date": sim_date, "ticker": ticker})
        else:
            session.execute(text(f"""
                UPDATE {table_name} SET is_fe_ready = TRUE, last_computed_at = NOW()
                WHERE date = :sim_date
            """), {"sim_date": sim_date})
        session.commit()
    except Exception as e:
        session.rollback()
        logger.debug("mark_fe_ready failed: %s", e)
    finally:
        session.close()
