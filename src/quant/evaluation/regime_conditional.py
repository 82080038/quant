"""Regime-conditional evaluation.

Evaluates strategy performance per market regime, not just aggregate.
Regimes: bull, bear, sideways, crisis.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class RegimeEvalResult:
    """Per-regime evaluation result."""
    regime: str
    n_days: int
    sharpe: float
    max_drawdown: float
    win_rate: float
    annual_return: float
    ic: float = 0.0


class RegimeConditionalEvaluator:
    """Evaluate strategy performance per market regime."""

    REGIMES = ["bull", "bear", "sideways", "crisis"]

    def classify_regime(
        self,
        returns: pd.Series,
        window: int = 63,
        bull_threshold: float = 0.0,
        bear_threshold: float = -0.0,
        crisis_vol_threshold: float = 2.0,
    ) -> pd.Series:
        """Classify each day into a market regime.

        Uses rolling mean and volatility:
        - Bull: rolling mean > 0 and vol < crisis threshold
        - Bear: rolling mean < 0 and vol < crisis threshold
        - Crisis: vol > crisis_vol_threshold (relative to historical)
        - Sideways: otherwise

        Args:
            returns: Daily returns series
            window: Rolling window for regime classification
            bull_threshold: Minimum rolling mean for bull
            bear_threshold: Maximum rolling mean for bear
            crisis_vol_threshold: Volatility ratio for crisis classification

        Returns:
            Series of regime labels
        """
        rolling_mean = returns.rolling(window, min_periods=20).mean()
        rolling_vol = returns.rolling(window, min_periods=20).std()
        historical_vol = returns.expanding(min_periods=60).std().shift(1)
        vol_ratio = rolling_vol / historical_vol

        regimes = pd.Series("sideways", index=returns.index)
        regimes[rolling_mean > bull_threshold] = "bull"
        regimes[rolling_mean < bear_threshold] = "bear"
        # Crisis: volatility spike (>2x historical average)
        crisis_mask = vol_ratio > crisis_vol_threshold
        regimes[crisis_mask] = "crisis"

        return regimes

    def evaluate(
        self,
        strategy_returns: pd.Series,
        regime_labels: pd.Series = None,
        predictions: pd.Series = None,
        actual_returns: pd.Series = None,
        periods_per_year: int = 252,
    ) -> dict[str, RegimeEvalResult]:
        """Evaluate strategy per regime.

        Args:
            strategy_returns: Daily strategy returns
            regime_labels: Pre-computed regime labels (auto-computed if None)
            predictions: Signal predictions for IC computation
            actual_returns: Actual returns for IC computation
            periods_per_year: Annualization factor

        Returns:
            Dict of regime → RegimeEvalResult
        """
        if regime_labels is None:
            regime_labels = self.classify_regime(strategy_returns)

        results = {}

        for regime in self.REGIMES:
            mask = regime_labels == regime
            n_days = mask.sum()

            if n_days < 5:
                results[regime] = RegimeEvalResult(
                    regime=regime, n_days=int(n_days),
                    sharpe=0, max_drawdown=0, win_rate=0, annual_return=0
                )
                continue

            regime_returns = strategy_returns[mask]

            # Sharpe
            std = regime_returns.std()
            sharpe = np.sqrt(periods_per_year) * regime_returns.mean() / std if std > 0 else 0

            # Max drawdown
            cumulative = (1 + regime_returns).cumprod()
            peak = cumulative.cummax()
            drawdown = (cumulative - peak) / peak
            max_dd = drawdown.min()

            # Win rate
            win_rate = (regime_returns > 0).mean()

            # Annual return
            ann_ret = (1 + regime_returns.mean()) ** periods_per_year - 1

            # IC if predictions provided
            ic = 0.0
            if predictions is not None and actual_returns is not None:
                from quant.evaluation.ic_tracking import ICTracker
                tracker = ICTracker()
                regime_pred = predictions[mask].values
                regime_actual = actual_returns[mask].values
                if len(regime_pred) > 3:
                    ic_result = tracker.compute_ic(regime_pred, regime_actual)
                    ic = ic_result.ic

            results[regime] = RegimeEvalResult(
                regime=regime,
                n_days=int(n_days),
                sharpe=float(sharpe),
                max_drawdown=float(max_dd),
                win_rate=float(win_rate),
                annual_return=float(ann_ret),
                ic=float(ic),
            )

        return results

    def summary_table(self, results: dict[str, RegimeEvalResult]) -> pd.DataFrame:
        """Convert results to a summary table."""
        rows = []
        for regime, r in results.items():
            rows.append({
                "regime": regime,
                "n_days": r.n_days,
                "sharpe": r.sharpe,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
                "annual_return": r.annual_return,
                "ic": r.ic,
            })
        return pd.DataFrame(rows)
