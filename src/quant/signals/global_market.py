"""Global Market Engine — Cross-Asset Interdependency Aware.

Monitors major global indices and measures their impact on target tickers
using the pre-computed interdependency matrix from
`global_market_interdependencies`.

The engine now operates in two modes:
1. **Causality-weighted mode**: Reads impact weights from the DB
   interdependency matrix and produces a score weighted by the actual
   causal influence of each global index on the target ticker.
2. **Legacy MA-based mode**: Falls back to the original MA50/MA200
   scoring when DB interdependency data is unavailable.

Indices:
    ^GSPC  - S&P 500
    ^IXIC  - Nasdaq
    ^DJI   - Dow Jones
    ^HSI   - Hang Seng
    ^N225  - Nikkei 225
    ^FTSE  - FTSE 100
    ^GDAXI - DAX 40

Scoring (causality-weighted):
    For each index with a causal link to the target ticker:
        contribution = direction_signal * impact_weight * time_decay_factor
    Score = Σ(contributions) normalised to [0, 100]

Scoring (legacy fallback):
    Above MA50:  (count_above / total) * 50
    Above MA200: (count_above / total) * 50
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import text

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

GLOBAL_INDICES: dict[str, str] = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^DJI": "Dow Jones",
    "^HSI": "Hang Seng",
    "^N225": "Nikkei 225",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX 40",
}


@dataclass
class GlobalMarketScore:
    """Global market analysis result."""

    score: float
    above_ma50: list[str] = field(default_factory=list)
    below_ma50: list[str] = field(default_factory=list)
    above_ma200: list[str] = field(default_factory=list)
    below_ma200: list[str] = field(default_factory=list)
    breakdown: dict[str, float] = field(default_factory=dict)
    causal_sources: list[dict] = field(default_factory=list)
    dominant_source: Optional[str] = None
    avg_time_lag_periods: float = 0.0
    mode: str = "legacy"  # "causality" or "legacy"


class GlobalMarketEngine:
    """Global market engine monitoring major world indices.

    When `analyze_with_causality` is called, the engine reads the
    pre-computed interdependency matrix from the database to weight
    each global index by its actual causal impact on the target ticker.
    """

    def analyze(
        self,
        data: dict[str, pd.DataFrame],
    ) -> GlobalMarketScore:
        """Analyze global indices data (legacy MA-based mode).

        Args:
            data: Dict mapping ticker to OHLCV DataFrame with 'close' column.

        Returns:
            GlobalMarketScore with score and above/below lists.
        """
        if not data:
            return GlobalMarketScore(score=0.0)

        above_ma50: list[str] = []
        below_ma50: list[str] = []
        above_ma200: list[str] = []
        below_ma200: list[str] = []

        for ticker, df in data.items():
            if df.empty or "close" not in df.columns:
                continue

            close = df["close"].astype(float)
            last_close = float(close.iloc[-1])

            if len(close) >= 50:
                ma50 = float(close.rolling(50).mean().iloc[-1])
                if last_close > ma50:
                    above_ma50.append(ticker)
                else:
                    below_ma50.append(ticker)

            if len(close) >= 200:
                ma200 = float(close.rolling(200).mean().iloc[-1])
                if last_close > ma200:
                    above_ma200.append(ticker)
                else:
                    below_ma200.append(ticker)

        total_ma50 = len(above_ma50) + len(below_ma50)
        total_ma200 = len(above_ma200) + len(below_ma200)
        ma50_score = (len(above_ma50) / total_ma50) * 50 if total_ma50 > 0 else 0
        ma200_score = (len(above_ma200) / total_ma200) * 50 if total_ma200 > 0 else 0
        total_score = min(100.0, ma50_score + ma200_score)

        return GlobalMarketScore(
            score=round(total_score, 2),
            above_ma50=above_ma50,
            below_ma50=below_ma50,
            above_ma200=above_ma200,
            below_ma200=below_ma200,
            breakdown={
                "above_ma50": round(ma50_score, 2),
                "above_ma200": round(ma200_score, 2),
            },
            mode="legacy",
        )

    def analyze_with_causality(
        self,
        ticker: str,
        as_of: date,
        session,
        index_data: Optional[dict[str, pd.DataFrame]] = None,
        regime: Optional[str] = None,
    ) -> GlobalMarketScore:
        """Analyze global market with causality-weighted scoring.

        Reads the interdependency matrix from the DB to determine which
        global indices have statistically significant causal impact on
        the target ticker, then weights the MA-based score by impact_weight.

        Args:
            ticker: Target stock ticker.
            as_of: Decision date.
            session: SQLAlchemy session.
            index_data: Optional dict of OHLCV DataFrames for global indices.
            regime: Optional market regime filter.

        Returns:
            GlobalMarketScore with causality-weighted score and source list.
        """
        # Step 1: Load causal sources from DB
        causal_sources = self._load_causal_sources(ticker, as_of, session, regime)

        if not causal_sources:
            # Fallback to legacy mode
            if index_data:
                return self.analyze(index_data)
            return GlobalMarketScore(score=0.0, mode="legacy")

        # Step 2: Compute MA signals for each index (if data provided)
        ma_signals: dict[str, float] = {}
        if index_data:
            for idx_ticker, df in index_data.items():
                if df.empty or "close" not in df.columns:
                    continue
                close = df["close"].astype(float)
                signal = 0.0
                if len(close) >= 50:
                    ma50 = float(close.rolling(50).mean().iloc[-1])
                    last = float(close.iloc[-1])
                    signal += 0.5 if last > ma50 else -0.5
                if len(close) >= 200:
                    ma200 = float(close.rolling(200).mean().iloc[-1])
                    last = float(close.iloc[-1])
                    signal += 0.5 if last > ma200 else -0.5
                ma_signals[idx_ticker] = signal

        # Step 3: Compute causality-weighted score
        total_score = 0.0
        total_weight = 0.0
        time_lags: list[int] = []
        breakdown: dict[str, float] = {}
        dominant_source = None
        best_weight = 0.0

        for src in causal_sources:
            src_id = src["source_instrument_id"]
            impact = src["impact_weight"]
            direction = src["causality_direction"]
            lag_periods = src["time_lag_periods"]

            # MA signal for this source (if available)
            ma_sig = ma_signals.get(src_id, 0.0)

            # Causality-weighted contribution
            # If no MA data, use impact_weight alone as a positive signal
            if ma_sig != 0.0:
                contribution = ma_sig * impact * 50  # scale to 0-100
            else:
                contribution = impact * 50  # impact-only contribution

            total_score += contribution
            total_weight += impact

            if direction in ("source→target", "bidirectional"):
                time_lags.append(abs(lag_periods))

            breakdown[src_id] = round(contribution, 2)

            if impact > best_weight:
                best_weight = impact
                dominant_source = src_id

        # Normalise score to [0, 100]
        if total_weight > 0:
            normalised = (total_score / total_weight + 50)  # shift from [-50,50] to [0,100]
        else:
            normalised = 50.0
        normalised = max(0.0, min(100.0, normalised))

        avg_lag = float(sum(time_lags) / len(time_lags)) if time_lags else 0.0

        return GlobalMarketScore(
            score=round(normalised, 2),
            breakdown=breakdown,
            causal_sources=causal_sources,
            dominant_source=dominant_source,
            avg_time_lag_periods=avg_lag,
            mode="causality",
        )

    def _load_causal_sources(
        self,
        ticker: str,
        as_of: date,
        session,
        regime: Optional[str] = None,
    ) -> list[dict]:
        """Load causal source instruments from the interdependency table.

        Returns a list of dicts sorted by impact_weight (descending).
        """
        try:
            if regime:
                rows = session.execute(
                    text("""
                        SELECT source_instrument_id, correlation_coefficient,
                               causality_score, causality_direction,
                               time_lag_seconds, time_lag_periods,
                               impact_weight, regime
                        FROM global_market_interdependencies
                        WHERE target_instrument_id = :ticker
                          AND as_of_date = (
                              SELECT MAX(as_of_date)
                              FROM global_market_interdependencies
                              WHERE target_instrument_id = :ticker
                          )
                          AND regime = :regime
                          AND impact_weight > 0
                        ORDER BY impact_weight DESC
                    """),
                    {"ticker": ticker, "regime": regime},
                ).fetchall()
            else:
                rows = session.execute(
                    text("""
                        SELECT source_instrument_id, correlation_coefficient,
                               causality_score, causality_direction,
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
                    "correlation_coefficient": float(r[1]) if r[1] else 0.0,
                    "causality_score": float(r[2]) if r[2] else 0.0,
                    "causality_direction": r[3] or "none",
                    "time_lag_seconds": int(r[4]) if r[4] else 0,
                    "time_lag_periods": int(r[5]) if r[5] else 0,
                    "impact_weight": float(r[6]) if r[6] else 0.0,
                    "regime": r[7] or "unknown",
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug("Failed to load causal sources for %s: %s", ticker, e)
            return []
