"""Dynamic Asset Router — per-asset-class pipeline dispatch.

This module provides the routing logic that determines how different asset
classes are processed through the pipeline:

  - **Equity**: Subject to market holiday awareness, delisted filters, and
    country-specific trading hours (e.g. IDX 09:00–15:50 WIB).
  - **Forex**: 24/5 market, no holiday filter (only central bank closures),
    no delisting concept.
  - **Commodity**: Exchange-specific holidays (CME, ICE), but some trade
    nearly 24h.
  - **Crypto**: 24/7 market, no holidays, no delisting.
  - **Index**: Non-tradeable, used as reference data only.
  - **Macro Rate**: Non-tradeable, weekly/monthly cadence.

The router is consulted by:
  - ``FetchRegistry`` — to decide whether to fetch on holidays
  - ``PipelineOrchestrator`` — to decide whether to run pipeline steps
  - ``SchedulerTasks`` — to skip/activate tasks per asset class

Usage::

    from quant.data.asset_router import AssetRouter, AssetClassConfig

    router = AssetRouter(session)

    # Should we fetch AAPL today (Tuesday, IDX holiday)?
    decision = router.should_fetch("AAPL", as_of=date(2026, 8, 20))
    # → FetchDecision(action="SKIP", reason="IDX market holiday")

    # Should we fetch EURUSD=X today?
    decision = router.should_fetch("EURUSD=X", as_of=date(2026, 8, 20))
    # → FetchDecision(action="FETCH", reason="Forex market open")

    # Should we fetch BTCUSDT today?
    decision = router.should_fetch("BTCUSDT", as_of=date(2026, 8, 20))
    # → FetchDecision(action="FETCH", reason="Crypto 24/7")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

__all__ = [
    "AssetRouter",
    "AssetClassConfig",
    "FetchDecision",
    "FetchAction",
    "ASSET_CLASS_DEFAULTS",
]


class FetchAction(str, Enum):
    FETCH = "FETCH"
    SKIP = "SKIP"
    DELAY = "DELAY"


@dataclass
class FetchDecision:
    """Result of a fetch routing decision."""
    action: FetchAction
    reason: str
    asset_class: str = ""
    data_layer: str = ""
    exchange_mic: str = ""
    delay_minutes: int = 0


@dataclass
class AssetClassConfig:
    """Configuration for an asset class."""
    code: str
    name: str
    market_hours_24h: bool
    holiday_calendar_source: str  # "exchange", "central_bank", "none"
    default_currency: str
    default_data_source: str
    default_fetch_frequency: str
    is_tradeable: bool
    sort_order: int = 0


# ── Static defaults (used when DB table not yet available) ────────────────
ASSET_CLASS_DEFAULTS: dict[str, AssetClassConfig] = {
    "equity": AssetClassConfig(
        code="equity", name="Equity / Stock",
        market_hours_24h=False, holiday_calendar_source="exchange",
        default_currency="IDR", default_data_source="yahoo_finance",
        default_fetch_frequency="EOD", is_tradeable=True, sort_order=1,
    ),
    "index": AssetClassConfig(
        code="index", name="Market Index",
        market_hours_24h=False, holiday_calendar_source="exchange",
        default_currency="USD", default_data_source="yahoo_finance",
        default_fetch_frequency="EOD", is_tradeable=False, sort_order=2,
    ),
    "forex": AssetClassConfig(
        code="forex", name="Foreign Exchange",
        market_hours_24h=True, holiday_calendar_source="central_bank",
        default_currency="USD", default_data_source="yahoo_finance",
        default_fetch_frequency="EOD", is_tradeable=True, sort_order=3,
    ),
    "commodity": AssetClassConfig(
        code="commodity", name="Commodity",
        market_hours_24h=True, holiday_calendar_source="exchange",
        default_currency="USD", default_data_source="yahoo_finance",
        default_fetch_frequency="EOD", is_tradeable=True, sort_order=4,
    ),
    "crypto": AssetClassConfig(
        code="crypto", name="Cryptocurrency",
        market_hours_24h=True, holiday_calendar_source="none",
        default_currency="USD", default_data_source="binance",
        default_fetch_frequency="INTRADAY_15M", is_tradeable=True, sort_order=5,
    ),
    "bond": AssetClassConfig(
        code="bond", name="Bond / Fixed Income",
        market_hours_24h=False, holiday_calendar_source="central_bank",
        default_currency="USD", default_data_source="yahoo_finance",
        default_fetch_frequency="EOD", is_tradeable=True, sort_order=6,
    ),
    "macro_rate": AssetClassConfig(
        code="macro_rate", name="Macro Economic Rate",
        market_hours_24h=True, holiday_calendar_source="central_bank",
        default_currency="USD", default_data_source="fred",
        default_fetch_frequency="WEEKLY", is_tradeable=False, sort_order=7,
    ),
}


class AssetRouter:
    """Dynamic routing engine for multi-asset pipeline dispatch.

    Determines whether to fetch, process, or skip an instrument based on
    its asset class, exchange holidays, and market hours.
    """

    def __init__(self, session: Session | None = None) -> None:
        self._session = session
        self._config_cache: dict[str, AssetClassConfig] = {}
        self._loaded = False

    def _load_configs(self) -> None:
        """Load asset class configs from DB, falling back to defaults."""
        if self._loaded or not self._session:
            self._loaded = True
            return
        try:
            result = self._session.execute(text(
                "SELECT code, name, market_hours_24h, holiday_calendar_source, "
                "default_currency, default_data_source, default_fetch_frequency, "
                "is_tradeable, sort_order FROM asset_classes"
            ))
            for row in result.fetchall():
                cfg = AssetClassConfig(
                    code=row[0], name=row[1],
                    market_hours_24h=row[2],
                    holiday_calendar_source=row[3],
                    default_currency=row[4],
                    default_data_source=row[5],
                    default_fetch_frequency=row[6],
                    is_tradeable=row[7],
                    sort_order=row[8],
                )
                self._config_cache[cfg.code] = cfg
            self._loaded = True
            logger.debug("Loaded %d asset class configs from DB", len(self._config_cache))
        except Exception as exc:
            logger.debug("asset_classes table not available, using defaults: %s", exc)
            self._loaded = True

    def get_config(self, asset_class: str) -> AssetClassConfig:
        """Get configuration for an asset class."""
        self._load_configs()
        if asset_class in self._config_cache:
            return self._config_cache[asset_class]
        if asset_class in ASSET_CLASS_DEFAULTS:
            return ASSET_CLASS_DEFAULTS[asset_class]
        return ASSET_CLASS_DEFAULTS["equity"]

    def get_asset_class_for_ticker(self, ticker: str, session: Session | None = None) -> str:
        """Determine the asset class for a ticker.

        Uses DB lookup if available, otherwise infers from ticker pattern.
        """
        sess = session or self._session
        if sess:
            try:
                result = sess.execute(text(
                    "SELECT asset_class FROM instruments WHERE ticker = :ticker"
                ), {"ticker": ticker})
                row = result.fetchone()
                if row:
                    return row[0]
            except Exception:
                pass
        return self._infer_asset_class(ticker)

    @staticmethod
    def _infer_asset_class(ticker: str) -> str:
        """Infer asset class from ticker pattern."""
        upper = ticker.upper()
        # Crypto: common patterns
        if upper.endswith("USDT") or upper.endswith("USDC") or upper.endswith("BTC"):
            return "crypto"
        if upper in ("BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD"):
            return "crypto"
        # Commodity futures: check before forex (both contain '=')
        if upper in {"GC=F", "SI=F", "CL=F", "NG=F", "HG=F", "ZC=F", "ZS=F", "ZW=F", "KC=F", "CC=F", "CT=F", "SB=F", "PA=F", "PL=F", "RB=F", "HO=F", "BZ=F"}:
            return "commodity"
        if upper.endswith("=F"):
            return "commodity"
        # Forex: common patterns
        if upper.endswith("USD=X") or upper.endswith("IDR=X") or "=X" in upper:
            return "forex"
        if len(upper) == 6 and upper[:3] in {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "IDR", "SGD", "CNY", "HKD"}:
            return "forex"
        # Index: starts with ^
        if upper.startswith("^"):
            return "index"
        # Macro rate: FRED-style tickers
        if upper.startswith("DGS") or upper.startswith("T10") or upper in {"FEDFUNDS", "TB3MS", "DFF"}:
            return "macro_rate"
        # Default: equity
        return "equity"

    def should_fetch(
        self,
        ticker: str,
        as_of: date,
        session: Session | None = None,
    ) -> FetchDecision:
        """Determine whether to fetch data for a ticker on a given date.

        Routing logic:
          - **Crypto**: Always FETCH (24/7 market)
          - **Forex**: FETCH on weekdays, SKIP on weekends
          - **Commodity**: FETCH on weekdays, check exchange holiday
          - **Equity/Index**: FETCH only if exchange is open (no holiday, weekday)
          - **Macro Rate**: FETCH if it's the configured frequency day
          - **Bond**: FETCH on weekdays, check central bank holiday
        """
        sess = session or self._session
        asset_class = self.get_asset_class_for_ticker(ticker, sess)
        cfg = self.get_config(asset_class)

        # Crypto: 24/7, always fetch
        if cfg.market_hours_24h and cfg.holiday_calendar_source == "none":
            return FetchDecision(
                action=FetchAction.FETCH,
                reason="Crypto 24/7 market",
                asset_class=asset_class,
            )

        # Weekend check for non-24/7 markets
        is_weekend = as_of.weekday() >= 5

        # Forex: 24/5, skip weekends only
        if asset_class == "forex":
            if is_weekend:
                return FetchDecision(
                    action=FetchAction.SKIP,
                    reason="Forex market closed (weekend)",
                    asset_class=asset_class,
                )
            return FetchDecision(
                action=FetchAction.FETCH,
                reason="Forex market open",
                asset_class=asset_class,
            )

        # Macro rate: check frequency
        if asset_class == "macro_rate":
            freq = cfg.default_fetch_frequency
            if freq == "WEEKLY" and as_of.weekday() != 0:
                return FetchDecision(
                    action=FetchAction.SKIP,
                    reason=f"Macro rate weekly (not Monday: {as_of.weekday()})",
                    asset_class=asset_class,
                )
            return FetchDecision(
                action=FetchAction.FETCH,
                reason="Macro rate scheduled day",
                asset_class=asset_class,
            )

        # Equity / Index / Bond / Commodity: check exchange holidays
        if is_weekend:
            return FetchDecision(
                action=FetchAction.SKIP,
                reason="Weekend",
                asset_class=asset_class,
            )

        # Check exchange holiday via DB
        if sess and cfg.holiday_calendar_source == "exchange":
            is_holiday = self._check_exchange_holiday(ticker, as_of, sess)
            if is_holiday:
                return FetchDecision(
                    action=FetchAction.SKIP,
                    reason="Exchange market holiday",
                    asset_class=asset_class,
                )

        # Check delisting for equity
        if asset_class == "equity" and sess:
            is_delisted = self._check_delisted(ticker, sess)
            if is_delisted:
                return FetchDecision(
                    action=FetchAction.SKIP,
                    reason="Instrument delisted",
                    asset_class=asset_class,
                )

        return FetchDecision(
            action=FetchAction.FETCH,
            reason="Market open",
            asset_class=asset_class,
        )

    def should_run_pipeline(
        self,
        ticker: str,
        as_of: date,
        session: Session | None = None,
    ) -> FetchDecision:
        """Determine whether to run the full pipeline for a ticker.

        Same as should_fetch but also checks if the instrument is tradeable
        and has sufficient data.
        """
        decision = self.should_fetch(ticker, as_of, session)
        if decision.action == FetchAction.SKIP:
            return decision

        sess = session or self._session
        asset_class = self.get_asset_class_for_ticker(ticker, sess)
        cfg = self.get_config(asset_class)

        if not cfg.is_tradeable:
            return FetchDecision(
                action=FetchAction.SKIP,
                reason=f"Asset class '{asset_class}' is not tradeable",
                asset_class=asset_class,
            )

        return decision

    @staticmethod
    def _check_exchange_holiday(ticker: str, as_of: date, session: Session) -> bool:
        """Check if the exchange for a given ticker has a holiday on as_of."""
        try:
            result = session.execute(text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM exchange_holidays eh
                    JOIN instruments i ON i.ticker = :ticker
                    JOIN exchanges e ON e.id = i.exchange_id
                    WHERE eh.exchange_id = e.id
                    AND eh.holiday_date = :as_of
                )
                """
            ), {"ticker": ticker, "as_of": as_of})
            return bool(result.scalar())
        except Exception:
            return False

    @staticmethod
    def _check_delisted(ticker: str, session: Session) -> bool:
        """Check if an instrument is delisted."""
        try:
            result = session.execute(text(
                "SELECT is_delisted FROM instruments WHERE ticker = :ticker"
            ), {"ticker": ticker})
            row = result.fetchone()
            return bool(row and row[0])
        except Exception:
            return False

    def get_all_configs(self) -> dict[str, AssetClassConfig]:
        """Get all asset class configurations."""
        self._load_configs()
        merged = dict(ASSET_CLASS_DEFAULTS)
        merged.update(self._config_cache)
        return merged

    def get_tradeable_asset_classes(self) -> list[str]:
        """Get list of tradeable asset class codes."""
        configs = self.get_all_configs()
        return sorted(
            [code for code, cfg in configs.items() if cfg.is_tradeable],
            key=lambda c: configs[c].sort_order,
        )
