"""Engine Registry — unified interface for all signal engines.

Wraps heterogeneous engine interfaces into a common `generate_signal()` method
that returns `quant.signals.aggregator.SignalResult`.

Each adapter handles:
  1. Loading appropriate data from DB (via PointInTimeQuery)
  2. Calling the engine's native method
  3. Converting the engine-specific result to SignalResult [-1, +1]
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.signals.aggregator import SignalResult
from quant.signals.technical import TechnicalAnalysisEngine
from quant.signals.fundamental import FundamentalAnalysisEngine
from quant.signals.macro import MacroEconomicEngine
from quant.signals.global_market import GlobalMarketEngine
from quant.signals.sentiment import SentimentEngine
from quant.signals.relationship import MarketRelationshipEngine
from quant.signals.alpha_signals import (
    MeanReversionEngine,
    ShortTermReversalEngine,
    EWMAMomentumEngine,
    RegimeSwitchEngine,
)
from quant.signals.hmm_regime import HMMRegimeDetector
from quant.signals.fama_french import FamaFrench5Factor
from quant.signals.holiday_effect import HolidayEffectAnalyzer
from quant.signals.volume_features import (
    compute_vwap,
    compute_ofi_proxy,
    detect_obv_divergence,
    compute_vw_momentum,
    compute_foreign_flow_signal,
)

logger = logging.getLogger(__name__)

__all__ = ["EngineRegistry", "ENGINE_NAMES"]


def _score_to_signal(score: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    """Convert a 0-100 score to [-1, +1] signal. 50 = neutral."""
    normalized = (score - 50.0) / 50.0
    return float(np.clip(normalized, -1.0, 1.0))


def _confidence_from_score(score: float) -> float:
    """Confidence from score: further from 50 → higher confidence."""
    return float(min(1.0, abs(score - 50.0) / 50.0))


class EngineRegistry:
    """Unified registry for all signal engines.

    Usage::

        registry = EngineRegistry(session=db_session)
        signals = registry.generate_all("BBCA", date(2026, 8, 19))
        # signals: list[SignalResult]
    """

    def __init__(self, session=None, pit=None):
        self._session = session
        self._pit = pit
        self._engines: dict[str, object] = {}
        self._init_engines()

    def _init_engines(self):
        """Instantiate all engines."""
        self._engines = {
            "technical": TechnicalAnalysisEngine(),
            "fundamental": FundamentalAnalysisEngine(),
            "macro": MacroEconomicEngine(),
            "global_market": GlobalMarketEngine(),
            "sentiment": SentimentEngine(),
            "relationship": MarketRelationshipEngine(),
            "alpha_mean_reversion": MeanReversionEngine(),
            "alpha_reversal": ShortTermReversalEngine(),
            "alpha_momentum": EWMAMomentumEngine(),
            "alpha_regime_switch": RegimeSwitchEngine(),
            "hmm_regime": HMMRegimeDetector(),
            "fama_french": FamaFrench5Factor(),
            "holiday_effect": HolidayEffectAnalyzer(),
        }

    @property
    def pit(self):
        if self._pit is None:
            from quant.data.point_in_time import PointInTimeQuery

            self._pit = PointInTimeQuery(self._session)
        return self._pit

    def _load_ohlcv(self, ticker: str, as_of: date, lookback: int = 300) -> pd.DataFrame:
        """Load OHLCV data from DB."""
        try:
            df = self.pit.get_prices(ticker, as_of, lookback=lookback)
            if df is not None and not df.empty:
                df = df.sort_values("date")
                cols = {c.lower(): c for c in df.columns}
                rename = {}
                for needed in ["open", "high", "low", "close", "volume"]:
                    if needed not in df.columns and needed.capitalize() in df.columns:
                        rename[needed.capitalize()] = needed
                if rename:
                    df = df.rename(columns=rename)
            return df
        except Exception as e:
            logger.debug("Failed to load OHLCV for %s: %s", ticker, e)
            if self._session is not None:
                self._session.rollback()
            return pd.DataFrame()

    def _load_fundamentals(self, ticker: str, as_of: date) -> dict:
        """Load fundamental data from DB."""
        try:
            from sqlalchemy import text
            from decimal import Decimal

            row = self._session.execute(
                text("""
                    SELECT pe_ratio, pb_ratio, roe, debt_ratio,
                           dividend_yield, eps, revenue, net_income
                    FROM fundamental_data
                    WHERE ticker = :ticker AND as_of_date <= :as_of
                    ORDER BY as_of_date DESC LIMIT 1
                """),
                {"ticker": ticker, "as_of": as_of},
            ).fetchone()
            if row:
                def _f(v):
                    return float(v) if isinstance(v, (Decimal, int, float)) and v is not None else None
                return {
                    "pe": _f(row[0]), "pb": _f(row[1]), "roe": _f(row[2]),
                    "der": _f(row[3]), "dividend_yield": _f(row[4]),
                }
        except Exception as e:
            logger.debug("Failed to load fundamentals for %s: %s", ticker, e)
            if self._session is not None:
                self._session.rollback()
        return {}

    def _load_foreign_flow(self, ticker: str, as_of: date, lookback: int = 20) -> pd.DataFrame:
        """Load foreign flow data from DB."""
        try:
            from sqlalchemy import text

            rows = self._session.execute(
                text("""
                    SELECT date, foreign_net, domestic_buy, domestic_sell, volume
                    FROM foreign_flow
                    WHERE ticker = :ticker AND date <= :as_of
                    ORDER BY date DESC LIMIT :limit
                """),
                {"ticker": ticker, "as_of": as_of, "limit": lookback},
            ).fetchall()
            if rows:
                return pd.DataFrame(rows, columns=["date", "foreign_net", "domestic_buy", "domestic_sell", "volume"])
        except Exception as e:
            logger.debug("Failed to load foreign flow for %s: %s", ticker, e)
            if self._session is not None:
                self._session.rollback()
        return pd.DataFrame()

    # ── Engine Adapters ──────────────────────────────────────────────────

    def _signal_technical(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 50:
            return SignalResult("technical", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        result = self._engines["technical"].analyze(ticker, df)
        signal = _score_to_signal(result.score)
        conf = _confidence_from_score(result.score)
        direction = "long" if signal > 0.1 else "short" if signal < -0.1 else "neutral"
        return SignalResult("technical", ticker, signal, conf, direction, f"Score={result.score:.1f}, Trend={result.trend}")

    def _signal_fundamental(self, ticker: str, as_of: date) -> SignalResult:
        fund = self._load_fundamentals(ticker, as_of)
        if not fund:
            return SignalResult("fundamental", ticker, 0.0, 0.0, "neutral", "No fundamental data")
        result = self._engines["fundamental"].analyze(ticker, **fund)
        signal = _score_to_signal(result.score)
        conf = _confidence_from_score(result.score)
        direction = "long" if signal > 0.1 else "short" if signal < -0.1 else "neutral"
        return SignalResult("fundamental", ticker, signal, conf, direction, f"Score={result.score:.1f}")

    def _signal_macro(self, ticker: str, as_of: date) -> SignalResult:
        # Macro is market-wide, not ticker-specific
        # Would need macro data from DB; return neutral for now
        return SignalResult("macro", ticker, 0.0, 0.0, "neutral", "Macro data adapter pending")

    def _load_interdependency_matrix(self, ticker: str, as_of: date) -> list[dict]:
        """Load pre-computed cross-asset interdependency matrix from DB.

        Queries `global_market_interdependencies` for all source instruments
        that have a statistically significant causal impact on the target
        ticker. Uses the composite index `idx_gmi_target_date` for
        sub-millisecond lookup.

        Returns a list of dicts sorted by impact_weight (descending).
        """
        if self._session is None:
            return []
        try:
            rows = self._session.execute(
                text("""
                    SELECT source_instrument_id, target_instrument_id,
                           correlation_coefficient, causality_score,
                           causality_p_value, causality_direction,
                           time_lag_seconds, time_lag_periods,
                           impact_weight, regime
                    FROM global_market_interdependencies
                    WHERE target_instrument_id = :ticker
                      AND as_of_date = (
                          SELECT MAX(as_of_date)
                          FROM global_market_interdependencies
                          WHERE target_instrument_id = :ticker
                      )
                      AND impact_weight > 0
                    ORDER BY impact_weight DESC
                """),
                {"ticker": ticker},
            ).fetchall()

            return [
                {
                    "source_instrument_id": r[0],
                    "target_instrument_id": r[1],
                    "correlation_coefficient": float(r[2]) if r[2] else 0.0,
                    "causality_score": float(r[3]) if r[3] else 0.0,
                    "causality_p_value": float(r[4]) if r[4] else 1.0,
                    "causality_direction": r[5] or "none",
                    "time_lag_seconds": int(r[6]) if r[6] else 0,
                    "time_lag_periods": int(r[7]) if r[7] else 0,
                    "impact_weight": float(r[8]) if r[8] else 0.0,
                    "regime": r[9] or "unknown",
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug("Interdependency matrix load failed for %s: %s", ticker, e)
            if self._session is not None:
                self._session.rollback()
            return []

    def _signal_global_market(self, ticker: str, as_of: date) -> SignalResult:
        """Generate global market signal using the interdependency matrix.

        Reads pre-computed causality data from `global_market_interdependencies`
        to weight the influence of each global source asset on the target ticker.
        Falls back to neutral if no DB data is available.
        """
        causal_sources = self._load_interdependency_matrix(ticker, as_of)
        if not causal_sources:
            return SignalResult("global_market", ticker, 0.0, 0.0, "neutral", "No interdependency data")

        # Compute weighted signal from causal sources
        total_signal = 0.0
        total_weight = 0.0
        top_sources = []

        for src in causal_sources[:5]:  # top 5 sources
            corr = src["correlation_coefficient"]
            impact = src["impact_weight"]
            direction = src["causality_direction"]
            lag = src["time_lag_periods"]

            # Signal from correlation sign weighted by impact
            src_signal = corr * impact
            total_signal += src_signal
            total_weight += impact
            top_sources.append(f"{src['source_instrument_id']}(lag={lag}d,impact={impact:.3f})")

        if total_weight > 0:
            signal_val = float(np.clip(total_signal / total_weight, -1.0, 1.0))
        else:
            signal_val = 0.0

        conf = float(min(1.0, total_weight / len(causal_sources))) if causal_sources else 0.0
        direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
        rationale = f"Causal sources: {', '.join(top_sources[:3])}"

        return SignalResult("global_market", ticker, signal_val, conf, direction, rationale)

    def _signal_sentiment(self, ticker: str, as_of: date) -> SignalResult:
        # Would need news sentiment and foreign flow data
        ff = self._load_foreign_flow(ticker, as_of)
        ff_score = None
        if not ff.empty and "foreign_net" in ff.columns:
            recent_net = ff["foreign_net"].iloc[-5:].sum()
            total_vol = ff["volume"].iloc[-5:].sum() if "volume" in ff.columns else 1
            if total_vol > 0:
                ff_score = float(np.clip(50 + (recent_net / total_vol) * 100, 0, 100))
        result = self._engines["sentiment"].analyze(ticker, foreign_flow_score=ff_score)
        signal = _score_to_signal(result.score)
        conf = _confidence_from_score(result.score)
        direction = "long" if signal > 0.1 else "short" if signal < -0.1 else "neutral"
        return SignalResult("sentiment", ticker, signal, conf, direction, f"Score={result.score:.1f}, Label={result.label}")

    def _signal_relationship(self, ticker: str, as_of: date) -> SignalResult:
        """Generate relationship signal from the interdependency matrix.

        Uses the pre-computed causality data to determine the dominant
        source assets and their impact on the target ticker.
        """
        engine = self._engines.get("relationship")
        if engine is None or self._session is None:
            return SignalResult("relationship", ticker, 0.0, 0.0, "neutral", "No session or engine")

        try:
            result = engine.analyze_from_db(ticker, as_of, self._session)
            if result is None:
                return SignalResult("relationship", ticker, 0.0, 0.0, "neutral", "No DB relationship data")

            signal = _score_to_signal(result.score)
            conf = _confidence_from_score(result.score)
            direction = "long" if signal > 0.1 else "short" if signal < -0.1 else "neutral"
            dom = result.dominant_source or "none"
            lag = result.avg_time_lag_periods
            rationale = f"Dominant={dom}, avg_lag={lag:.1f}d, n_sources={len(result.relationships)}"
            return SignalResult("relationship", ticker, signal, conf, direction, rationale)
        except Exception as e:
            logger.debug("Relationship signal failed for %s: %s", ticker, e)
            if self._session is not None:
                self._session.rollback()
            return SignalResult("relationship", ticker, 0.0, 0.0, "neutral", f"Error: {e}")

    def _signal_alpha_mean_reversion(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 50:
            return SignalResult("alpha_mean_reversion", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        close = df["close"].astype(float)
        result = self._engines["alpha_mean_reversion"].generate_signals(close)
        signal_val = float(result.signal.iloc[-1]) if not result.signal.empty else 0.0
        conf_val = float(result.confidence.iloc[-1]) if not result.confidence.empty else 0.0
        direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
        return SignalResult("alpha_mean_reversion", ticker, signal_val, conf_val, direction, "Bollinger+RSI")

    def _signal_alpha_reversal(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 30:
            return SignalResult("alpha_reversal", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        close = df["close"].astype(float)
        result = self._engines["alpha_reversal"].generate_signals(close)
        signal_val = float(result.signal.iloc[-1]) if not result.signal.empty else 0.0
        conf_val = float(result.confidence.iloc[-1]) if not result.confidence.empty else 0.0
        direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
        return SignalResult("alpha_reversal", ticker, signal_val, conf_val, direction, "Short-term reversal")

    def _signal_alpha_momentum(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 50:
            return SignalResult("alpha_momentum", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        close = df["close"].astype(float)
        result = self._engines["alpha_momentum"].generate_signals(close)
        signal_val = float(result.signal.iloc[-1]) if not result.signal.empty else 0.0
        conf_val = float(result.confidence.iloc[-1]) if not result.confidence.empty else 0.0
        direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
        return SignalResult("alpha_momentum", ticker, signal_val, conf_val, direction, "EWMA momentum")

    def _signal_alpha_regime_switch(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 50:
            return SignalResult("alpha_regime_switch", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        close = df["close"].astype(float)
        result = self._engines["alpha_regime_switch"].generate_signals(close)
        signal_val = float(result.signal.iloc[-1]) if not result.signal.empty else 0.0
        conf_val = float(result.confidence.iloc[-1]) if not result.confidence.empty else 0.0
        direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
        return SignalResult("alpha_regime_switch", ticker, signal_val, conf_val, direction, "Regime switch")

    def _signal_hmm_regime(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 60:
            return SignalResult("hmm_regime", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        close = df["close"].astype(float)
        try:
            signal_val, conf_val, regime_name = self._engines["hmm_regime"].compute_signal(close)
            direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
            return SignalResult("hmm_regime", ticker, signal_val, conf_val, direction, f"Regime={regime_name}")
        except Exception as e:
            logger.debug("HMM regime failed for %s: %s", ticker, e)
            return SignalResult("hmm_regime", ticker, 0.0, 0.0, "neutral", f"Error: {e}")

    def _signal_fama_french(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 60:
            return SignalResult("fama_french", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        try:
            result = self._engines["fama_french"].compute_signal(ticker, df)
            signal_val = float(np.clip(result.predicted_return * 10, -1, 1))
            conf_val = result.confidence
            direction = "long" if signal_val > 0.1 else "short" if signal_val < -0.1 else "neutral"
            return SignalResult("fama_french", ticker, signal_val, conf_val, direction, f"Predicted return={result.predicted_return:.4f}")
        except Exception as e:
            logger.debug("Fama-French failed for %s: %s", ticker, e)
            return SignalResult("fama_french", ticker, 0.0, 0.0, "neutral", f"Error: {e}")

    def _signal_holiday_effect(self, ticker: str, as_of: date) -> SignalResult:
        # Holiday effect is calendar-based; needs exchange holidays from DB
        return SignalResult("holiday_effect", ticker, 0.0, 0.0, "neutral", "Holiday calendar adapter pending")

    def _signal_volume_features(self, ticker: str, as_of: date) -> SignalResult:
        df = self._load_ohlcv(ticker, as_of)
        if df.empty or len(df) < 20:
            return SignalResult("volume_features", ticker, 0.0, 0.0, "neutral", "Insufficient data")
        try:
            h, l, c, v = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float), df["volume"].astype(float)
            vwap_result = compute_vwap(h, l, c, v)
            dev = float(vwap_result.deviation.iloc[-1]) if not vwap_result.deviation.empty else 0.0
            ofi_result = compute_ofi_proxy(c, v, h, l)
            ofi_val = float(ofi_result.ofi.iloc[-1]) if hasattr(ofi_result, "ofi") and not ofi_result.ofi.empty else 0.0
            vw_mom = compute_vw_momentum(c, v)
            vw_mom_val = float(vw_mom.iloc[-1]) if not vw_mom.empty else 0.0
            composite = float(np.clip(dev * 2 + ofi_val + vw_mom_val, -1, 1))
            conf = float(min(1.0, abs(composite)))
            direction = "long" if composite > 0.1 else "short" if composite < -0.1 else "neutral"
            return SignalResult("volume_features", ticker, composite, conf, direction, f"VWAP_dev={dev:.3f}, OFI={ofi_val:.3f}")
        except Exception as e:
            logger.debug("Volume features failed for %s: %s", ticker, e)
            return SignalResult("volume_features", ticker, 0.0, 0.0, "neutral", f"Error: {e}")

    def _signal_policy_events(self, ticker: str, as_of: date) -> SignalResult:
        return SignalResult("policy_events", ticker, 0.0, 0.0, "neutral", "Policy event adapter pending")

    # ── Dispatcher ───────────────────────────────────────────────────────

    _SIGNAL_METHODS = {
        "technical": "_signal_technical",
        "fundamental": "_signal_fundamental",
        "macro": "_signal_macro",
        "global_market": "_signal_global_market",
        "sentiment": "_signal_sentiment",
        "relationship": "_signal_relationship",
        "alpha_mean_reversion": "_signal_alpha_mean_reversion",
        "alpha_reversal": "_signal_alpha_reversal",
        "alpha_momentum": "_signal_alpha_momentum",
        "alpha_regime_switch": "_signal_alpha_regime_switch",
        "hmm_regime": "_signal_hmm_regime",
        "fama_french": "_signal_fama_french",
        "holiday_effect": "_signal_holiday_effect",
        "volume_features": "_signal_volume_features",
        "policy_events": "_signal_policy_events",
    }

    def generate_signal(self, engine_name: str, ticker: str, as_of: date) -> SignalResult:
        """Generate a single engine signal for a ticker."""
        method_name = self._SIGNAL_METHODS.get(engine_name)
        if method_name is None:
            return SignalResult(engine_name, ticker, 0.0, 0.0, "neutral", f"Unknown engine: {engine_name}")
        method = getattr(self, method_name)
        try:
            return method(ticker, as_of)
        except Exception as e:
            logger.warning("Engine %s failed for %s: %s", engine_name, ticker, e)
            return SignalResult(engine_name, ticker, 0.0, 0.0, "neutral", f"Error: {e}")

    def generate_all(self, ticker: str, as_of: date) -> list[SignalResult]:
        """Generate signals from all registered engines for a ticker."""
        return [self.generate_signal(name, ticker, as_of) for name in self._SIGNAL_METHODS]

    def generate_available(self, ticker: str, as_of: date) -> list[SignalResult]:
        """Generate signals only from engines that have data (non-neutral, non-pending)."""
        results = self.generate_all(ticker, as_of)
        return [r for r in results if r.confidence > 0.0 or "pending" not in r.rationale]


ENGINE_NAMES = list(EngineRegistry._SIGNAL_METHODS.keys())
