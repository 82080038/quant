"""Signal generation engines for the quant trading system.

All engines produce continuous signals [-1, +1] with confidence [0, 1].
Use EngineRegistry for a unified interface across all engines.
"""

# Aggregator
from quant.signals.aggregator import SignalResult, CompositeSignal, SignalAggregator

# Registry
from quant.signals.registry import EngineRegistry, ENGINE_NAMES

# Technical
from quant.signals.technical import TechnicalAnalysisEngine, TechnicalScore

# Fundamental
from quant.signals.fundamental import FundamentalAnalysisEngine, FundamentalScore

# Macro
from quant.signals.macro import MacroEconomicEngine, MacroScore

# Global Market
from quant.signals.global_market import GlobalMarketEngine, GlobalMarketScore

# Sentiment
from quant.signals.sentiment import SentimentEngine, SentimentScore

# Relationship
from quant.signals.relationship import MarketRelationshipEngine, RelationshipResult

# Alpha Signals
from quant.signals.alpha_signals import (
    MeanReversionEngine,
    ShortTermReversalEngine,
    EWMAMomentumEngine,
    RegimeSwitchEngine,
)

# HMM Regime
from quant.signals.hmm_regime import HMMRegimeDetector, RegimeResult

# Fama-French
from quant.signals.fama_french import FamaFrench5Factor, FactorExposure

# Holiday Effect
from quant.signals.holiday_effect import HolidayEffectAnalyzer, HolidayEffectResult

# Volume Features
from quant.signals.volume_features import (
    compute_vwap,
    compute_ofi_proxy,
    detect_obv_divergence,
    compute_vw_momentum,
    compute_foreign_flow_signal,
)

# Policy Event Scorer
from quant.signals.policy_event_scorer import PolicyEventScorer, EventImpact, EventSignal

# Strategy Selector
from quant.signals.strategy_selector import StrategySelector, StrategyAssignmentResult

# Triple Barrier Labeling
from quant.signals.tbl import TBLConfig, TBLResult, apply_triple_barrier, meta_label

# Deep Learning
from quant.signals.vae import VAEFeatureExtractor, VAEConfig
from quant.signals.transformer import TransformerPredictor, TransformerConfig
from quant.signals.lstm import LSTMSignalPredictor, LSTMConfig
from quant.signals.xgb_lgbm import XGBLGBMEnsemble
from quant.signals.ensemble import DLEnsemble, EnsembleConfig

# Astronacci
from quant.signals.astronacci import AstronacciEngine

__all__ = [
    # Aggregator
    "SignalResult", "CompositeSignal", "SignalAggregator",
    # Registry
    "EngineRegistry", "ENGINE_NAMES",
    # Technical
    "TechnicalAnalysisEngine", "TechnicalScore",
    # Fundamental
    "FundamentalAnalysisEngine", "FundamentalScore",
    # Macro
    "MacroEconomicEngine", "MacroScore",
    # Global Market
    "GlobalMarketEngine", "GlobalMarketScore",
    # Sentiment
    "SentimentEngine", "SentimentScore",
    # Relationship
    "MarketRelationshipEngine", "RelationshipResult",
    # Alpha
    "MeanReversionEngine", "ShortTermReversalEngine",
    "EWMAMomentumEngine", "RegimeSwitchEngine",
    # HMM
    "HMMRegimeDetector", "RegimeResult",
    # Fama-French
    "FamaFrench5Factor", "FactorExposure",
    # Holiday
    "HolidayEffectAnalyzer", "HolidayEffectResult",
    # Volume
    "compute_vwap", "compute_ofi_proxy", "detect_obv_divergence",
    "compute_vw_momentum", "compute_foreign_flow_signal",
    # Policy
    "PolicyEventScorer", "EventImpact", "EventSignal",
    # Strategy
    "StrategySelector", "StrategyAssignmentResult",
    # TBL
    "TBLConfig", "TBLResult", "apply_triple_barrier", "meta_label",
    # DL
    "VAEFeatureExtractor", "VAEConfig",
    "TransformerPredictor", "TransformerConfig",
    "LSTMSignalPredictor", "LSTMConfig",
    "XGBLGBMEnsemble",
    "DLEnsemble", "EnsembleConfig",
    # Astronacci
    "AstronacciEngine",
]
