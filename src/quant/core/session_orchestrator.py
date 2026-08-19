"""Global Market Timezone & Session Orchestrator.

DST-aware session status engine for all world exchanges.
Reads ``market_sessions`` table and computes real-time session status
(OPEN / PRE-MARKET / CLOSED / POST-MARKET) using ``zoneinfo`` for
accurate DST handling on both Windows and Linux.

Usage::

    from quant.core.session_orchestrator import GlobalSessionOrchestrator
    orch = GlobalSessionOrchestrator()
    status = orch.get_session_status("XIDX")
    # → {"market_code": "XIDX", "status": "OPEN", "open_wib": "09:00", ...}

    all_status = orch.get_all_sessions_status()
    # → [{"market_code": "XIDX", ...}, ...]

    orch.should_trigger_render("XIDX")  # True if just opened + 5 min
    orch.should_trigger_close("XIDX")   # True if just closed
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from quant.core.db import engine
from quant.core.pre_trade_guard import PreTradeGuard

log = logging.getLogger(__name__)

WIB = ZoneInfo("Asia/Jakarta")
UTC = timezone.utc

# Minutes after open to trigger data render
RENDER_DELAY_MINUTES = 5
# Minutes after close to trigger closing data fetch
CLOSE_DELAY_MINUTES = 2


class SessionStatus:
    OPEN = "OPEN"
    PRE_MARKET = "PRE-MARKET"
    CLOSED = "CLOSED"
    POST_MARKET = "POST-MARKET"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"


class GlobalSessionOrchestrator:
    """DST-aware global market session tracker.

    Reads session times from ``market_sessions`` table and computes
    real-time status using ``zoneinfo`` (IANA timezone database) for
    accurate DST handling on both Windows and Linux.
    """

    def __init__(self):
        self._guard = PreTradeGuard()

    def _load_sessions(self) -> list[dict]:
        """Load all market sessions from database."""
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT market_code, market_name, timezone_iana,
                       open_time_utc, close_time_utc,
                       open_time_wib, close_time_wib,
                       timezone_offset_hours, has_dst,
                       pre_market_open_utc, post_market_close_utc,
                       is_active
                FROM market_sessions
                WHERE is_active = TRUE
                ORDER BY open_time_utc
            """)).fetchall()

        return [
            {
                "market_code": r[0],
                "market_name": r[1],
                "timezone_iana": r[2],
                "open_time_utc": r[3],
                "close_time_utc": r[4],
                "open_time_wib": r[5],
                "close_time_wib": r[6],
                "timezone_offset_hours": float(r[7]),
                "has_dst": r[8],
                "pre_market_open_utc": r[9],
                "post_market_close_utc": r[10],
                "is_active": r[11],
            }
            for r in rows
        ]

    def _get_current_utc_times(self, now_utc: datetime) -> time:
        """Extract time portion in UTC."""
        return now_utc.time()

    def _is_weekend(self, dt: datetime) -> bool:
        return dt.weekday() >= 5

    def _compute_dst_adjusted_times(
        self, session: dict, now_utc: datetime
    ) -> tuple[time, time]:
        """Compute DST-adjusted open/close times in UTC.

        For exchanges with DST, the stored UTC times are winter (standard)
        times. During summer/DST, the local market still opens at the same
        local time, but UTC shifts by 1 hour.

        We use zoneinfo to compute the actual current UTC offset and adjust.
        """
        open_utc = session["open_time_utc"]
        close_utc = session["close_time_utc"]

        if not session["has_dst"]:
            return open_utc, close_utc

        # Compute current UTC offset for the exchange's timezone
        tz = ZoneInfo(session["timezone_iana"])
        local_now = now_utc.astimezone(tz)
        current_offset = local_now.utcoffset().total_seconds() / 3600

        # Stored offset is winter (standard) offset
        stored_offset = session["timezone_offset_hours"]

        # Shift = stored - current (when DST active, current > stored, shift is negative)
        # This makes UTC times earlier during DST (local open stays same, UTC decreases)
        shift_hours = stored_offset - current_offset

        if shift_hours == 0:
            return open_utc, close_utc

        # Shift times
        def shift(t: time, hours: float) -> time:
            dt = datetime(2000, 1, 1, t.hour, t.minute, t.second)
            dt += timedelta(hours=hours)
            return dt.time()

        return shift(open_utc, shift_hours), shift(close_utc, shift_hours)

    def get_session_status(
        self, market_code: str, now_utc: datetime | None = None
    ) -> dict:
        """Get real-time session status for a single market.

        Returns dict with:
            market_code, market_name, status, open_time_utc, close_time_utc,
            open_time_wib, close_time_wib, current_time_utc, current_time_wib,
            timezone_iana, has_dst, current_offset_hours
        """
        if now_utc is None:
            now_utc = datetime.now(UTC)

        sessions = self._load_sessions()
        sess = next((s for s in sessions if s["market_code"] == market_code), None)
        if sess is None:
            return {"market_code": market_code, "status": SessionStatus.CLOSED, "error": "not found"}

        # Check weekend
        if self._is_weekend(now_utc):
            return self._build_status(sess, now_utc, SessionStatus.WEEKEND)

        # Check holiday
        today = now_utc.date()
        if not self._guard.is_market_open(market_code, today):
            return self._build_status(sess, now_utc, SessionStatus.HOLIDAY)

        # Compute DST-adjusted times
        adj_open, adj_close = self._compute_dst_adjusted_times(sess, now_utc)

        current_time = now_utc.time()

        # Handle sessions that cross midnight (e.g., XASX 23:00→05:00 UTC)
        if adj_close <= adj_open:
            # Session crosses midnight
            is_open = current_time >= adj_open or current_time < adj_close
        else:
            is_open = adj_open <= current_time < adj_close

        # Pre-market check
        pre_open = sess.get("pre_market_open_utc")
        in_pre_market = False
        if pre_open is not None:
            if adj_close <= adj_open:
                in_pre_market = pre_open <= current_time < adj_open
            else:
                in_pre_market = pre_open <= current_time < adj_open

        # Post-market check
        post_close = sess.get("post_market_close_utc")
        in_post_market = False
        if post_close is not None:
            if adj_close <= adj_open:
                in_post_market = adj_close <= current_time < post_close
            else:
                in_post_market = adj_close <= current_time < post_close

        if is_open:
            status = SessionStatus.OPEN
        elif in_pre_market:
            status = SessionStatus.PRE_MARKET
        elif in_post_market:
            status = SessionStatus.POST_MARKET
        else:
            status = SessionStatus.CLOSED

        return self._build_status(sess, now_utc, status, adj_open, adj_close)

    def _build_status(
        self, sess: dict, now_utc: datetime, status: str,
        adj_open: time | None = None, adj_close: time | None = None,
    ) -> dict:
        """Build the status response dict."""
        now_wib = now_utc.astimezone(WIB)
        tz = ZoneInfo(sess["timezone_iana"])
        local_now = now_utc.astimezone(tz)
        current_offset = local_now.utcoffset().total_seconds() / 3600

        return {
            "market_code": sess["market_code"],
            "market_name": sess["market_name"],
            "status": status,
            "open_time_utc": str(adj_open or sess["open_time_utc"])[:8],
            "close_time_utc": str(adj_close or sess["close_time_utc"])[:8],
            "open_time_wib": str(sess["open_time_wib"])[:8],
            "close_time_wib": str(sess["close_time_wib"])[:8],
            "current_time_utc": now_utc.strftime("%H:%M:%S"),
            "current_time_wib": now_wib.strftime("%H:%M:%S"),
            "current_time_local": local_now.strftime("%H:%M:%S"),
            "timezone_iana": sess["timezone_iana"],
            "has_dst": sess["has_dst"],
            "current_offset_hours": current_offset,
            "is_dst_active": sess["has_dst"] and current_offset != sess["timezone_offset_hours"],
        }

    def get_all_sessions_status(self, now_utc: datetime | None = None) -> list[dict]:
        """Get session status for all active markets, sorted by open time."""
        if now_utc is None:
            now_utc = datetime.now(UTC)

        sessions = self._load_sessions()
        results = []
        for sess in sessions:
            mc = sess["market_code"]

            # Check weekend
            if self._is_weekend(now_utc):
                results.append(self._build_status(sess, now_utc, SessionStatus.WEEKEND))
                continue

            # Check holiday
            today = now_utc.date()
            if not self._guard.is_market_open(mc, today):
                results.append(self._build_status(sess, now_utc, SessionStatus.HOLIDAY))
                continue

            adj_open, adj_close = self._compute_dst_adjusted_times(sess, now_utc)
            current_time = now_utc.time()

            if adj_close <= adj_open:
                is_open = current_time >= adj_open or current_time < adj_close
            else:
                is_open = adj_open <= current_time < adj_close

            pre_open = sess.get("pre_market_open_utc")
            in_pre = pre_open is not None and pre_open <= current_time < adj_open

            post_close = sess.get("post_market_close_utc")
            in_post = post_close is not None and adj_close <= current_time < post_close

            if is_open:
                status = SessionStatus.OPEN
            elif in_pre:
                status = SessionStatus.PRE_MARKET
            elif in_post:
                status = SessionStatus.POST_MARKET
            else:
                status = SessionStatus.CLOSED

            results.append(self._build_status(sess, now_utc, status, adj_open, adj_close))

        return results

    def get_open_markets(self, now_utc: datetime | None = None) -> list[str]:
        """Return list of market codes currently OPEN."""
        if now_utc is None:
            now_utc = datetime.now(UTC)
        all_status = self.get_all_sessions_status(now_utc)
        return [s["market_code"] for s in all_status if s["status"] == SessionStatus.OPEN]

    def should_trigger_render(self, market_code: str, now_utc: datetime | None = None) -> bool:
        """True if market just opened RENDER_DELAY_MINUTES ago — trigger data render."""
        if now_utc is None:
            now_utc = datetime.now(UTC)

        sess = next(
            (s for s in self._load_sessions() if s["market_code"] == market_code), None
        )
        if sess is None:
            return False

        if self._is_weekend(now_utc):
            return False
        if not self._guard.is_market_open(market_code, now_utc.date()):
            return False

        adj_open, _ = self._compute_dst_adjusted_times(sess, now_utc)
        current_time = now_utc.time()

        # Check if we're within RENDER_DELAY_MINUTES after open
        open_dt = datetime.combine(now_utc.date(), adj_open)
        render_start = open_dt + timedelta(minutes=RENDER_DELAY_MINUTES)
        render_end = open_dt + timedelta(minutes=RENDER_DELAY_MINUTES + 5)

        return render_start.time() <= current_time <= render_end.time()

    def should_trigger_close(self, market_code: str, now_utc: datetime | None = None) -> bool:
        """True if market just closed CLOSE_DELAY_MINUTES ago — trigger closing data fetch."""
        if now_utc is None:
            now_utc = datetime.now(UTC)

        sess = next(
            (s for s in self._load_sessions() if s["market_code"] == market_code), None
        )
        if sess is None:
            return False

        if self._is_weekend(now_utc):
            return False
        if not self._guard.is_market_open(market_code, now_utc.date()):
            return False

        _, adj_close = self._compute_dst_adjusted_times(sess, now_utc)
        current_time = now_utc.time()

        close_dt = datetime.combine(now_utc.date(), adj_close)
        fetch_start = close_dt + timedelta(minutes=CLOSE_DELAY_MINUTES)
        fetch_end = close_dt + timedelta(minutes=CLOSE_DELAY_MINUTES + 5)

        return fetch_start.time() <= current_time <= fetch_end.time()

    def get_next_event(self, market_code: str, now_utc: datetime | None = None) -> dict:
        """Get next session event (open or close) for a market."""
        if now_utc is None:
            now_utc = datetime.now(UTC)

        status = self.get_session_status(market_code, now_utc)

        if status["status"] == SessionStatus.OPEN:
            return {
                "event": "close",
                "time_utc": status["close_time_utc"],
                "time_wib": status["close_time_wib"],
                "minutes_until": self._minutes_until(status["close_time_utc"], now_utc),
            }
        else:
            return {
                "event": "open",
                "time_utc": status["open_time_utc"],
                "time_wib": status["open_time_wib"],
                "minutes_until": self._minutes_until(status["open_time_utc"], now_utc),
            }

    def _minutes_until(self, time_str: str, now_utc: datetime) -> int:
        """Estimate minutes until a given UTC time string."""
        h, m, s = time_str.split(":")
        target_time = time(int(h), int(m), int(s))
        now_time = now_utc.time()

        if target_time > now_time:
            diff = datetime.combine(now_utc.date(), target_time) - datetime.combine(now_utc.date(), now_time)
        else:
            diff = datetime.combine(now_utc.date() + timedelta(days=1), target_time) - datetime.combine(now_utc.date(), now_time)

        return int(diff.total_seconds() / 60)

    def log_all_status(self, now_utc: datetime | None = None):
        """Log a comprehensive status table of all markets."""
        if now_utc is None:
            now_utc = datetime.now(UTC)

        all_status = self.get_all_sessions_status(now_utc)
        now_wib = now_utc.astimezone(WIB)

        log.info("=" * 80)
        log.info("GLOBAL MARKET STATUS — UTC: %s | WIB: %s", now_utc.strftime("%H:%M:%S"), now_wib.strftime("%H:%M:%S"))
        log.info("=" * 80)

        for s in all_status:
            icon = {
                SessionStatus.OPEN: "🟢",
                SessionStatus.PRE_MARKET: "🟡",
                SessionStatus.POST_MARKET: "🟠",
                SessionStatus.CLOSED: "⚫",
                SessionStatus.HOLIDAY: "🔴",
                SessionStatus.WEEKEND: "🔴",
            }.get(s["status"], "❓")

            dst_flag = " (DST)" if s.get("is_dst_active") else ""
            log.info(
                "%s %-8s %-25s %-12s UTC %s-%s WIB %s-%s%s",
                icon, s["market_code"], s["market_name"][:25],
                s["status"], s["open_time_utc"][:5], s["close_time_utc"][:5],
                s["open_time_wib"][:5], s["close_time_wib"][:5], dst_flag,
            )

        open_count = sum(1 for s in all_status if s["status"] == SessionStatus.OPEN)
        log.info("=" * 80)
        log.info("Summary: %d OPEN / %d total", open_count, len(all_status))
        log.info("=" * 80)
