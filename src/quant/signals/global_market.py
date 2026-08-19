"""Global Market Engine (pustaka/18 §3.4).

Monitors 7 major global indices and measures their impact.

Indices:
    ^GSPC  - S&P 500
    ^IXIC  - Nasdaq
    ^DJI   - Dow Jones
    ^HSI   - Hang Seng
    ^N225  - Nikkei 225
    ^FTSE  - FTSE 100
    ^GDAXI - DAX 40

Scoring:
    Above MA50:  (count_above / total) * 50
    Above MA200: (count_above / total) * 50
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

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


class GlobalMarketEngine:
    """Global market engine monitoring major world indices."""

    def analyze(
        self,
        data: dict[str, pd.DataFrame],
    ) -> GlobalMarketScore:
        """Analyze global indices data.

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
        )
