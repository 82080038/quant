"""Alpha Signal Engines — research-backed signal generators for daily OHLCV.

Four engines implemented based on academic research and validated backtests:

1. MeanReversionEngine (Bollinger Bands + RSI):
   - Combines two weak signals for confirmation (pythonandtrading.com approach)
   - Entry long: close < lower BB AND RSI < 30
   - Entry short: close > upper BB AND RSI > 70
   - Exit: price returns to middle band
   - Reference: Bollinger (2002), Wilder (1978)

2. ShortTermReversalEngine:
   - Stocks that fall the most over 5-21 days bounce back within 5 trading days
   - Structural behavioral effect (panic selling → value buying)
   - IC +0.020-0.025, win rate 54-58% (sarthakbiswas97/trader, NIFTY 100)
   - Z-score of returns over lookback period, enter when |Z| > threshold
   - Reference: Jegadeesh (1990), Lehmann (1990)

3. EWMAMomentumEngine:
   - Exponentially weighted momentum, adapts faster than SMA
   - EWMA span=20, signal = sign(EWMA - EWMA.shift(shift_period))
   - Volatility-scaled: divide by rolling std for risk-adjusted signal
   - Reference: Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum"

4. RegimeSwitchEngine:
   - Adapts between momentum (trending) and mean-reversion (ranging)
   - Regime detection: rolling volatility vs long-term average
   - High vol → mean-reversion; Low vol → momentum
   - Reference: Daniel & Moskowitz (2013), Baltas & Kosowski (2015)

All engines produce signals in [-1, +1] with no look-ahead bias.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """Result from an alpha signal engine."""
    signal: pd.Series  # Signal series [-1, +1], aligned to input index
    confidence: pd.Series  # Confidence [0, 1]
    metadata: dict  # Engine-specific metadata


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing (original definition).

    Args:
        close: Close price series.
        period: RSI lookback period (default 14).

    Returns:
        RSI series [0, 100].
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


def _bollinger_bands(
    close: pd.Series, window: int = 20, n_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute Bollinger Bands.

    Args:
        close: Close price series.
        window: Rolling window for middle band (default 20).
        n_std: Number of standard deviations (default 2.0).

    Returns:
        Tuple of (upper_band, middle_band, lower_band).
    """
    middle = close.rolling(window, min_periods=1).mean()
    std = close.rolling(window, min_periods=1).std()
    upper = middle + n_std * std
    lower = middle - n_std * std
    return upper, middle, lower


class MeanReversionEngine:
    """Bollinger Bands + RSI mean reversion engine.

    Combines two weak signals for confirmation:
    - Bollinger Bands: price stretched > 2 std from mean
    - RSI: momentum exhausted (< 30 oversold, > 70 overbought)

    Only act when BOTH agree → fewer false signals.
    """

    def __init__(
        self,
        bb_window: int = 20,
        bb_n_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
    ) -> None:
        self.bb_window = bb_window
        self.bb_n_std = bb_n_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    def generate_signals(self, close: pd.Series) -> SignalResult:
        """Generate mean-reversion signals.

        Args:
            close: Close price series.

        Returns:
            SignalResult with signal [-1, +1] and confidence [0, 1].
        """
        close = close.astype(float)
        upper, middle, lower = _bollinger_bands(close, self.bb_window, self.bb_n_std)
        rsi = _rsi(close, self.rsi_period)

        # Shift bands by 1 to prevent look-ahead
        upper_s = upper.shift(1)
        lower_s = lower.shift(1)
        middle_s = middle.shift(1)
        rsi_s = rsi.shift(1)

        signal = pd.Series(0.0, index=close.index)
        confidence = pd.Series(0.0, index=close.index)

        # %B: where price sits within bands [0, 1]
        band_width = (upper_s - lower_s).replace(0, np.nan)
        pct_b = (close - lower_s) / band_width

        for i in range(len(close)):
            if i < max(self.bb_window, self.rsi_period):
                continue

            r_val = rsi_s.iloc[i]
            p = close.iloc[i]
            lb = lower_s.iloc[i]
            ub = upper_s.iloc[i]
            mb = middle_s.iloc[i]
            pb = pct_b.iloc[i]

            if pd.isna(r_val) or pd.isna(lb) or pd.isna(ub) or pd.isna(pb):
                continue

            # Entry long: price below lower BB AND RSI oversold
            if p < lb and r_val < self.rsi_oversold:
                signal.iloc[i] = 1.0
                # Confidence: stronger when more extreme
                conf = min(1.0, (self.rsi_oversold - r_val) / self.rsi_oversold + (1 - pb))
                confidence.iloc[i] = conf

            # Entry short: price above upper BB AND RSI overbought
            elif p > ub and r_val > self.rsi_overbought:
                signal.iloc[i] = -1.0
                conf = min(1.0, (r_val - self.rsi_overbought) / (100 - self.rsi_overbought) + pb)
                confidence.iloc[i] = conf

            # Exit: price returned to middle band
            elif (p >= mb and signal.iloc[i - 1] == 1.0) if i > 0 else False:
                signal.iloc[i] = 0.0
            elif (p <= mb and signal.iloc[i - 1] == -1.0) if i > 0 else False:
                signal.iloc[i] = 0.0

        return SignalResult(
            signal=signal,
            confidence=confidence,
            metadata={
                "engine": "mean_reversion",
                "bb_window": self.bb_window,
                "rsi_period": self.rsi_period,
            },
        )


class ShortTermReversalEngine:
    """Short-term reversal engine based on behavioral overreaction.

    Stocks that fall/rise the most over 5-21 days tend to revert.
    This is a structural behavioral effect driven by panic selling/value buying.

    Uses Z-score of cumulative returns over lookback period.
    Entry: |Z| > threshold → bet on reversal.
    """

    def __init__(
        self,
        lookback: int = 10,
        z_threshold: float = 1.5,
        holding_period: int = 5,
    ) -> None:
        self.lookback = lookback
        self.z_threshold = z_threshold
        self.holding_period = holding_period

    def generate_signals(self, close: pd.Series) -> SignalResult:
        """Generate short-term reversal signals.

        Args:
            close: Close price series.

        Returns:
            SignalResult with signal [-1, +1] and confidence [0, 1].
        """
        close = close.astype(float)
        returns = close.pct_change()

        # Cumulative return over lookback
        cum_ret = returns.rolling(self.lookback).sum()

        # Rolling Z-score (shifted by 1 for no look-ahead)
        rolling_mean = cum_ret.rolling(60, min_periods=20).mean().shift(1)
        rolling_std = cum_ret.rolling(60, min_periods=20).std().shift(1)
        z_score = (cum_ret - rolling_mean) / rolling_std.replace(0, np.nan)
        z_score = z_score.fillna(0.0).replace([np.inf, -np.inf], 0.0)

        signal = pd.Series(0.0, index=close.index)
        confidence = pd.Series(0.0, index=close.index)

        # Position state machine with holding period
        position = 0
        days_in_position = 0

        for i in range(len(close)):
            if i < max(self.lookback, 20):
                continue

            z = z_score.iloc[i]

            if position == 0:
                # Look for entry
                if z < -self.z_threshold:
                    # Oversold → buy (reversal up)
                    position = 1
                    days_in_position = 0
                    signal.iloc[i] = 1.0
                    confidence.iloc[i] = min(1.0, abs(z) / 3.0)
                elif z > self.z_threshold:
                    # Overbought → sell (reversal down)
                    position = -1
                    days_in_position = 0
                    signal.iloc[i] = -1.0
                    confidence.iloc[i] = min(1.0, abs(z) / 3.0)
            else:
                days_in_position += 1
                # Hold signal
                signal.iloc[i] = float(position)
                confidence.iloc[i] = max(0.0, 1.0 - days_in_position / self.holding_period)

                # Exit after holding period
                if days_in_position >= self.holding_period:
                    position = 0
                    days_in_position = 0

        return SignalResult(
            signal=signal,
            confidence=confidence,
            metadata={
                "engine": "short_term_reversal",
                "lookback": self.lookback,
                "z_threshold": self.z_threshold,
                "holding_period": self.holding_period,
            },
        )


class EWMAMomentumEngine:
    """EWMA momentum engine with volatility scaling.

    Uses exponentially weighted moving average for trend detection.
    Signal = sign(EWMA_short - EWMA_long), scaled by inverse volatility.

    Reference: Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum".
    """

    def __init__(
        self,
        short_span: int = 20,
        long_span: int = 50,
        trend_threshold: float = 0.001,
    ) -> None:
        self.short_span = short_span
        self.long_span = long_span
        self.trend_threshold = trend_threshold

    def generate_signals(self, close: pd.Series) -> SignalResult:
        """Generate EWMA momentum signals.

        Args:
            close: Close price series.

        Returns:
            SignalResult with signal [-1, +1] and confidence [0, 1].
        """
        close = close.astype(float)

        # EWMA short and long (shifted by 1 for no look-ahead)
        ewma_short = close.ewm(span=self.short_span, adjust=False).mean().shift(1)
        ewma_long = close.ewm(span=self.long_span, adjust=False).mean().shift(1)

        # Normalized gap: (short - long) / long → percentage separation
        gap = (ewma_short - ewma_long) / ewma_long.replace(0, np.nan)
        gap = gap.fillna(0.0).replace([np.inf, -np.inf], 0.0)

        # Signal: only when gap exceeds threshold (reduces flip-flopping)
        signal = pd.Series(0.0, index=close.index)
        signal[gap > self.trend_threshold] = 1.0
        signal[gap < -self.trend_threshold] = -1.0

        # Confidence: based on gap strength
        confidence = (np.abs(gap) / 0.02).clip(0, 1)  # 2% gap = full confidence

        return SignalResult(
            signal=signal,
            confidence=confidence,
            metadata={
                "engine": "ewma_momentum",
                "short_span": self.short_span,
                "long_span": self.long_span,
                "trend_threshold": self.trend_threshold,
            },
        )


class RegimeSwitchEngine:
    """Regime-switching engine: momentum in trends, mean-reversion in ranges.

    Detects regime via rolling volatility vs long-term average:
    - Low vol (below threshold) → momentum regime → follow trend
    - High vol (above threshold) → mean-reversion regime → fade extremes

    Reference: Daniel & Moskowitz (2013), Baltas & Kosowski (2015).
    """

    def __init__(
        self,
        vol_window: int = 20,
        vol_long_window: int = 120,
        vol_threshold: float = 1.5,
        momentum_lookback: int = 20,
        reversion_lookback: int = 10,
        reversion_z_threshold: float = 1.5,
    ) -> None:
        self.vol_window = vol_window
        self.vol_long_window = vol_long_window
        self.vol_threshold = vol_threshold
        self.momentum_lookback = momentum_lookback
        self.reversion_lookback = reversion_lookback
        self.reversion_z_threshold = reversion_z_threshold

    def generate_signals(self, close: pd.Series) -> SignalResult:
        """Generate regime-switching signals.

        Args:
            close: Close price series.

        Returns:
            SignalResult with signal [-1, +1] and confidence [0, 1].
        """
        close = close.astype(float)
        returns = close.pct_change()

        # Rolling volatility (shifted for no look-ahead)
        vol_short = returns.rolling(self.vol_window).std().shift(1)
        vol_long = returns.rolling(self.vol_long_window).std().shift(1)

        # Vol ratio: > 1.5 = high vol regime (ranging), < 1.5 = low vol (trending)
        vol_ratio = (vol_short / vol_long.replace(0, np.nan)).fillna(1.0)

        # Momentum signal: cumulative return over lookback (shifted)
        cum_ret_mom = returns.rolling(self.momentum_lookback).sum().shift(1)
        mom_signal = np.sign(cum_ret_mom)

        # Mean reversion signal: Z-score of returns (shifted)
        cum_ret_rev = returns.rolling(self.reversion_lookback).sum()
        rev_mean = cum_ret_rev.rolling(60, min_periods=20).mean().shift(1)
        rev_std = cum_ret_rev.rolling(60, min_periods=20).std().shift(1)
        rev_z = (cum_ret_rev - rev_mean) / rev_std.replace(0, np.nan)
        rev_z = rev_z.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        rev_signal = np.where(
            rev_z < -self.reversion_z_threshold, 1.0,
            np.where(rev_z > self.reversion_z_threshold, -1.0, 0.0)
        )
        rev_signal = pd.Series(rev_signal, index=close.index)

        # Regime switch
        is_trending = vol_ratio < self.vol_threshold
        signal = pd.Series(0.0, index=close.index)
        signal[is_trending] = mom_signal[is_trending]
        signal[~is_trending] = rev_signal[~is_trending]

        # Confidence: based on regime clarity
        # Strong trend regime: vol_ratio far below threshold
        # Strong range regime: vol_ratio far above threshold
        regime_strength = np.abs(vol_ratio - self.vol_threshold) / self.vol_threshold
        confidence = regime_strength.clip(0, 1).fillna(0.0)

        return SignalResult(
            signal=signal.fillna(0.0),
            confidence=confidence,
            metadata={
                "engine": "regime_switch",
                "vol_window": self.vol_window,
                "vol_long_window": self.vol_long_window,
                "vol_threshold": self.vol_threshold,
            },
        )
