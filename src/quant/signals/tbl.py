"""Triple Barrier Labeling (TBL) for IDX-specific volatility.

Based on López de Prado (2018) "Advances in Financial Machine Learning".

Three barriers:
  1. Upper barrier: +take_profit (e.g. +3%)
  2. Lower barrier: -stop_loss (e.g. -3%)
  3. Vertical barrier: time limit (e.g. 5 trading days)

Label = which barrier was touched first:
  +1 = upper (profit)
  -1 = lower (loss)
   0 = vertical (time expired, neutral)

For IDX: 3%/5-day optimal per Paperium research.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class TBLConfig:
    """Triple Barrier Labeling configuration."""
    take_profit: float = 0.03    # +3% upper barrier
    stop_loss: float = 0.03      # -3% lower barrier
    max_holding: int = 5         # 5 trading days vertical barrier
    use_atr: bool = True         # Use ATR-based dynamic barriers
    atr_multiplier: float = 1.5  # ATR multiplier for barriers
    atr_period: int = 14         # ATR calculation period


@dataclass
class TBLResult:
    """Triple Barrier Labeling result for a single observation."""
    label: int           # +1, -1, 0
    barrier_hit: str     # "upper", "lower", "vertical"
    holding_period: int  # Days until barrier hit
    return_pct: float    # Actual return at barrier


def compute_atr(prices: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = prices.rolling(period).max()
    low = prices.rolling(period).min()
    prev_close = prices.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = tr1.combine(tr2, max).combine(tr3, max)
    return tr.rolling(period).mean()


def apply_triple_barrier(
    prices: pd.Series,
    config: TBLConfig = None,
    side: pd.Series = None,
) -> pd.DataFrame:
    """Apply Triple Barrier Labeling to a price series.

    Args:
        prices: Close price series
        config: TBL configuration
        side: Optional side signal (1=long, -1=short). If None, default to long.

    Returns:
        DataFrame with columns: label, barrier_hit, holding_period, return_pct
    """
    if config is None:
        config = TBLConfig()

    if side is None:
        side = pd.Series(1.0, index=prices.index)

    # Compute ATR for dynamic barriers if enabled
    if config.use_atr:
        atr = compute_atr(prices, config.atr_period)
        atr_pct = atr / prices
    else:
        atr_pct = pd.Series(config.take_profit, index=prices.index)

    results = []
    prices_arr = prices.values
    side_arr = side.values
    atr_arr = atr_pct.values

    for i in range(len(prices_arr)):
        if np.isnan(prices_arr[i]) or np.isnan(side_arr[i]):
            results.append(TBLResult(0, "vertical", 0, 0.0))
            continue

        entry_price = prices_arr[i]
        s = side_arr[i]

        # Dynamic barriers based on ATR
        tp = config.atr_multiplier * atr_arr[i] if not np.isnan(atr_arr[i]) else config.take_profit
        sl = config.atr_multiplier * atr_arr[i] if not np.isnan(atr_arr[i]) else config.stop_loss

        upper = entry_price * (1 + tp) if s > 0 else entry_price * (1 - sl)
        lower = entry_price * (1 - sl) if s > 0 else entry_price * (1 + tp)

        label = 0
        barrier = "vertical"
        holding = config.max_holding
        ret = 0.0

        for j in range(1, min(config.max_holding + 1, len(prices_arr) - i)):
            p = prices_arr[i + j]
            if np.isnan(p):
                continue

            if s > 0:  # Long
                if p >= upper:
                    label = 1
                    barrier = "upper"
                    holding = j
                    ret = (p - entry_price) / entry_price
                    break
                elif p <= lower:
                    label = -1
                    barrier = "lower"
                    holding = j
                    ret = (p - entry_price) / entry_price
                    break
            else:  # Short
                if p <= upper:
                    label = 1
                    barrier = "upper"
                    holding = j
                    ret = (entry_price - p) / entry_price
                    break
                elif p >= lower:
                    label = -1
                    barrier = "lower"
                    holding = j
                    ret = (entry_price - p) / entry_price
                    break

        if label == 0 and i + config.max_holding < len(prices_arr):
            final = prices_arr[i + config.max_holding]
            if not np.isnan(final):
                if s > 0:
                    ret = (final - entry_price) / entry_price
                else:
                    ret = (entry_price - final) / entry_price

        results.append(TBLResult(label, barrier, holding, float(ret)))

    return pd.DataFrame([
        {"label": r.label, "barrier_hit": r.barrier_hit,
         "holding_period": r.holding_period, "return_pct": r.return_pct}
        for r in results
    ], index=prices.index)


def meta_label(
    primary_signals: pd.Series,
    prices: pd.Series,
    config: TBLConfig = None,
) -> pd.Series:
    """Meta-labeling: produce secondary model predictions.

    The primary model provides direction (side),
    the meta-model predicts whether the primary will be correct.

    Returns:
        Series of {0, 1} — 1 = primary signal likely correct, 0 = likely wrong
    """
    if config is None:
        config = TBLConfig()

    tbl = apply_triple_barrier(prices, config, side=primary_signals)
    # Meta label: 1 if primary direction matched TBL result
    meta = (tbl["label"] == 1).astype(int)
    meta[tbl["label"] == 0] = 0  # Vertical = uncertain
    return meta
