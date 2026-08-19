"""Fetch Registry — database-as-source-of-truth for data fetching.

Every module/engine must query this registry before fetching data.
The registry reads from the `instruments` table which has:
  - data_layer: idx_equity, global_index, commodity, fx, macro_rate, etf, etc.
  - fetch_frequency: EOD, INTRADAY_15M, WEEKLY, MONTHLY
  - last_fetch_at: when data was last fetched
  - next_fetch_at: when next fetch should happen
  - fetch_status: OK, STALE, FAILED, PAUSED, NEVER_FETCHED
  - data_source_type: yahoo_finance, idx_co_id, pirana_api, sectors_api, etc.
  - data_source_url: endpoint URL for fetching
  - data_source_fallback: fallback source if primary fails
  - fetch_adapter: which adapter module to use (YahooFinanceAdapter, IDXOfficialAdapter)
  - data_source_metadata: JSON with adapter-specific config (interval, period, etc.)
  - delisting_reason: why instrument was delisted (if applicable)
  - merged_to_ticker: successor ticker if company merged

Usage:
    from quant.data.fetch_registry import FetchRegistry
    registry = FetchRegistry(session)

    # What needs fetching now?
    pending = registry.get_pending_fetches("commodity")
    for item in pending:
        print(f"{item.ticker} adapter={item.fetch_adapter} source={item.data_source_type}")
        print(f"  url={item.data_source_url} fallback={item.data_source_fallback}")

    # Mark as fetched
    registry.mark_fetched("GC=F", rows=4)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Fetch frequency → interval mapping
FREQUENCY_INTERVAL: dict[str, timedelta] = {
    "EOD": timedelta(days=1),
    "INTRADAY_15M": timedelta(minutes=15),
    "WEEKLY": timedelta(weeks=1),
    "MONTHLY": timedelta(days=30),
}


class FetchItem:
    """A single instrument's fetch metadata from DB."""

    __slots__ = (
        "ticker", "exchange_mic", "currency", "data_layer",
        "fetch_frequency", "last_fetch_at", "next_fetch_at",
        "fetch_status", "name", "sector",
        "data_source_type", "data_source_url", "data_source_fallback",
        "fetch_adapter", "data_source_metadata",
        "delisting_reason", "merged_to_ticker",
    )

    def __init__(self, row: tuple) -> None:
        (
            self.ticker,
            self.exchange_mic,
            self.currency,
            self.data_layer,
            self.fetch_frequency,
            self.last_fetch_at,
            self.next_fetch_at,
            self.fetch_status,
            self.name,
            self.sector,
            self.data_source_type,
            self.data_source_url,
            self.data_source_fallback,
            self.fetch_adapter,
            self.data_source_metadata,
            self.delisting_reason,
            self.merged_to_ticker,
        ) = row

    def __repr__(self) -> str:
        return (
            f"FetchItem(ticker={self.ticker!r}, layer={self.data_layer}, "
            f"status={self.fetch_status}, last={self.last_fetch_at})"
        )


class FetchRegistry:
    """Query DB for fetch metadata — the single source of truth.

    All fetch pipelines must consult this before fetching.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_pending_fetches(
        self,
        data_layer: str | None = None,
        max_items: int | None = None,
    ) -> list[FetchItem]:
        """Get instruments that need fetching now.

        Args:
            data_layer: Filter by layer (idx_equity, global_index, commodity, etc.)
                        If None, returns all layers.
            max_items: Limit number of results.

        Returns:
            List of FetchItem for instruments where:
              - is_active = true
              - fetch_status in (STALE, NEVER_FETCHED, FAILED)
              - next_fetch_at IS NULL or next_fetch_at <= now()
        """
        from quant.db.models import Instrument

        now = datetime.now(UTC)

        stmt = select(
            Instrument.ticker,
            Instrument.exchange_mic,
            Instrument.currency,
            Instrument.data_layer,
            Instrument.fetch_frequency,
            Instrument.last_fetch_at,
            Instrument.next_fetch_at,
            Instrument.fetch_status,
            Instrument.name,
            Instrument.sector,
            Instrument.data_source_type,
            Instrument.data_source_url,
            Instrument.data_source_fallback,
            Instrument.fetch_adapter,
            Instrument.data_source_metadata,
            Instrument.delisting_reason,
            Instrument.merged_to_ticker,
        ).where(
            Instrument.is_active == True,  # noqa: E712
            Instrument.fetch_status.in_(["STALE", "NEVER_FETCHED", "FAILED"]),
        )

        if data_layer:
            stmt = stmt.where(Instrument.data_layer == data_layer)

        stmt = stmt.order_by(Instrument.fetch_status, Instrument.next_fetch_at)

        if max_items:
            stmt = stmt.limit(max_items)

        rows = self._session.execute(stmt).all()
        return [FetchItem(row) for row in rows]

    def get_by_layer(self, data_layer: str) -> list[FetchItem]:
        """Get all active instruments in a data layer, regardless of status."""
        from quant.db.models import Instrument

        stmt = select(
            Instrument.ticker,
            Instrument.exchange_mic,
            Instrument.currency,
            Instrument.data_layer,
            Instrument.fetch_frequency,
            Instrument.last_fetch_at,
            Instrument.next_fetch_at,
            Instrument.fetch_status,
            Instrument.name,
            Instrument.sector,
            Instrument.data_source_type,
            Instrument.data_source_url,
            Instrument.data_source_fallback,
            Instrument.fetch_adapter,
            Instrument.data_source_metadata,
            Instrument.delisting_reason,
            Instrument.merged_to_ticker,
        ).where(
            Instrument.is_active == True,  # noqa: E712
            Instrument.data_layer == data_layer,
        ).order_by(Instrument.ticker)

        rows = self._session.execute(stmt).all()
        return [FetchItem(row) for row in rows]

    def mark_fetched(
        self,
        ticker: str,
        rows: int = 0,
        status: str = "OK",
    ) -> None:
        """Mark an instrument as successfully fetched.

        Updates last_fetch_at, next_fetch_at, and fetch_status.
        """
        from quant.db.models import Instrument

        now = datetime.now(UTC)

        inst = self._session.execute(
            select(Instrument).where(Instrument.ticker == ticker)
        ).scalars().first()

        if not inst:
            logger.warning("mark_fetched: ticker %s not found", ticker)
            return

        freq = inst.fetch_frequency or "EOD"
        interval = FREQUENCY_INTERVAL.get(freq, timedelta(days=1))

        inst.last_fetch_at = now
        inst.next_fetch_at = now + interval
        inst.fetch_status = status

        self._session.flush()
        logger.debug(
            "mark_fetched: %s rows=%d status=%s next=%s",
            ticker, rows, status, inst.next_fetch_at,
        )

    def mark_failed(self, ticker: str, error: str = "") -> None:
        """Mark an instrument fetch as failed."""
        from quant.db.models import Instrument

        now = datetime.now(UTC)

        inst = self._session.execute(
            select(Instrument).where(Instrument.ticker == ticker)
        ).scalars().first()

        if not inst:
            return

        freq = inst.fetch_frequency or "EOD"
        interval = FREQUENCY_INTERVAL.get(freq, timedelta(days=1))

        inst.fetch_status = "FAILED"
        inst.next_fetch_at = now + interval
        self._session.flush()
        logger.warning("mark_failed: %s error=%s", ticker, error[:200])

    def get_stale_count(self, data_layer: str | None = None) -> int:
        """Count stale/never-fetched/failed instruments."""
        from quant.db.models import Instrument

        stmt = select(Instrument).where(
            Instrument.is_active == True,  # noqa: E712
            Instrument.fetch_status.in_(["STALE", "NEVER_FETCHED", "FAILED"]),
        )
        if data_layer:
            stmt = stmt.where(Instrument.data_layer == data_layer)

        return len(self._session.execute(stmt).scalars().all())

    def get_summary(self) -> dict[str, dict[str, int]]:
        """Get fetch status summary per data_layer.

        Returns:
            {data_layer: {status: count, ...}, ...}
        """
        from quant.db.models import Instrument
        from sqlalchemy import func

        stmt = select(
            Instrument.data_layer,
            Instrument.fetch_status,
            func.count().label("cnt"),
        ).where(
            Instrument.is_active == True,  # noqa: E712
        ).group_by(
            Instrument.data_layer, Instrument.fetch_status,
        ).order_by(Instrument.data_layer)

        result: dict[str, dict[str, int]] = {}
        for row in self._session.execute(stmt).all():
            layer, status, cnt = row
            if layer not in result:
                result[layer] = {}
            result[layer][status] = cnt

        return result
