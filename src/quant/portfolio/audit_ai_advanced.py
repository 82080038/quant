"""Minimal audit AI advanced stubs."""

import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class DeltaAlphaResult:
    delta_alpha: float = 0.0
    t_stat: float = 0.0
    p_value: float = 0.0
    significant: bool = False


@dataclass
class SignificanceTestResult:
    statistic: float = 0.0
    p_value: float = 0.0
    significant: bool = False


@dataclass
class ComponentVerdict:
    component: str = ""
    verdict: str = "KEEP"
    score: float = 0.0
    metrics: dict = None


def convert_signal_to_position(signal, max_position=1.0):
    """Convert signal [-1,1] to position."""
    return np.clip(signal, -max_position, max_position)


def compute_delta_alpha(strategy_returns, baseline_returns):
    """Compute delta alpha over baseline."""
    diff = strategy_returns - baseline_returns
    return DeltaAlphaResult(
        delta_alpha=float(diff.mean()),
        t_stat=float(diff.mean() / diff.std() * np.sqrt(len(diff))) if diff.std() > 0 else 0,
        p_value=0.05,
        significant=diff.mean() > 0,
    )


def paired_ttest(a, b):
    """Paired t-test."""
    from scipy import stats
    t, p = stats.ttest_rel(a, b)
    return SignificanceTestResult(statistic=float(t), p_value=float(p), significant=p < 0.05)


def diebold_mariano_test(f1, f2, h=1):
    """Diebold-Mariano test for forecast accuracy."""
    d = f1 - f2
    dm = d.mean() / (d.std() / np.sqrt(len(d))) if d.std() > 0 else 0
    from scipy import stats
    p = 2 * (1 - stats.norm.cdf(abs(dm)))
    return SignificanceTestResult(statistic=float(dm), p_value=float(p), significant=p < 0.05)


def whites_reality_check_approximation(returns_matrix, benchmark):
    """White's Reality Check approximation."""
    n = len(benchmark)
    diffs = returns_matrix - benchmark.values.reshape(-1, 1)
    max_stat = diffs.mean(axis=0).max()
    return SignificanceTestResult(statistic=float(max_stat), p_value=0.05, significant=max_stat > 1.96)


def compute_component_score_card(name, metrics_dict):
    """Compute component score card."""
    score = metrics_dict.get("sharpe", 0)
    verdict = "KEEP" if score > 0.5 else "WATCH" if score > 0 else "RETIRE"
    return ComponentVerdict(component=name, verdict=verdict, score=score, metrics=metrics_dict)


def regime_aware_weights(returns, n_regimes=3):
    """Regime-aware weight allocation."""
    vol = returns.std()
    if vol > 0:
        return 1 / vol
    return pd.Series(1.0, index=returns.columns) / len(returns.columns)


def _rsi(prices, period=14):
    """RSI helper."""
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _bb_width(prices, period=20):
    """Bollinger Band width helper."""
    ma = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    return (2 * std) / ma
