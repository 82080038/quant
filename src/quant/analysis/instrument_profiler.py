"""Instrument profiling stub — will be implemented in Phase 2."""

from dataclasses import dataclass


@dataclass
class InstrumentBehaviorProfile:
    ticker: str = ""
    volatility_regime: str = "normal"
    trend_strength: float = 0.0
    mean_reversion_score: float = 0.0
    liquidity_score: float = 0.0


@dataclass
class InstrumentProfile:
    ticker: str = ""
    personality: str = "momentum"
    volatility_regime: str = "normal"
    trend_strength: float = 0.0
    mean_reversion_score: float = 0.0
    liquidity_score: float = 0.0


class InstrumentBehaviorProfiler:
    """Minimal profiler stub."""
    def __init__(self, *args, **kwargs):
        pass

    def profile_instrument(self, ticker, prices):
        return InstrumentBehaviorProfile(ticker=ticker)

    def profile_all(self, *args, **kwargs):
        return {}


def profile_all_instruments(*args, **kwargs):
    return {}


def detect_regime_change(*args, **kwargs):
    return None
