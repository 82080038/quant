"""Strategy Selector — maps instrument personality to best strategy class.

Extends the simple 3-strategy selection (donchian, rsi_meanrev, ema_envelope)
with personality-aware strategy assignment:

- Blue chip / low volatility → mean_reversion (RSI oversold/overbought)
- High beta / momentum → momentum_breakout (Donchian channel breakout)
- Commodity linked → sector_rotation (rotate based on commodity cycle)
- Cointegrated pairs → pairs_trading (spread reversion)
- Dividend stock → value_dividend (hold for yield + capital appreciation)
- Gorengan / illiquid → technical_only (pure price action, no fundamental)
- Extreme volatility → macro_regime (regime-aware position sizing)

The selector evaluates multiple strategy classes on in-sample data and
persists the best assignment to ``strategy_assignment`` table.

Usage:
    from quant.analysis.strategy_selector import StrategySelector
    selector = StrategySelector()
    assignment = selector.select(ticker, ohlcv_df, profile)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quant.analysis.profiling import (
    InstrumentProfile,
    PersonalityLabel,
    VolatilityRegime,
)

logger = logging.getLogger(__name__)


# ── Strategy classes ────────────────────────────────────────────────────────

STRATEGY_CLASSES: dict[str, list[str]] = {
    "trend_following": ["donchian", "ema_envelope", "macd_crossover"],
    "mean_reversion": ["rsi_meanrev", "bollinger_reversion", "ema_envelope"],
    "momentum_breakout": ["donchian", "macd_crossover", "rsi_momentum"],
    "sector_rotation": ["sector_rs", "sector_momentum"],
    "pairs_trading": ["cointegration_spread", "zscore_reversion"],
    "value_dividend": ["dividend_capture", "value_hold"],
    "macro_regime": ["regime_aware_trend", "regime_aware_meanrev"],
    "technical_only": ["donchian", "rsi_meanrev", "ema_envelope"],
}

# Personality → recommended strategy class mapping
PERSONALITY_TO_CLASS: dict[PersonalityLabel, str] = {
    PersonalityLabel.BLUE_CHIP: "mean_reversion",
    PersonalityLabel.MID_CAP: "trend_following",
    PersonalityLabel.SMALL_CAP: "momentum_breakout",
    PersonalityLabel.GORENGAN: "technical_only",
    PersonalityLabel.ILLIQUID: "technical_only",
    PersonalityLabel.HIGH_BETA: "momentum_breakout",
    PersonalityLabel.LOW_BETA: "mean_reversion",
    PersonalityLabel.DIVIDEND_STOCK: "value_dividend",
    PersonalityLabel.COMMODITY_LINKED: "sector_rotation",
    PersonalityLabel.UNKNOWN: "trend_following",
}

# Volatility regime → strategy class override
VOLATILITY_TO_CLASS: dict[VolatilityRegime, str | None] = {
    VolatilityRegime.LOW: "mean_reversion",
    VolatilityRegime.MEDIUM: None,  # no override
    VolatilityRegime.HIGH: "momentum_breakout",
    VolatilityRegime.EXTREME: "macro_regime",
}


@dataclass
class StrategyAssignmentResult:
    """Result of strategy selection for a ticker."""

    ticker: str
    best_strategy: str
    strategy_class: str
    strategy_rationale: str
    in_sample_sharpe: float = 0.0
    in_sample_max_dd: float = 0.0
    in_sample_winrate: float = 0.0


# ── Strategy signal generators ──────────────────────────────────────────────

def donchian_signals(close: pd.Series, period: int = 20) -> pd.Series:
    """Donchian channel breakout."""
    upper = close.rolling(period).max().shift(1)
    lower = close.rolling(period).min().shift(1)
    signal = pd.Series(0, index=close.index)
    signal[close > upper] = 1
    signal[close < lower] = -1
    return signal


def rsi_mean_reversion_signals(close: pd.Series, period: int = 14,
                                oversold: float = 30, overbought: float = 70) -> pd.Series:
    """RSI mean reversion — buy oversold, sell overbought."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    signal = pd.Series(0, index=close.index)
    signal[rsi < oversold] = 1
    signal[rsi > overbought] = -1
    return signal


def ema_envelope_signals(close: pd.Series, span: int = 20,
                          band: float = 0.05) -> pd.Series:
    """EMA envelope — buy below lower band, sell above upper."""
    ema = close.ewm(span=span).mean()
    upper = ema * (1 + band)
    lower = ema * (1 - band)
    signal = pd.Series(0, index=close.index)
    signal[close < lower] = 1
    signal[close > upper] = -1
    return signal


def macd_crossover_signals(close: pd.Series, fast: int = 12,
                            slow: int = 26, signal_period: int = 9) -> pd.Series:
    """MACD crossover — buy when MACD crosses above signal, sell below."""
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal_period).mean()

    signal = pd.Series(0, index=close.index)
    signal[macd > signal_line] = 1
    signal[macd < signal_line] = -1
    return signal


def bollinger_reversion_signals(close: pd.Series, period: int = 20,
                                 std_dev: float = 2.0) -> pd.Series:
    """Bollinger Band reversion — buy below lower, sell above upper."""
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + std_dev * std
    lower = ma - std_dev * std

    signal = pd.Series(0, index=close.index)
    signal[close < lower] = 1
    signal[close > upper] = -1
    return signal


def rsi_momentum_signals(close: pd.Series, period: int = 14,
                          threshold: float = 55) -> pd.Series:
    """RSI momentum — buy when RSI > threshold, sell when < 50."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    signal = pd.Series(0, index=close.index)
    signal[rsi > threshold] = 1
    signal[rsi < 50] = -1
    return signal


# ── Strategy evaluation ─────────────────────────────────────────────────────

ALL_STRATEGIES = {
    "donchian": donchian_signals,
    "rsi_meanrev": rsi_mean_reversion_signals,
    "ema_envelope": ema_envelope_signals,
    "macd_crossover": macd_crossover_signals,
    "bollinger_reversion": bollinger_reversion_signals,
    "rsi_momentum": rsi_momentum_signals,
}


def _compute_sharpe(returns: pd.Series) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    return float(np.sqrt(252) * returns.mean() / returns.std())


def _compute_max_dd(returns: pd.Series) -> float:
    cumulative = (1 + returns).cumprod()
    peak = cumulative.expanding().max()
    dd = (cumulative - peak) / peak
    return float(dd.min()) if not dd.empty else 0.0


def _compute_winrate(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    wins = (returns > 0).sum()
    total = (returns != 0).sum()
    return float(wins / total * 100) if total > 0 else 0.0


def _strategy_returns(close: pd.Series, signal: pd.Series) -> pd.Series:
    pos = signal.shift(1).fillna(0)
    ret = close.astype(float).pct_change()
    return pos * ret


class StrategySelector:
    """Selects the best strategy class and specific strategy for a ticker.

    Combines personality-based recommendation with in-sample backtesting
    to pick the strategy with the best risk-adjusted return.
    """

    def __init__(self, min_bars: int = 100) -> None:
        self.min_bars = min_bars

    def select(
        self,
        ticker: str,
        close: pd.Series,
        profile: InstrumentProfile | None = None,
        train_end: str | None = None,
    ) -> StrategyAssignmentResult:
        """Select best strategy for a ticker.

        Args:
            ticker: Instrument ticker.
            close: Close price series.
            profile: Instrument profile from InstrumentProfiler.
            train_end: End date for in-sample evaluation (exclusive).

        Returns:
            StrategyAssignmentResult with best strategy and rationale.
        """
        if len(close) < self.min_bars:
            return StrategyAssignmentResult(
                ticker=ticker,
                best_strategy="donchian",
                strategy_class="trend_following",
                strategy_rationale="Insufficient data — defaulting to donchian.",
            )

        # Determine candidate strategies from personality
        candidate_class = self._recommend_class(profile)
        candidates = STRATEGY_CLASSES.get(candidate_class, ["donchian"])

        # Also evaluate all strategies for comparison
        all_candidates = list(set(candidates + list(ALL_STRATEGIES.keys())))

        # In-sample evaluation
        train_close = close
        if train_end:
            train_close = close.loc[:pd.Timestamp(train_end) - pd.Timedelta(days=1)]
            if len(train_close) < self.min_bars:
                train_close = close

        best_name = "donchian"
        best_sharpe = -999.0
        best_dd = 0.0
        best_wr = 0.0

        for name in all_candidates:
            if name not in ALL_STRATEGIES:
                continue
            try:
                sig = ALL_STRATEGIES[name](train_close)
                rets = _strategy_returns(train_close, sig)
                sharpe = _compute_sharpe(rets)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_name = name
                    best_dd = _compute_max_dd(rets)
                    best_wr = _compute_winrate(rets)
            except Exception:
                continue

        # Determine final class from winning strategy
        # Prefer the recommended candidate_class if the winning strategy belongs to it
        final_class = candidate_class
        candidate_strategies = STRATEGY_CLASSES.get(candidate_class, [])
        candidate_evaluable = [s for s in candidate_strategies if s in ALL_STRATEGIES]

        if candidate_evaluable and best_name in candidate_strategies:
            final_class = candidate_class
        elif not candidate_evaluable:
            # Candidate class has no implemented strategies — keep the class
            # but use the best overall strategy as the specific pick
            final_class = candidate_class
        else:
            for cls, strategies in STRATEGY_CLASSES.items():
                if best_name in strategies:
                    final_class = cls
                    break

        rationale = self._build_rationale(
            ticker, best_name, final_class, profile, best_sharpe,
        )

        return StrategyAssignmentResult(
            ticker=ticker,
            best_strategy=best_name,
            strategy_class=final_class,
            strategy_rationale=rationale,
            in_sample_sharpe=round(best_sharpe, 4),
            in_sample_max_dd=round(best_dd, 4),
            in_sample_winrate=round(best_wr, 2),
        )

    def _recommend_class(self, profile: InstrumentProfile | None) -> str:
        """Recommend strategy class based on instrument profile."""
        if profile is None:
            return "trend_following"

        # Priority 1: Gorengan/illiquid — always technical_only regardless of volatility
        high_priority = {PersonalityLabel.GORENGAN, PersonalityLabel.ILLIQUID}
        for label in high_priority:
            if label in profile.personality_labels:
                return PERSONALITY_TO_CLASS.get(label, "technical_only")

        # Priority 2: Volatility regime override
        vol_override = VOLATILITY_TO_CLASS.get(profile.volatility_regime)
        if vol_override:
            return vol_override

        # Priority 3: Other personality labels
        priority_order = [
            PersonalityLabel.COMMODITY_LINKED,
            PersonalityLabel.DIVIDEND_STOCK,
            PersonalityLabel.BLUE_CHIP,
            PersonalityLabel.HIGH_BETA,
            PersonalityLabel.LOW_BETA,
            PersonalityLabel.SMALL_CAP,
            PersonalityLabel.MID_CAP,
        ]

        for label in priority_order:
            if label in profile.personality_labels:
                return PERSONALITY_TO_CLASS.get(label, "trend_following")

        return "trend_following"

    def _build_rationale(
        self,
        ticker: str,
        strategy: str,
        cls: str,
        profile: InstrumentProfile | None,
        sharpe: float,
    ) -> str:
        parts = [f"Best strategy: {strategy} (class: {cls}, Sharpe: {sharpe:.3f})."]

        if profile:
            labels = [l.value for l in profile.personality_labels]
            parts.append(f"Personality: {', '.join(labels)}.")
            parts.append(f"Volatility: {profile.volatility_regime.value}.")
            parts.append(f"Beta vs IHSG: {profile.beta_vs_ihsg:.2f}.")

            if profile.commodity_linkage:
                parts.append(f"Commodity linkage: {profile.commodity_linkage}.")

        return " ".join(parts)

    def select_batch(
        self,
        instruments: dict[str, pd.Series],
        profiles: dict[str, InstrumentProfile] | None = None,
        train_end: str | None = None,
    ) -> dict[str, StrategyAssignmentResult]:
        """Select strategies for multiple tickers.

        Args:
            instruments: Dict of ticker → close price Series.
            profiles: Dict of ticker → InstrumentProfile.
            train_end: End date for in-sample evaluation.

        Returns:
            Dict of ticker → StrategyAssignmentResult.
        """
        results: dict[str, StrategyAssignmentResult] = {}
        profiles = profiles or {}

        for ticker, close in instruments.items():
            try:
                profile = profiles.get(ticker)
                results[ticker] = self.select(ticker, close, profile, train_end)
            except Exception as e:
                logger.warning("Strategy selection failed for %s: %s", ticker, e)
                results[ticker] = StrategyAssignmentResult(
                    ticker=ticker,
                    best_strategy="donchian",
                    strategy_class="trend_following",
                    strategy_rationale=f"Selection failed: {e}",
                )

        return results

    def persist_assignment(
        self,
        result: StrategyAssignmentResult,
        session_factory=None,
    ) -> None:
        """Persist strategy assignment to strategy_assignment table.

        Args:
            result: Strategy selection result.
            session_factory: SQLAlchemy session factory.
        """
        if session_factory is None:
            logger.warning("No session_factory — assignment not persisted.")
            return

        from quant.db.models import StrategyAssignment

        session = session_factory()
        try:
            row = StrategyAssignment(
                ticker=result.ticker,
                best_strategy=result.best_strategy,
                strategy_class=result.strategy_class,
                strategy_rationale=result.strategy_rationale,
                in_sample_sharpe=result.in_sample_sharpe,
                in_sample_max_dd=result.in_sample_max_dd,
                in_sample_winrate=result.in_sample_winrate,
                updated_at=datetime.now(UTC),
            )
            session.merge(row)
            session.commit()
            logger.info("Persisted strategy assignment for %s: %s (%s)",
                        result.ticker, result.best_strategy, result.strategy_class)
        except Exception as e:
            session.rollback()
            logger.error("Failed to persist assignment for %s: %s", result.ticker, e)
        finally:
            session.close()
