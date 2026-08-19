"""Profiling module stub — re-exports instrument profiler."""

from dataclasses import dataclass
from enum import Enum

from quant.analysis.instrument_profiler import (
    InstrumentBehaviorProfile,
    profile_all_instruments,
    detect_regime_change,
)


class VolatilityRegime(Enum):
    LOW = "low"
    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class PersonalityLabel(Enum):
    TREND_FOLLOWER = "trend_follower"
    MEAN_REVERTER = "mean_reverter"
    MOMENTUM = "momentum"
    VOLATILE = "volatile"
    DORMANT = "dormant"
    BLUE_CHIP = "blue_chip"
    GORENGAN = "gorengan"
    ILLIQUID = "illiquid"
    COMMODITY_LINKED = "commodity_linked"
    DIVIDEND_STOCK = "dividend_stock"
    HIGH_BETA = "high_beta"
    LOW_BETA = "low_beta"
    SMALL_CAP = "small_cap"
    MID_CAP = "mid_cap"
    UNKNOWN = "unknown"


@dataclass
class InstrumentProfile:
    ticker: str = ""
    personality: PersonalityLabel = PersonalityLabel.MOMENTUM
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    trend_strength: float = 0.0
    mean_reversion_score: float = 0.0
    liquidity_score: float = 0.0
