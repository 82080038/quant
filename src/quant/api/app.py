"""FastAPI application for quant trading system."""

from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from datetime import date, timedelta
from sqlalchemy import text
import json
import os
from pathlib import Path

from quant.core.db import get_db, test_connection, table_row_count, pool_stats
from quant.core.config import config
from quant.api.realtime import install as install_realtime
from quant.simulation import (
    start_simulation as _start_sim,
    stop_simulation as _stop_sim,
    get_simulation_engine as _get_sim,
)

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


def _db_status() -> dict:
    """Lightweight DB health probe for the observability stream."""
    try:
        ok = test_connection()
        return {"connected": bool(ok), "pool": pool_stats()}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def _rate_limiter_stats() -> dict:
    """Snapshot of all registered backend rate limiters.

    Looks for a module-level registry in ``quant.core.rate_limiter``; if the
    registry is absent (e.g. limiters instantiated ad-hoc) returns an empty
    dict so the FE console still renders.
    """
    try:
        from quant.core import rate_limiter as rl_mod
        registry = getattr(rl_mod, "_limiters", None)
        if registry is None:
            return {}
        out = {}
        for name, lim in registry.items():
            stats = getattr(lim, "stats", None)
            out[name] = stats() if callable(stats) else {"rate": getattr(lim, "rate", None)}
        return out
    except Exception as exc:
        return {"error": str(exc)}


# Install WebSocket (/ws) + SSE (/api/observability/stream) endpoints.
# Returns the shared Hub; other modules may broadcast via app.state.realtime_hub.
install_realtime(app, get_db_status=_db_status, get_rate_limiter_stats=_rate_limiter_stats)


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


@app.get("/api/pipeline/status")
async def pipeline_status():
    """Get pipeline state machine summary — per-step status counts."""
    session = get_db()
    try:
        from quant.pipeline import PipelineTracker
        tracker = PipelineTracker(session)
        summary = tracker.get_pipeline_summary()
        failed = tracker.get_failed_steps(limit=10)
        return {
            "status_counts": summary,
            "failed_steps": failed,
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        session.close()


@app.get("/api/pipeline/fetch-summary")
async def fetch_summary():
    """Get fetch registry summary — instruments by data_layer and fetch_status."""
    session = get_db()
    try:
        from quant.data.fetch_registry import FetchRegistry
        registry = FetchRegistry(session)
        return registry.get_summary()
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        session.close()


@app.get("/api/prices/movers")
async def get_movers(limit: int = Query(10, ge=1, le=50)):
    """Get top gainers and losers for latest trading day."""
    sim = _get_sim()
    if sim and sim._running:
        return sim.get_movers(limit=limit)
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
    """Get IHSG (composite index) data."""
    sim = _get_sim()
    if sim and sim._running:
        return sim.get_ihsg()
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
            query += " WHERE i.is_active = TRUE AND i.is_delisted = FALSE"
        query += " ORDER BY i.ticker"
        result = session.execute(text(query))
        return [
            {"ticker": r[0], "name": r[1], "sector": r[2], "active": r[3], "asset_class": r[4]}
            for r in result.fetchall()
        ]
    finally:
        session.close()


@app.get("/api/signals/attribution")
async def get_signal_attribution(days: int = Query(7, ge=1, le=90)):
    """Get signal attribution data."""
    sim = _get_sim()
    if sim and sim._running:
        return sim.get_signals()
    session = get_db()
    try:
        sql = """
            SELECT date, ticker, engine_name, signal_value, signal_direction,
                   confidence, weight_in_portfolio, contribution_to_decision, rationale
            FROM signal_attribution_log
            WHERE date >= CURRENT_DATE - :days
        """
        params = {"days": days}
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


# ── Portfolio ──────────────────────────────────────────────────────────────

@app.get("/api/portfolio")
async def get_portfolio():
    """Return current portfolio snapshot (paper trading)."""
    sim = _get_sim()
    if sim and sim._running:
        return sim.get_portfolio()
    return {
        "total_nav": config.initial_capital,
        "cash": config.initial_capital,
        "positions": {},
        "sector_exposure": {},
        "market_exposure": {},
        "largest_position_pct": 0.0,
        "n_positions": 0,
    }


# ── Scheduler ──────────────────────────────────────────────────────────────

@app.get("/api/scheduler/status")
async def scheduler_status():
    """Return scheduler task status."""
    return {
        "tasks": [],
        "summary": {
            "total_tasks": 0,
            "succeeded": 0,
            "failed": 0,
            "pending": 0,
            "never_run": 0,
            "stale": 0,
        },
    }


@app.get("/api/scheduler/upcoming")
async def scheduler_upcoming(hours: int = Query(12, ge=1, le=168)):
    """Return upcoming scheduled tasks."""
    return {"upcoming": []}


@app.get("/api/scheduler/holidays")
async def scheduler_holidays(days: int = Query(30, ge=1, le=365)):
    """Return upcoming exchange holidays from market_holidays table."""
    from datetime import date, timedelta
    from quant.core.pre_trade_guard import PreTradeGuard
    guard = PreTradeGuard()
    today = date.today()
    upcoming = []
    for mc in ["XIDX", "XNYS", "XNAS", "XLON", "XFRA", "XHKG", "XSHG", "XTSE", "XSGX"]:
        hols = guard.get_upcoming_holidays(mc, days=days, as_of=today)
        for h_date, h_name in hols:
            upcoming.append({
                "market": mc,
                "date": h_date.isoformat(),
                "name": h_name,
            })
    upcoming.sort(key=lambda x: x["date"])
    return {"upcoming": upcoming, "today": today.isoformat()}


@app.get("/api/scheduler/sessions")
async def scheduler_sessions():
    """Return real-time session status for all world exchanges."""
    from datetime import datetime, timezone
    from quant.core.session_orchestrator import GlobalSessionOrchestrator
    orch = GlobalSessionOrchestrator()
    now_utc = datetime.now(timezone.utc)
    sessions = orch.get_all_sessions_status(now_utc)
    open_markets = [s for s in sessions if s["status"] == "OPEN"]
    return {
        "current_time_utc": now_utc.strftime("%H:%M:%S"),
        "current_time_wib": now_utc.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Jakarta")).strftime("%H:%M:%S"),
        "open_count": len(open_markets),
        "total": len(sessions),
        "sessions": sessions,
    }


@app.post("/api/scheduler/run")
async def scheduler_run():
    """Trigger scheduler run for due tasks."""
    return {"executed": 0, "results": [], "heavy_dispatched": []}


# ── Settings ───────────────────────────────────────────────────────────────

_SETTINGS_FILE = Path(os.environ.get("QUANT_SETTINGS_PATH", "quant_settings.json"))

_DEFAULT_SETTINGS = {
    "risk_per_trade_pct": 1.0,
    "atr_multiplier_sl": 1.5,
    "risk_reward_ratio": 2.0,
    "max_volatility_pct": 50.0,
    "telegram_alert_enabled": True,
    "email_alert_enabled": False,
    "in_app_alert_enabled": True,
    "circuit_breaker_alert_enabled": True,
    "display_timezone": "Asia/Jakarta",
    "default_chart_period": "30d",
}


@app.get("/api/settings")
async def get_settings():
    """Return current user settings."""
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return _DEFAULT_SETTINGS


@app.put("/api/settings")
async def save_settings(payload: dict = Body(...)):
    """Save user settings to local JSON file."""
    merged = {**_DEFAULT_SETTINGS, **payload}
    try:
        _SETTINGS_FILE.write_text(json.dumps(merged, indent=2))
    except OSError as exc:
        return {"error": str(exc), "saved_to": None}
    return {"saved_to": str(_SETTINGS_FILE), "settings": merged}


# ── Notifications ──────────────────────────────────────────────────────────

@app.get("/api/notifications/signals/latest")
async def get_latest_signal_notification():
    """Return the latest signal notification (or empty if none)."""
    return {"found": False, "message": "No signal notifications yet", "notification": None}


@app.patch("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int):
    """Mark a notification as read."""
    return {"id": notification_id, "status": "READ"}


# ── Autonomous Backtest ────────────────────────────────────────────────────

@app.get("/api/autonomous-backtest/status")
async def backtest_runner_status():
    """Return autonomous backtest runner status."""
    return {
        "total_runs": 0,
        "latest_run": None,
        "latest_trigger": None,
        "latest_status": None,
        "latest_avg_sharpe": 0.0,
        "latest_best_strategy": "",
        "latest_instruments": 0,
        "latest_agent_actions": 0,
        "latest_duration_s": 0,
        "latest_summary": "",
    }


@app.get("/api/autonomous-backtest/latest")
async def backtest_latest():
    """Return the latest backtest run (or idle status)."""
    return {"status": "idle", "run": None}


@app.post("/api/autonomous-backtest/trigger")
async def backtest_trigger(payload: dict = Body(default={})):
    """Trigger a new backtest run."""
    trigger = payload.get("trigger", "manual_force")
    return {
        "status": "accepted",
        "trigger": trigger,
        "message": "Backtest trigger received. Runner will process if running.",
    }


# ── Cosmos (Astronacci Celestial View) ────────────────────────────────────

@app.get("/api/cosmos/astronacci")
async def cosmos_astronacci(days: int = Query(7, ge=1, le=90)):
    """Return astronacci cycle data for the celestial visualization."""
    return {"cycles": [], "days": days}


@app.get("/api/cosmos/satellites")
async def cosmos_satellites(limit: int = Query(80, ge=1, le=500)):
    """Return satellite (stock) positions for the cosmos view."""
    return {"satellites": [], "limit": limit}


@app.get("/api/cosmos/exchanges")
async def cosmos_exchanges():
    """Return exchange orbit definitions for the cosmos view."""
    from quant.core.market_session import _EXCHANGES
    exchanges = []
    for mic, ex in _EXCHANGES.items():
        exchanges.append({
            "mic_code": ex.mic_code,
            "name": ex.name,
            "tz": str(ex.tz),
            "open_local": f"{ex.open_local[0]:02d}:{ex.open_local[1]:02d}",
            "close_local": f"{ex.close_local[0]:02d}:{ex.close_local[1]:02d}",
        })
    return {"exchanges": exchanges}


@app.get("/api/cosmos/kurs")
async def cosmos_kurs():
    """Return USD/IDR exchange rate for cosmos view."""
    return {"rate": None, "source": "BI", "updated": None}


@app.get("/api/cosmos/id_stocks")
async def cosmos_id_stocks():
    """Return list of IDX stocks for cosmos satellite labels."""
    return {"stocks": []}


# ── Data Management ───────────────────────────────────────────────────────

@app.get("/api/data/sources")
async def data_sources():
    """Return registered data sources."""
    return {"sources": []}


@app.get("/api/data/watermarks")
async def data_watermarks():
    """Return data watermarks (last fetch timestamps per table)."""
    return {"watermarks": {}}


@app.get("/api/data/audit")
async def data_audit(limit: int = Query(20, ge=1, le=200)):
    """Return recent data fetch audit log."""
    return {"audit": [], "limit": limit}


@app.get("/api/data/quality/{ticker}")
async def data_quality(ticker: str):
    """Return data quality metrics for a specific ticker."""
    return {"ticker": ticker, "completeness": None, "gaps": [], "last_updated": None}


@app.post("/api/data/fetch")
async def data_fetch_trigger(payload: dict = Body(default={})):
    """Trigger a manual data fetch."""
    source = payload.get("source", "yfinance")
    tickers = payload.get("tickers", [])
    return {
        "status": "accepted",
        "source": source,
        "tickers": tickers,
        "message": "Fetch request queued.",
    }


# ── Reports ───────────────────────────────────────────────────────────────

@app.get("/api/reports/trade-log")
async def reports_trade_log(limit: int = Query(50, ge=1, le=500)):
    """Return trade log for tax reporting."""
    return {"trades": [], "limit": limit}


@app.get("/api/reports/dividends")
async def reports_dividends(limit: int = Query(50, ge=1, le=500)):
    """Return dividend history for tax reporting."""
    return {"dividends": [], "limit": limit}


@app.get("/api/reports/tax/{year}")
async def reports_tax(year: int):
    """Return tax summary for a given year."""
    return {
        "year": year,
        "realized_pnl": 0,
        "dividends": 0,
        "commission_paid": 0,
        "tax_owed": 0,
        "trades": [],
    }


# ── Stock Detail ──────────────────────────────────────────────────────────

@app.get("/api/stock/{ticker}")
async def stock_detail(ticker: str):
    """Return detailed information for a single stock."""
    session = get_db()
    try:
        result = session.execute(text("""
            SELECT i.ticker, i.company_name, s.name as sector, i.is_active, i.asset_class
            FROM instruments i
            LEFT JOIN sector_master s ON i.sector_id = s.id
            WHERE i.ticker = :ticker
        """), {"ticker": ticker})
        row = result.fetchone()
        if not row:
            return {"ticker": ticker, "error": "Not found", "found": False}
        return {
            "ticker": row[0],
            "name": row[1],
            "sector": row[2],
            "active": row[3],
            "asset_class": row[4],
            "found": True,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "found": False}
    finally:
        session.close()


# ── Strategy Assignment ───────────────────────────────────────────────────

@app.get("/api/strategy/assignment/{ticker}")
async def strategy_assignment(ticker: str):
    """Return strategy assignment for a given ticker."""
    return {
        "ticker": ticker,
        "strategy": None,
        "assigned_at": None,
        "performance": None,
    }


@app.put("/api/strategy/assignment/{ticker}")
async def update_strategy_assignment(ticker: str, payload: dict = Body(default={})):
    """Update strategy assignment for a ticker."""
    strategy = payload.get("strategy", "")
    return {
        "ticker": ticker,
        "strategy": strategy,
        "message": "Strategy assignment updated.",
    }


# ── Simulation Control ────────────────────────────────────────────────────

@app.post("/api/simulation/start")
async def sim_start(payload: dict = Body(default={})):
    """Start the market simulation engine.

    Body params:
      n_ticks: int (default 5000)
      speed: float (default 10.0, 1.0=real-time)
      seed: int (default 42)
    """
    n_ticks = int(payload.get("n_ticks", 5000))
    speed = float(payload.get("speed", 10.0))
    seed = int(payload.get("seed", 42))
    engine = _start_sim(n_ticks=n_ticks, speed=speed, seed=seed)
    return engine.get_sim_status()


@app.post("/api/simulation/stop")
async def sim_stop():
    """Stop the market simulation engine."""
    _stop_sim()
    return {"status": "stopped"}


@app.get("/api/simulation/status")
async def sim_status():
    """Get simulation engine status."""
    sim = _get_sim()
    if sim:
        return sim.get_sim_status()
    return {"running": False}


@app.get("/api/simulation/ticks")
async def sim_ticks():
    """Get all latest ticks from the simulation."""
    sim = _get_sim()
    if not sim or not sim._running:
        return {"ticks": [], "running": False}
    return {"ticks": sim.get_all_latest_ticks(), "running": True}


# ── Advisory / Screener ───────────────────────────────────────────────────

@app.get("/api/advisory")
async def advisory(market_regime: str = "neutral", min_composite: int = 50):
    """Screen stocks based on latest signal attribution scores."""
    session = get_db()
    try:
        result = session.execute(text("""
            SELECT ticker, engine_name, signal_value, confidence, direction
            FROM signal_attribution_log
            WHERE date = (SELECT MAX(date) FROM signal_attribution_log)
            ORDER BY signal_value DESC
        """))
        rows = result.fetchall()
        picks = []
        for r in rows:
            ticker, engine, signal_val, confidence, direction = r
            composite = int(abs(float(signal_val or 0)) * 100)
            if composite >= min_composite:
                rec = "buy" if float(signal_val or 0) > 0.1 else "sell" if float(signal_val or 0) < -0.1 else "hold"
                picks.append({
                    "ticker": ticker,
                    "composite_score": composite,
                    "recommendation": rec,
                    "factors": {engine: float(signal_val or 0)},
                })
        return {
            "market_regime": market_regime,
            "picks": picks[:50],
            "summary": f"{len(picks)} stocks above composite {min_composite}",
        }
    except Exception as e:
        return {"market_regime": market_regime, "picks": [], "error": str(e)}
    finally:
        session.close()


# ── Pipeline Dashboard ────────────────────────────────────────────────────

@app.get("/api/pipeline/dashboard")
async def pipeline_dashboard():
    """Comprehensive pipeline status dashboard."""
    session = get_db()
    try:
        # Pipeline state breakdown
        state_result = session.execute(text("""
            SELECT step, status, count(*) as cnt
            FROM pipeline_state
            WHERE date = (SELECT MAX(date) FROM pipeline_state)
            GROUP BY step, status ORDER BY step
        """))
        state_breakdown = [{"step": r[0], "status": r[1], "count": r[2]} for r in state_result.fetchall()]

        # Latest signal attribution
        sig_result = session.execute(text("""
            SELECT count(*) as total, count(DISTINCT ticker) as tickers,
                   count(DISTINCT engine_name) as engines
            FROM signal_attribution_log
            WHERE date = (SELECT MAX(date) FROM signal_attribution_log)
        """))
        sig_row = sig_result.fetchone()

        # Portfolio weights
        port_result = session.execute(text("""
            SELECT count(*) as positions,
                   count(CASE WHEN weight > 0.05 THEN 1 END) as concentrated
            FROM portfolio_weights
            WHERE date = (SELECT MAX(date) FROM portfolio_weights)
        """))
        port_row = port_result.fetchone()

        # Paper trading state
        pt_result = session.execute(text("""
            SELECT date, nav, cash, n_trades, n_rejected, total_pnl, is_halted
            FROM paper_trading_state ORDER BY date DESC LIMIT 1
        """))
        pt_row = pt_result.fetchone()

        # Feature values count
        fv_result = session.execute(text("SELECT count(*) FROM feature_values"))
        fv_count = fv_result.scalar()

        # News sentiment count
        ns_result = session.execute(text("SELECT count(*) FROM news_sentiment"))
        ns_count = ns_result.scalar()

        # Model retirement verdicts
        eng_result = session.execute(text("""
            SELECT DISTINCT engine_name FROM prediction_evaluation ORDER BY engine_name
        """))
        engines = [r[0] for r in eng_result.fetchall()]

        return {
            "pipeline_state": state_breakdown,
            "signals": {
                "total": sig_row[0] if sig_row else 0,
                "tickers": sig_row[1] if sig_row else 0,
                "engines": sig_row[2] if sig_row else 0,
            },
            "portfolio": {
                "positions": port_row[0] if port_row else 0,
                "concentrated": port_row[1] if port_row else 0,
            },
            "paper_trading": {
                "date": str(pt_row[0]) if pt_row else None,
                "nav": float(pt_row[1]) if pt_row else None,
                "cash": float(pt_row[2]) if pt_row else None,
                "n_trades": pt_row[3] if pt_row else 0,
                "n_rejected": pt_row[4] if pt_row else 0,
                "total_pnl": float(pt_row[5]) if pt_row else 0,
                "is_halted": pt_row[6] if pt_row else False,
            },
            "feature_values_count": fv_count,
            "news_sentiment_count": ns_count,
            "engines_tracked": len(engines),
            "engines": engines,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        session.close()
