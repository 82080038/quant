"""Market Relationship Engine — Cross-Asset Causality & Time-Lag.

Computes correlation, Granger causality, and lead-lag relationships between
a target stock and global reference assets (indices, commodities, forex, crypto).

This refactored engine now integrates with the `global_market_interdependencies`
database table. When DB data is available, it reads the pre-computed
causality matrix for sub-millisecond lookups. When DB data is stale or
missing, it falls back to live computation using the CausalityAnalyzer.

Reference assets cover the full global macro chain:
    - Equities: S&P 500, Nasdaq, Dow Jones, Hang Seng, Nikkei, FTSE, DAX
    - Bonds:    US 10Y Yield (^TNX)
    - Commodities: Gold (GC=F), Crude Oil (CL=F)
    - Forex:    USD/IDR, DXY
    - Local:    IHSG (^JKSE)

Influence Score = Σ(|correlation| × causality_score) / N × 100
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.analysis.causality import CausalityAnalyzer

logger = logging.getLogger(__name__)

REFERENCE_ASSETS: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^DJI": "Dow Jones",
    "^HSI": "Hang Seng",
    "^N225": "Nikkei 225",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX 40",
    "^TNX": "US 10Y Yield",
    "GC=F": "Gold",
    "CL=F": "Crude Oil",
    "IDR=X": "USD/IDR",
    "DX-Y.NYB": "DXY",
    "^JKSE": "IHSG",
}


@dataclass
class RelationshipResult:
    """Relationship analysis result with causality metrics."""

    ticker: str
    score: float
    window: int
    relationships: list[dict[str, object]] = field(default_factory=list)
    dominant_source: Optional[str] = None
    avg_time_lag_periods: float = 0.0
    regime: str = "unknown"


class MarketRelationshipEngine:
    """Market relationship engine computing cross-asset causality and lead-lag.

    Two modes of operation:
    1. **DB-backed mode**: Reads pre-computed causality data from
       `global_market_interdependencies` table for instant lookups.
    2. **Compute mode**: Falls back to live CausalityAnalyzer computation
       when DB data is unavailable or stale.
    """

    def __init__(self, max_lag: int = 5, significance_level: float = 0.05) -> None:
        self._analyzer = CausalityAnalyzer(
            max_lag=max_lag,
            significance_level=significance_level,
        )

    def analyze(
        self,
        ticker: str,
        target_returns: pd.Series,
        reference_returns: dict[str, pd.Series],
        window: int = 60,
        max_lag: int = 5,
        regime: str = "unknown",
    ) -> RelationshipResult:
        """Analyze relationships between ticker and reference assets.

        Computes pairwise causality (Granger test), correlation (CCF),
        and time-lag for each reference asset → target pair.

        Args:
            ticker: Target stock ticker.
            target_returns: Daily returns series for the target stock.
            reference_returns: Dict mapping reference ticker to returns series.
            window: Rolling window for correlation (days).
            max_lag: Maximum lag to test (±max_lag days).
            regime: Current market regime label.

        Returns:
            RelationshipResult with influence score, per-asset relationships,
            dominant source, and average time-lag.
        """
        if target_returns.empty or not reference_returns:
            return RelationshipResult(
                ticker=ticker,
                score=0.0,
                window=window,
                relationships=[],
                regime=regime,
            )

        relationships: list[dict[str, object]] = []
        impact_scores: list[float] = []
        time_lags: list[int] = []

        for ref_ticker, ref_returns in reference_returns.items():
            if ref_returns.empty:
                continue

            result = self._analyzer.analyze_pair(
                source_returns=ref_returns,
                target_returns=target_returns,
                source_name=ref_ticker,
                target_name=ticker,
                regime=regime,
            )

            if result.sample_size < 20:
                continue

            relationships.append({
                "asset": REFERENCE_ASSETS.get(ref_ticker, ref_ticker),
                "ticker": ref_ticker,
                "correlation": result.correlation_coefficient,
                "causality_score": result.causality_score,
                "causality_direction": result.causality_direction,
                "p_value": result.causality_p_value,
                "lag": result.time_lag_periods,
                "time_lag_seconds": result.time_lag_seconds,
                "impact_weight": result.impact_weight,
            })

            impact_scores.append(result.impact_weight)
            if result.causality_direction in ("source→target", "bidirectional"):
                time_lags.append(abs(result.time_lag_periods))

        # Influence score: weighted by impact magnitude
        score = float(np.mean(impact_scores)) * 100 if impact_scores else 0.0

        # Dominant source: highest impact_weight
        dominant_source = None
        if relationships:
            best = max(relationships, key=lambda r: r.get("impact_weight", 0))
            if best.get("impact_weight", 0) > 0:
                dominant_source = best["ticker"]

        avg_lag = float(np.mean(time_lags)) if time_lags else 0.0

        return RelationshipResult(
            ticker=ticker,
            score=round(score, 2),
            window=window,
            relationships=relationships,
            dominant_source=dominant_source,
            avg_time_lag_periods=avg_lag,
            regime=regime,
        )

    def analyze_from_db(
        self,
        ticker: str,
        as_of: date,
        session,
        regime: Optional[str] = None,
    ) -> Optional[RelationshipResult]:
        """Load pre-computed relationship data from the interdependency table.

        Queries `global_market_interdependencies` for all source→ticker
        pairs as of the given date. This is the fast path — sub-millisecond
        lookup using the composite index `idx_gmi_target_date`.

        Args:
            ticker: Target ticker.
            as_of: Decision date.
            session: SQLAlchemy session.
            regime: Optional regime filter.

        Returns:
            RelationshipResult or None if no DB data available.
        """
        try:
            if regime:
                rows = session.execute(
                    text("""
                        SELECT source_instrument_id, target_instrument_id,
                               correlation_coefficient, causality_score,
                               causality_p_value, causality_direction,
                               time_lag_seconds, time_lag_periods,
                               impact_weight, regime, var_order, sample_size
                        FROM global_market_interdependencies
                        WHERE target_instrument_id = :ticker
                          AND as_of_date = (
                              SELECT MAX(as_of_date)
                              FROM global_market_interdependencies
                              WHERE target_instrument_id = :ticker
                          )
                          AND regime = :regime
                        ORDER BY impact_weight DESC
                    """),
                    {"ticker": ticker, "regime": regime},
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                        SELECT source_instrument_id, target_instrument_id,
                               correlation_coefficient, causality_score,
                               causality_p_value, causality_direction,
                               time_lag_seconds, time_lag_periods,
                               impact_weight, regime, var_order, sample_size
                        FROM global_market_interdependencies
                        WHERE target_instrument_id = :ticker
                          AND as_of_date = (
                              SELECT MAX(as_of_date)
                              FROM global_market_interdependencies
                              WHERE target_instrument_id = :ticker
                          )
                        ORDER BY impact_weight DESC
                    """),
                    {"ticker": ticker},
                ).fetchall()

            if not rows:
                return None

            relationships: list[dict[str, object]] = []
            impact_scores: list[float] = []
            time_lags: list[int] = []
            dominant_source = None
            best_regime = "unknown"

            for row in rows:
                src_id = row[0]
                corr = float(row[2]) if row[2] is not None else 0.0
                caus_score = float(row[3]) if row[3] is not None else 0.0
                p_val = float(row[4]) if row[4] is not None else 1.0
                direction = row[5] or "none"
                lag_sec = int(row[6]) if row[6] is not None else 0
                lag_periods = int(row[7]) if row[7] is not None else 0
                impact = float(row[8]) if row[8] is not None else 0.0
                best_regime = row[9] or "unknown"

                relationships.append({
                    "asset": REFERENCE_ASSETS.get(src_id, src_id),
                    "ticker": src_id,
                    "correlation": corr,
                    "causality_score": caus_score,
                    "causality_direction": direction,
                    "p_value": p_val,
                    "lag": lag_periods,
                    "time_lag_seconds": lag_sec,
                    "impact_weight": impact,
                })
                impact_scores.append(impact)
                if direction in ("source→target", "bidirectional"):
                    time_lags.append(abs(lag_periods))

            score = float(np.mean(impact_scores)) * 100 if impact_scores else 0.0
            if relationships:
                dominant_source = relationships[0]["ticker"]

            avg_lag = float(np.mean(time_lags)) if time_lags else 0.0

            return RelationshipResult(
                ticker=ticker,
                score=round(score, 2),
                window=60,
                relationships=relationships,
                dominant_source=dominant_source,
                avg_time_lag_periods=avg_lag,
                regime=best_regime,
            )

        except Exception as e:
            logger.debug("DB relationship lookup failed for %s: %s", ticker, e)
            return None
