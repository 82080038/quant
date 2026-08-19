"""Market Session Manager (catatan.md TAHAP 1 -- Prompt 1.1).

Menyediakan status sesi real-time untuk 21 bursa: IDX, NYSE, NASDAQ,
TSE (Tokyo), HSE (Hong Kong), LSE (London), XETRA (Frankfurt), KRX (Korea),
SGX (Singapore), ASX (Australia), SET (Thailand), PSE (Philippines),
NSE (India), TWSE (Taiwan), Euronext Paris, Borsa Italiana, BME Madrid,
B3 Brasil, TSX (Toronto), Tadawul (Saudi), JSE (South Africa).

Fitur:
- Jam buka/tutup per bursa dalam UTC dan WIB (UTC+7).
- DST handling otomatis untuk US/EU via ``zoneinfo`` (IANA tz database).
- ``get_status(exchange)`` → OPEN | CLOSED | PRE_MARKET | AFTER_HOURS.
- ``get_next_open(exchange)`` → datetime UTC untuk sesi buka berikutnya.
- ``get_recently_closed(minutes=30)`` → list bursa yang baru saja tutup.
- Integrasi opsional dengan ``daily_signal_cron.py`` via ``should_run_pipeline()``.

Data holiday dibaca dari tabel ``exchange_holidays`` (migration 0023) sehingga
status CLOSED akurat untuk hari libur nasional; jika DB tidak tersedia,
fallback ke pengecekan akhir pekan saja (Sabtu/Minggu).

Referensi:
- pustaka/36-gap-data-timezone-global-idx.md
- pustaka/92-multi-market-multi-asset-trading-system.md §4
- catatan.md L559-L570 (Prompt 1.1)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy import text

from quant.db.engine import get_engine

logger = logging.getLogger(__name__)

WIB = ZoneInfo("Asia/Jakarta")  # UTC+7, no DST


class SessionStatus(StrEnum):
    """Status sesi sebuah bursa pada momen tertentu."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    AFTER_HOURS = "AFTER_HOURS"


@dataclass(frozen=True)
class ExchangeSchedule:
    """Jam operasi regular sebuah bursa (lokal time, HH:MM)."""

    mic_code: str
    name: str
    tz: ZoneInfo
    open_local: tuple[int, int]  # (hour, minute) regular session
    close_local: tuple[int, int]
    pre_open_local: tuple[int, int] | None = None
    after_close_local: tuple[int, int] | None = None  # end of after-hours


# ── 21 bursa utama ───────────────────────────────────────────────────────────
# Jam lokal regular session; pre/after-hours opsional.
# Sumber: situs resmi masing-masing bursa (per 2026).
_EXCHANGES: dict[str, ExchangeSchedule] = {
    "XIDX": ExchangeSchedule(
        "XIDX", "Indonesia Stock Exchange", ZoneInfo("Asia/Jakarta"),
        (9, 0), (15, 50), pre_open_local=(8, 45),
    ),
    "XNYS": ExchangeSchedule(
        "XNYS", "New York Stock Exchange", ZoneInfo("America/New_York"),
        (9, 30), (16, 0), pre_open_local=(4, 0), after_close_local=(20, 0),
    ),
    "XNAS": ExchangeSchedule(
        "XNAS", "NASDAQ", ZoneInfo("America/New_York"),
        (9, 30), (16, 0), pre_open_local=(4, 0), after_close_local=(20, 0),
    ),
    "XTSE": ExchangeSchedule(
        "XTSE", "Tokyo Stock Exchange", ZoneInfo("Asia/Tokyo"),
        (9, 0), (15, 30), pre_open_local=(8, 0),
    ),
    "XHKG": ExchangeSchedule(
        "XHKG", "Hong Kong Stock Exchange", ZoneInfo("Asia/Hong_Kong"),
        (9, 30), (16, 0), pre_open_local=(9, 0),
    ),
    "XLON": ExchangeSchedule(
        "XLON", "London Stock Exchange", ZoneInfo("Europe/London"),
        (8, 0), (16, 30), pre_open_local=(7, 0),
    ),
    "XFRA": ExchangeSchedule(
        "XFRA", "XETRA / Frankfurt", ZoneInfo("Europe/Berlin"),
        (9, 0), (17, 30), pre_open_local=(8, 0),
    ),
    "XKRX": ExchangeSchedule(
        "XKRX", "Korea Exchange", ZoneInfo("Asia/Seoul"),
        (9, 0), (15, 30), pre_open_local=(8, 0),
    ),
    "XSES": ExchangeSchedule(
        "XSES", "Singapore Exchange", ZoneInfo("Asia/Singapore"),
        (9, 0), (17, 0), pre_open_local=(8, 30),
    ),
    "XASX": ExchangeSchedule(
        "XASX", "Australian Securities Exchange", ZoneInfo("Australia/Sydney"),
        (10, 0), (16, 0), pre_open_local=(7, 0),
    ),
    # ── ASEAN peers (2-way causality dengan IDX) ──
    "XBKK": ExchangeSchedule(
        "XBKK", "Stock Exchange of Thailand", ZoneInfo("Asia/Bangkok"),
        (10, 0), (16, 30), pre_open_local=(9, 30),
    ),
    "XPHS": ExchangeSchedule(
        "XPHS", "Philippine Stock Exchange", ZoneInfo("Asia/Manila"),
        (9, 30), (15, 30), pre_open_local=(9, 0),
    ),
    # ── Asia peers ──
    "XNSE": ExchangeSchedule(
        "XNSE", "National Stock Exchange of India", ZoneInfo("Asia/Kolkata"),
        (9, 15), (15, 30), pre_open_local=(9, 0),
    ),
    "XTAI": ExchangeSchedule(
        "XTAI", "Taiwan Stock Exchange", ZoneInfo("Asia/Taipei"),
        (9, 0), (13, 30),
    ),
    # ── EU ──
    "XPAR": ExchangeSchedule(
        "XPAR", "Euronext Paris", ZoneInfo("Europe/Paris"),
        (9, 0), (17, 30), pre_open_local=(7, 15),
    ),
    "XMTA": ExchangeSchedule(
        "XMTA", "Borsa Italiana", ZoneInfo("Europe/Rome"),
        (9, 0), (17, 30), pre_open_local=(8, 0),
    ),
    "XMAD": ExchangeSchedule(
        "XMAD", "BME Spanish Exchanges", ZoneInfo("Europe/Madrid"),
        (9, 0), (17, 30), pre_open_local=(8, 0),
    ),
    # ── Americas ──
    "BVMF": ExchangeSchedule(
        "BVMF", "B3 Brasil Bolsa Balcão", ZoneInfo("America/Sao_Paulo"),
        (10, 0), (17, 30), pre_open_local=(9, 45),
    ),
    "XTSX": ExchangeSchedule(
        "XTSX", "TMX Group (Toronto)", ZoneInfo("America/Toronto"),
        (9, 30), (16, 0), pre_open_local=(7, 0),
    ),
    # ── Middle East ──
    "XSAU": ExchangeSchedule(
        "XSAU", "Saudi Stock Exchange (Tadawul)", ZoneInfo("Asia/Riyadh"),
        (10, 0), (15, 0),
    ),
    # ── Africa ──
    "XJSE": ExchangeSchedule(
        "XJSE", "Johannesburg Stock Exchange", ZoneInfo("Africa/Johannesburg"),
        (9, 0), (17, 0),
    ),
}

# Alias ramah pengguna (catatan.md menyebut IDX, NYSE, NASDAQ, TSE, HSI, LSE,
# XETRA, KRX, SGX, ASX)
_ALIASES: dict[str, str] = {
    "IDX": "XIDX",
    "NYSE": "XNYS",
    "NASDAQ": "XNAS",
    "TSE": "XTSE",
    "TOYO": "XTSE",
    "HSI": "XHKG",
    "HKEX": "XHKG",
    "LSE": "XLON",
    "XETRA": "XFRA",
    "FRANKFURT": "XFRA",
    "KRX": "XKRX",
    "KOREA": "XKRX",
    "SGX": "XSES",
    "SINGAPORE": "XSES",
    "ASX": "XASX",
    "AUSTRALIA": "XASX",
    # New exchanges
    "SET": "XBKK",
    "THAILAND": "XBKK",
    "PSE": "XPHS",
    "PHILIPPINES": "XPHS",
    "NSE": "XNSE",
    "INDIA": "XNSE",
    "TWSE": "XTAI",
    "TAIWAN": "XTAI",
    "PARIS": "XPAR",
    "EURONEXT": "XPAR",
    "MILAN": "XMTA",
    "ITALY": "XMTA",
    "MADRID": "XMAD",
    "SPAIN": "XMAD",
    "B3": "BVMF",
    "BRASIL": "BVMF",
    "BRAZIL": "BVMF",
    "TSX": "XTSX",
    "CANADA": "XTSX",
    "TADAWUL": "XSAU",
    "SAUDI": "XSAU",
    "JSE": "XJSE",
    "SOUTH_AFRICA": "XJSE",
}


def _resolve_mic(exchange: str) -> str:
    """Resolve nama exchange (alias atau MIC) → MIC code."""
    key = exchange.strip().upper()
    if key in _EXCHANGES:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    raise KeyError(f"Unknown exchange: {exchange!r}")


def _is_holiday(mic_code: str, d: date) -> bool:
    """Cek apakah ``d`` adalah holiday di ``exchange_holidays``."""
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM exchange_holidays "
                    "WHERE mic_code = :mic AND holiday_date = :d LIMIT 1"
                ),
                {"mic": mic_code, "d": d},
            ).first()
        return row is not None
    except Exception as exc:
        logger.debug("exchange_holidays lookup failed: %s", exc)
        return False


class MarketSessionManager:
    """Manager status sesi real-time untuk 10 bursa utama.

    Thread-safe untuk read-only; tidak menyimpan state mutable.
    Gunakan satu instance per proses (cheap to construct).
    """

    def __init__(self, now_utc: datetime | None = None) -> None:
        # Accept injection untuk testing; selalu simpan sebagai aware UTC.
        if now_utc is None:
            self._now = datetime.now(UTC)
        else:
            self._now = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=UTC)

    # ── public API ──────────────────────────────────────────────────────────

    @staticmethod
    def list_exchanges() -> list[str]:
        """Return semua MIC code yang didukung."""
        return sorted(_EXCHANGES.keys())

    def now_utc(self) -> datetime:
        return self._now

    def now_wib(self) -> datetime:
        return self._now.astimezone(WIB)

    def get_status(self, exchange: str) -> SessionStatus:
        """Status sesi saat ini: OPEN | CLOSED | PRE_MARKET | AFTER_HOURS."""
        mic = _resolve_mic(exchange)
        sched = _EXCHANGES[mic]
        local = self._now.astimezone(sched.tz)
        # Weekend (Sabtu=5, Minggu=6) atau holiday → CLOSED
        if local.weekday() >= 5 or _is_holiday(mic, local.date()):
            return SessionStatus.CLOSED
        cur = local.hour * 60 + local.minute
        o = sched.open_local[0] * 60 + sched.open_local[1]
        c = sched.close_local[0] * 60 + sched.close_local[1]
        if o <= cur < c:
            return SessionStatus.OPEN
        if sched.pre_open_local and (
            sched.pre_open_local[0] * 60 + sched.pre_open_local[1] <= cur < o
        ):
            return SessionStatus.PRE_MARKET
        if sched.after_close_local and (
            c <= cur < sched.after_close_local[0] * 60 + sched.after_close_local[1]
        ):
            return SessionStatus.AFTER_HOURS
        return SessionStatus.CLOSED

    def get_next_open(self, exchange: str, max_days: int = 14) -> datetime:
        """Datetime UTC untuk sesi buka berikutnya (maks ``max_days`` hari ke depan).

        Raises RuntimeError jika tidak ada sesi buka dalam ``max_days``.
        """
        mic = _resolve_mic(exchange)
        sched = _EXCHANGES[mic]
        local = self._now.astimezone(sched.tz)
        # Jika sekarang sebelum open hari ini dan hari ini trading day → buka hari ini.
        for delta in range(max_days + 1):
            cand_date = (local + timedelta(days=delta)).date()
            cand_local = datetime(
                cand_date.year, cand_date.month, cand_date.day,
                sched.open_local[0], sched.open_local[1],
                tzinfo=sched.tz,
            )
            if cand_local <= local:
                continue
            if cand_date.weekday() >= 5 or _is_holiday(mic, cand_date):
                continue
            return cand_local.astimezone(UTC)
        raise RuntimeError(
            f"No open session for {mic} within {max_days} days from {self._now.isoformat()}"
        )

    def get_recently_closed(self, minutes: int = 30) -> list[tuple[str, SessionStatus]]:
        """List bursa yang CLOSE regular session dalam ``minutes`` menit terakhir.

        Returns list of (mic_code, status) -- status biasanya CLOSED atau
        AFTER_HOURS (jika after-hours masih berlangsung).
        """
        cutoff = self._now - timedelta(minutes=minutes)
        out: list[tuple[str, SessionStatus]] = []
        for mic, sched in _EXCHANGES.items():
            local = self._now.astimezone(sched.tz)
            if local.weekday() >= 5 or _is_holiday(mic, local.date()):
                continue
            close_local = datetime(
                local.year, local.month, local.day,
                sched.close_local[0], sched.close_local[1], tzinfo=sched.tz,
            )
            close_utc = close_local.astimezone(UTC)
            if cutoff <= close_utc <= self._now:
                out.append((mic, self.get_status(mic)))
        return out

    def get_session_info(self, exchange: str) -> dict:
        """Info lengkap sebuah bursa: status, jam lokal, jam WIB, next open."""
        mic = _resolve_mic(exchange)
        sched = _EXCHANGES[mic]
        local = self._now.astimezone(sched.tz)
        status = self.get_status(mic)
        next_open = self.get_next_open(mic)
        return {
            "mic_code": mic,
            "name": sched.name,
            "timezone": str(sched.tz),
            "status": status.value,
            "local_time": local.isoformat(),
            "wib_time": self.now_wib().isoformat(),
            "open_local": f"{sched.open_local[0]:02d}:{sched.open_local[1]:02d}",
            "close_local": f"{sched.close_local[0]:02d}:{sched.close_local[1]:02d}",
            "next_open_utc": next_open.isoformat(),
            "next_open_wib": next_open.astimezone(WIB).isoformat(),
        }

    def get_next_holiday(self, exchange: str, max_days: int = 90) -> dict | None:
        """Get next upcoming holiday for an exchange.

        Returns dict with keys: mic_code, date, name, days_until.
        Returns None if no holiday within max_days.
        """
        mic = _resolve_mic(exchange)
        local = self._now.astimezone(_EXCHANGES[mic].tz)
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT holiday_date, holiday_name "
                        "FROM exchange_holidays "
                        "WHERE mic_code = :mic AND holiday_date > :d "
                        "ORDER BY holiday_date LIMIT 1"
                    ),
                    {"mic": mic, "d": local.date()},
                ).first()
        except Exception as exc:
            logger.debug("exchange_holidays lookup failed: %s", exc)
            return None
        if row is None:
            return None
        h_date = row[0]
        h_name = row[1] or "Market Holiday"
        days_until = (h_date - local.date()).days
        if days_until > max_days:
            return None
        return {
            "mic_code": mic,
            "date": h_date.isoformat(),
            "name": h_name,
            "days_until": days_until,
        }

    def get_upcoming_holidays(self, days: int = 30) -> list[dict]:
        """Get upcoming holidays for ALL exchanges within N days.

        Returns list of dicts sorted by date:
            {mic_code, exchange_name, date, name, days_until}
        """
        local_now = self._now
        results = []
        try:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT mic_code, holiday_date, holiday_name "
                        "FROM exchange_holidays "
                        "WHERE holiday_date > :d AND holiday_date <= :end "
                        "ORDER BY holiday_date, mic_code"
                    ),
                    {
                        "d": local_now.date(),
                        "end": local_now.date() + timedelta(days=days),
                    },
                ).fetchall()
        except Exception as exc:
            logger.debug("exchange_holidays lookup failed: %s", exc)
            return []
        for r in rows:
            mic = r[0]
            h_date = r[1]
            h_name = r[2] or "Market Holiday"
            sched = _EXCHANGES.get(mic)
            ex_name = sched.name if sched else mic
            days_until = (h_date - local_now.date()).days
            results.append({
                "mic_code": mic,
                "exchange_name": ex_name,
                "date": h_date.isoformat(),
                "name": h_name,
                "days_until": days_until,
            })
        return results

    # ── Integrasi cron ──────────────────────────────────────────────────────

    def should_run_pipeline(self, exchange: str = "IDX") -> tuple[bool, str]:
        """Apakah pipeline ``daily_signal_cron.py`` sebaiknya jalan sekarang?

        Default: trigger setelah IDX close (status CLOSED atau AFTER_HOURS)
        dalam window 30 menit setelah close. Return (should_run, reason).
        """
        mic = _resolve_mic(exchange)
        sched = _EXCHANGES[mic]
        local = self._now.astimezone(sched.tz)
        if local.weekday() >= 5 or _is_holiday(mic, local.date()):
            return False, f"{mic} weekend/holiday -- no pipeline"
        close_local = datetime(
            local.year, local.month, local.day,
            sched.close_local[0], sched.close_local[1], tzinfo=sched.tz,
        )
        close_utc = close_local.astimezone(UTC)
        delta = (self._now - close_utc).total_seconds()
        if 0 <= delta <= 30 * 60:
            return True, f"{mic} closed {delta/60:.0f} min ago -- pipeline window"
        if delta < 0:
            return False, f"{mic} still open -- close in {-delta/60:.0f} min"
        return False, f"{mic} closed {delta/60:.0f} min ago -- outside 30-min window"


__all__ = [
    "WIB",
    "ExchangeSchedule",
    "MarketSessionManager",
    "SessionStatus",
]
