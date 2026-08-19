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
    # Weights for global_market and relationship are boosted to reflect the
    # importance of cross-asset causality in the decision process.
    DEFAULT_WEIGHTS = {
        "technical": 0.18,
        "fundamental": 0.12,
        "macro": 0.08,
        "sentiment": 0.12,
        "global_market": 0.15,
        "relationship": 0.10,
        "alpha_momentum": 0.07,
        "alpha_mean_reversion": 0.05,
        "alpha_reversal": 0.04,
        "hmm_regime": 0.03,
        "volume_features": 0.03,
        "policy_events": 0.02,
        "holiday_effect": 0.01,
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
        interdependency_matrix: Optional[list[dict]] = None,
    ) -> CompositeSignal:
        """Aggregate engine signals into composite.

        Args:
            ticker: Stock ticker
            as_of_date: Decision date
            engine_signals: List of SignalResult from each engine
            regime: Current market regime ("bull", "bear", "sideways", "crisis")
            interdependency_matrix: Optional pre-loaded causality data from
                global_market_interdependencies table. When provided, the
                global_market and relationship engine signals receive an
                additional causality boost proportional to the aggregate
                impact_weight of the interdependency matrix.

        Returns:
            CompositeSignal with full attribution
        """
        weights = self._get_regime_weights(regime)

        # Causality boost: when interdependency matrix data is available,
        # boost the weight of global_market and relationship engines
        # proportionally to the aggregate causal impact on this ticker.
        if interdependency_matrix:
            total_impact = sum(s.get("impact_weight", 0) for s in interdependency_matrix)
            n_sources = len(interdependency_matrix)
            if n_sources > 0 and total_impact > 0:
                avg_impact = total_impact / n_sources
                # Boost factor: up to 1.5x for strong causal links
                boost = 1.0 + min(0.5, avg_impact * 2)
                if "global_market" in weights:
                    weights["global_market"] *= boost
                if "relationship" in weights:
                    weights["relationship"] *= boost

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
                "technical": 0.22,
                "global_market": 0.15,
                "alpha_momentum": 0.13,
                "relationship": 0.10,
                "fundamental": 0.10,
                "sentiment": 0.10,
                "macro": 0.07,
                "alpha_mean_reversion": 0.04,
                "alpha_reversal": 0.03,
                "hmm_regime": 0.03,
                "volume_features": 0.04,
                "policy_events": 0.02,
                "holiday_effect": 0.01,
            }
        elif regime == "bear":
            return {
                "fundamental": 0.18,
                "macro": 0.15,
                "global_market": 0.12,
                "relationship": 0.10,
                "policy_events": 0.10,
                "technical": 0.10,
                "sentiment": 0.08,
                "alpha_reversal": 0.06,
                "alpha_mean_reversion": 0.04,
                "alpha_momentum": 0.02,
                "hmm_regime": 0.03,
                "volume_features": 0.02,
                "holiday_effect": 0.00,
            }
        elif regime == "sideways":
            return {
                "alpha_mean_reversion": 0.18,
                "volume_features": 0.12,
                "sentiment": 0.12,
                "technical": 0.10,
                "fundamental": 0.10,
                "global_market": 0.08,
                "relationship": 0.08,
                "macro": 0.07,
                "alpha_reversal": 0.07,
                "alpha_momentum": 0.02,
                "hmm_regime": 0.02,
                "policy_events": 0.01,
                "holiday_effect": 0.00,
            }
        elif regime == "crisis":
            return {
                "macro": 0.20,
                "global_market": 0.15,
                "relationship": 0.12,
                "policy_events": 0.15,
                "fundamental": 0.12,
                "technical": 0.07,
                "sentiment": 0.07,
                "alpha_reversal": 0.05,
                "alpha_mean_reversion": 0.03,
                "volume_features": 0.02,
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
