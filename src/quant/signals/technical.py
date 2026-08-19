"""Technical Analysis Engine (pustaka/18 §3.1).

Computes technical indicators (MA, RSI, MACD, ADX, ATR, Bollinger Bands,
Volume Profile) and produces a technical_score (0-100) with breakdown.

Scoring:
    Trend:       Uptrend=25, Sideways=12, Downtrend=0
    RSI:         (RSI - 30) * (25/40), clamped 0-25
    MACD:        MACD > Signal = 25, else 0
    Volatility:  max(0, 25 - vol*100)
    Volume:      min(25, vol_ratio * 12.5)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class TechnicalScore:
    """Technical analysis result."""

    ticker: str
    score: float
    trend: str
    breakdown: dict[str, float] = field(default_factory=dict)
    indicators: dict[str, float] = field(default_factory=dict)


class TechnicalAnalysisEngine:
    """Technical analysis engine computing indicators and score."""

    def analyze(self, ticker: str, df: pd.DataFrame) -> TechnicalScore:
        """Analyze OHLCV data and return a technical score.

        Args:
            ticker: Stock ticker.
            df: DataFrame with columns: open, high, low, close, volume.
                Index should be datetime.

        Returns:
            TechnicalScore with score, trend, breakdown, and indicators.
        """
        if df.empty or len(df) < 50:
            return TechnicalScore(
                ticker=ticker,
                score=0.0,
                trend="insufficient_data",
                breakdown={},
                indicators={},
            )

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        indicators: dict[str, float] = {}

        # Moving Averages
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        indicators["ma20"] = float(ma20)
        indicators["ma50"] = float(ma50)

        # Trend classification
        last_close = float(close.iloc[-1])
        if ma20 > ma50 and last_close > ma20:
            trend = "uptrend"
            trend_score = 25.0
        elif ma20 < ma50 and last_close < ma20:
            trend = "downtrend"
            trend_score = 0.0
        else:
            trend = "sideways"
            trend_score = 12.0

        # RSI (14)
        rsi = self._compute_rsi(close, period=14)
        indicators["rsi"] = rsi
        rsi_score = max(0.0, min(25.0, (rsi - 30) * (25 / 40)))

        # MACD (12, 26, 9)
        macd, signal, hist = self._compute_macd(close)
        indicators["macd"] = macd
        indicators["macd_signal"] = signal
        indicators["macd_hist"] = hist
        macd_score = 25.0 if macd > signal else 0.0

        # ATR (14) — volatility
        atr = self._compute_atr(high, low, close, period=14)
        indicators["atr"] = atr
        vol_annualized = (atr / last_close) * np.sqrt(252)
        indicators["volatility_annualized"] = float(vol_annualized)
        vol_score = max(0.0, 25.0 - float(vol_annualized) * 100)

        # Bollinger Bands (20, 2)
        bb_upper, bb_lower = self._compute_bollinger(close, period=20, std=2)
        indicators["bb_upper"] = bb_upper
        indicators["bb_lower"] = bb_lower

        # ADX (14)
        adx = self._compute_adx(high, low, close, period=14)
        indicators["adx"] = adx

        # Volume
        vol_sma20 = volume.rolling(20).mean().iloc[-1]
        vol_ratio = float(volume.iloc[-1] / vol_sma20) if vol_sma20 > 0 else 0.0
        indicators["vol_ratio"] = vol_ratio
        vol_ratio_score = min(25.0, vol_ratio * 12.5)

        # EMA (50) — used by ema_envelope strategy
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        indicators["ema50"] = float(ema50)

        # EMA Envelope (50, 3%) — used by ema_envelope strategy
        ema_series = close.ewm(span=50, adjust=False).mean()
        indicators["ema_env_upper"] = float(ema_series.iloc[-1] * 1.03)
        indicators["ema_env_lower"] = float(ema_series.iloc[-1] * 0.97)

        # Donchian Channel (20) — used by donchian strategy
        dc_period = 20
        dc_upper = high.rolling(dc_period).max().iloc[-1]
        dc_lower = low.rolling(dc_period).min().iloc[-1]
        indicators["donchian_upper"] = float(dc_upper)
        indicators["donchian_lower"] = float(dc_lower)
        indicators["donchian_mid"] = float((dc_upper + dc_lower) / 2)

        # Volume Profile (POC, VAH, VAL)
        poc, vah, val = self._compute_volume_profile(
            high, low, close, volume,
        )
        indicators["poc"] = poc
        indicators["vah"] = vah
        indicators["val"] = val

        total_score = (
            trend_score + rsi_score + macd_score + vol_score + vol_ratio_score
        )
        total_score = min(100.0, max(0.0, total_score))

        return TechnicalScore(
            ticker=ticker,
            score=round(total_score, 2),
            trend=trend,
            breakdown={
                "trend": round(trend_score, 2),
                "rsi": round(rsi_score, 2),
                "macd": round(macd_score, 2),
                "volatility": round(vol_score, 2),
                "volume": round(vol_ratio_score, 2),
            },
            indicators=indicators,
        )

    def _compute_rsi(self, close: pd.Series, period: int = 14) -> float:
        """Compute RSI."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])

    def _compute_macd(
        self, close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9,
    ) -> tuple[float, float, float]:
        """Compute MACD, signal line, and histogram."""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        hist = macd_line - signal_line
        return (
            float(macd_line.iloc[-1]),
            float(signal_line.iloc[-1]),
            float(hist.iloc[-1]),
        )

    def _compute_atr(
        self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
    ) -> float:
        """Compute ATR."""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
        return float(atr.iloc[-1])

    def _compute_bollinger(
        self, close: pd.Series, period: int = 20, std: int = 2,
    ) -> tuple[float, float]:
        """Compute Bollinger Bands upper and lower."""
        ma = close.rolling(period).mean()
        sd = close.rolling(period).std()
        upper = ma + std * sd
        lower = ma - std * sd
        return float(upper.iloc[-1]), float(lower.iloc[-1])

    def _compute_adx(
        self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
    ) -> float:
        """Compute ADX."""
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[plus_dm < minus_dm] = 0
        minus_dm[minus_dm < plus_dm] = 0

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
        adx = dx.ewm(alpha=1 / period, min_periods=period).mean()
        return float(adx.iloc[-1])

    def _compute_volume_profile(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        volume: pd.Series,
        n_bins: int = 20,
    ) -> tuple[float, float, float]:
        """Compute Volume Profile: POC, VAH, VAL.

        Returns:
            (POC, VAH, VAL) prices.
        """
        price_range = (low.min(), high.max())
        if price_range[1] <= price_range[0]:
            return float(close.iloc[-1]), float(close.iloc[-1]), float(close.iloc[-1])

        bins = np.linspace(price_range[0], price_range[1], n_bins + 1)
        midpoints = (bins[:-1] + bins[1:]) / 2

        vol_by_bin = np.zeros(n_bins)
        for i in range(len(close)):
            idx = np.searchsorted(bins, float(close.iloc[i])) - 1
            idx_val: int = max(0, min(n_bins - 1, int(idx)))
            vol_by_bin[idx_val] += float(volume.iloc[i])

        poc_idx = int(np.argmax(vol_by_bin))
        poc = float(midpoints[poc_idx])

        total_vol = vol_by_bin.sum()
        if total_vol == 0:
            return poc, poc, poc

        sorted_indices = np.argsort(vol_by_bin)[::-1]
        cumvol = 0
        value_area_indices: list[int] = []
        for idx in sorted_indices:
            cumvol += vol_by_bin[idx]
            value_area_indices.append(idx)
            if cumvol >= 0.7 * total_vol:
                break

        vah_idx = max(value_area_indices)
        val_idx = min(value_area_indices)
        vah = float(midpoints[vah_idx])
        val = float(midpoints[val_idx])

        return poc, vah, val
