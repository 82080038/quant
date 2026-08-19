"""Signal aggregation — continuous signal [-1, +1] from multiple engines.

Weight-centric: produces composite signal per ticker, with full attribution.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import text
from quant.core.db import get_db
from quant.data.point_in_time import PointInTimeQuery


@dataclass
class SignalResult:
    """Single engine signal output."""
    engine_name: str
    ticker: str
    signal_value: float  # [-1, +1]
    confidence: float    # [0, 1]
    direction: str       # "long" / "short" / "neutral"
    rationale: str = ""
    weight: float = 0.0  # weight in composite


@dataclass
class CompositeSignal:
    """Aggregated signal across all engines."""
    ticker: str
    composite_value: float  # [-1, +1]
    confidence: float       # [0, 1]
    direction: str          # "long" / "short" / "neutral"
    attributions: list[SignalResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "composite_signal": round(self.composite_value, 4),
            "confidence": round(self.confidence, 4),
            "direction": self.direction,
            "engines": [
                {
                    "engine": a.engine_name,
                    "signal": round(a.signal_value, 4),
                    "confidence": round(a.confidence, 4),
                    "weight": round(a.weight, 4),
                    "contribution": round(a.signal_value * a.weight, 4),
                    "rationale": a.rationale,
                }
                for a in self.attributions
            ],
        }


class SignalAggregator:
    """Aggregates signals from multiple engines into a composite signal.

    Signals are continuous [-1, +1], NOT binary.
    Weight allocation is dynamic based on regime and engine confidence.
    """

    # Default engine weights (will be overridden by regime-conditional weights)
    DEFAULT_WEIGHTS = {
        "technical": 0.20,
        "fundamental": 0.15,
        "macro": 0.10,
        "sentiment": 0.15,
        "global_market": 0.10,
        "alpha_momentum": 0.08,
        "alpha_mean_reversion": 0.05,
        "alpha_reversal": 0.05,
        "hmm_regime": 0.04,
        "volume_features": 0.04,
        "policy_events": 0.02,
        "holiday_effect": 0.02,
    }

    def __init__(self, session=None, pit: Optional[PointInTimeQuery] = None):
        self._session = session
        self._pit = pit

    @property
    def pit(self) -> PointInTimeQuery:
        if self._pit is None:
            self._pit = PointInTimeQuery(self._session)
        return self._pit

    def aggregate(
        self,
        ticker: str,
        as_of_date: date,
        engine_signals: list[SignalResult],
        regime: str = "unknown",
    ) -> CompositeSignal:
        """Aggregate engine signals into composite.

        Args:
            ticker: Stock ticker
            as_of_date: Decision date
            engine_signals: List of SignalResult from each engine
            regime: Current market regime ("bull", "bear", "sideways", "crisis")

        Returns:
            CompositeSignal with full attribution
        """
        weights = self._get_regime_weights(regime)

        # Assign weights to engines
        total_weight = 0.0
        for sig in engine_signals:
            w = weights.get(sig.engine_name, 0.0)
            # Adjust weight by confidence
            sig.weight = w * sig.confidence
            total_weight += sig.weight

        # Normalize weights
        if total_weight > 0:
            for sig in engine_signals:
                sig.weight /= total_weight

        # Compute composite signal
        composite = sum(s.signal_value * s.weight for s in engine_signals)

        # Compute aggregate confidence
        confidence = sum(s.confidence * s.weight for s in engine_signals) if total_weight > 0 else 0.0

        # Determine direction
        if composite > 0.1:
            direction = "long"
        elif composite < -0.1:
            direction = "short"
        else:
            direction = "neutral"

        return CompositeSignal(
            ticker=ticker,
            composite_value=composite,
            confidence=confidence,
            direction=direction,
            attributions=engine_signals,
        )

    def _get_regime_weights(self, regime: str) -> dict[str, float]:
        """Get regime-conditional weights for engines.

        Different regimes favor different signal types:
        - Bull: momentum, technical, global
        - Bear: fundamental, macro, policy events
        - Sideways: mean reversion, volume, sentiment
        - Crisis: macro, policy events, risk-off
        """
        if regime == "bull":
            return {
                "technical": 0.25,
                "alpha_momentum": 0.15,
                "global_market": 0.12,
                "fundamental": 0.12,
                "sentiment": 0.10,
                "macro": 0.08,
                "alpha_mean_reversion": 0.05,
                "alpha_reversal": 0.03,
                "hmm_regime": 0.03,
                "volume_features": 0.04,
                "policy_events": 0.02,
                "holiday_effect": 0.01,
            }
        elif regime == "bear":
            return {
                "fundamental": 0.22,
                "macro": 0.18,
                "policy_events": 0.12,
                "technical": 0.12,
                "sentiment": 0.10,
                "global_market": 0.08,
                "alpha_reversal": 0.06,
                "alpha_mean_reversion": 0.05,
                "alpha_momentum": 0.02,
                "hmm_regime": 0.03,
                "volume_features": 0.02,
                "holiday_effect": 0.00,
            }
        elif regime == "sideways":
            return {
                "alpha_mean_reversion": 0.20,
                "volume_features": 0.15,
                "sentiment": 0.15,
                "technical": 0.12,
                "fundamental": 0.12,
                "macro": 0.08,
                "alpha_reversal": 0.08,
                "global_market": 0.05,
                "alpha_momentum": 0.02,
                "hmm_regime": 0.02,
                "policy_events": 0.01,
                "holiday_effect": 0.00,
            }
        elif regime == "crisis":
            return {
                "macro": 0.25,
                "policy_events": 0.20,
                "fundamental": 0.15,
                "global_market": 0.10,
                "technical": 0.08,
                "sentiment": 0.08,
                "alpha_reversal": 0.05,
                "alpha_mean_reversion": 0.04,
                "volume_features": 0.03,
                "alpha_momentum": 0.00,
                "hmm_regime": 0.02,
                "holiday_effect": 0.00,
            }
        else:
            return self.DEFAULT_WEIGHTS.copy()

    def log_attribution(
        self,
        composite: CompositeSignal,
        as_of_date: date,
        session=None,
    ) -> None:
        """Log signal attribution to database."""
        sess = session or self._session or get_db()
        try:
            for sig in composite.attributions:
                sess.execute(
                    text("""
                        INSERT INTO signal_attribution_log
                            (date, ticker, engine_name, signal_value, signal_direction,
                             confidence, weight_in_portfolio, contribution_to_decision, rationale)
                        VALUES
                            (:date, :ticker, :engine, :signal, :direction,
                             :confidence, :weight, :contribution, :rationale)
                    """),
                    {
                        "date": as_of_date,
                        "ticker": sig.ticker,
                        "engine": sig.engine_name,
                        "signal": sig.signal_value,
                        "direction": sig.direction,
                        "confidence": sig.confidence,
                        "weight": sig.weight,
                        "contribution": sig.signal_value * sig.weight,
                        "rationale": sig.rationale,
                    },
                )
            if session is None:
                sess.commit()
        except Exception:
            if session is None:
                sess.rollback()
            raise
        finally:
            if session is None:
                sess.close()
