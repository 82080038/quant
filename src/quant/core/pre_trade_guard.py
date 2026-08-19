"""Global Pre-Trade Guard Clause — market holiday bypass engine.

Checks the ``market_holidays`` table before any exchange's pre-market
session. If the target exchange is on holiday, the system enters
**idle mode** for that exchange — blocking cron jobs, data ingestion,
and calculation modules to save bandwidth, RAM, and CPU.

Usage (cron, daily before pre-market)::

    from quant.core.pre_trade_guard import PreTradeGuard
    guard = PreTradeGuard()
    if guard.is_market_open("XIDX", as_of=date.today()):
        # ... run pipeline ...
    else:
        guard.log_idle_mode("XIDX")
        # skip all work for this exchange
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import text

from quant.core.db import get_db, engine

log = logging.getLogger(__name__)


class PreTradeGuard:
    """Check market holidays before executing any trading pipeline work."""

    def __init__(self, session=None):
        self._session = session
        self._engine = engine

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def is_market_open(self, market_code: str, as_of: date | None = None) -> bool:
        """Return ``True`` if *market_code* is open on *as_of* (default today).

        Checks the ``market_holidays`` table. Also falls back to the
        legacy ``exchange_holidays`` table for backward compatibility.
        """
        if as_of is None:
            as_of = date.today()

        # Skip weekends entirely
        if as_of.weekday() >= 5:
            return False

        # Check market_holidays (new table)
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM market_holidays
                        WHERE market_code = :mc AND holiday_date = :d
                        LIMIT 1
                    """),
                    {"mc": market_code, "d": as_of},
                ).first()
            if row is not None:
                return False
        except Exception:
            pass

        # Fallback: check exchange_holidays (legacy table via JOIN)
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM exchange_holidays eh
                        JOIN exchanges e ON eh.exchange_id = e.id
                        WHERE e.mic = :mc AND eh.holiday_date = :d
                        LIMIT 1
                    """),
                    {"mc": market_code, "d": as_of},
                ).first()
            if row is not None:
                return False
        except Exception:
            pass

        return True

    def get_holiday_name(self, market_code: str, as_of: date | None = None) -> str | None:
        """Return the holiday name if *as_of* is a holiday, else ``None``."""
        if as_of is None:
            as_of = date.today()

        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT holiday_name FROM market_holidays
                        WHERE market_code = :mc AND holiday_date = :d
                        LIMIT 1
                    """),
                    {"mc": market_code, "d": as_of},
                ).first()
            if row is not None:
                return row[0] or "Market Holiday"
        except Exception:
            pass

        # Fallback: legacy table
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT eh.name FROM exchange_holidays eh
                        JOIN exchanges e ON eh.exchange_id = e.id
                        WHERE e.mic = :mc AND eh.holiday_date = :d
                        LIMIT 1
                    """),
                    {"mc": market_code, "d": as_of},
                ).first()
            if row is not None:
                return row[0] or "Market Holiday"
        except Exception:
            pass

        return None

    def get_open_markets(self, as_of: date | None = None) -> list[str]:
        """Return list of market codes that are OPEN on *as_of*."""
        if as_of is None:
            as_of = date.today()

        if as_of.weekday() >= 5:
            return []

        try:
            with self._engine.connect() as conn:
                # All active exchanges minus those on holiday
                rows = conn.execute(
                    text("""
                        SELECT e.mic FROM exchanges e
                        WHERE e.is_active = TRUE
                        AND e.mic NOT IN (
                            SELECT market_code FROM market_holidays
                            WHERE holiday_date = :d
                        )
                        ORDER BY e.mic
                    """),
                    {"d": as_of},
                ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            # Fallback: just return all active exchanges
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text("SELECT mic FROM exchanges WHERE is_active = TRUE ORDER BY mic")
                    ).fetchall()
                return [r[0] for r in rows]
            except Exception:
                return []

    def get_closed_markets(self, as_of: date | None = None) -> list[tuple[str, str]]:
        """Return list of (market_code, holiday_name) for markets closed on *as_of*."""
        if as_of is None:
            as_of = date.today()

        if as_of.weekday() >= 5:
            # Weekend — all markets closed
            try:
                with self._engine.connect() as conn:
                    rows = conn.execute(
                        text("SELECT mic FROM exchanges WHERE is_active = TRUE ORDER BY mic")
                    ).fetchall()
                return [(r[0], "Weekend") for r in rows]
            except Exception:
                return []

        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT market_code, holiday_name
                        FROM market_holidays
                        WHERE holiday_date = :d
                        ORDER BY market_code
                    """),
                    {"d": as_of},
                ).fetchall()
            return [(r[0], r[1] or "Market Holiday") for r in rows]
        except Exception:
            return []

    def log_idle_mode(self, market_code: str, as_of: date | None = None):
        """Log that the system is entering idle mode for *market_code*."""
        if as_of is None:
            as_of = date.today()
        holiday_name = self.get_holiday_name(market_code, as_of) or "Unknown"
        log.info(
            "🛑 IDLE MODE — %s closed on %s (%s). "
            "Bypassing cron jobs, ingestion, and calculations to save resources.",
            market_code, as_of.isoformat(), holiday_name,
        )

    def log_market_status(self, as_of: date | None = None):
        """Log a comprehensive status of all markets for *as_of*."""
        if as_of is None:
            as_of = date.today()

        open_markets = self.get_open_markets(as_of)
        closed_markets = self.get_closed_markets(as_of)

        log.info("=" * 60)
        log.info("MARKET STATUS for %s", as_of.isoformat())
        log.info("=" * 60)

        if open_markets:
            log.info("🟢 OPEN: %s", ", ".join(open_markets))
        else:
            log.info("🟢 OPEN: (none)")

        if closed_markets:
            for mc, name in closed_markets:
                log.info("🔴 CLOSED: %s — %s", mc, name)
        else:
            log.info("🔴 CLOSED: (none)")

        log.info("=" * 60)

    def should_run_pipeline(self, market_code: str = "XIDX", as_of: date | None = None) -> bool:
        """Master guard: returns True only if market is open and pipeline should run."""
        if as_of is None:
            as_of = date.today()

        if not self.is_market_open(market_code, as_of):
            self.log_idle_mode(market_code, as_of)
            return False

        log.info("✅ %s is OPEN on %s — pipeline cleared for execution.", market_code, as_of.isoformat())
        return True

    def get_upcoming_holidays(
        self, market_code: str, days: int = 30, as_of: date | None = None
    ) -> list[tuple[date, str]]:
        """Return upcoming holidays for *market_code* within *days*."""
        if as_of is None:
            as_of = date.today()
        end = as_of + timedelta(days=days)

        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT holiday_date, holiday_name
                        FROM market_holidays
                        WHERE market_code = :mc
                          AND holiday_date > :d
                          AND holiday_date <= :end
                        ORDER BY holiday_date
                    """),
                    {"mc": market_code, "d": as_of, "end": end},
                ).fetchall()
            return [(r[0], r[1] or "Market Holiday") for r in rows]
        except Exception:
            return []
