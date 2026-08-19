"""FastAPI application for quant trading system."""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from datetime import date, timedelta
from sqlalchemy import text

from quant.core.db import get_db, test_connection, table_row_count
from quant.core.config import config

app = FastAPI(
    title="Quant Trading API",
    description="Gigantic AI Quant Trading System for IDX & Global Markets",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    """System health check."""
    db_ok = test_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "version": "0.1.0",
        "config": {
            "initial_capital": config.initial_capital,
            "max_position_pct": config.max_position_pct,
            "max_drawdown": config.max_drawdown,
        },
    }


@app.get("/api/db/stats")
async def db_stats():
    """Database statistics."""
    tables = [
        "stock_prices", "foreign_flow", "macro_data", "fundamental_data",
        "news_sentiment", "instruments", "exchanges", "sector_master",
        "exchange_holidays", "policy_events", "external_events",
        "signal_attribution_log", "prediction_evaluation",
    ]
    stats = {}
    for t in tables:
        try:
            stats[t] = table_row_count(t)
        except Exception:
            stats[t] = "error"
    return stats


@app.get("/api/prices/movers")
async def get_movers(limit: int = Query(10, ge=1, le=50)):
    """Get top gainers and losers for latest trading day."""
    session = get_db()
    try:
        # Get latest trading day
        result = session.execute(text("SELECT MAX(date) FROM stock_prices"))
        latest_date = result.scalar()
        if not latest_date:
            return {"gainers": [], "losers": [], "as_of": None, "count": 0}

        # Get movers
        result = session.execute(text("""
            WITH latest AS (
                SELECT ticker, close, date,
                       LAG(close) OVER (PARTITION BY ticker ORDER BY date) as prev_close
                FROM stock_prices
                WHERE date = :latest_date
                   OR date = (
                       SELECT MAX(date) FROM stock_prices WHERE date < :latest_date
                   )
            )
            SELECT ticker, close, prev_close,
                   ((close - prev_close) / prev_close * 100) as pct_change
            FROM latest
            WHERE prev_close IS NOT NULL AND prev_close > 0
            ORDER BY pct_change DESC
            LIMIT :limit
        """), {"latest_date": latest_date, "limit": limit})
        gainers = [
            {"ticker": r[0], "close": float(r[1]), "prev_close": float(r[2]), "pct_change": float(r[3])}
            for r in result.fetchall()
        ]

        result = session.execute(text("""
            WITH latest AS (
                SELECT ticker, close, date,
                       LAG(close) OVER (PARTITION BY ticker ORDER BY date) as prev_close
                FROM stock_prices
                WHERE date = :latest_date
                   OR date = (
                       SELECT MAX(date) FROM stock_prices WHERE date < :latest_date
                   )
            )
            SELECT ticker, close, prev_close,
                   ((close - prev_close) / prev_close * 100) as pct_change
            FROM latest
            WHERE prev_close IS NOT NULL AND prev_close > 0
            ORDER BY pct_change ASC
            LIMIT :limit
        """), {"latest_date": latest_date, "limit": limit})
        losers = [
            {"ticker": r[0], "close": float(r[1]), "prev_close": float(r[2]), "pct_change": float(r[3])}
            for r in result.fetchall()
        ]

        return {
            "gainers": gainers,
            "losers": losers,
            "as_of": str(latest_date),
            "count": len(gainers) + len(losers),
        }
    finally:
        session.close()


@app.get("/api/prices/ihsg")
async def get_ihsg():
    """Get IHSG (composite index) latest data."""
    session = get_db()
    try:
        result = session.execute(text("""
            SELECT date, close,
                   LAG(close) OVER (ORDER BY date) as prev_close
            FROM stock_prices
            WHERE ticker = '^JKSE'
            ORDER BY date DESC
            LIMIT 2
        """))
        rows = result.fetchall()
        if len(rows) >= 2:
            latest = rows[0]
            prev = rows[1]
            price = float(latest[1])
            prev_close = float(prev[1])
            change = price - prev_close
            pct_change = (change / prev_close) * 100
            return {
                "price": price,
                "change": change,
                "pct_change": pct_change,
                "as_of": str(latest[0]),
            }
        return {"price": None, "change": None, "pct_change": None, "as_of": None}
    finally:
        session.close()


@app.get("/api/instruments")
async def list_instruments(active_only: bool = True):
    """List all instruments."""
    session = get_db()
    try:
        query = """
            SELECT i.ticker, i.company_name, s.name as sector, i.is_active, i.asset_class
            FROM instruments i
            LEFT JOIN sector_master s ON i.sector_id = s.id
        """
        if active_only:
            query += " WHERE i.is_active = TRUE"
        query += " ORDER BY i.ticker"
        result = session.execute(text(query))
        return [
            {"ticker": r[0], "name": r[1], "sector": r[2], "active": r[3], "asset_class": r[4]}
            for r in result.fetchall()
        ]
    finally:
        session.close()


@app.get("/api/signals/attribution")
async def get_signal_attribution(
    ticker: str = None,
    engine: str = None,
    days: int = Query(30, ge=1, le=365),
):
    """Get signal attribution log."""
    session = get_db()
    try:
        sql = """
            SELECT date, ticker, engine_name, signal_value, signal_direction,
                   confidence, weight_in_portfolio, contribution_to_decision, rationale
            FROM signal_attribution_log
            WHERE date >= CURRENT_DATE - :days
        """
        params = {"days": days}
        if ticker:
            sql += " AND ticker = :ticker"
            params["ticker"] = ticker
        if engine:
            sql += " AND engine_name = :engine"
            params["engine"] = engine
        sql += " ORDER BY date DESC, ticker, engine_name LIMIT 1000"
        result = session.execute(text(sql), params)
        return [
            {
                "date": str(r[0]),
                "ticker": r[1],
                "engine": r[2],
                "signal": float(r[3]) if r[3] else 0,
                "direction": r[4],
                "confidence": float(r[5]) if r[5] else 0,
                "weight": float(r[6]) if r[6] else 0,
                "contribution": float(r[7]) if r[7] else 0,
                "rationale": r[8],
            }
            for r in result.fetchall()
        ]
    finally:
        session.close()


@app.get("/api/evaluation/engines")
async def get_engine_evaluations():
    """Get evaluation summary for all engines (IC tracking)."""
    from quant.evaluation.ic_tracking import ICTracker
    tracker = ICTracker()
    try:
        df = tracker.engine_summary()
        if df.empty:
            return {"engines": [], "message": "No evaluation data yet"}
        return {
            "engines": df.to_dict(orient="records"),
            "total_engines": len(df),
        }
    except Exception as e:
        return {"error": str(e), "engines": []}


@app.get("/api/evaluation/ic/{engine_name}")
async def get_engine_ic(engine_name: str, window: int = Query(60, ge=1, le=365)):
    """Get rolling IC for a specific engine."""
    from quant.evaluation.ic_tracking import ICTracker
    tracker = ICTracker()
    try:
        df = tracker.rolling_ic(engine_name, window=window)
        if df.empty:
            return {"engine": engine_name, "ic_history": [], "message": "No IC data"}
        return {
            "engine": engine_name,
            "ic_history": df.to_dict(orient="records"),
            "latest_ic": float(df["ic"].iloc[-1]) if not df.empty else 0,
            "rolling_mean": float(df["rolling_mean"].iloc[-1]) if not df.empty and not pd.isna(df["rolling_mean"].iloc[-1]) else 0,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/evaluation/dsr")
async def compute_dsr(
    n_trials: int = Query(1, ge=1, le=100000),
    n_observations: int = Query(252, ge=10, le=10000),
    mean_return: float = Query(0.001, ge=-0.1, le=0.1),
    std_return: float = Query(0.015, ge=0.001, le=0.1),
):
    """Compute DSR for given parameters (demo endpoint)."""
    import numpy as np
    from quant.evaluation.dsr import deflated_sharpe_ratio
    rng = np.random.default_rng(42)
    returns = rng.normal(mean_return, std_return, n_observations)
    result = deflated_sharpe_ratio(returns, n_trials=n_trials)
    return {
        "observed_sr": result.observed_sr,
        "expected_max_sr": result.expected_max_sr,
        "psr": result.psr,
        "deflated_sr": result.deflated_sr,
        "is_real": result.is_real,
        "n_trials": result.n_trials,
        "n_observations": result.n_observations,
        "skewness": result.skewness,
        "kurtosis": result.kurtosis,
    }
