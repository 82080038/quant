"""Daily paper trading loop.

Runs the full pipeline, executes orders via PaperTradingOMS,
persists state to DB, and sends alerts.

Usage:
    python scripts/run_paper_trading.py [--date 2026-08-18] [--universe 50]
"""

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from quant.core.db import get_db
from quant.pipeline.orchestrator import PipelineOrchestrator
from quant.monitoring.alerts import AlertManager, Alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def load_oms_state(session) -> dict:
    """Load latest OMS state from DB."""
    result = session.execute(text(
        "SELECT date, nav, cash, positions, peak_nav, current_drawdown, "
        "n_trades, n_rejected, total_pnl, is_halted, halt_reason "
        "FROM paper_trading_state ORDER BY date DESC LIMIT 1"
    ))
    row = result.fetchone()
    if row is None:
        return None
    return {
        "date": row[0],
        "nav": float(row[1]),
        "cash": float(row[2]),
        "positions": row[3] if isinstance(row[3], dict) else json.loads(row[3]),
        "peak_nav": float(row[4]),
        "current_drawdown": float(row[5]),
        "n_trades": row[6],
        "n_rejected": row[7],
        "total_pnl": float(row[8]),
        "is_halted": row[9],
        "halt_reason": row[10],
    }


def save_oms_state(session, state: dict) -> None:
    """Save OMS state to DB."""
    session.execute(text("""
        INSERT INTO paper_trading_state
            (date, nav, cash, positions, peak_nav, current_drawdown,
             n_trades, n_rejected, total_pnl, is_halted, halt_reason)
        VALUES
            (:date, :nav, :cash, :positions, :peak_nav, :drawdown,
             :n_trades, :n_rejected, :pnl, :halted, :reason)
        ON CONFLICT (date) DO UPDATE SET
            nav=EXCLUDED.nav, cash=EXCLUDED.cash, positions=EXCLUDED.positions,
            peak_nav=EXCLUDED.peak_nav, current_drawdown=EXCLUDED.current_drawdown,
            n_trades=EXCLUDED.n_trades, n_rejected=EXCLUDED.n_rejected,
            total_pnl=EXCLUDED.total_pnl, is_halted=EXCLUDED.is_halted,
            halt_reason=EXCLUDED.halt_reason
    """), {
        "date": state["date"],
        "nav": state["nav"],
        "cash": state["cash"],
        "positions": json.dumps(state["positions"]),
        "peak_nav": state["peak_nav"],
        "drawdown": state["current_drawdown"],
        "n_trades": state["n_trades"],
        "n_rejected": state["n_rejected"],
        "pnl": state["total_pnl"],
        "halted": state["is_halted"],
        "reason": state["halt_reason"],
    })
    session.commit()


def main():
    parser = argparse.ArgumentParser(description="Daily paper trading loop")
    parser.add_argument("--date", type=str, default=None, help="Trading date (YYYY-MM-DD)")
    parser.add_argument("--universe", type=int, default=50, help="Universe size")
    args = parser.parse_args()

    trading_date = date.fromisoformat(args.date) if args.date else date.today()
    session = get_db()

    # Load previous state
    prev_state = load_oms_state(session)
    if prev_state:
        logger.info("Previous state: date=%s nav=%.0f cash=%.0f trades=%d",
                     prev_state["date"], prev_state["nav"], prev_state["cash"], prev_state["n_trades"])
    else:
        logger.info("No previous state — starting fresh with 100M IDR")

    # Run pipeline
    logger.info("Running pipeline for %s (universe=%d)...", trading_date, args.universe)
    orch = PipelineOrchestrator(session=session)
    summary = orch.run_daily(trading_date, universe_limit=args.universe)

    logger.info("Pipeline: ingested=%d screened=%d signals=%d portfolio=%d executed=%d",
                summary.get("ingested", 0),
                summary.get("screened", 0),
                summary.get("signal_generated", 0),
                summary.get("portfolio_optimized", 0),
                summary.get("executed", 0))

    # Evaluate IC
    try:
        ic_result = orch.evaluate_ic(trading_date, horizon=5)
        logger.info("IC evaluated: %d engines", ic_result.get("engines_evaluated", 0))
    except Exception as e:
        logger.warning("IC evaluation failed: %s", e)

    # Save state
    execution = summary.get("execution_summary", {})
    current_state = {
        "date": str(trading_date),
        "nav": execution.get("nav", 100_000_000),
        "cash": execution.get("cash", 100_000_000),
        "positions": execution.get("positions", {}),
        "peak_nav": execution.get("peak_nav", 100_000_000),
        "current_drawdown": execution.get("current_drawdown", 0.0),
        "n_trades": execution.get("n_orders_accepted", 0),
        "n_rejected": execution.get("n_orders_rejected", 0),
        "total_pnl": execution.get("total_pnl", 0.0),
        "is_halted": False,
        "halt_reason": "",
    }
    save_oms_state(session, current_state)
    logger.info("State saved: nav=%.0f trades=%d rejected=%d",
                current_state["nav"], current_state["n_trades"], current_state["n_rejected"])

    # Send alerts
    am = AlertManager()
    alert_msg = (
        f"Date: {trading_date}\n"
        f"Signals: {summary.get('signal_generated', 0)}\n"
        f"Portfolio: {summary.get('portfolio_optimized', 0)} positions\n"
        f"Orders: {current_state['n_trades']} accepted, {current_state['n_rejected']} rejected\n"
        f"NAV: {current_state['nav']:,.0f} IDR"
    )
    am.send(Alert(
        title="Daily Paper Trading Complete",
        message=alert_msg,
        level="info" if current_state["n_rejected"] == 0 else "warning",
    ))

    # Print summary
    print("\n" + "=" * 60)
    print(f"PAPER TRADING SUMMARY — {trading_date}")
    print("=" * 60)
    print(f"  Signals generated: {summary.get('signal_generated', 0)}")
    print(f"  Portfolio positions: {summary.get('portfolio_optimized', 0)}")
    print(f"  Orders accepted: {current_state['n_trades']}")
    print(f"  Orders rejected: {current_state['n_rejected']}")
    print(f"  NAV: {current_state['nav']:,.0f} IDR")
    print(f"  State saved to paper_trading_state")

    session.close()


if __name__ == "__main__":
    main()
