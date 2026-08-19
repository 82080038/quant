"""Pipeline orchestrator — end-to-end daily pipeline runner.

Integrates:
  1. PipelineTracker for per-ticker state tracking
  2. FactorLibrary for feature computation
  3. EngineRegistry for signal generation
  4. SignalAggregator for composite signal
  5. HRP-µ for portfolio construction
  6. PaperTradingOMS for execution
  7. ICTracker for evaluation

Pipeline steps:
  ingest → screen → analyze → signal → portfolio → execute

Each step is tracked in pipeline_state with error tracking for self-healing.
"""

from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Optional

from sqlalchemy import text

from quant.core.db import get_db
from quant.core.pre_trade_guard import PreTradeGuard
from quant.data.point_in_time import PointInTimeQuery
from quant.pipeline.state_machine import PipelineTracker, PipelineStatus
from quant.features.factor_library import FactorLibrary
from quant.signals.registry import EngineRegistry
from quant.signals.aggregator import SignalAggregator

logger = logging.getLogger(__name__)

__all__ = ["PipelineOrchestrator", "run_daily_pipeline"]


class PipelineOrchestrator:
    """End-to-end pipeline orchestrator with state tracking."""

    def __init__(self, session=None):
        self._session = session
        self._owns_session = session is None
        self._tracker = PipelineTracker(session=session)
        self._pit = None
        self._factor_lib = None
        self._engine_registry = None
        self._aggregator = None
        self._guard = PreTradeGuard()

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    @property
    def pit(self):
        if self._pit is None:
            self._pit = PointInTimeQuery(self.session)
        return self._pit

    @property
    def factor_lib(self):
        if self._factor_lib is None:
            self._factor_lib = FactorLibrary(session=self.session)
            self._factor_lib.register_default_factors()
        return self._factor_lib

    @property
    def engine_registry(self):
        if self._engine_registry is None:
            self._engine_registry = EngineRegistry(session=self.session, pit=self.pit)
        return self._engine_registry

    @property
    def aggregator(self):
        if self._aggregator is None:
            self._aggregator = SignalAggregator(session=self.session)
        return self._aggregator

    def _get_universe(self, as_of: date, limit: int = 100) -> list[str]:
        """Get the trading universe — top liquid individual equities only.

        Excludes index/ETF tickers (IDX*, KOMPAS*, ^*, etc.) to ensure
        only tradeable individual stocks enter the pipeline.
        """
        start_date = as_of.replace(day=1) if as_of.month > 1 else as_of.replace(month=as_of.month - 1, year=as_of.year - 1)
        result = self.session.execute(text(
            "SELECT sp.ticker, avg(sp.volume) as avg_vol "
            "FROM stock_prices sp "
            "JOIN instruments i ON sp.ticker = i.ticker "
            "WHERE sp.date >= :start_date AND sp.volume > 0 "
            "AND i.asset_class = 'EQUITY_INDIVIDUAL' "
            "AND i.is_delisted = FALSE "
            "AND i.is_active = TRUE "
            "AND sp.ticker NOT LIKE 'IDX%%' "
            "AND sp.ticker NOT LIKE 'KOMPAS%%' "
            "AND sp.ticker NOT LIKE 'INFOBANK%%' "
            "AND sp.ticker NOT LIKE 'MNC%%' "
            "AND sp.ticker NOT LIKE 'JII%%' "
            "AND sp.ticker NOT LIKE 'ISSI%%' "
            "AND sp.ticker NOT LIKE 'ESG%%' "
            "AND sp.ticker NOT LIKE 'PRIMBANK%%' "
            "AND sp.ticker NOT LIKE 'BISNIS%%' "
            "AND sp.ticker NOT LIKE 'IGRADE%%' "
            "AND sp.ticker NOT LIKE '^%%' "
            "AND i.company_name NOT LIKE '%%Index%%' "
            "AND i.company_name NOT LIKE '%%Indeks%%' "
            "GROUP BY sp.ticker "
            "ORDER BY avg_vol DESC "
            "LIMIT :limit"
        ), {"start_date": start_date, "limit": limit})
        return [r[0] for r in result.fetchall()]

    def _step_ingest(self, ticker: str, as_of: date) -> bool:
        """Step 0: Verify data is ingested for this ticker."""
        count = self.session.execute(text(
            "SELECT count(*) FROM stock_prices WHERE ticker = :ticker AND date <= :as_of"
        ), {"ticker": ticker, "as_of": as_of}).scalar()
        if count and count > 20:
            self._tracker.mark_status(ticker, as_of, "ingest", PipelineStatus.INGESTED)
            return True
        self._tracker.mark_status(ticker, as_of, "ingest", PipelineStatus.SKIPPED)
        return False

    def _step_screen(self, ticker: str, as_of: date) -> bool:
        """Step 1: Screen ticker — check liquidity and data quality."""
        df = self.pit.get_prices(ticker, as_of, lookback=30)
        if df.empty or len(df) < 20:
            self._tracker.mark_status(ticker, as_of, "screen", PipelineStatus.SKIPPED)
            return False
        avg_vol = float(df["volume"].mean()) if "volume" in df.columns else 0
        if avg_vol < 10000:
            self._tracker.mark_status(ticker, as_of, "screen", PipelineStatus.SKIPPED)
            return False
        self._tracker.mark_status(ticker, as_of, "screen", PipelineStatus.SCREENED)
        return True

    def _step_analyze(self, ticker: str, as_of: date) -> bool:
        """Step 2: Compute factors/features for this ticker."""
        try:
            count = 0
            for fname in self.factor_lib.factor_names:
                val = self.factor_lib.compute_and_store(fname, ticker, as_of)
                if val is not None:
                    count += 1
            if count > 0:
                self._tracker.mark_status(ticker, as_of, "analyze", PipelineStatus.ANALYZED)
                return True
            self._tracker.mark_status(ticker, as_of, "analyze", PipelineStatus.SKIPPED)
            return False
        except Exception as e:
            self._tracker.mark_failed(ticker, as_of, "analyze", str(e), traceback.format_exc())
            return False

    def _step_signal(self, ticker: str, as_of: date) -> Optional[dict]:
        """Step 3: Generate signals from all engines and aggregate."""
        try:
            signals = self.engine_registry.generate_all(ticker, as_of)
            if not any(s.confidence > 0 for s in signals):
                self._tracker.mark_status(ticker, as_of, "signal", PipelineStatus.SKIPPED)
                return None

            regime = "sideways"
            for s in signals:
                if s.engine_name == "hmm_regime":
                    if "trending" in s.rationale:
                        regime = "bull"
                    elif "crisis" in s.rationale:
                        regime = "crisis"

            composite = self.aggregator.aggregate(ticker, as_of, signals, regime=regime)
            self.aggregator.log_attribution(composite, as_of)
            self._tracker.mark_status(ticker, as_of, "signal", PipelineStatus.SIGNAL_GENERATED)
            return composite.to_dict()
        except Exception as e:
            self._tracker.mark_failed(ticker, as_of, "signal", str(e), traceback.format_exc())
            return None

    def _step_portfolio(self, tickers_signals: list[tuple[str, dict]], as_of: date) -> Optional[dict]:
        """Step 4: Portfolio construction from composite signals using HRP-µ."""
        try:
            from quant.portfolio.hrp_mu import HRPMu

            selected = []
            for ticker, sig_dict in tickers_signals:
                composite = sig_dict.get("composite_signal", 0)
                if abs(composite) > 0.05:
                    selected.append((ticker, composite))

            if len(selected) < 3:
                logger.info("Portfolio: only %d tickers with signals, skipping", len(selected))
                for ticker, _ in tickers_signals:
                    self._tracker.mark_status(ticker, as_of, "portfolio", PipelineStatus.SKIPPED)
                return None

            tickers = [t for t, _ in selected]
            signals = {t: s for t, s in selected}

            # Build covariance matrix from recent returns
            import pandas as pd
            returns_data = {}
            for ticker in tickers:
                df = self.pit.get_prices(ticker, as_of, lookback=60)
                if not df.empty and len(df) >= 20:
                    rets = df["close"].astype(float).pct_change().dropna()
                    returns_data[ticker] = rets

            # Only use tickers with return data
            valid_tickers = [t for t in tickers if t in returns_data]
            if len(valid_tickers) < 3:
                # Fallback to equal-weight
                logger.info("Portfolio: insufficient return data for HRP, using equal weight")
                tickers = valid_tickers if valid_tickers else tickers
                raw_weights = [max(0, signals.get(t, 0)) for t in tickers]
                total = sum(raw_weights)
                if total == 0:
                    weights = [1.0 / len(tickers)] * len(tickers)
                else:
                    weights = [w / total for w in raw_weights]
            else:
                # Build returns DataFrame and covariance
                rets_df = pd.DataFrame(returns_data)
                cov_df = rets_df.cov()

                # Use HRP-µ for allocation
                allocator = HRPMu(gamma=0.5)
                valid_signals = {t: signals[t] for t in valid_tickers}
                weight_dict = allocator.allocate(
                    signals=valid_signals,
                    covariance=cov_df,
                    max_weight=0.10,
                )
                tickers = list(weight_dict.keys())
                weights = [weight_dict[t] for t in tickers]

            portfolio = {
                "date": str(as_of),
                "tickers": tickers,
                "weights": weights,
                "n_positions": len(tickers),
                "signals": {t: s for t, s in selected if t in tickers},
            }

            for ticker, weight in zip(tickers, weights):
                self.session.execute(text(
                    "INSERT INTO portfolio_weights (date, ticker, weight, method) "
                    "VALUES (:date, :ticker, :weight, 'hrp_mu') "
                    "ON CONFLICT (date, ticker, method) DO UPDATE SET weight = EXCLUDED.weight"
                ), {"date": as_of, "ticker": ticker, "weight": float(weight)})
            self.session.commit()

            selected_set = set(tickers)
            for ticker, _ in tickers_signals:
                if ticker in selected_set:
                    self._tracker.mark_status(ticker, as_of, "portfolio", PipelineStatus.PORTFOLIO_OPTIMIZED)
                else:
                    self._tracker.mark_status(ticker, as_of, "portfolio", PipelineStatus.SKIPPED)

            return portfolio
        except Exception as e:
            logger.error("Portfolio construction failed: %s", e)
            self.session.rollback()
            for ticker, _ in tickers_signals:
                self._tracker.mark_failed(ticker, as_of, "portfolio", str(e), traceback.format_exc())
            return None

    def _step_execute(self, portfolio: dict, as_of: date) -> Optional[dict]:
        """Step 5: Paper trading execution."""
        try:
            from quant.execution.paper_trading import PaperTradingOMS
            from quant.execution.oms import OrderSide

            # Build sector_map from instruments table
            sector_rows = self.session.execute(text(
                "SELECT i.ticker, s.name FROM instruments i "
                "JOIN sector_master s ON i.sector_id = s.id "
                "WHERE i.is_active = TRUE AND i.is_delisted = FALSE"
            )).fetchall()
            sector_map = {r[0]: r[1] for r in sector_rows}

            oms = PaperTradingOMS(sector_map=sector_map)
            tickers = portfolio["tickers"]
            weights = portfolio["weights"]

            prices = {}
            for ticker in tickers:
                df = self.pit.get_prices(ticker, as_of, lookback=5)
                if not df.empty:
                    prices[ticker] = float(df["close"].iloc[-1])

            if not prices:
                return None

            orders = []
            nav = oms.nav
            for ticker, weight in zip(tickers, weights):
                if ticker not in prices:
                    continue
                # Cap at 9% NAV to stay under 10% risk gate limit
                capped_weight = min(weight, 0.09)
                order_value = capped_weight * nav
                shares = int(order_value / prices[ticker] / 100) * 100
                if shares > 0:
                    try:
                        result = oms.submit_order(
                            ticker=ticker,
                            side=OrderSide.BUY,
                            shares=shares,
                            current_price=prices[ticker],
                        )
                        orders.append({"ticker": ticker, "shares": shares, "accepted": result.passed})
                    except Exception as oe:
                        logger.warning("Order failed for %s: %s", ticker, oe)

            for ticker in portfolio["tickers"]:
                self._tracker.mark_status(ticker, as_of, "execute", PipelineStatus.DONE)

            return {"orders": orders, "n_orders": len(orders)}
        except Exception as e:
            logger.error("Execution failed: %s", e)
            for ticker in portfolio.get("tickers", []):
                self._tracker.mark_failed(ticker, as_of, "execute", str(e), traceback.format_exc())
            return None

    def run_daily(self, as_of: date, universe_limit: int = 50) -> dict:
        """Run the complete daily pipeline.

        Args:
            as_of: Decision date
            universe_limit: Max tickers to process

        Returns:
            Summary dict with counts per step
        """
        logger.info("=== Daily pipeline run for %s ===", as_of)

        # Pre-trade guard: check if IDX market is open
        if not self._guard.should_run_pipeline("XIDX", as_of):
            return {
                "date": str(as_of),
                "universe": 0,
                "ingested": 0,
                "screened": 0,
                "analyzed": 0,
                "signal_generated": 0,
                "portfolio_optimized": 0,
                "executed": 0,
                "errors": 0,
                "portfolio": None,
                "execution": None,
                "skipped": True,
                "skip_reason": "market_holiday",
            }

        universe = self._get_universe(as_of, limit=universe_limit)
        logger.info("Universe: %d tickers", len(universe))

        summary = {
            "date": str(as_of),
            "universe": len(universe),
            "ingested": 0,
            "screened": 0,
            "analyzed": 0,
            "signal_generated": 0,
            "portfolio_optimized": 0,
            "executed": 0,
            "errors": 0,
            "portfolio": None,
            "execution": None,
        }

        # Steps 0-3: Per-ticker
        tickers_signals = []
        for ticker in universe:
            # Step 0: Ingest
            if not self._step_ingest(ticker, as_of):
                continue
            summary["ingested"] += 1

            # Step 1: Screen
            if not self._step_screen(ticker, as_of):
                continue
            summary["screened"] += 1

            # Step 2: Analyze (compute features)
            if not self._step_analyze(ticker, as_of):
                continue
            summary["analyzed"] += 1

            # Step 3: Signal generation
            sig_dict = self._step_signal(ticker, as_of)
            if sig_dict is not None:
                summary["signal_generated"] += 1
                tickers_signals.append((ticker, sig_dict))

        # Step 4: Portfolio construction
        if tickers_signals:
            portfolio = self._step_portfolio(tickers_signals, as_of)
            if portfolio:
                summary["portfolio_optimized"] = portfolio["n_positions"]
                summary["portfolio"] = portfolio

                # Step 5: Execute
                execution = self._step_execute(portfolio, as_of)
                if execution:
                    summary["executed"] = execution["n_orders"]
                    summary["execution"] = execution

        # Count errors
        error_count = self.session.execute(text(
            "SELECT count(*) FROM pipeline_state WHERE date = :date AND status = 'failed'"
        ), {"date": as_of}).scalar()
        summary["errors"] = error_count or 0

        logger.info(
            "Pipeline complete: ingest=%d screen=%d analyze=%d signal=%d portfolio=%d execute=%d errors=%d",
            summary["ingested"], summary["screened"], summary["analyzed"],
            summary["signal_generated"], summary["portfolio_optimized"],
            summary["executed"], summary["errors"],
        )
        return summary

    def evaluate_ic(self, signal_date: date, horizon: int = 5) -> dict:
        """Evaluate IC for signals generated on signal_date.

        Computes actual forward returns and compares to predicted signals.

        Args:
            signal_date: The date signals were generated
            horizon: Forward return horizon in trading days

        Returns:
            Summary dict with IC per engine
        """
        from quant.evaluation.ic_tracking import ICTracker
        from datetime import timedelta

        tracker = ICTracker(session=self.session)

        # Get all signal attributions for this date
        rows = self.session.execute(text(
            "SELECT engine_name, ticker, signal_value "
            "FROM signal_attribution_log WHERE date = :date"
        ), {"date": signal_date}).fetchall()

        if not rows:
            return {"date": str(signal_date), "engines_evaluated": 0}

        # Group predictions by engine
        engine_preds: dict[str, dict[str, float]] = {}
        for engine_name, ticker, signal_val in rows:
            if engine_name not in engine_preds:
                engine_preds[engine_name] = {}
            engine_preds[engine_name][ticker] = float(signal_val)

        # Compute actual forward returns for all tickers
        all_tickers = set()
        for preds in engine_preds.values():
            all_tickers.update(preds.keys())

        actual_returns = {}
        forward_date = signal_date + timedelta(days=horizon + 2)  # +2 for weekend buffer

        for ticker in all_tickers:
            # Get price at signal_date and forward_date
            p_now = self.pit.get_prices(ticker, signal_date, lookback=5)
            p_fwd = self.pit.get_prices(ticker, forward_date, lookback=5)

            if not p_now.empty and not p_fwd.empty:
                price_now = float(p_now["close"].iloc[-1])
                price_fwd = float(p_fwd["close"].iloc[-1])
                if price_now > 0:
                    actual_returns[ticker] = (price_fwd - price_now) / price_now

        if len(actual_returns) < 3:
            return {"date": str(signal_date), "engines_evaluated": 0, "reason": "insufficient forward data"}

        # Compute IC per engine
        results = {}
        for engine_name, preds in engine_preds.items():
            common_tickers = set(preds.keys()) & set(actual_returns.keys())
            if len(common_tickers) < 3:
                continue

            pred_dict = {t: preds[t] for t in common_tickers}
            ret_dict = {t: actual_returns[t] for t in common_tickers}

            ic_result = tracker.update(engine_name, signal_date, pred_dict, ret_dict, horizon)
            results[engine_name] = {
                "ic": ic_result.ic,
                "n_pairs": ic_result.n_pairs,
                "p_value": ic_result.p_value,
            }

        return {
            "date": str(signal_date),
            "engines_evaluated": len(results),
            "n_tickers_with_returns": len(actual_returns),
            "results": results,
        }

    def close(self):
        if self._owns_session and self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass


def run_daily_pipeline(as_of: date, universe_limit: int = 50) -> dict:
    """Convenience function to run the daily pipeline."""
    orch = PipelineOrchestrator()
    try:
        return orch.run_daily(as_of, universe_limit=universe_limit)
    finally:
        orch.close()
