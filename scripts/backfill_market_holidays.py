"""Backfill market holidays from exchange_calendars into market_holidays table.

Extracts ALL available historical holidays (from calendar first_session)
and forward holidays (1 year ahead) for all exchanges in the database.
Uses named holidays from calendar rules where available.
"""

import logging
from datetime import date, timedelta

import exchange_calendars as xcals
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Mapping: MIC code → exchange_calendars calendar name
CAL_MAP = {
    "XIDX": "XIDX",
    "XNYS": "XNYS",
    "XNAS": "XNAS",
    "XLON": "XLON",
    "XFRA": "XFRA",
    "XHKG": "XHKG",
    "XSHG": "XSHG",
    "XTSE": "XTKS",
    "XSGX": "XSES",
    "XKRX": "XKRX",
    "XASX": "XASX",
    "XBOM": "XBOM",
    "XBKK": "XBKK",
    "XPHS": "XPHS",
    "XTAI": "XTAI",
    "XPAR": "XPAR",
    "XMAD": "XMAD",
    "BVMF": "BVMF",
    "XTSX": "XTSX",
    "XSAU": "XSAU",
    "XJSE": "XJSE",
    "XKLSE": "XKLS",
}


def extract_holidays(cal_name: str, start: date, end: date) -> list[dict]:
    """Extract named holidays for a calendar between start and end.

    Returns list of dicts: {holiday_date, holiday_name}
    """
    cal = xcals.get_calendar(cal_name)
    results: dict[str, str] = {}  # date_str → name

    # 1. Regular (rule-based) holidays with names
    if cal.regular_holidays is not None:
        for rule in cal.regular_holidays.rules:
            try:
                dates = rule.dates(str(start), str(end))
                for d in dates:
                    ds = pd.Timestamp(d).strftime("%Y-%m-%d")
                    results[ds] = rule.name
            except Exception:
                pass

    # 2. Adhoc holidays (dates without names) — label as "Special Holiday"
    for d in cal.adhoc_holidays:
        ts = pd.Timestamp(d)
        if start <= ts.date() <= end:
            ds = ts.strftime("%Y-%m-%d")
            if ds not in results:
                results[ds] = "Special Holiday"

    # 3. Also compute business-day-gap holidays (sessions not in all_bdays)
    #    This catches any holidays missed by rules + adhoc
    try:
        sessions = cal.sessions_in_range(str(start), str(end))
        all_bdays = pd.bdate_range(str(start), str(end))
        missed = all_bdays.difference(sessions)
        for d in missed:
            ds = pd.Timestamp(d).strftime("%Y-%m-%d")
            if ds not in results:
                results[ds] = "Market Holiday"
    except Exception:
        pass

    return [
        {"holiday_date": ds, "holiday_name": name}
        for ds, name in sorted(results.items())
    ]


def main():
    session = get_db()

    # Create market_holidays table
    log.info("Creating market_holidays table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS market_holidays (
            id SERIAL PRIMARY KEY,
            exchange_id INTEGER REFERENCES exchanges(id) ON DELETE CASCADE,
            market_code VARCHAR(10) NOT NULL,
            holiday_date DATE NOT NULL,
            holiday_name VARCHAR(200),
            is_historical BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE (exchange_id, holiday_date, holiday_name)
        )
    """))

    # Index for fast lookups
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_market_holidays_date
        ON market_holidays (holiday_date)
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_market_holidays_market_date
        ON market_holidays (market_code, holiday_date)
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_market_holidays_exchange_date
        ON market_holidays (exchange_id, holiday_date)
    """))
    session.commit()

    # Date ranges: full calendar availability + 1 year forward
    today = date.today()
    future_end = date(today.year + 1, today.month, today.day)

    log.info(
        "Backfill: full history → %s (today), %s → %s (1 year forward)",
        today, today, future_end,
    )

    # Get exchange IDs from DB
    exchanges = session.execute(text(
        "SELECT id, mic FROM exchanges WHERE is_active = TRUE ORDER BY id"
    )).fetchall()

    total_inserted = 0
    for ex_id, mic in exchanges:
        cal_name = CAL_MAP.get(mic)
        if not cal_name:
            log.warning("No calendar mapping for %s — skipping", mic)
            continue

        try:
            # Use calendar's own first_session as start
            cal = xcals.get_calendar(cal_name)
            cal_start = cal.first_session.date()
            cal_end = cal.last_session.date()
            # Historical: from calendar start to today
            hist_end = min(today, cal_end)
            hist_hols = extract_holidays(cal_name, cal_start, hist_end)
            # Forward: from today to 1 year ahead (or calendar end if sooner)
            fwd_end = min(future_end, cal_end)
            fwd_hols = extract_holidays(cal_name, today + timedelta(days=1), fwd_end) if fwd_end > today else []

            inserted = 0
            for h in hist_hols:
                try:
                    session.execute(text("""
                        INSERT INTO market_holidays (exchange_id, market_code, holiday_date, holiday_name, is_historical)
                        VALUES (:eid, :mc, :hd, :hn, TRUE)
                        ON CONFLICT (exchange_id, holiday_date, holiday_name) DO NOTHING
                    """), {"eid": ex_id, "mc": mic, "hd": h["holiday_date"], "hn": h["holiday_name"]})
                    inserted += 1
                except Exception:
                    pass

            for h in fwd_hols:
                try:
                    session.execute(text("""
                        INSERT INTO market_holidays (exchange_id, market_code, holiday_date, holiday_name, is_historical)
                        VALUES (:eid, :mc, :hd, :hn, FALSE)
                        ON CONFLICT (exchange_id, holiday_date, holiday_name) DO NOTHING
                    """), {"eid": ex_id, "mc": mic, "hd": h["holiday_date"], "hn": h["holiday_name"]})
                    inserted += 1
                except Exception:
                    pass

            session.commit()
            total_inserted += inserted
            log.info(
                "%s (%s): %d historical + %d forward = %d total",
                mic, cal_name, len(hist_hols), len(fwd_hols), inserted,
            )
        except Exception as e:
            log.error("Failed for %s: %s", mic, e)
            session.rollback()

    # Verify
    result = session.execute(text("""
        SELECT market_code,
               count(*) FILTER (WHERE is_historical = TRUE) as hist,
               count(*) FILTER (WHERE is_historical = FALSE) as fwd,
               count(*) as total,
               min(holiday_date) as earliest,
               max(holiday_date) as latest
        FROM market_holidays
        GROUP BY market_code
        ORDER BY market_code
    """)).fetchall()

    log.info("\n=== MARKET HOLIDAYS SUMMARY ===")
    for r in result:
        log.info(
            "  %s: hist=%d fwd=%d total=%d range=%s→%s",
            r[0], r[1], r[2], r[3], r[4], r[5],
        )

    session.close()
    log.info("Done. Total rows inserted: %d", total_inserted)


if __name__ == "__main__":
    main()
