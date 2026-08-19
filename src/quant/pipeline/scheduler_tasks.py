"""Register pipeline tasks in the TaskScheduler.

Wires the PipelineOrchestrator steps into the TaskScheduler
with proper scheduling and dependencies.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Optional

from quant.core.db import get_db
from quant.monitoring.scheduler import TaskScheduler
from quant.pipeline.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)

__all__ = ["register_pipeline_tasks", "create_scheduler"]


def create_scheduler(session=None) -> TaskScheduler:
    """Create a TaskScheduler with all pipeline tasks registered."""
    if session is None:
        session = get_db()
    scheduler = TaskScheduler(session=session)
    register_pipeline_tasks(scheduler, session)
    return scheduler


def register_pipeline_tasks(scheduler: TaskScheduler, session=None) -> None:
    """Register all pipeline tasks in the scheduler.

    Tasks registered:
      1. daily_pipeline — full pipeline run at 17:30 WIB
      2. daily_reconciliation — portfolio reconciliation at 17:45 WIB
      3. weekly_backtest — backtest validation weekly on Monday 18:00
      4. weekly_retirement — model retirement check weekly Monday 18:30
    """
    if session is None:
        session = get_db()

    def _run_daily_pipeline():
        orch = PipelineOrchestrator(session=session)
        try:
            today = date.today()
            summary = orch.run_daily(today, universe_limit=50)
            logger.info("Daily pipeline completed: %s", summary)
        finally:
            orch.close()

    def _run_reconciliation():
        from quant.execution.paper_trading import PaperTradingOMS
        from quant.data.point_in_time import PointInTimeQuery

        oms = PaperTradingOMS()
        pit = PointInTimeQuery(session)
        today = date.today()

        # Get current portfolio prices
        prices = {}
        for ticker in oms.positions:
            df = pit.get_prices(ticker, today, lookback=5)
            if not df.empty:
                prices[ticker] = float(df["close"].iloc[-1])

        if prices:
            result = oms.reconcile(prices)
            logger.info(
                "Reconciliation: NAV=%.0f, PnL=%.0f, drawdown=%.2f%%, ok=%s",
                result.nav, result.total_pnl, result.max_drawdown * 100,
                result.reconciliation_ok,
            )

    def _run_weekly_backtest():
        from quant.backtest.engine import BacktestEngine
        engine = BacktestEngine(session=session)
        result = engine.run(
            start_date=date.today().replace(month=date.today().month - 3),
            end_date=date.today(),
            strategy="hrp_mu",
        )
        logger.info("Weekly backtest: Sharpe=%.2f, MaxDD=%.2f%%", result.sharpe_ratio, result.max_drawdown * 100)

    def _run_retirement_check():
        from quant.evaluation.ic_tracking import ICTracker
        tracker = ICTracker(session=session)
        report = tracker.generate_report()
        retired = tracker.retire_low_ic_engines(threshold=0.01)
        logger.info("Retirement check: retired %d engines", len(retired))

    scheduler.add_task(
        "daily_pipeline",
        _run_daily_pipeline,
        schedule="daily",
        time=time(17, 30),
    )
    scheduler.add_task(
        "daily_reconciliation",
        _run_reconciliation,
        schedule="daily",
        time=time(17, 45),
    )
    scheduler.add_task(
        "weekly_backtest",
        _run_weekly_backtest,
        schedule="weekly",
        time=time(18, 0),
    )
    scheduler.add_task(
        "retirement_check",
        _run_retirement_check,
        schedule="weekly",
        time=time(18, 30),
    )

    logger.info("Registered %d pipeline tasks", len(scheduler._tasks))
