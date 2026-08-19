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

    def _run_causality_computation():
        """Compute cross-asset causality matrix and store in DB.

        Runs Granger causality, CCF time-lag, and VAR analysis for all
        target tickers against global reference assets, then upserts
        results into global_market_interdependencies and snapshots into
        global_market_interdependency_history.
        """
        from quant.analysis.causality import CausalityAnalyzer
        from quant.signals.relationship import REFERENCE_ASSETS
        from quant.data.point_in_time import PointInTimeQuery
        from sqlalchemy import text as sa_text
        import pandas as pd
        import numpy as np

        pit = PointInTimeQuery(session)
        today = date.today()
        analyzer = CausalityAnalyzer(max_lag=5, significance_level=0.05)

        # Get active tickers
        tickers = session.execute(sa_text(
            "SELECT ticker FROM instruments WHERE is_active = TRUE "
            "AND asset_class = 'equity' LIMIT 50"
        )).fetchall()
        tickers = [r[0] for r in tickers]

        # Load reference asset returns
        ref_returns = {}
        for ref_ticker in REFERENCE_ASSETS:
            try:
                df = pit.get_prices(ref_ticker, today, lookback=120)
                if df is not None and not df.empty and "close" in df.columns:
                    rets = df["close"].astype(float).pct_change().dropna()
                    if len(rets) >= 30:
                        ref_returns[ref_ticker] = rets
            except Exception:
                pass

        if not ref_returns:
            logger.warning("Causality computation: no reference asset data available")
            return

        total_pairs = 0
        for ticker in tickers:
            try:
                df = pit.get_prices(ticker, today, lookback=120)
                if df is None or df.empty or "close" not in df.columns:
                    continue
                target_returns = df["close"].astype(float).pct_change().dropna()
                if len(target_returns) < 30:
                    continue

                for ref_ticker, ref_rets in ref_returns.items():
                    result = analyzer.analyze_pair(
                        source_returns=ref_rets,
                        target_returns=target_returns,
                        source_name=ref_ticker,
                        target_name=ticker,
                    )

                    # Upsert into master table
                    session.execute(sa_text("""
                        INSERT INTO global_market_interdependencies
                            (source_instrument_id, target_instrument_id,
                             correlation_coefficient, causality_score,
                             causality_p_value, causality_direction,
                             time_lag_seconds, time_lag_periods,
                             impact_weight, regime, var_order, sample_size,
                             as_of_date, updated_at)
                        VALUES
                            (:src, :tgt, :corr, :caus, :pval, :dir,
                             :lag_sec, :lag_per, :impact, :regime,
                             :var_order, :n, :as_of, now())
                        ON CONFLICT (source_instrument_id, target_instrument_id, as_of_date)
                        DO UPDATE SET
                            correlation_coefficient = EXCLUDED.correlation_coefficient,
                            causality_score = EXCLUDED.causality_score,
                            causality_p_value = EXCLUDED.causality_p_value,
                            causality_direction = EXCLUDED.causality_direction,
                            time_lag_seconds = EXCLUDED.time_lag_seconds,
                            time_lag_periods = EXCLUDED.time_lag_periods,
                            impact_weight = EXCLUDED.impact_weight,
                            regime = EXCLUDED.regime,
                            var_order = EXCLUDED.var_order,
                            sample_size = EXCLUDED.sample_size,
                            updated_at = EXCLUDED.updated_at
                    """), {
                        "src": ref_ticker,
                        "tgt": ticker,
                        "corr": result.correlation_coefficient,
                        "caus": result.causality_score,
                        "pval": result.causality_p_value,
                        "dir": result.causality_direction,
                        "lag_sec": result.time_lag_seconds,
                        "lag_per": result.time_lag_periods,
                        "impact": result.impact_weight,
                        "regime": result.regime,
                        "var_order": result.var_order,
                        "n": result.sample_size,
                        "as_of": today,
                    })

                    # Snapshot into history table
                    session.execute(sa_text("""
                        INSERT INTO global_market_interdependency_history
                            (source_instrument_id, target_instrument_id,
                             correlation_coefficient, causality_score,
                             causality_p_value, causality_direction,
                             time_lag_seconds, time_lag_periods,
                             impact_weight, regime, var_order, sample_size,
                             snapshot_date)
                        VALUES
                            (:src, :tgt, :corr, :caus, :pval, :dir,
                             :lag_sec, :lag_per, :impact, :regime,
                             :var_order, :n, :snapshot_date)
                        ON CONFLICT (source_instrument_id, target_instrument_id, snapshot_date)
                        DO NOTHING
                    """), {
                        "src": ref_ticker,
                        "tgt": ticker,
                        "corr": result.correlation_coefficient,
                        "caus": result.causality_score,
                        "pval": result.causality_p_value,
                        "dir": result.causality_direction,
                        "lag_sec": result.time_lag_seconds,
                        "lag_per": result.time_lag_periods,
                        "impact": result.impact_weight,
                        "regime": result.regime,
                        "var_order": result.var_order,
                        "n": result.sample_size,
                        "snapshot_date": today,
                    })

                    total_pairs += 1

            except Exception as e:
                logger.warning("Causality computation failed for %s: %s", ticker, e)
                session.rollback()
                continue

        session.commit()
        logger.info("Causality computation complete: %d pairs processed", total_pairs)

    scheduler.add_task(
        "daily_pipeline",
        _run_daily_pipeline,
        schedule="daily",
        time=time(17, 30),
    )
    scheduler.add_task(
        "causality_computation",
        _run_causality_computation,
        schedule="daily",
        time=time(17, 15),
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
