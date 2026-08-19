"""Volume-Based Feature Engineering (pustaka/05 §6, pustaka/89 §4.4).

Computes volume-weighted trading signals for Indonesian stocks (IDX).
All functions are CPU-only (pandas/numpy) and strictly non-look-ahead:
features at time T use only data available at or before T.

Components:
    1. VWAP — rolling and session, with deviation signal.
    2. Volume Profile — price-level volume distribution, POC, Value Area.
    3. Order Flow Imbalance (OFI) Proxy — daily buy/sell pressure estimate.
    4. OBV Divergence Detection — bullish/bearish divergence vs price.
    5. Volume-Weighted Momentum — volume-weighted return momentum.
    6. Foreign Flow Momentum — signal from foreign net buy/sell flow.

References:
    - pustaka/05-analisis-teknikal.md §6 (Volume Indicators)
    - pustaka/89-faktor-pasar-modal-analisis-implementasi.md §4.4 (Volume Profile/VWAP gap)
    - Kolm et al., "Order Flow Imbalance and Alpha", Mathematical Finance 2023.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ── 1. VWAP (Volume-Weighted Average Price) ────────────────────────────────


@dataclass
class VWAPResult:
    """VWAP computation result.

    Attributes:
        vwap: Rolling VWAP series.
        deviation: (close - vwap) / vwap — positive = price above VWAP (bullish).
        typical_price: (high + low + close) / 3.
    """

    vwap: pd.Series
    deviation: pd.Series
    typical_price: pd.Series


def compute_vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> VWAPResult:
    """Compute rolling VWAP and deviation signal.

    Uses typical price = (high + low + close) / 3 as the price input,
    consistent with institutional VWAP convention (pustaka/05 §6.2).

    The deviation signal is shifted by 1 to prevent look-ahead bias:
    the signal at time T uses VWAP computed from data up to T-1.

    Args:
        high: High price series.
        low: Low price series.
        close: Close price series.
        volume: Volume series.
        window: Rolling window size (default 20 bars).

    Returns:
        VWAPResult with vwap, deviation, and typical_price series.
    """
    typical_price = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    vol = volume.astype(float)

    vol_price = typical_price * vol
    vol_sum = vol.rolling(window, min_periods=1).sum()
    vp_sum = vol_price.rolling(window, min_periods=1).sum()

    vwap = vp_sum / vol_sum.replace(0, np.nan)

    # Deviation: shift VWAP by 1 so signal at T uses data up to T-1 (no look-ahead).
    vwap_shifted = vwap.shift(1)
    deviation = (close.astype(float) - vwap_shifted) / vwap_shifted.replace(0, np.nan)
    deviation = deviation.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    return VWAPResult(
        vwap=vwap,
        deviation=deviation,
        typical_price=typical_price,
    )


# ── 2. Volume Profile ──────────────────────────────────────────────────────


@dataclass
class VolumeProfile:
    """Volume profile computation result for a rolling window.

    Attributes:
        poc: Point of Control — price level with highest volume.
        vah: Value Area High — upper bound of 70% volume region.
        val: Value Area Low — lower bound of 70% volume region.
        price_levels: Array of price bin midpoints.
        volume_by_level: Array of volume per price bin.
        poc_index: Index of POC in price_levels.
    """

    poc: float
    vah: float
    val: float
    price_levels: np.ndarray
    volume_by_level: np.ndarray
    poc_index: int


def compute_volume_profile(
    close: pd.Series,
    volume: pd.Series,
    bins: int = 50,
    window: int = 60,
) -> pd.Series:
    """Compute rolling volume profile (POC, VAH, VAL) over a window.

    For each time T, the volume profile is computed using only data in
    the window [T-window+1, T]. The result at T is then shifted by 1
    so that signals at T use volume profile from data up to T-1
    (no look-ahead bias).

    Args:
        close: Close price series.
        volume: Volume series.
        bins: Number of price bins for the histogram (default 50).
        window: Rolling window size in bars (default 60).

    Returns:
        pd.Series of VolumeProfile objects (one per bar), with NaN for
        insufficient data periods.
    """
    close = close.astype(float)
    volume = volume.astype(float)
    n = len(close)

    results: list[VolumeProfile | float] = [np.nan] * n

    values = close.values
    vol_values = volume.values

    for i in range(n):
        start = max(0, i - window + 1)
        if i - start + 1 < 2:
            continue

        window_close = values[start : i + 1]
        window_vol = vol_values[start : i + 1]

        price_min = float(np.nanmin(window_close))
        price_max = float(np.nanmax(window_close))
        if price_max <= price_min:
            poc_val = float(window_close[-1])
            results[i] = VolumeProfile(
                poc=poc_val,
                vah=poc_val,
                val=poc_val,
                price_levels=np.array([poc_val]),
                volume_by_level=np.array([float(window_vol.sum())]),
                poc_index=0,
            )
            continue

        edges = np.linspace(price_min, price_max, bins + 1)
        midpoints = (edges[:-1] + edges[1:]) / 2.0

        vol_by_bin = np.zeros(bins)
        for j in range(len(window_close)):
            idx = int(np.searchsorted(edges, window_close[j]) - 1)
            idx = max(0, min(bins - 1, idx))
            vol_by_bin[idx] += window_vol[j]

        poc_idx = int(np.argmax(vol_by_bin))
        poc = float(midpoints[poc_idx])

        total_vol = vol_by_bin.sum()
        if total_vol == 0:
            results[i] = VolumeProfile(
                poc=poc,
                vah=poc,
                val=poc,
                price_levels=midpoints,
                volume_by_level=vol_by_bin,
                poc_index=poc_idx,
            )
            continue

        # Value Area: expand from POC outward until 70% of volume is captured.
        sorted_indices = np.argsort(vol_by_bin)[::-1]
        cumvol = 0.0
        value_area_indices: list[int] = []
        for idx in sorted_indices:
            cumvol += vol_by_bin[idx]
            value_area_indices.append(int(idx))
            if cumvol >= 0.7 * total_vol:
                break

        vah_idx = max(value_area_indices)
        val_idx = min(value_area_indices)
        vah = float(midpoints[vah_idx])
        val = float(midpoints[val_idx])

        results[i] = VolumeProfile(
            poc=poc,
            vah=vah,
            val=val,
            price_levels=midpoints,
            volume_by_level=vol_by_bin,
            poc_index=poc_idx,
        )

    series = pd.Series(results, index=close.index, dtype=object)

    # Shift by 1 to prevent look-ahead: signal at T uses profile up to T-1.
    return series.shift(1)


# ── 3. Order Flow Imbalance (OFI) Proxy ────────────────────────────────────


@dataclass
class OFIResult:
    """Order Flow Imbalance proxy result.

    Attributes:
        ofi: Instantaneous OFI per bar, range [-1, 1].
        ofi_5: 5-bar rolling mean OFI.
        ofi_10: 10-bar rolling mean OFI.
        buy_volume: Estimated buy volume per bar.
        sell_volume: Estimated sell volume per bar.
    """

    ofi: pd.Series
    ofi_5: pd.Series
    ofi_10: pd.Series
    buy_volume: pd.Series
    sell_volume: pd.Series


def compute_ofi_proxy(
    close: pd.Series,
    volume: pd.Series,
    high: pd.Series,
    low: pd.Series,
) -> OFIResult:
    """Compute Order Flow Imbalance (OFI) proxy from daily OHLCV.

    IDX has no tick-level data, so we use a daily proxy based on the
    close position within the day's range (similar to Accumulation/Distribution
    multiplier, pustaka/05 §6.4). When close is near the high, most volume
    is assumed buyer-initiated; when near the low, seller-initiated.

    Proxy formula:
        buy_volume = volume * ((close - low) / (high - low + epsilon))
        sell_volume = volume - buy_volume
        OFI = (buy_volume - sell_volume) / total_volume  → range [-1, 1]

    Rolling OFI (5-day, 10-day) is shifted by 1 for no look-ahead.

    Args:
        close: Close price series.
        volume: Volume series.
        high: High price series.
        low: Low price series.

    Returns:
        OFIResult with instantaneous and rolling OFI series.
    """
    close = close.astype(float)
    volume = volume.astype(float)
    high = high.astype(float)
    low = low.astype(float)

    hl_range = high - low + 1e-10
    buy_ratio = ((close - low) / hl_range).clip(0.0, 1.0)
    buy_volume = volume * buy_ratio
    sell_volume = volume - buy_volume

    ofi = (buy_volume - sell_volume) / volume.replace(0, np.nan)
    ofi = ofi.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    # Rolling OFI shifted by 1 for no look-ahead in signal usage.
    ofi_5 = ofi.rolling(5, min_periods=1).mean().shift(1).fillna(0.0)
    ofi_10 = ofi.rolling(10, min_periods=1).mean().shift(1).fillna(0.0)

    return OFIResult(
        ofi=ofi,
        ofi_5=ofi_5,
        ofi_10=ofi_10,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
    )


# ── 4. OBV Divergence Detection ────────────────────────────────────────────


@dataclass
class DivergenceResult:
    """OBV divergence detection result.

    Attributes:
        divergence_type: "bullish", "bearish", or "none".
        strength: Divergence strength in [0, 1]. Higher = stronger divergence.
        price_low: Price low at the divergence point (bullish) or NaN.
        price_high: Price high at the divergence point (bearish) or NaN.
        obv_at_divergence: OBV value at the divergence point.
    """

    divergence_type: str
    strength: float
    price_low: float = field(default=float("nan"))
    price_high: float = field(default=float("nan"))
    obv_at_divergence: float = field(default=float("nan"))


def detect_obv_divergence(
    close: pd.Series,
    obv: pd.Series,
    window: int = 20,
) -> DivergenceResult:
    """Detect bullish or bearish OBV divergence vs price.

    Bullish divergence: price makes a lower low while OBV makes a higher low
    → accumulation (smart money buying despite price decline).

    Bearish divergence: price makes a higher high while OBV makes a lower high
    → distribution (smart money selling despite price advance).

    Uses only data in the window [T-window, T] where T is the last bar.
    The detection itself is causal (uses only past data), so no additional
    shift is needed.

    Args:
        close: Close price series.
        obv: OBV series (e.g. from market_factors.compute_obv).
        window: Lookback window for detecting swings (default 20).

    Returns:
        DivergenceResult with type, strength, and key levels.
    """
    if len(close) < window or len(obv) < window:
        return DivergenceResult(divergence_type="none", strength=0.0)

    close = close.astype(float)
    obv = obv.astype(float)

    # Use the last `window` bars to find recent swing highs/lows.
    recent_close = close.iloc[-window:]
    recent_obv = obv.iloc[-window:]

    # Split into two halves to compare swings.
    mid = len(recent_close) // 2
    if mid < 1:
        return DivergenceResult(divergence_type="none", strength=0.0)

    first_half_close = recent_close.iloc[:mid]
    second_half_close = recent_close.iloc[mid:]

    price_low_1 = float(first_half_close.min())
    price_low_2 = float(second_half_close.min())
    price_high_1 = float(first_half_close.max())
    price_high_2 = float(second_half_close.max())

    obv_at_low_1 = float(recent_obv.iloc[first_half_close.values.argmin()])
    obv_at_low_2 = float(recent_obv.iloc[
        mid + second_half_close.values.argmin()
    ])
    obv_at_high_1 = float(recent_obv.iloc[first_half_close.values.argmax()])
    obv_at_high_2 = float(recent_obv.iloc[
        mid + second_half_close.values.argmax()
    ])

    # Bullish divergence: price lower low, OBV higher low.
    if price_low_2 < price_low_1 and obv_at_low_2 > obv_at_low_1:
        price_drop = abs(price_low_1 - price_low_2) / (abs(price_low_1) + 1e-10)
        obv_rise = abs(obv_at_low_2 - obv_at_low_1) / (abs(obv_at_low_1) + 1e-10)
        strength = float(min(1.0, (price_drop + obv_rise) / 2.0))
        return DivergenceResult(
            divergence_type="bullish",
            strength=strength,
            price_low=price_low_2,
            obv_at_divergence=obv_at_low_2,
        )

    # Bearish divergence: price higher high, OBV lower high.
    if price_high_2 > price_high_1 and obv_at_high_2 < obv_at_high_1:
        price_rise = abs(price_high_2 - price_high_1) / (abs(price_high_1) + 1e-10)
        obv_drop = abs(obv_at_high_1 - obv_at_high_2) / (abs(obv_at_high_1) + 1e-10)
        strength = float(min(1.0, (price_rise + obv_drop) / 2.0))
        return DivergenceResult(
            divergence_type="bearish",
            strength=strength,
            price_high=price_high_2,
            obv_at_divergence=obv_at_high_2,
        )

    return DivergenceResult(divergence_type="none", strength=0.0)


# ── 5. Volume-Weighted Momentum ─────────────────────────────────────────────


def compute_vw_momentum(
    close: pd.Series,
    volume: pd.Series,
    period: int = 10,
) -> pd.Series:
    """Compute volume-weighted momentum.

    High-volume moves get more weight than low-volume moves. The momentum
    at time T is the sum of (return_t * volume_t / volume_avg) over the
    lookback period. Volume average is computed over a 20-bar window
    shifted by 1 to prevent look-ahead.

    Formula:
        vw_momentum = sum(return_i * volume_i / volume_avg_i) for i in [T-period+1, T]

    Args:
        close: Close price series.
        volume: Volume series.
        period: Lookback period (default 10).

    Returns:
        pd.Series of volume-weighted momentum values.
    """
    close = close.astype(float)
    volume = volume.astype(float)

    returns = close.pct_change()
    # Volume average shifted by 1 to avoid using current bar in the average.
    vol_avg = volume.rolling(20, min_periods=1).mean().shift(1)
    vol_ratio = volume / vol_avg.replace(0, np.nan)
    vol_ratio = vol_ratio.fillna(0.0).replace([np.inf, -np.inf], 0.0)

    weighted_returns = returns * vol_ratio
    momentum = weighted_returns.rolling(period, min_periods=1).sum()

    return momentum.fillna(0.0)


# ── 6. Foreign Flow Momentum ────────────────────────────────────────────────


@dataclass
class ForeignFlowResult:
    """Foreign flow momentum signal result.

    Attributes:
        cumulative_5d: 5-day cumulative foreign net flow.
        z_score: Z-score of foreign flow over a 60-bar window.
        signal: Trading signal: "bullish" (net inflow), "contrarian_buy"
            (extreme outflow), or "neutral".
    """

    cumulative_5d: float
    z_score: float
    signal: str


def compute_foreign_flow_signal(
    foreign_flow_series: pd.Series,
    window: int = 5,
) -> ForeignFlowResult:
    """Compute foreign flow momentum signal from net buy/sell series.

    This is a pure function — it takes a pre-loaded Series of foreign net
    flow per day (e.g. from the `foreign_flow` DB table) and does NOT
    access the database directly.

    Signal logic:
        - 5-day cumulative net flow > 0 → "bullish" (foreign inflow).
        - Z-score of flow < -2.0 → "contrarian_buy" (extreme outflow,
          potential reversal per contrarian strategy).
        - Otherwise → "neutral".

    The z-score is computed over a 60-bar rolling window shifted by 1
    to prevent look-ahead bias.

    Args:
        foreign_flow_series: Series of foreign net flow per day (positive =
            net buy, negative = net sell).
        window: Cumulative window size (default 5).

    Returns:
        ForeignFlowResult with cumulative flow, z-score, and signal.
    """
    flow = foreign_flow_series.astype(float)

    if len(flow) == 0:
        return ForeignFlowResult(
            cumulative_5d=0.0,
            z_score=0.0,
            signal="neutral",
        )

    # Cumulative flow over the last `window` bars.
    cumulative = float(flow.iloc[-window:].sum()) if len(flow) >= window else float(flow.sum())

    # Z-score over 60-bar window, shifted by 1 for no look-ahead.
    z_window = 60
    if len(flow) >= z_window:
        rolling_mean = flow.rolling(z_window, min_periods=1).mean().shift(1)
        rolling_std = flow.rolling(z_window, min_periods=1).std().shift(1)
        last_mean = float(rolling_mean.iloc[-1])
        last_std = float(rolling_std.iloc[-1])
    else:
        last_mean = float(flow.mean())
        last_std = float(flow.std())

    if last_std == 0 or not np.isfinite(last_std):
        z_score = 0.0
    else:
        z_score = float((flow.iloc[-1] - last_mean) / last_std)
        if not np.isfinite(z_score):
            z_score = 0.0

    # Signal determination.
    if z_score < -2.0:
        signal = "contrarian_buy"
    elif cumulative > 0:
        signal = "bullish"
    else:
        signal = "neutral"

    return ForeignFlowResult(
        cumulative_5d=cumulative,
        z_score=z_score,
        signal=signal,
    )


# ── 7. Retail Absorption Rate (Smart Money / Bandarmology) ─────────────────


# IDX retail broker codes (pustaka/91 — Bandarmology broker classification)
RETAIL_BROKER_CODES = frozenset({"YP", "CC", "XL", "PD"})


@dataclass
class RetailAbsorptionResult:
    """Retail absorption rate analysis result (Smart Money Score).

    Attributes:
        smart_money_score: Accumulation score in [-1, +1]. Positive = institutional
            accumulation (retail selling, price holding). Negative = institutional
            distribution (retail buying, price weak).
        retail_net_volume: Net volume from retail brokers (negative = net selling).
        retail_net_value: Net value from retail brokers (negative = net selling).
        retail_sell_ratio: Ratio of retail net sell volume to total daily volume [0, 1].
        price_above_vwap: Whether close is at or above VWAP.
        accumulation_streak: Number of consecutive days with positive smart_money_score.
        daily_scores: List of per-day scores for the lookback period (D-0 to D-(lookback-1)).
        label: Human-readable label: "accumulation", "distribution", or "neutral".
    """

    smart_money_score: float
    retail_net_volume: float
    retail_net_value: float
    retail_sell_ratio: float
    price_above_vwap: bool
    accumulation_streak: int
    daily_scores: list[float]
    label: str


def calculate_retail_absorption(
    broker_flow_df: pd.DataFrame,
    ohlcv_df: pd.DataFrame,
    ticker: str,
    lookback: int = 5,
    retail_brokers: frozenset[str] = RETAIL_BROKER_CODES,
    retail_sell_threshold: float = 0.60,
) -> RetailAbsorptionResult:
    """Calculate Retail Absorption Rate and Smart Money Score.

    Detects institutional accumulation by analyzing retail broker flow:
    if retail brokers (YP, CC, XL, PD) are net selling >60% of daily volume
    but the closing price remains at or above VWAP, this indicates smart money
    is absorbing retail supply — a bullish accumulation signal (Bandarmology).

    The function is purely computational (no DB access). It requires pre-loaded
    broker_flow and OHLCV DataFrames.

    Args:
        broker_flow_df: DataFrame with columns [ticker, date, broker, buy_volume,
            sell_volume, net_volume, buy_value, sell_value, net_value].
            Must be filtered to the target ticker (or contain all tickers).
        ohlcv_df: DataFrame with columns [high, low, close, volume] indexed by date.
        ticker: Target ticker symbol (e.g. "BBCA.JK").
        lookback: Number of days to analyze (default 5, i.e. D-0 to D-4).
        retail_brokers: Set of retail broker codes (default: YP, CC, XL, PD).
        retail_sell_threshold: Ratio threshold for retail net sell to trigger
            accumulation signal (default 0.60 = 60% of total volume).

    Returns:
        RetailAbsorptionResult with smart_money_score and per-day breakdown.
    """
    # Filter broker_flow for this ticker
    if "ticker" in broker_flow_df.columns:
        bf = broker_flow_df[broker_flow_df["ticker"] == ticker].copy()
    else:
        bf = broker_flow_df.copy()

    if bf.empty or ohlcv_df.empty:
        return RetailAbsorptionResult(
            smart_money_score=0.0,
            retail_net_volume=0.0,
            retail_net_value=0.0,
            retail_sell_ratio=0.0,
            price_above_vwap=False,
            accumulation_streak=0,
            daily_scores=[],
            label="neutral",
        )

    # Ensure date columns are datetime
    if "date" in bf.columns:
        bf["date"] = pd.to_datetime(bf["date"])
    bf = bf.sort_values("date")

    ohlcv_df = ohlcv_df.copy()
    ohlcv_df.index = pd.to_datetime(ohlcv_df.index)

    # Get the last `lookback` trading dates
    recent_dates = ohlcv_df.index[-lookback:] if len(ohlcv_df) >= lookback else ohlcv_df.index

    daily_scores: list[float] = []
    total_retail_net_vol = 0.0
    total_retail_net_val = 0.0
    total_retail_sell_ratio = 0.0
    price_above_vwap_count = 0
    n_days = 0

    for date in recent_dates:
        date_mask = bf["date"] == date if "date" in bf.columns else pd.Series([True] * len(bf))
        day_bf = bf[date_mask]
        day_ohlcv = ohlcv_df.loc[[date]] if date in ohlcv_df.index else pd.DataFrame()

        if day_bf.empty or day_ohlcv.empty:
            daily_scores.append(0.0)
            continue

        # Retail broker flow for this day
        retail_mask = day_bf["broker"].isin(retail_brokers)
        retail_bf = day_bf[retail_mask]
        all_bf = day_bf

        # Total daily volume from all brokers
        total_buy_vol = float(all_bf["buy_volume"].fillna(0).sum()) if "buy_volume" in all_bf.columns else 0.0
        total_sell_vol = float(all_bf["sell_volume"].fillna(0).sum()) if "sell_volume" in all_bf.columns else 0.0
        total_vol = total_buy_vol + total_sell_vol

        # Retail net volume (negative = net selling)
        retail_net_vol = float(retail_bf["net_volume"].fillna(0).sum()) if "net_volume" in retail_bf.columns else 0.0
        retail_net_val = float(retail_bf["net_value"].fillna(0).sum()) if "net_value" in retail_bf.columns else 0.0

        # Retail sell ratio: how much of total volume is retail net selling
        if total_vol > 0:
            retail_sell_ratio = abs(min(0.0, retail_net_vol)) / total_vol
        else:
            retail_sell_ratio = 0.0

        # VWAP check: is close at or above VWAP?
        close = float(day_ohlcv["close"].iloc[0])
        high = float(day_ohlcv["high"].iloc[0]) if "high" in day_ohlcv.columns else close
        low = float(day_ohlcv["low"].iloc[0]) if "low" in day_ohlcv.columns else close

        typical_price = (high + low + close) / 3.0
        vwap = typical_price  # Single-bar VWAP approximation
        price_above_vwap = close >= vwap

        # Smart Money Score calculation:
        # +1.0 when retail is heavily net selling (>threshold) AND price holds at/above VWAP
        # -1.0 when retail is heavily net buying AND price below VWAP (distribution)
        # Scaled by the intensity of retail selling/buying
        if retail_sell_ratio >= retail_sell_threshold and price_above_vwap:
            # Accumulation: institutions absorbing retail supply
            score = min(1.0, retail_sell_ratio)
        elif retail_sell_ratio >= retail_sell_threshold and not price_above_vwap:
            # Retail selling and price dropping — could be genuine sell-off, not accumulation
            score = -min(0.5, retail_sell_ratio * 0.5)
        else:
            # Neutral or mild signals
            score = 0.0

        daily_scores.append(score)
        total_retail_net_vol += retail_net_vol
        total_retail_net_val += retail_net_val
        total_retail_sell_ratio += retail_sell_ratio
        if price_above_vwap:
            price_above_vwap_count += 1
        n_days += 1

    # Aggregate score: average of daily scores, scaled
    if n_days > 0:
        avg_score = sum(daily_scores) / n_days
        avg_retail_sell_ratio = total_retail_sell_ratio / n_days
        price_above_vwap_avg = price_above_vwap_count > (n_days / 2)
    else:
        avg_score = 0.0
        avg_retail_sell_ratio = 0.0
        price_above_vwap_avg = False

    # Calculate accumulation streak (consecutive positive scores from most recent)
    streak = 0
    for score in reversed(daily_scores):
        if score > 0:
            streak += 1
        else:
            break

    # Label
    if avg_score > 0.3:
        label = "accumulation"
    elif avg_score < -0.2:
        label = "distribution"
    else:
        label = "neutral"

    return RetailAbsorptionResult(
        smart_money_score=round(avg_score, 4),
        retail_net_volume=round(total_retail_net_vol, 2),
        retail_net_value=round(total_retail_net_val, 2),
        retail_sell_ratio=round(avg_retail_sell_ratio, 4),
        price_above_vwap=price_above_vwap_avg,
        accumulation_streak=streak,
        daily_scores=[round(s, 4) for s in daily_scores],
        label=label,
    )
