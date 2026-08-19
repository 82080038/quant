"""Policy & Corporate Event Impact Scorer for IDX (pustaka/89, pustaka/10).

Scores the impact of policy and corporate events on Indonesian stock market
tickers. Supports market-wide events (BI/Fed rate decisions, geopolitical,
pandemic, election) and ticker-specific events (buyback, rights issue, stock
split, dividend, merger, earnings).

Design guarantees:
    - **No look-ahead bias**: only events with ``event_date <= as_of_date``
      contribute to ``compute_event_signal``. Future events are surfaced via
      ``get_upcoming_events`` and used to *reduce* confidence (uncertainty),
      never to inflate the score.
    - **CPU-only**: pure Python math, no GPU/network required.
    - Exponential decay: recent events weigh more than stale ones.

References:
    - pustaka/89-faktor-pasar-modal-analisis-implementasi.md
    - pustaka/10-regulasi-pasar-modal.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Policy or corporate event type."""

    BI_RATE_CUT = "bi_rate_cut"
    BI_RATE_HIKE = "bi_rate_hike"
    FED_RATE_CUT = "fed_rate_cut"
    FED_RATE_HIKE = "fed_rate_hike"
    BUYBACK = "buyback"
    RIGHTS_ISSUE = "rights_issue"
    STOCK_SPLIT = "stock_split"
    DIVIDEND = "dividend"
    MERGER = "merger"
    AUTO_REJECT_CHANGE = "auto_reject_change"
    GEOPOLITICAL = "geopolitical"
    TRADE_WAR = "trade_war"
    PANDEMIC = "pandemic"
    ELECTION = "election"
    EARNINGS_BEAT = "earnings_beat"
    EARNINGS_MISS = "earnings_miss"
    OTHER = "other"


class EventDirection(Enum):
    """Directional bias of an event."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class EventScope(Enum):
    """Scope of an event's impact."""

    MARKET_WIDE = "market_wide"
    TICKER_SPECIFIC = "ticker_specific"


# Default (direction, scope, base_impact) per event type.
# base_impact in [-100, +100]; positive = bullish, negative = bearish.
DEFAULT_IMPACTS: dict[EventType, tuple[EventDirection, EventScope, float]] = {
    EventType.BI_RATE_CUT: (EventDirection.BULLISH, EventScope.MARKET_WIDE, 30.0),
    EventType.BI_RATE_HIKE: (EventDirection.BEARISH, EventScope.MARKET_WIDE, -40.0),
    EventType.FED_RATE_CUT: (EventDirection.BULLISH, EventScope.MARKET_WIDE, 20.0),
    EventType.FED_RATE_HIKE: (EventDirection.BEARISH, EventScope.MARKET_WIDE, -25.0),
    EventType.BUYBACK: (EventDirection.BULLISH, EventScope.TICKER_SPECIFIC, 50.0),
    EventType.RIGHTS_ISSUE: (EventDirection.BEARISH, EventScope.TICKER_SPECIFIC, -45.0),
    EventType.STOCK_SPLIT: (EventDirection.BULLISH, EventScope.TICKER_SPECIFIC, 15.0),
    EventType.DIVIDEND: (EventDirection.BULLISH, EventScope.TICKER_SPECIFIC, 10.0),
    EventType.MERGER: (EventDirection.NEUTRAL, EventScope.TICKER_SPECIFIC, 20.0),
    EventType.AUTO_REJECT_CHANGE: (EventDirection.NEUTRAL, EventScope.MARKET_WIDE, 0.0),
    EventType.GEOPOLITICAL: (EventDirection.BEARISH, EventScope.MARKET_WIDE, -40.0),
    EventType.TRADE_WAR: (EventDirection.BEARISH, EventScope.MARKET_WIDE, -35.0),
    EventType.PANDEMIC: (EventDirection.BEARISH, EventScope.MARKET_WIDE, -50.0),
    EventType.ELECTION: (EventDirection.BEARISH, EventScope.MARKET_WIDE, -20.0),
    EventType.EARNINGS_BEAT: (EventDirection.BULLISH, EventScope.TICKER_SPECIFIC, 25.0),
    EventType.EARNINGS_MISS: (EventDirection.BEARISH, EventScope.TICKER_SPECIFIC, -30.0),
    EventType.OTHER: (EventDirection.NEUTRAL, EventScope.MARKET_WIDE, 0.0),
}


@dataclass
class EventImpact:
    """A single policy or corporate event with its impact parameters.

    Attributes:
        event_type: Category of the event (see :class:`EventType`).
        direction: Bullish/bearish/neutral bias.
        scope: Whether the event affects the whole market or one ticker.
        base_impact: Raw impact magnitude in [-100, +100] before decay.
        event_date: When the event occurred (or was announced).
        ticker: Affected ticker for TICKER_SPECIFIC events; ``None`` for
            MARKET_WIDE events.
        description: Human-readable description of the event.
    """

    event_type: EventType
    direction: EventDirection
    scope: EventScope
    base_impact: float
    event_date: datetime
    ticker: str | None = None
    description: str = ""


def event_decay(days_since: float, half_life: float = 10.0) -> float:
    """Exponential decay factor for an event ``days_since`` days old.

    Returns 1.0 at day 0, 0.5 at ``half_life`` days, 0.125 at 3*half_life days.

    Args:
        days_since: Elapsed days since the event date (>= 0).
        half_life: Days for the impact to halve. Default 10.

    Returns:
        Decay multiplier in (0.0, 1.0].
    """
    if days_since < 0:
        return 0.0
    return 0.5 ** (days_since / half_life)


@dataclass
class EventSignal:
    """Composite event-driven signal for a single ticker.

    Attributes:
        score: Weighted composite impact score (can be negative).
        direction: ``"bullish"`` if score > 5, ``"bearish"`` if < -5, else
            ``"neutral"``.
        confidence: Confidence in [0.0, 1.0], derived from ``abs(score)/100``.
        active_events: List of contributing events (dicts with metadata).
        market_wide_score: Sum of market-wide contributions.
        ticker_specific_score: Sum of ticker-specific contributions.
    """

    score: float
    direction: str
    confidence: float
    active_events: list[dict] = field(default_factory=list)
    market_wide_score: float = 0.0
    ticker_specific_score: float = 0.0


@dataclass
class UpcomingEvent:
    """A future event within the lookahead window.

    Attributes:
        event_type: Category of the event.
        event_date: Scheduled/expected date of the event.
        days_until: Days from ``as_of_date`` until ``event_date``.
        description: Human-readable description.
    """

    event_type: EventType
    event_date: datetime
    days_until: int
    description: str = ""


def compute_event_signal(
    ticker: str,
    events: list[EventImpact],
    as_of_date: datetime,
    half_life: float = 10.0,
) -> EventSignal:
    """Compute a composite event-driven signal for ``ticker`` as of ``as_of_date``.

    No look-ahead: only events with ``event_date <= as_of_date`` contribute.
    Market-wide events are weighted 0.3 per ticker (distributed effect);
    ticker-specific events are weighted 1.0 and only count when
    ``event.ticker == ticker``.

    Args:
        ticker: Target ticker (e.g. ``"BBCA.JK"``).
        events: List of :class:`EventImpact` instances (may include future
            events, which are filtered out).
        as_of_date: Evaluation cutoff date.
        half_life: Decay half-life in days (default 10).

    Returns:
        :class:`EventSignal` with composite score, direction, and confidence.
    """
    market_wide_score = 0.0
    ticker_specific_score = 0.0
    active_events: list[dict] = []

    for event in events:
        # No look-ahead: skip events that haven't happened yet.
        if event.event_date > as_of_date:
            continue

        days_since = (as_of_date - event.event_date).total_seconds() / 86400.0
        decay = event_decay(days_since, half_life=half_life)
        if decay <= 0.0:
            continue

        if event.scope is EventScope.MARKET_WIDE:
            weight = 0.3
            contribution = event.base_impact * decay * weight
            market_wide_score += contribution
            active_events.append({
                "event_type": event.event_type.value,
                "direction": event.direction.value,
                "scope": event.scope.value,
                "days_since": round(days_since, 2),
                "decay": round(decay, 4),
                "weight": weight,
                "contribution": round(contribution, 4),
                "description": event.description,
            })
        elif event.scope is EventScope.TICKER_SPECIFIC:
            # Only affects the target ticker.
            if event.ticker is None or event.ticker != ticker:
                continue
            weight = 1.0
            contribution = event.base_impact * decay * weight
            ticker_specific_score += contribution
            active_events.append({
                "event_type": event.event_type.value,
                "direction": event.direction.value,
                "scope": event.scope.value,
                "ticker": event.ticker,
                "days_since": round(days_since, 2),
                "decay": round(decay, 4),
                "weight": weight,
                "contribution": round(contribution, 4),
                "description": event.description,
            })

    score = market_wide_score + ticker_specific_score

    if score > 5:
        direction = "bullish"
    elif score < -5:
        direction = "bearish"
    else:
        direction = "neutral"

    confidence = min(1.0, abs(score) / 100.0)

    return EventSignal(
        score=round(score, 4),
        direction=direction,
        confidence=round(confidence, 4),
        active_events=active_events,
        market_wide_score=round(market_wide_score, 4),
        ticker_specific_score=round(ticker_specific_score, 4),
    )


def get_upcoming_events(
    events: list[EventImpact],
    as_of_date: datetime,
    lookahead_days: int = 14,
) -> list[UpcomingEvent]:
    """Return events scheduled within ``(as_of_date, as_of_date + lookahead_days]``.

    Args:
        events: List of :class:`EventImpact` instances.
        as_of_date: Evaluation cutoff date.
        lookahead_days: How many days forward to scan (default 14).

    Returns:
        List of :class:`UpcomingEvent` sorted by ``days_until`` ascending.
    """
    horizon = as_of_date + timedelta(days=lookahead_days)
    upcoming: list[UpcomingEvent] = []
    for event in events:
        if as_of_date < event.event_date <= horizon:
            days_until = (event.event_date - as_of_date).days
            upcoming.append(UpcomingEvent(
                event_type=event.event_type,
                event_date=event.event_date,
                days_until=days_until,
                description=event.description,
            ))
    upcoming.sort(key=lambda e: e.days_until)
    return upcoming


def pre_event_confidence_reduction(
    upcoming_events: list[UpcomingEvent],
    reduction_per_day: float = 0.02,
) -> float:
    """Compute a confidence multiplier accounting for imminent upcoming events.

    For each upcoming event within 7 days, confidence is reduced by
    ``(7 - days_until) * reduction_per_day``. The aggregate multiplier is
    clamped to ``[0.8, 1.0]``.

    Args:
        upcoming_events: Output of :func:`get_upcoming_events`.
        reduction_per_day: Confidence reduction per day of proximity
            (default 0.02).

    Returns:
        Float multiplier in [0.8, 1.0].
    """
    total_reduction = 0.0
    for event in upcoming_events:
        if 0 <= event.days_until <= 7:
            total_reduction += (7 - event.days_until) * reduction_per_day
    multiplier = 1.0 - total_reduction
    return max(0.8, min(1.0, multiplier))


# ── Category mapping helpers ──────────────────────────────────────────────

_KATEGORI_TO_EVENT_TYPE: dict[str, EventType] = {
    "Moneter": EventType.BI_RATE_CUT,
    "Fiskal": EventType.OTHER,
    "Regulasi OJK": EventType.OTHER,
    "Regulasi BEI": EventType.OTHER,
    "Politik": EventType.ELECTION,
}

_DAMPAK_TO_DIRECTION: dict[str, EventDirection] = {
    "Positif": EventDirection.BULLISH,
    "Negatif": EventDirection.BEARISH,
    "Netral": EventDirection.NEUTRAL,
}

_DAMPAK_TO_BASE_IMPACT: dict[str, float] = {
    "Positif": 25.0,
    "Negatif": -30.0,
    "Netral": 0.0,
}

_EXT_KATEGORI_TO_EVENT_TYPE: dict[str, EventType] = {
    "Konflik Geopolitik": EventType.GEOPOLITICAL,
    "Perang": EventType.GEOPOLITICAL,
    "Bencana Alam": EventType.OTHER,
    "Pandemi": EventType.PANDEMIC,
    "Perubahan Iklim": EventType.OTHER,
    "ESG": EventType.OTHER,
}

_EXT_DAMPAK_TO_IMPACT: dict[str, float] = {
    "Tinggi": -35.0,
    "Sedang": -20.0,
    "Rendah": -10.0,
}


def _parse_date(val: str | date | datetime) -> datetime:
    """Parse a date value (str, date, or datetime) into a UTC-aware datetime."""
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=UTC)
    if isinstance(val, date):
        return datetime(val.year, val.month, val.day, tzinfo=UTC)
    return datetime.strptime(str(val)[:10], "%Y-%m-%d").replace(tzinfo=UTC)


class PolicyEventScorer:
    """Loads policy_events + external_events from DB and scores them.

    Bridges the ``policy_events`` and ``external_events`` tables to the
    :func:`compute_event_signal` function. Maps Indonesian-language categories
    to :class:`EventType` / :class:`EventDirection` / base impact.

    Usage::

        scorer = PolicyEventScorer(db_path=None)  # uses PostgreSQL from settings
        scorer.load()
        signal = scorer.compute_event_signal(ticker="BBCA.JK", as_of_date=...)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path) if db_path else None
        self._events: list[EventImpact] = []

    def load(self, db_path: str | Path | None = None) -> int:
        """Load events from ``policy_events`` + ``external_events`` tables.

        Returns:
            Number of events loaded.
        """
        from quant.db.raw import get_raw_connection
        with get_raw_connection() as conn:
            return self._load_events(conn)

    def _load_events(self, conn: object) -> int:
        """Load events from an open DBAPI connection."""
        events: list[EventImpact] = []

        rows = conn.execute(
            "SELECT tanggal, kategori, judul, instansi, dampak, sektor, deskripsi "
            "FROM policy_events ORDER BY tanggal"
        ).fetchall()
        for row in rows:
            tanggal, kategori, judul, instansi, dampak, _sektor, _deskripsi = row
            etype = _KATEGORI_TO_EVENT_TYPE.get(kategori or "", EventType.OTHER)
            direction = _DAMPAK_TO_DIRECTION.get(dampak or "", EventDirection.NEUTRAL)
            base_impact = _DAMPAK_TO_BASE_IMPACT.get(dampak or "", 0.0)

            if "suku bunga" in (judul or "").lower() and "naik" in (judul or "").lower():
                etype = EventType.BI_RATE_HIKE
                direction = EventDirection.BEARISH
                base_impact = -40.0
            elif "suku bunga" in (judul or "").lower() and ("turun" in (judul or "").lower() or "potong" in (judul or "").lower()):
                etype = EventType.BI_RATE_CUT
                direction = EventDirection.BULLISH
                base_impact = 30.0
            elif "fed" in (judul or "").lower() and "hike" in (judul or "").lower():
                etype = EventType.FED_RATE_HIKE
                base_impact = -25.0
            elif "fed" in (judul or "").lower() and "cut" in (judul or "").lower():
                etype = EventType.FED_RATE_CUT
                base_impact = 20.0

            events.append(EventImpact(
                event_type=etype,
                direction=direction,
                scope=EventScope.MARKET_WIDE,
                base_impact=base_impact,
                event_date=_parse_date(tanggal),
                ticker=None,
                description=f"{judul or ''} ({instansi or ''})",
            ))

        ext_rows = conn.execute(
            "SELECT tanggal, kategori, judul, lokasi, dampak_market, sektor, deskripsi "
            "FROM external_events ORDER BY tanggal"
        ).fetchall()
        for row in ext_rows:
            tanggal, kategori, judul, lokasi, dampak_market, _sektor, _deskripsi = row
            etype = _EXT_KATEGORI_TO_EVENT_TYPE.get(kategori or "", EventType.OTHER)
            base_impact = _EXT_DAMPAK_TO_IMPACT.get(dampak_market or "", -15.0)

            events.append(EventImpact(
                event_type=etype,
                direction=EventDirection.BEARISH if base_impact < 0 else EventDirection.NEUTRAL,
                scope=EventScope.MARKET_WIDE,
                base_impact=base_impact,
                event_date=_parse_date(tanggal),
                ticker=None,
                description=f"{judul or ''} ({lokasi or ''})",
            ))

        # Load corporate calendar events from idx.co.id (corporate_calendar table)
        cc_rows = self._load_corporate_calendar(conn)
        events.extend(cc_rows)

        self._events = events
        logger.info("PolicyEventScorer: loaded %d events (%d policy, %d external, %d corporate_calendar)",
                    len(events), len(rows), len(ext_rows), len(cc_rows))
        return len(events)

    @staticmethod
    def _load_corporate_calendar(conn: object) -> list[EventImpact]:
        """Load ticker-specific corporate events from corporate_calendar table.

        Maps IDX calendar event types to EventType with TICKER_SPECIFIC scope:
        - Buyback → BUYBACK (bullish, +50)
        - Dividen → DIVIDEND (bullish, +10)
        - RUPS Tahunan/Luar Biasa → OTHER (neutral, +5)
        - RUPS Rencana → OTHER (neutral, +3)
        - obligasiJatuhTempo → OTHER (neutral, 0)
        - pencatatanAwal → OTHER (neutral, +10)
        - Rights issue → RIGHTS_ISSUE (bearish, -45)
        - Stock split → STOCK_SPLIT (bullish, +15)
        """
        # Check if corporate_calendar table exists
        try:
            cc_rows = conn.execute(
                "SELECT ticker, event_date, event_type, description "
                "FROM corporate_calendar ORDER BY event_date"
            ).fetchall()
        except Exception:
            return []

        events: list[EventImpact] = []
        for row in cc_rows:
            ticker, event_date, event_type_raw, description = row
            if not ticker or not event_date:
                continue

            desc_lower = (description or "").lower()
            etype_raw_lower = (event_type_raw or "").lower()

            # Classify based on description + event_type
            if "buyback" in desc_lower or "pembelian kembali" in desc_lower:
                etype = EventType.BUYBACK
                direction = EventDirection.BULLISH
                base_impact = 50.0
            elif "dividen" in desc_lower:
                etype = EventType.DIVIDEND
                direction = EventDirection.BULLISH
                base_impact = 10.0
            elif "right issue" in desc_lower or "right" in desc_lower:
                etype = EventType.RIGHTS_ISSUE
                direction = EventDirection.BEARISH
                base_impact = -45.0
            elif "split" in desc_lower or "pemecahan" in desc_lower:
                etype = EventType.STOCK_SPLIT
                direction = EventDirection.BULLISH
                base_impact = 15.0
            elif "merger" in desc_lower or "penggabungan" in desc_lower:
                etype = EventType.MERGER
                direction = EventDirection.NEUTRAL
                base_impact = 20.0
            elif "obligasi" in desc_lower or "sukuk" in desc_lower:
                etype = EventType.OTHER
                direction = EventDirection.NEUTRAL
                base_impact = 0.0
            elif "pencatatan" in etype_raw_lower or "pencatatan" in desc_lower:
                etype = EventType.OTHER
                direction = EventDirection.BULLISH
                base_impact = 10.0
            elif "rencana" in etype_raw_lower:
                etype = EventType.OTHER
                direction = EventDirection.NEUTRAL
                base_impact = 3.0
            elif "tahunan" in etype_raw_lower or "luar biasa" in etype_raw_lower:
                etype = EventType.OTHER
                direction = EventDirection.NEUTRAL
                base_impact = 5.0
            else:
                etype = EventType.OTHER
                direction = EventDirection.NEUTRAL
                base_impact = 0.0

            events.append(EventImpact(
                event_type=etype,
                direction=direction,
                scope=EventScope.TICKER_SPECIFIC,
                base_impact=base_impact,
                event_date=_parse_date(event_date),
                ticker=ticker,
                description=description or "",
            ))

        return events

    def compute_event_signal(
        self,
        ticker: str,
        as_of_date: datetime,
    ) -> EventSignal | None:
        """Compute composite event signal for ``ticker`` as of ``as_of_date``.

        Returns ``None`` if no events loaded.
        """
        if not self._events:
            return None
        return compute_event_signal(
            ticker=ticker,
            events=self._events,
            as_of_date=as_of_date,
        )

    def get_upcoming(
        self,
        as_of_date: datetime,
        lookahead_days: int = 14,
    ) -> list[UpcomingEvent]:
        """Get upcoming events within lookahead window."""
        return get_upcoming_events(self._events, as_of_date, lookahead_days)
