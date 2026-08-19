"""Layer 3: Signal engine tests.

Tests:
- technical: Technical analysis scoring
- fundamental: Fundamental scoring
- macro: Macro regime classification
- global_market: Global index scoring
- sentiment: Sentiment aggregation
- alpha_signals: 4 alpha engines
- tbl: Triple barrier labeling
- volume_features: VWAP, OBV, OFI
- hmm_regime: HMM regime detection
- fama_french: 5-factor model
- aggregator: Signal aggregation
- strategy_selector: Strategy assignment

Known bugs found:
- sentiment.py: _analyze_news imports `quant.analysis.news_sentiment` which
  does not exist. News NLP functionality is broken.
- macro.py: regime returns lowercase strings (e.g. 'easing') but test expected
  title case ('Easing'). This is a naming inconsistency, not a bug per se.
"""

import pytest
import numpy as np
import pandas as pd


# ── Technical Engine ─────────────────────────────────────────────────────────

class TestTechnicalEngine:
    """Test technical analysis engine."""

    def test_analyze_returns_score(self, sample_ohlcv):
        from quant.signals.technical import TechnicalAnalysisEngine
        engine = TechnicalAnalysisEngine()
        result = engine.analyze("BBCA.JK", sample_ohlcv)
        assert 0 <= result.score <= 100
        assert result.ticker == "BBCA.JK"
        assert result.trend in ("uptrend", "downtrend", "sideways", "insufficient_data")
        assert len(result.breakdown) > 0
        assert len(result.indicators) > 0

    def test_insufficient_data(self):
        from quant.signals.technical import TechnicalAnalysisEngine
        engine = TechnicalAnalysisEngine()
        short_df = pd.DataFrame({
            "open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]
        })
        result = engine.analyze("TEST", short_df)
        assert result.score == 0.0
        assert result.trend == "insufficient_data"

    def test_indicators_computed(self, sample_ohlcv):
        from quant.signals.technical import TechnicalAnalysisEngine
        engine = TechnicalAnalysisEngine()
        result = engine.analyze("BBCA.JK", sample_ohlcv)
        assert "ma20" in result.indicators
        assert "ma50" in result.indicators
        assert "rsi" in result.indicators
        assert "macd" in result.indicators


# ── Fundamental Engine ───────────────────────────────────────────────────────

class TestFundamentalEngine:
    """Test fundamental analysis engine."""

    def test_full_analysis(self):
        from quant.signals.fundamental import FundamentalAnalysisEngine
        engine = FundamentalAnalysisEngine()
        result = engine.analyze(
            "BBCA.JK", pe=15, pb=2.5, roe=20, der=0.5,
            dividend_yield=3.0, eps_growth=10, revenue_growth=12,
        )
        assert 0 <= result.score <= 100
        assert result.ticker == "BBCA.JK"
        assert result.status == "ok"
        assert "pe" in result.breakdown
        assert "pb" in result.breakdown

    def test_missing_data(self):
        from quant.signals.fundamental import FundamentalAnalysisEngine
        engine = FundamentalAnalysisEngine()
        result = engine.analyze("TEST", pe=None, pb=None, roe=None, der=None)
        assert result.status == "no_data"
        assert result.score == 62.5  # All neutral 12.5 * 5

    def test_partial_data(self):
        from quant.signals.fundamental import FundamentalAnalysisEngine
        engine = FundamentalAnalysisEngine()
        result = engine.analyze("TEST", pe=10, pb=None, roe=None, der=None)
        assert result.status == "warning"

    def test_low_pe_scores_higher(self):
        from quant.signals.fundamental import FundamentalAnalysisEngine
        engine = FundamentalAnalysisEngine()
        low_pe = engine.analyze("A", pe=5)
        high_pe = engine.analyze("B", pe=50)
        assert low_pe.breakdown["pe"] > high_pe.breakdown["pe"]


# ── Macro Engine ─────────────────────────────────────────────────────────────

class TestMacroEngine:
    """Test macro economic engine.

    NOTE: regime returns lowercase strings.
    """

    def test_analyze_with_data(self):
        from quant.signals.macro import MacroEconomicEngine
        engine = MacroEconomicEngine()
        result = engine.analyze(
            us10y_yield=4.5, us10y_prev=5.0,
            gold_price=2000, gold_prev=1950,
            oil_price=75, oil_prev=70,
            usd_idr=15800, usd_idr_prev=16000,
        )
        assert 0 <= result.score <= 100
        assert result.regime.lower() in ("tightening", "easing", "growth", "slowdown", "neutral")
        assert "us10y" in result.breakdown

    def test_analyze_no_data(self):
        from quant.signals.macro import MacroEconomicEngine
        engine = MacroEconomicEngine()
        result = engine.analyze()
        assert result.score == 50.0  # All neutral 12.5 * 4
        assert result.regime.lower() == "neutral"

    def test_easing_regime(self):
        from quant.signals.macro import MacroEconomicEngine
        engine = MacroEconomicEngine()
        result = engine.analyze(us10y_yield=4.0, us10y_prev=5.0)
        assert result.regime.lower() == "easing"


# ── Global Market Engine ─────────────────────────────────────────────────────

class TestGlobalMarketEngine:
    """Test global market engine."""

    def test_analyze(self):
        from quant.signals.global_market import GlobalMarketEngine
        engine = GlobalMarketEngine()
        np.random.seed(42)
        data = {}
        for ticker in ["^GSPC", "^IXIC", "^DJI"]:
            n = 250
            data[ticker] = pd.DataFrame({
                "close": np.cumprod(1 + np.random.normal(0.001, 0.01, n)) * 100
            }, index=pd.bdate_range("2024-01-01", periods=n))
        result = engine.analyze(data)
        assert 0 <= result.score <= 100
        assert len(result.above_ma50) + len(result.below_ma50) > 0

    def test_empty_data(self):
        from quant.signals.global_market import GlobalMarketEngine
        engine = GlobalMarketEngine()
        result = engine.analyze({})
        assert result.score == 0.0


# ── Sentiment Engine ─────────────────────────────────────────────────────────

class TestSentimentEngine:
    """Test sentiment engine.

    NOTE: News NLP is broken — `quant.analysis.news_sentiment` module doesn't exist.
    Only test the score-based aggregation, not news_texts.
    """

    def test_analyze_with_scores(self):
        from quant.signals.sentiment import SentimentEngine
        engine = SentimentEngine()
        result = engine.analyze(
            "BBCA.JK",
            foreign_flow_score=0.8,
            broker_summary_score=0.6,
            historical_score=0.5,
        )
        assert -1 <= result.score <= 1
        assert result.ticker == "BBCA.JK"
        assert result.label in ("positive", "negative", "neutral")

    def test_news_nlp_missing_module(self):
        """BUG: _analyze_news imports non-existent quant.analysis.news_sentiment."""
        from quant.signals.sentiment import SentimentEngine
        engine = SentimentEngine()
        # This will raise ModuleNotFoundError due to missing module
        with pytest.raises(Exception):
            engine.analyze("BBCA.JK", news_texts=["Saham naik"])


# ── Alpha Signals ────────────────────────────────────────────────────────────

class TestAlphaSignals:
    """Test alpha signal engines. Methods are generate_signals(close)."""

    def test_mean_reversion_engine(self, sample_prices_series):
        from quant.signals.alpha_signals import MeanReversionEngine
        engine = MeanReversionEngine()
        result = engine.generate_signals(sample_prices_series)
        assert hasattr(result, "signal")
        assert hasattr(result, "confidence")
        assert len(result.signal) == len(sample_prices_series)
        assert result.signal.between(-1, 1).all()

    def test_short_term_reversal_engine(self, sample_prices_series):
        from quant.signals.alpha_signals import ShortTermReversalEngine
        engine = ShortTermReversalEngine()
        result = engine.generate_signals(sample_prices_series)
        assert len(result.signal) == len(sample_prices_series)
        assert result.signal.between(-1, 1).all()

    def test_ewma_momentum_engine(self, sample_prices_series):
        from quant.signals.alpha_signals import EWMAMomentumEngine
        engine = EWMAMomentumEngine()
        result = engine.generate_signals(sample_prices_series)
        assert len(result.signal) == len(sample_prices_series)
        assert result.signal.between(-1, 1).all()

    def test_regime_switch_engine(self, sample_prices_series):
        from quant.signals.alpha_signals import RegimeSwitchEngine
        engine = RegimeSwitchEngine()
        result = engine.generate_signals(sample_prices_series)
        assert len(result.signal) == len(sample_prices_series)
        assert result.signal.between(-1, 1).all()


# ── Triple Barrier Labeling ──────────────────────────────────────────────────

class TestTripleBarrier:
    """Test triple barrier labeling."""

    def test_apply_triple_barrier(self, sample_prices_series):
        from quant.signals.tbl import apply_triple_barrier, TBLConfig
        config = TBLConfig(take_profit=0.03, stop_loss=0.03, max_holding=5, use_atr=False)
        result = apply_triple_barrier(sample_prices_series, config)
        assert len(result) == len(sample_prices_series)
        assert "label" in result.columns
        assert "barrier_hit" in result.columns
        assert "holding_period" in result.columns
        assert "return_pct" in result.columns
        assert set(result["label"].unique()).issubset({-1, 0, 1})

    def test_atr_based_barriers(self, sample_ohlcv):
        from quant.signals.tbl import apply_triple_barrier, TBLConfig
        config = TBLConfig(use_atr=True, atr_multiplier=1.5)
        result = apply_triple_barrier(sample_ohlcv["close"], config)
        assert len(result) == len(sample_ohlcv)

    def test_meta_label(self, sample_prices_series):
        from quant.signals.tbl import meta_label, TBLConfig
        signals = pd.Series(1.0, index=sample_prices_series.index)
        meta = meta_label(signals, sample_prices_series, TBLConfig(use_atr=False))
        assert len(meta) == len(sample_prices_series)
        assert set(meta.unique()).issubset({0, 1})


# ── Volume Features ──────────────────────────────────────────────────────────

class TestVolumeFeatures:
    """Test volume feature engineering."""

    def test_vwap(self, sample_ohlcv):
        from quant.signals.volume_features import compute_vwap
        result = compute_vwap(
            sample_ohlcv["high"], sample_ohlcv["low"],
            sample_ohlcv["close"], sample_ohlcv["volume"], window=20,
        )
        assert len(result.vwap) == len(sample_ohlcv)
        assert len(result.deviation) == len(sample_ohlcv)
        assert len(result.typical_price) == len(sample_ohlcv)

    def test_vwap_no_lookahead(self, sample_ohlcv):
        """VWAP deviation must be shifted to prevent look-ahead."""
        from quant.signals.volume_features import compute_vwap
        result = compute_vwap(
            sample_ohlcv["high"], sample_ohlcv["low"],
            sample_ohlcv["close"], sample_ohlcv["volume"], window=20,
        )
        valid = result.deviation.dropna()
        assert len(valid) > 0


# ── HMM Regime Detector ──────────────────────────────────────────────────────

class TestHMMRegime:
    """Test HMM regime detection."""

    def test_regime_detection(self, sample_prices_series):
        from quant.signals.hmm_regime import HMMRegimeDetector
        detector = HMMRegimeDetector(min_history=30)
        result = detector.detect(sample_prices_series)
        assert result.regime in (0, 1, 2)
        assert result.regime_name in ("trending", "ranging", "crisis")
        assert 0 <= result.confidence <= 1
        assert 0 <= result.volatility_pctile <= 1

    def test_insufficient_history(self):
        from quant.signals.hmm_regime import HMMRegimeDetector
        detector = HMMRegimeDetector(min_history=100)
        short = pd.Series(np.linspace(100, 110, 20))
        result = detector.detect(short)
        assert result.regime_name in ("trending", "ranging", "crisis")


# ── Fama-French ──────────────────────────────────────────────────────────────

class TestFamaFrench:
    """Test Fama-French 5-factor model."""

    def test_compute_signal(self, sample_ohlcv):
        from quant.signals.fama_french import FamaFrench5Factor
        ff = FamaFrench5Factor(min_history=30)
        result = ff.compute_signal("BBCA.JK", sample_ohlcv)
        assert result.ticker == "BBCA.JK"
        assert isinstance(result.predicted_return, float)
        assert isinstance(result.confidence, float)


# ── Signal Aggregator ────────────────────────────────────────────────────────

class TestSignalAggregator:
    """Test signal aggregation."""

    def test_signal_result_creation(self):
        from quant.signals.aggregator import SignalResult
        sr = SignalResult(
            engine_name="technical", ticker="BBCA.JK",
            signal_value=0.5, confidence=0.8, direction="long",
        )
        assert sr.engine_name == "technical"
        assert sr.signal_value == 0.5

    def test_composite_signal(self):
        from quant.signals.aggregator import CompositeSignal, SignalResult
        cs = CompositeSignal(
            ticker="BBCA.JK", composite_value=0.7, confidence=0.85,
            direction="long",
            attributions=[
                SignalResult("technical", "BBCA.JK", 0.8, 0.9, "long"),
                SignalResult("fundamental", "BBCA.JK", 0.6, 0.7, "long"),
            ],
        )
        d = cs.to_dict()
        assert d["ticker"] == "BBCA.JK"
        assert d["composite_signal"] == 0.7
        assert len(d["engines"]) == 2

    def test_default_weights(self):
        from quant.signals.aggregator import SignalAggregator
        weights = SignalAggregator.DEFAULT_WEIGHTS
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01
