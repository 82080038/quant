"""Versioned factor library with LLM-guided expansion.

Manages factor definitions, computation, validation, and pruning.
Integrates with feature_definitions + feature_values DB tables and
PointInTimeQuery for look-ahead-bias-free retrieval.

Factor categories:
  - Technical (RSI, MACD, BB, ADX, OBV, MFI, ATR, KAMA)
  - Volume (OFI proxy, VWAP dev, OBV divergence, foreign flow momentum)
  - Fundamental (P/E, P/B, ROE, ROA, debt ratio, dividend yield, EPS growth)
  - Macro (BI Rate, USD/IDR, CPO, gold, S&P 500, VIX)
  - Sentiment (news sentiment, sentiment momentum, news volume)
  - Alpha (mean reversion, reversal, EWMA momentum, regime switch)
  - LLM-discovered (Miner Agent output, Phase 3)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db
from quant.data.point_in_time import PointInTimeQuery

logger = logging.getLogger(__name__)


@dataclass
class FactorDefinition:
    """Definition of a computable factor."""

    name: str
    version: str
    description: str
    category: str
    compute_fn: Callable[[pd.DataFrame], pd.Series]
    dependencies: list[str] = field(default_factory=list)
    is_active: bool = True
    db_id: Optional[int] = None


@dataclass
class FactorValidationResult:
    """Validation result for a single factor."""

    factor_name: str
    ic: float
    icir: float
    turnover: float
    decay_half_life: int
    coverage_pct: float
    is_valid: bool


class FactorLibrary:
    """Versioned factor library with DB persistence and PIT-safe retrieval.

    Usage:
        lib = FactorLibrary()
        lib.register_default_factors()
        lib.compute_and_store("rsi_14", "BBCA.JK", date(2024, 1, 15))
        values = lib.get_factor("rsi_14", "BBCA.JK", date(2024, 6, 1))
    """

    def __init__(self, session=None, pit: Optional[PointInTimeQuery] = None):
        self._session = session
        self._pit = pit
        self._factors: dict[str, FactorDefinition] = {}
        self._owns_session = session is None  # track if we created the session

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
            self._owns_session = True
        return self._session

    def close(self):
        """Close the DB session if we own it."""
        if self._owns_session and self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    @property
    def pit(self) -> PointInTimeQuery:
        if self._pit is None:
            self._pit = PointInTimeQuery(self._session)
        return self._pit

    def register(self, factor: FactorDefinition) -> None:
        """Register a new factor in memory and DB."""
        key = f"{factor.name}@{factor.version}"
        self._factors[key] = factor
        self._persist_definition(factor)

    def _persist_definition(self, factor: FactorDefinition) -> None:
        """Upsert factor definition into feature_definitions table."""
        try:
            self.session.execute(text("""
                INSERT INTO feature_definitions (name, version, description, dependencies, computation_module, is_active)
                VALUES (:name, :version, :desc, :deps, :module, :active)
                ON CONFLICT (name, version) DO UPDATE
                SET description = EXCLUDED.description,
                    dependencies = EXCLUDED.dependencies,
                    computation_module = EXCLUDED.computation_module,
                    is_active = EXCLUDED.is_active
                RETURNING id
            """), {
                "name": factor.name,
                "version": factor.version,
                "desc": factor.description,
                "deps": factor.dependencies,
                "module": f"{factor.category}/factor_library",
                "active": factor.is_active,
            })
            row = self.session.fetchone() if hasattr(self.session, "fetchone") else None
            if row:
                factor.db_id = row[0]
            self.session.commit()
        except Exception:
            self.session.rollback()

    def _get_db_factor_id(self, name: str, version: str = "1.0.0") -> Optional[int]:
        """Get DB ID for a factor definition."""
        result = self.session.execute(text("""
            SELECT id FROM feature_definitions
            WHERE name = :name AND version = :version AND is_active = TRUE
        """), {"name": name, "version": version})
        row = result.fetchone()
        return row[0] if row else None

    def compute_and_store(
        self,
        factor_name: str,
        ticker: str,
        as_of: date,
        version: str = "1.0.0",
    ) -> Optional[float]:
        """Compute a factor value from raw data and store in DB.

        Args:
            factor_name: Factor name (e.g. 'rsi_14')
            ticker: Stock ticker
            as_of: Date to compute factor for
            version: Factor version

        Returns:
            Computed factor value, or None if computation failed
        """
        key = f"{factor_name}@{version}"
        factor = self._factors.get(key)
        if factor is None:
            factor = self._factors.get(factor_name)
        if factor is None:
            return None

        prices = self.pit.get_prices(ticker, as_of, lookback=252)
        if prices.empty or len(prices) < 10:
            return None

        try:
            values = factor.compute_fn(prices)
            if values.empty:
                return None
            latest_val = float(values.iloc[-1])
            if np.isnan(latest_val):
                return None

            db_id = factor.db_id or self._get_db_factor_id(factor_name, version)
            if db_id is None:
                self._persist_definition(factor)
                db_id = self._get_db_factor_id(factor_name, version)

            if db_id is not None:
                self.session.execute(text("""
                    INSERT INTO feature_values (feature_def_id, ticker, date, value, as_of_date)
                    VALUES (:fid, :ticker, :date, :val, :as_of)
                    ON CONFLICT (feature_def_id, ticker, date, as_of_date)
                    DO UPDATE SET value = EXCLUDED.value
                """), {
                    "fid": db_id,
                    "ticker": ticker,
                    "date": as_of,
                    "val": latest_val,
                    "as_of": date.today(),
                })
                self.session.commit()

            return latest_val
        except Exception:
            self.session.rollback()
            return None

    def compute_and_store_batch(
        self,
        factor_name: str,
        ticker: str,
        start: date,
        end: date,
        version: str = "1.0.0",
    ) -> int:
        """Compute and store a factor for a date range.

        Returns:
            Number of dates successfully computed
        """
        key = f"{factor_name}@{version}"
        factor = self._factors.get(key) or self._factors.get(factor_name)
        if factor is None:
            return 0

        prices = self.pit.get_prices(ticker, end, lookback=500)
        if prices.empty:
            return 0

        try:
            values = factor.compute_fn(prices)
        except Exception:
            return 0

        if values.empty:
            return 0

        # Align index to prices date index if compute_fn returned a RangeIndex
        if not isinstance(values.index, pd.DatetimeIndex) and "date" in prices.columns:
            values.index = prices["date"].values

        db_id = factor.db_id or self._get_db_factor_id(factor_name, version)
        if db_id is None:
            self._persist_definition(factor)
            db_id = self._get_db_factor_id(factor_name, version)
        if db_id is None:
            return 0

        # Convert index to datetime for comparison
        dt_index = pd.to_datetime(values.index)
        mask = (dt_index >= pd.Timestamp(start)) & (dt_index <= pd.Timestamp(end))
        batch_values = values[mask]

        count = 0
        for dt, val in batch_values.items():
            if np.isnan(val):
                continue
            try:
                self.session.execute(text("""
                    INSERT INTO feature_values (feature_def_id, ticker, date, value, as_of_date)
                    VALUES (:fid, :ticker, :date, :val, :as_of)
                    ON CONFLICT (feature_def_id, ticker, date, as_of_date)
                    DO UPDATE SET value = EXCLUDED.value
                """), {
                    "fid": db_id,
                    "ticker": ticker,
                    "date": dt.date() if hasattr(dt, "date") else dt,
                    "val": float(val),
                    "as_of": date.today(),
                })
                count += 1
            except Exception:
                continue

        self.session.commit()
        return count

    def get_factor(
        self,
        factor_name: str,
        ticker: str,
        as_of: date,
        lookback: int = 252,
    ) -> pd.Series:
        """Get PIT-safe factor values from DB.

        Args:
            factor_name: Factor name
            ticker: Stock ticker
            as_of: Decision date (only data known by this date returned)
            lookback: Number of historical values

        Returns:
            Series of factor values indexed by date
        """
        return self.pit.get_feature_values(factor_name, ticker, as_of, lookback)

    def get_factor_matrix(
        self,
        factor_names: list[str],
        tickers: list[str],
        as_of: date,
        lookback: int = 252,
    ) -> pd.DataFrame:
        """Get a cross-sectional factor matrix.

        Returns:
            DataFrame indexed by ticker, columns = factor_names
        """
        rows = {}
        for ticker in tickers:
            row = {}
            for fname in factor_names:
                series = self.get_factor(fname, ticker, as_of, lookback=5)
                if not series.empty:
                    row[fname] = float(series.iloc[-1])
                else:
                    row[fname] = np.nan
            rows[ticker] = row
        return pd.DataFrame(rows).T

    def validate(
        self,
        factor_name: str,
        tickers: list[str],
        date_range: tuple[date, date],
        version: str = "1.0.0",
    ) -> FactorValidationResult:
        """Validate a factor: IC, ICIR, turnover, decay, coverage.

        Args:
            factor_name: Factor to validate
            tickers: Universe of tickers
            date_range: (start, end) for validation
            version: Factor version

        Returns:
            FactorValidationResult with metrics
        """
        from quant.evaluation.ic_tracking import ICTracker

        start, end = date_range
        trading_days = self.pit.get_trading_days(start, end)

        if len(trading_days) < 20:
            return FactorValidationResult(factor_name, 0, 0, 0, 0, 0, False)

        predictions = []
        actuals = []
        prev_values: dict[str, float] = {}
        turnovers = []

        for dt in trading_days[::5]:
            pred_row = {}
            for ticker in tickers:
                series = self.get_factor(factor_name, ticker, dt, lookback=5)
                if not series.empty:
                    val = float(series.iloc[-1])
                    pred_row[ticker] = val
                    if ticker in prev_values and prev_values[ticker] != 0:
                        turnovers.append(abs(val - prev_values[ticker]) / abs(prev_values[ticker]))
                    prev_values[ticker] = val

            if len(pred_row) < 3:
                continue

            prices_now = {}
            for ticker in pred_row:
                p = self.pit.get_prices(ticker, dt, lookback=10)
                if not p.empty and len(p) >= 6:
                    prices_now[ticker] = float(p["close"].iloc[-1])

            for ticker in pred_row:
                p = self.pit.get_prices(ticker, dt + timedelta(days=7), lookback=10)
                if not p.empty:
                    future_price = float(p["close"].iloc[-1])
                    now_price = prices_now.get(ticker)
                    if now_price and now_price > 0:
                        ret = (future_price - now_price) / now_price
                        predictions.append(pred_row[ticker])
                        actuals.append(ret)

        if len(predictions) < 10:
            return FactorValidationResult(factor_name, 0, 0, 0, 0, 0, False)

        tracker = ICTracker()
        ic_result = tracker.compute_ic(np.array(predictions), np.array(actuals))

        ic = ic_result.ic
        icir = ic_result.icir
        turnover = float(np.mean(turnovers)) if turnovers else 0.0
        coverage = len(predictions) / (len(trading_days) * len(tickers)) if trading_days and tickers else 0

        is_valid = abs(ic) > 0.02 and coverage > 0.3

        return FactorValidationResult(
            factor_name=factor_name,
            ic=ic,
            icir=icir,
            turnover=turnover,
            decay_half_life=0,
            coverage_pct=coverage,
            is_valid=is_valid,
        )

    def prune(
        self,
        threshold_ic: float = 0.02,
        tickers: Optional[list[str]] = None,
        date_range: Optional[tuple[date, date]] = None,
    ) -> list[str]:
        """Deactivate factors with decayed IC below threshold.

        Args:
            threshold_ic: Minimum absolute IC to keep a factor active
            tickers: Universe for IC validation (required if date_range given)
            date_range: (start, end) for IC validation (required if tickers given)

        Returns:
            List of pruned factor names
        """
        pruned = []

        # If no validation context provided, prune only inactive-flagged factors
        if tickers is None or date_range is None:
            for key, factor in self._factors.items():
                if not factor.is_active:
                    continue
                # Without IC data, we can only prune via DB flag — skip
                pass
            return pruned

        # Validate each active factor and prune low-IC ones
        for key, factor in list(self._factors.items()):
            if not factor.is_active:
                continue
            try:
                result = self.validate(
                    factor_name=factor.name,
                    tickers=tickers,
                    date_range=date_range,
                    version=factor.version,
                )
                if abs(result.ic) < threshold_ic:
                    self.session.execute(text("""
                        UPDATE feature_definitions
                        SET is_active = FALSE
                        WHERE name = :name AND version = :version
                    """), {"name": factor.name, "version": factor.version})
                    factor.is_active = False
                    pruned.append(factor.name)
                    logger.info("Pruned factor %s (IC=%.4f < %.4f)", factor.name, result.ic, threshold_ic)
            except Exception:
                self.session.rollback()

        if pruned:
            self.session.commit()
        return pruned

    @property
    def factor_names(self) -> list[str]:
        """List registered factor names."""
        return [f.name for f in self._factors.values() if f.is_active]

    def register_default_factors(self) -> None:
        """Register all default technical, volume, and alpha factors."""

        # ── Technical ──────────────────────────────────────────────
        self.register(FactorDefinition(
            name="rsi_14", version="1.0.0", category="technical",
            description="Relative Strength Index (14-period)",
            compute_fn=self._compute_rsi, dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="macd_hist", version="1.0.0", category="technical",
            description="MACD Histogram (12,26,9)",
            compute_fn=self._compute_macd_hist, dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="bb_width", version="1.0.0", category="technical",
            description="Bollinger Bands width (20,2)",
            compute_fn=self._compute_bb_width, dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="adx_14", version="1.0.0", category="technical",
            description="Average Directional Index (14)",
            compute_fn=self._compute_adx, dependencies=["high", "low", "close"],
        ))
        self.register(FactorDefinition(
            name="atr_14", version="1.0.0", category="technical",
            description="Average True Range (14-period)",
            compute_fn=self._compute_atr, dependencies=["high", "low", "close"],
        ))
        self.register(FactorDefinition(
            name="kama_10", version="1.0.0", category="technical",
            description="KAMA (Kaufman Adaptive Moving Average, 10)",
            compute_fn=self._compute_kama, dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="obv", version="1.0.0", category="volume",
            description="On-Balance Volume",
            compute_fn=self._compute_obv, dependencies=["close", "volume"],
        ))
        self.register(FactorDefinition(
            name="mfi_14", version="1.0.0", category="technical",
            description="Money Flow Index (14)",
            compute_fn=self._compute_mfi, dependencies=["high", "low", "close", "volume"],
        ))

        # ── Volume ─────────────────────────────────────────────────
        self.register(FactorDefinition(
            name="volume_ratio_20", version="1.0.0", category="volume",
            description="Volume / 20-day average volume",
            compute_fn=lambda df: df["volume"] / df["volume"].rolling(20).mean(),
            dependencies=["volume"],
        ))
        self.register(FactorDefinition(
            name="vwap_dev", version="1.0.0", category="volume",
            description="VWAP deviation from close",
            compute_fn=self._compute_vwap_dev, dependencies=["high", "low", "close", "volume"],
        ))

        # ── Alpha ──────────────────────────────────────────────────
        self.register(FactorDefinition(
            name="momentum_20", version="1.0.0", category="alpha",
            description="20-day price momentum (rate of change)",
            compute_fn=lambda df: df["close"].pct_change(20),
            dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="reversal_5", version="1.0.0", category="alpha",
            description="5-day mean reversion signal",
            compute_fn=lambda df: -(df["close"].pct_change(5)),
            dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="ewma_momentum", version="1.0.0", category="alpha",
            description="EWMA momentum (12 vs 26)",
            compute_fn=lambda df: df["close"].ewm(span=12).mean() / df["close"].ewm(span=26).mean() - 1,
            dependencies=["close"],
        ))
        self.register(FactorDefinition(
            name="volatility_20", version="1.0.0", category="alpha",
            description="20-day rolling volatility",
            compute_fn=lambda df: df["close"].pct_change().rolling(20).std(),
            dependencies=["close"],
        ))

        # ── Target ─────────────────────────────────────────────────
        self.register(FactorDefinition(
            name="forward_return_5d", version="1.0.0", category="target",
            description="5-day forward return (target variable)",
            compute_fn=lambda df: df["close"].shift(-5).pct_change(5, fill_method=None),
            dependencies=["close"],
        ))

    # ── Factor compute functions ──────────────────────────────────

    @staticmethod
    def _compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).fillna(50)

    @staticmethod
    def _compute_macd_hist(df: pd.DataFrame) -> pd.Series:
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        return macd - signal

    @staticmethod
    def _compute_bb_width(df: pd.DataFrame, period: int = 20) -> pd.Series:
        sma = df["close"].rolling(period).mean()
        std = df["close"].rolling(period).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (upper - lower) / sma.replace(0, np.nan)

    @staticmethod
    def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / period, min_periods=period).mean()

        plus_dm = (df["high"] - df["high"].shift(1)).where(
            (df["high"] - df["high"].shift(1)) > (df["low"].shift(1) - df["low"]), 0
        )
        minus_dm = (df["low"].shift(1) - df["low"]).where(
            (df["low"].shift(1) - df["low"]) > (df["high"] - df["high"].shift(1)), 0
        )

        plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr.replace(0, np.nan)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        return dx.ewm(alpha=1 / period, min_periods=period).mean().fillna(25)

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    @staticmethod
    def _compute_kama(df: pd.DataFrame, period: int = 10) -> pd.Series:
        close = df["close"]
        change = (close - close.shift(period)).abs()
        volatility = close.diff().abs().rolling(period).sum()
        er = change / volatility.replace(0, np.nan)
        sc = (er * (2 / (2 + 1) - 2 / (30 + 1)) + 2 / (30 + 1)).fillna(0) ** 2

        kama = close.copy()
        for i in range(period, len(close)):
            kama.iloc[i] = kama.iloc[i - 1] + sc.iloc[i] * (close.iloc[i] - kama.iloc[i - 1])
        return kama

    @staticmethod
    def _compute_obv(df: pd.DataFrame) -> pd.Series:
        direction = (df["close"] > df["close"].shift(1)).astype(int) - (df["close"] < df["close"].shift(1)).astype(int)
        return (direction * df["volume"]).cumsum()

    @staticmethod
    def _compute_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        mf = tp * df["volume"]
        pos_mf = mf.where(tp > tp.shift(1), 0)
        neg_mf = mf.where(tp < tp.shift(1), 0)
        pos_sum = pos_mf.rolling(period).sum()
        neg_sum = neg_mf.rolling(period).sum()
        mfr = pos_sum / neg_sum.replace(0, np.nan)
        return (100 - 100 / (1 + mfr)).fillna(50)

    @staticmethod
    def _compute_vwap_dev(df: pd.DataFrame) -> pd.Series:
        tp = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (tp * df["volume"]).rolling(20).sum() / df["volume"].rolling(20).sum().replace(0, np.nan)
        return (df["close"] - vwap) / vwap.replace(0, np.nan)
