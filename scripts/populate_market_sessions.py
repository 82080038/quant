"""Populate market_sessions table with exchange open/close times.

Extracts session times from exchange_calendars for all mapped exchanges.
Stores both UTC and WIB times, plus the local timezone IANA name for
DST-aware dynamic conversion.
"""

import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
from sqlalchemy import text

from quant.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

WIB = ZoneInfo("Asia/Jakarta")

# MIC → exchange_calendars name (same as backfill_market_holidays)
CAL_MAP = {
    "XIDX": "XIDX", "XNYS": "XNYS", "XNAS": "XNAS",
    "XLON": "XLON", "XFRA": "XFRA", "XHKG": "XHKG",
    "XSHG": "XSHG", "XTSE": "XTKS", "XSGX": "XSES",
    "XKRX": "XKRX", "XASX": "XASX", "XBOM": "XBOM",
    "XBKK": "XBKK", "XPHS": "XPHS", "XTAI": "XTAI",
    "XPAR": "XPAR", "XMAD": "XMAD", "BVMF": "BVMF",
    "XTSX": "XTSX", "XSAU": "XSAU", "XJSE": "XJSE",
    "XKLSE": "XKLS",
}


def main():
    session = get_db()

    log.info("Creating market_sessions table...")
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS market_sessions (
            id SERIAL PRIMARY KEY,
            exchange_id INTEGER REFERENCES exchanges(id) ON DELETE CASCADE,
            market_code VARCHAR(10) NOT NULL UNIQUE,
            market_name VARCHAR(200),
            timezone_iana VARCHAR(50) NOT NULL,
            open_time_utc TIME NOT NULL,
            close_time_utc TIME NOT NULL,
            open_time_wib TIME NOT NULL,
            close_time_wib TIME NOT NULL,
            timezone_offset_hours NUMERIC(4,1) NOT NULL,
            has_dst BOOLEAN DEFAULT FALSE,
            pre_market_open_utc TIME,
            post_market_close_utc TIME,
            is_active BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_market_sessions_code
        ON market_sessions (market_code)
    """))
    session.commit()

    # Get exchange IDs
    exchanges = {}
    result = session.execute(text(
        "SELECT id, mic, name FROM exchanges WHERE is_active = TRUE"
    ))
    for r in result:
        exchanges[r[1]] = (r[0], r[2])

    today = date.today()
    # Use a winter date (no DST) to get base UTC times
    winter_date = date(today.year, 1, 5) if today.month > 6 else date(today.year - 1, 12, 7)
    # Use a summer date to check DST
    summer_date = date(today.year, 7, 6)

    total = 0
    for mic, cal_name in CAL_MAP.items():
        if mic not in exchanges:
            log.warning("No exchange %s in DB — skipping", mic)
            continue

        ex_id, ex_name = exchanges[mic]
        try:
            cal = xcals.get_calendar(cal_name)
            tz = cal.tz

            # Get winter session times (standard, no DST)
            sessions = cal.sessions_in_range(str(winter_date), str(winter_date + timedelta(days=7)))
            if len(sessions) == 0:
                # Try a broader range
                sessions = cal.sessions_in_range(str(cal.first_session.date()), str(cal.first_session.date() + timedelta(days=7)))
            if len(sessions) == 0:
                log.warning("No sessions for %s — skipping", mic)
                continue

            oc = cal.session_open_close(sessions[0])
            open_utc = oc[0]
            close_utc = oc[1]
            open_wib = open_utc.astimezone(WIB)
            close_wib = close_utc.astimezone(WIB)

            # Local offset (winter = standard time)
            local_offset = open_utc.astimezone(tz).utcoffset().total_seconds() / 3600

            # Check DST: compare summer session times
            has_dst = False
            summer_sessions = cal.sessions_in_range(str(summer_date), str(summer_date + timedelta(days=7)))
            if len(summer_sessions) > 0:
                oc_summer = cal.session_open_close(summer_sessions[0])
                summer_open_utc = oc_summer[0]
                summer_offset = summer_open_utc.astimezone(tz).utcoffset().total_seconds() / 3600
                if summer_offset != local_offset:
                    has_dst = True

            # Try to get pre/post market times
            pre_open = None
            post_close = None
            try:
                first_minute = cal.session_first_minute(sessions[0])
                last_minute = cal.session_last_minute(sessions[0])
                if first_minute < open_utc:
                    pre_open = first_minute.astimezone(ZoneInfo("UTC")).time()
                if last_minute > close_utc:
                    post_close = last_minute.astimezone(ZoneInfo("UTC")).time()
            except Exception:
                pass

            session.execute(text("""
                INSERT INTO market_sessions
                    (exchange_id, market_code, market_name, timezone_iana,
                     open_time_utc, close_time_utc, open_time_wib, close_time_wib,
                     timezone_offset_hours, has_dst, pre_market_open_utc, post_market_close_utc,
                     is_active, updated_at)
                VALUES
                    (:eid, :mc, :mn, :tz,
                     :ou, :cu, :ow, :cw,
                     :off, :dst, :pre, :post,
                     TRUE, now())
                ON CONFLICT (market_code) DO UPDATE SET
                    exchange_id = EXCLUDED.exchange_id,
                    market_name = EXCLUDED.market_name,
                    timezone_iana = EXCLUDED.timezone_iana,
                    open_time_utc = EXCLUDED.open_time_utc,
                    close_time_utc = EXCLUDED.close_time_utc,
                    open_time_wib = EXCLUDED.open_time_wib,
                    close_time_wib = EXCLUDED.close_time_wib,
                    timezone_offset_hours = EXCLUDED.timezone_offset_hours,
                    has_dst = EXCLUDED.has_dst,
                    pre_market_open_utc = EXCLUDED.pre_market_open_utc,
                    post_market_close_utc = EXCLUDED.post_market_close_utc,
                    updated_at = now()
            """), {
                "eid": ex_id, "mc": mic, "mn": ex_name, "tz": str(tz),
                "ou": open_utc.strftime("%H:%M:%S"),
                "cu": close_utc.strftime("%H:%M:%S"),
                "ow": open_wib.strftime("%H:%M:%S"),
                "cw": close_wib.strftime("%H:%M:%S"),
                "off": local_offset,
                "dst": has_dst,
                "pre": pre_open.strftime("%H:%M:%S") if pre_open else None,
                "post": post_close.strftime("%H:%M:%S") if post_close else None,
            })
            session.commit()
            total += 1
            log.info(
                "%s: tz=%s offset=%+.1f UTC=%s-%s WIB=%s-%s DST=%s",
                mic, str(tz), local_offset,
                open_utc.strftime("%H:%M"), close_utc.strftime("%H:%M"),
                open_wib.strftime("%H:%M"), close_wib.strftime("%H:%M"),
                has_dst,
            )
        except Exception as e:
            log.error("Failed for %s: %s", mic, e)
            session.rollback()

    # Summary
    result = session.execute(text("""
        SELECT market_code, market_name, timezone_iana,
               open_time_utc, close_time_utc,
               open_time_wib, close_time_wib,
               timezone_offset_hours, has_dst
        FROM market_sessions
        ORDER BY open_time_utc
    """)).fetchall()

    log.info("\n=== MARKET SESSIONS (%d exchanges) ===", len(result))
    log.info("%-8s %-25s %-25s %-7s %-7s %-7s %-7s %5s %3s",
             "MIC", "Name", "Timezone", "UTC_O", "UTC_C", "WIB_O", "WIB_C", "OFF", "DST")
    for r in result:
        log.info("%-8s %-25s %-25s %-7s %-7s %-7s %-7s %+.1f %s",
                 r[0], r[1][:25], r[2],
                 str(r[3])[:5], str(r[4])[:5],
                 str(r[5])[:5], str(r[6])[:5],
                 float(r[7]), "Y" if r[8] else "N")

    session.close()
    log.info("Done. Total exchanges: %d", total)


if __name__ == "__main__":
    main()
