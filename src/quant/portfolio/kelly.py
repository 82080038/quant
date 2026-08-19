"""Risk-Constrained Kelly position sizing.

Quarter-Kelly with liquidity and risk caps. The Kelly criterion gives
the optimal bet size for maximizing long-term wealth growth, but full
Kelly is too aggressive. We use quarter-Kelly with multiple safety constraints:

  f_kelly = (p * b - q) / b
  where p = win probability, q = 1-p, b = win/loss ratio

Constraints:
  1. Quarter-Kelly: f = 0.25 * f_kelly
  2. Max position cap: f ≤ max_weight (e.g. 15%)
  3. Liquidity constraint: f ≤ ADV_fraction
  4. VaR limit: f ≤ var_budget / position_var

Inspired by FinRL-DeepSeek risk-sensitive position sizing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class KellyConfig:
    """Kelly criterion configuration."""
    kelly_fraction: float = 0.25  # Quarter-Kelly
    max_weight: float = 0.15
    min_weight: float = 0.0
    var_confidence: float = 0.95
    max_var_budget: float = 0.03  # 3% daily VaR budget per position


class RiskConstrainedKelly:
    """Risk-constrained Kelly position sizing.

    Usage:
        kelly = RiskConstrainedKelly()
        weight = kelly.size(
            signal=0.8,
            win_rate=0.55,
            odds=1.5,
            max_weight=0.15,
        )
    """

    def __init__(self, config: KellyConfig = None):
        self.config = config or KellyConfig()

    def size(
        self,
        signal: float,
        win_rate: Optional[float] = None,
        odds: Optional[float] = None,
        max_weight: Optional[float] = None,
        liquidity_constraint: Optional[float] = None,
        var_limit: Optional[float] = None,
        position_volatility: Optional[float] = None,
    ) -> float:
        """Compute risk-constrained Kelly position size.

        Args:
            signal: Signal value [-1, 1] — direction and strength
            win_rate: Estimated win probability (default: derived from signal)
            odds: Win/loss ratio (default: 1.0)
            max_weight: Maximum position weight override
            liquidity_constraint: Max fraction of ADV (e.g. 0.05)
            var_limit: VaR budget for this position
            position_volatility: Position's daily volatility (for VaR calc)

        Returns:
            Position weight [0, max_weight]
        """
        if signal is None or abs(signal) < 0.01:
            return 0.0

        # Only size long positions (signal > 0)
        if signal < 0:
            return 0.0

        # Derive win rate from signal if not provided
        p = win_rate if win_rate is not None else 0.5 + signal * 0.1
        p = np.clip(p, 0.01, 0.99)

        # Derive odds from signal if not provided
        b = odds if odds is not None else 1.0 + abs(signal) * 0.5
        q = 1 - p

        # ── Kelly formula ──────────────────────────────────────────
        f_kelly = (p * b - q) / b
        f_kelly = max(0, f_kelly)

        # Quarter-Kelly
        f = self.config.kelly_fraction * f_kelly

        # Scale by signal strength
        f *= abs(signal)

        # ── Constraint 1: Max position ─────────────────────────────
        cap = max_weight or self.config.max_weight
        f = min(f, cap)

        # ── Constraint 2: Liquidity ────────────────────────────────
        if liquidity_constraint is not None:
            f = min(f, liquidity_constraint)

        # ── Constraint 3: VaR limit ────────────────────────────────
        if var_limit is not None and position_volatility is not None:
            if position_volatility > 0:
                var_weight = var_limit / (position_volatility * 1.65)  # 95% VaR
                f = min(f, var_weight)

        # ── Constraint 4: Min weight ───────────────────────────────
        f = max(f, self.config.min_weight)

        return float(np.clip(f, 0, cap))

    def size_portfolio(
        self,
        signals: dict[str, float],
        win_rates: Optional[dict[str, float]] = None,
        volatilities: Optional[dict[str, float]] = None,
        max_weight: float = 0.15,
        total_var_budget: float = 0.03,
    ) -> dict[str, float]:
        """Size multiple positions with portfolio-level VaR budget.

        Args:
            signals: ticker → signal value
            win_rates: ticker → win probability
            volatilities: ticker → daily volatility
            max_weight: Max weight per position
            total_var_budget: Total portfolio VaR budget

        Returns:
            ticker → weight
        """
        tickers = list(signals.keys())
        n = len(tickers)
        if n == 0:
            return {}

        per_position_var = total_var_budget / n

        weights = {}
        for ticker in tickers:
            signal = signals[ticker]
            wr = win_rates.get(ticker) if win_rates else None
            vol = volatilities.get(ticker) if volatilities else None

            w = self.size(
                signal=signal,
                win_rate=wr,
                max_weight=max_weight,
                var_limit=per_position_var,
                position_volatility=vol,
            )
            weights[ticker] = w

        # Normalize to sum ≤ 1
        total = sum(weights.values())
        if total > 1.0:
            weights = {k: v / total for k, v in weights.items()}

        return weights
