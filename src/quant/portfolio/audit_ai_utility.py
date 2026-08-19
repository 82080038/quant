"""Minimal audit AI utility stubs — replaced from market app scripts.

Provides constants and functions needed by portfolio modules.
Will be replaced with proper quant modules in Phase 2.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass

ROUND_TRIP_COST = 0.0035  # 0.35% round trip (commission + tax + slippage)
TRADING_DAYS = 252
RISK_FREE_RATE = 0.055  # BI Rate approximate


@dataclass
class PerformanceMetrics:
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    annual_return: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    calmar: float = 0.0
    total_return: float = 0.0
    n_trades: int = 0


def compute_performance_metrics(returns: pd.Series, benchmark: pd.Series = None) -> PerformanceMetrics:
    """Compute standard performance metrics from returns series."""
    if returns.empty:
        return PerformanceMetrics()
    excess = returns - RISK_FREE_RATE / TRADING_DAYS
    sharpe = np.sqrt(TRADING_DAYS) * excess.mean() / excess.std() if excess.std() > 0 else 0
    downside = returns[returns < 0]
    sortino = np.sqrt(TRADING_DAYS) * returns.mean() / downside.std() if len(downside) > 0 and downside.std() > 0 else 0
    cumulative = (1 + returns).cumprod()
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    max_dd = drawdown.min()
    annual_ret = (1 + returns.mean()) ** TRADING_DAYS - 1
    win_rate = (returns > 0).mean()
    gains = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    pf = gains / losses if losses > 0 else float('inf')
    calmar = annual_ret / abs(max_dd) if max_dd < 0 else 0
    return PerformanceMetrics(
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_drawdown=float(max_dd),
        annual_return=float(annual_ret),
        win_rate=float(win_rate),
        profit_factor=float(pf),
        calmar=float(calmar),
        total_return=float(cumulative.iloc[-1] - 1),
        n_trades=len(returns),
    )


def simulate_strategy_returns(signals, prices, cost=ROUND_TRIP_COST):
    """Simulate returns from signals."""
    if isinstance(signals, pd.DataFrame):
        position = signals.shift(1).fillna(0)
    else:
        position = pd.Series(signals).shift(1).fillna(0)
    returns = prices.pct_change() if hasattr(prices, 'pct_change') else prices
    strategy_returns = position * returns - cost * position.diff().abs().fillna(0)
    return strategy_returns.fillna(0)


def generate_baseline_signals(prices, method="buy_hold"):
    """Generate baseline signals for comparison."""
    if method == "buy_hold":
        return pd.Series(1.0, index=prices.index)
    return pd.Series(0.0, index=prices.index)


def load_ohlcv(ticker, start=None, end=None):
    """Load OHLCV from database."""
    from quant.data.point_in_time import PointInTimeQuery
    from datetime import date
    pit = PointInTimeQuery()
    end_date = end or date.today()
    return pit.get_prices(ticker, end_date, lookback=TRADING_DAYS)


def load_benchmark(ticker="^JKSE"):
    """Load benchmark prices."""
    return load_ohlcv(ticker)
