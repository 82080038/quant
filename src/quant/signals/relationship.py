"""Market Relationship Engine (pustaka/18 §4.1).

Computes correlation and lead-lag between a stock and 13 reference assets
(7 global indices + 5 macro proxies + IHSG benchmark).

Influence Score = average |correlation| * 100.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

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
    """Relationship analysis result."""

    ticker: str
    score: float
    window: int
    relationships: list[dict[str, object]] = field(default_factory=list)


class MarketRelationshipEngine:
    """Market relationship engine computing correlation and lead-lag."""

    def analyze(
        self,
        ticker: str,
        target_returns: pd.Series,
        reference_returns: dict[str, pd.Series],
        window: int = 60,
        max_lag: int = 5,
    ) -> RelationshipResult:
        """Analyze relationships between ticker and reference assets.

        Args:
            ticker: Target stock ticker.
            target_returns: Daily returns series for the target stock.
            reference_returns: Dict mapping reference ticker to returns series.
            window: Rolling window for correlation (days).
            max_lag: Maximum lag to test (±max_lag days).

        Returns:
            RelationshipResult with influence score and per-asset relationships.
        """
        if target_returns.empty or not reference_returns:
            return RelationshipResult(
                ticker=ticker,
                score=0.0,
                window=window,
                relationships=[],
            )

        relationships: list[dict[str, object]] = []
        correlations: list[float] = []

        for ref_ticker, ref_returns in reference_returns.items():
            if ref_returns.empty:
                continue

            # Align series
            combined = pd.DataFrame(
                {"target": target_returns, "ref": ref_returns},
            ).dropna()

            if len(combined) < 20:
                continue

            # Rolling correlation (last value)
            rolling_corr = combined["target"].rolling(window).corr(combined["ref"])
            corr = float(rolling_corr.iloc[-1]) if not rolling_corr.empty else 0.0

            # Lag analysis: find lag with highest absolute correlation
            best_lag = 0
            best_corr = corr
            for lag in range(-max_lag, max_lag + 1):
                if lag == 0:
                    continue
                shifted = combined["ref"].shift(lag)
                lagged = pd.DataFrame(
                    {"target": combined["target"], "ref": shifted},
                ).dropna()
                if len(lagged) < 20:
                    continue
                lag_corr = float(
                    lagged["target"].rolling(window).corr(lagged["ref"]).iloc[-1]
                )
                if abs(lag_corr) > abs(best_corr):
                    best_corr = lag_corr
                    best_lag = lag

            correlations.append(abs(best_corr))
            relationships.append(
                {
                    "asset": REFERENCE_ASSETS.get(ref_ticker, ref_ticker),
                    "ticker": ref_ticker,
                    "correlation": round(best_corr, 4),
                    "lag": best_lag,
                },
            )

        # Influence score
        score = float(np.mean(correlations)) * 100 if correlations else 0.0

        return RelationshipResult(
            ticker=ticker,
            score=round(score, 2),
            window=window,
            relationships=relationships,
        )
