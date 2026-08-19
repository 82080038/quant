"""Feature store automation (pustaka/58).

Manages feature computation, storage, and retrieval for ML pipelines.
Supports:
- Feature definition and registration
- Feature computation from raw OHLCV data
- Feature versioning and caching
- Feature serving for training and inference
- Freshness monitoring (Gap #36): track staleness of cached feature sets
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

import numpy as np
import pandas as pd


class FreshnessStatus(str, Enum):
    """Feature set freshness status (Gap #36)."""

    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"
    ERROR = "ERROR"


@dataclass
class FeatureDefinition:
    """Definition of a computable feature."""

    name: str
    description: str
    version: str
    compute_fn: Callable[[pd.DataFrame], pd.Series]
    dependencies: list[str] = field(default_factory=list)
    dtype: str = "float64"


@dataclass
class FeatureSet:
    """A computed feature set."""

    name: str
    version: str
    features: pd.DataFrame
    computed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    n_rows: int = 0
    source_data_last_date: str | None = None
    has_errors: bool = False

    def __post_init__(self) -> None:
        self.n_rows = len(self.features)


@dataclass
class FreshnessReport:
    """Freshness report for a cached feature set (Gap #36)."""

    cache_key: str
    status: FreshnessStatus
    computed_at: str | None
    age_hours: float | None
    source_data_last_date: str | None
    source_age_hours: float | None
    message: str


class FeatureStore:
    """Feature store for ML pipeline automation."""

    def __init__(self, max_fresh_age_hours: float = 24.0) -> None:
        self._definitions: dict[str, FeatureDefinition] = {}
        self._cache: dict[str, FeatureSet] = {}
        self._max_fresh_age = timedelta(hours=max_fresh_age_hours)

    def register(self, definition: FeatureDefinition) -> None:
        """Register a feature definition.

        Args:
            definition: Feature definition to register.
        """
        key = f"{definition.name}@{definition.version}"
        self._definitions[key] = definition

    def register_default_features(self) -> None:
        """Register default trading features."""
        # RSI
        self.register(FeatureDefinition(
            name="rsi_14",
            description="Relative Strength Index (14-period)",
            version="1.0.0",
            compute_fn=self._compute_rsi,
            dependencies=["close"],
        ))

        # Moving averages
        self.register(FeatureDefinition(
            name="sma_20",
            description="Simple Moving Average (20-period)",
            version="1.0.0",
            compute_fn=lambda df: df["close"].rolling(20).mean(),
            dependencies=["close"],
        ))

        self.register(FeatureDefinition(
            name="sma_50",
            description="Simple Moving Average (50-period)",
            version="1.0.0",
            compute_fn=lambda df: df["close"].rolling(50).mean(),
            dependencies=["close"],
        ))

        # Bollinger Bands width
        self.register(FeatureDefinition(
            name="bb_width",
            description="Bollinger Bands width",
            version="1.0.0",
            compute_fn=self._compute_bb_width,
            dependencies=["close"],
        ))

        # Volume ratio
        self.register(FeatureDefinition(
            name="volume_ratio",
            description="Volume / 20-day average volume",
            version="1.0.0",
            compute_fn=lambda df: df["volume"] / df["volume"].rolling(20).mean(),
            dependencies=["volume"],
        ))

        # ATR
        self.register(FeatureDefinition(
            name="atr_14",
            description="Average True Range (14-period)",
            version="1.0.0",
            compute_fn=self._compute_atr,
            dependencies=["high", "low", "close"],
        ))

        # Forward returns (target)
        self.register(FeatureDefinition(
            name="forward_return_5d",
            description="5-day forward return",
            version="1.0.0",
            compute_fn=lambda df: df["close"].shift(-5).pct_change(5, fill_method=None),
            dependencies=["close"],
        ))

    @staticmethod
    def _compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _compute_bb_width(df: pd.DataFrame, period: int = 20) -> pd.Series:
        sma = df["close"].rolling(period).mean()
        std = df["close"].rolling(period).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        return (upper - lower) / sma

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def compute(
        self,
        data: pd.DataFrame,
        feature_names: list[str] | None = None,
        version: str = "1.0.0",
    ) -> FeatureSet:
        """Compute features from raw data.

        Args:
            data: Raw OHLCV DataFrame.
            feature_names: Features to compute. All if None.
            version: Feature version.

        Returns:
            FeatureSet with computed features.
        """
        if not self._definitions:
            self.register_default_features()

        if feature_names is None:
            feature_names = list(self._definitions.keys())

        # Also compute any dependencies
        to_compute = set()
        for name in feature_names:
            key = f"{name}@{version}" if "@" not in name else name
            to_compute.add(key)

        results = {}
        for key in to_compute:
            defn = self._definitions.get(key)
            if defn is None:
                # Try without version
                name = key.split("@")[0]
                defn = self._definitions.get(f"{name}@{version}")
            if defn is None:
                continue
            try:
                results[defn.name] = defn.compute_fn(data)
            except Exception as e:
                results[defn.name] = pd.Series(
                    np.nan, index=data.index, name=defn.name,
                )
                results[defn.name].attrs["error"] = str(e)

        feature_df = pd.DataFrame(results, index=data.index)

        # Track source data last date for freshness monitoring (Gap #36)
        source_last = None
        if hasattr(data.index, "max"):
            try:
                source_last = str(data.index.max())
            except Exception:
                source_last = None

        # Check if any features had errors
        has_errors = any(
            isinstance(results.get(c), pd.Series) and "error" in results[c].attrs
            for c in results
        )

        return FeatureSet(
            name="default",
            version=version,
            features=feature_df,
            source_data_last_date=source_last,
            has_errors=has_errors,
        )

    def cache(self, feature_set: FeatureSet, key: str | None = None) -> str:
        """Cache a computed feature set.

        Args:
            feature_set: Feature set to cache.
            key: Optional cache key.

        Returns:
            Cache key used.
        """
        cache_key = key or f"{feature_set.name}@{feature_set.version}"
        self._cache[cache_key] = feature_set
        return cache_key

    def get_cached(self, key: str) -> FeatureSet | None:
        """Retrieve a cached feature set."""
        return self._cache.get(key)

    @property
    def registered_features(self) -> list[str]:
        """List registered feature names."""
        return list(self._definitions.keys())

    # ── Freshness Monitoring (Gap #36) ──────────────────────────────────────

    def check_freshness(self, cache_key: str) -> FreshnessReport:
        """Check freshness of a cached feature set.

        Args:
            cache_key: Cache key returned by cache().

        Returns:
            FreshnessReport with status and age info.
        """
        fs = self._cache.get(cache_key)
        if fs is None:
            return FreshnessReport(
                cache_key=cache_key,
                status=FreshnessStatus.MISSING,
                computed_at=None,
                age_hours=None,
                source_data_last_date=None,
                source_age_hours=None,
                message=f"Feature set '{cache_key}' not in cache.",
            )

        if fs.has_errors:
            return FreshnessReport(
                cache_key=cache_key,
                status=FreshnessStatus.ERROR,
                computed_at=fs.computed_at,
                age_hours=self._age_hours(fs.computed_at),
                source_data_last_date=fs.source_data_last_date,
                source_age_hours=self._age_hours(fs.source_data_last_date),
                message="Feature set has computation errors.",
            )

        age = self._age_hours(fs.computed_at)
        if age is None:
            return FreshnessReport(
                cache_key=cache_key,
                status=FreshnessStatus.ERROR,
                computed_at=fs.computed_at,
                age_hours=None,
                source_data_last_date=fs.source_data_last_date,
                source_age_hours=self._age_hours(fs.source_data_last_date),
                message="Cannot parse computed_at timestamp.",
            )

        max_h = self._max_fresh_age.total_seconds() / 3600
        if age < max_h:
            status = FreshnessStatus.FRESH
            msg = f"Fresh ({age:.1f}h < {max_h:.0f}h threshold)."
        elif age < 2 * max_h:
            status = FreshnessStatus.STALE
            msg = f"Stale ({age:.1f}h >= {max_h:.0f}h threshold)."
        else:
            status = FreshnessStatus.EXPIRED
            msg = f"Expired ({age:.1f}h >= {2 * max_h:.0f}h)."

        return FreshnessReport(
            cache_key=cache_key,
            status=status,
            computed_at=fs.computed_at,
            age_hours=age,
            source_data_last_date=fs.source_data_last_date,
            source_age_hours=self._age_hours(fs.source_data_last_date),
            message=msg,
        )

    def check_all_freshness(self) -> list[FreshnessReport]:
        """Check freshness of all cached feature sets.

        Returns:
            List of FreshnessReport for each cached key.
        """
        return [self.check_freshness(k) for k in self._cache]

    def get_stale_keys(self) -> list[str]:
        """Get cache keys for stale or expired feature sets.

        Returns:
            List of cache keys that are STALE or EXPIRED.
        """
        reports = self.check_all_freshness()
        return [
            r.cache_key for r in reports
            if r.status in (FreshnessStatus.STALE, FreshnessStatus.EXPIRED)
        ]

    def evict_stale(self) -> int:
        """Evict all stale and expired feature sets from cache.

        Returns:
            Number of evicted entries.
        """
        keys = self.get_stale_keys()
        for k in keys:
            self._cache.pop(k, None)
        return len(keys)

    @staticmethod
    def _age_hours(timestamp: str | None) -> float | None:
        """Compute age in hours from an ISO timestamp string."""
        if not timestamp:
            return None
        try:
            ts = datetime.fromisoformat(timestamp)
        except (ValueError, TypeError):
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return (datetime.now(UTC) - ts).total_seconds() / 3600
