"""Ticker suffix utility — standardizes ticker formatting for yfinance calls.

Looks up market_registry.data_suffix to determine the correct yfinance suffix
for a given ticker + market_mic. This replaces hardcoded ``.JK`` logic
throughout the codebase.

Usage:
    from quant.data.ticker_util import to_yf_ticker, get_currency

    yf_ticker = to_yf_ticker("BBCA", "XIDX")       # → "BBCA.JK"
    yf_ticker = to_yf_ticker("BBCA.JK", "XIDX")     # → "BBCA.JK" (already suffixed)
    yf_ticker = to_yf_ticker("^GSPC", "XNYS")       # → "^GSPC" (no suffix for XNYS)
    yf_ticker = to_yf_ticker("000001", "XSHG")       # → "000001.SS"
"""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant.db.models import Exchange

logger = logging.getLogger(__name__)

# Fallback suffix map for known markets (used when DB not available)
_FALLBACK_SUFFIXES: dict[str, str | None] = {
    "XIDX": ".JK",
    "XNYS": None,
    "XNAS": None,
    "XFRA": ".DE",
    "XHKG": ".HK",
    "XLON": ".L",
    "XSGX": ".SI",
    "XSHG": ".SS",
    "XTSE": ".T",
    "XCEC": None,
    "XFXS": None,
}


@lru_cache(maxsize=32)
def _get_suffix(market_mic: str) -> str | None:
    """Get yfinance suffix for a market MIC from cache or fallback."""
    return _FALLBACK_SUFFIXES.get(market_mic)


def get_suffix(market_mic: str, session: Session | None = None) -> str | None:
    """Get yfinance ticker suffix for a given market MIC.

    Args:
        market_mic: Market Identifier Code (e.g. ``XIDX``, ``XNYS``).
        session: Optional SQLAlchemy session to look up market_registry.

    Returns:
        Suffix string (e.g. ``.JK``) or None if no suffix needed.
    """
    if session is not None:
        try:
            result = session.execute(
                select(Exchange.data_suffix).where(
                    Exchange.mic_code == market_mic
                )
            ).scalar_one_or_none()
            if result is not None:
                return result
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            logger.debug("Could not query exchanges for %s, using fallback", market_mic)

    return _get_suffix(market_mic)


def to_yf_ticker(
    ticker: str,
    market_mic: str = "XIDX",
    session: Session | None = None,
) -> str:
    """Convert a bare DB ticker to a yfinance ticker with correct suffix.

    Args:
        ticker: Ticker symbol (e.g. ``BBCA``, ``BBCA.JK``, ``^GSPC``).
        market_mic: Market MIC code (e.g. ``XIDX``, ``XNYS``).
        session: Optional SQLAlchemy session for DB lookup.

    Returns:
        yfinance-compatible ticker (e.g. ``BBCA.JK``, ``^GSPC``).

    Examples:
        >>> to_yf_ticker("BBCA", "XIDX")
        'BBCA.JK'
        >>> to_yf_ticker("BBCA.JK", "XIDX")
        'BBCA.JK'
        >>> to_yf_ticker("^GSPC", "XNYS")
        '^GSPC'
        >>> to_yf_ticker("000001", "XSHG")
        '000001.SS'
    """
    # Indices (^ prefix) and futures (= suffix) never need market suffix
    if ticker.startswith("^") or ticker.endswith("=F") or "=" in ticker:
        return ticker

    # ETFs on US exchanges (XNYS/XNAS) don't need suffix
    if market_mic in ("XNYS", "XNAS", "XCEC", "XFXS") and not _needs_suffix(ticker):
        return ticker

    suffix = get_suffix(market_mic, session)
    if suffix is None:
        return ticker

    # Already has the suffix
    if ticker.endswith(suffix):
        return ticker

    # Has a different suffix — strip it and add the correct one
    for s in (".JK", ".DE", ".HK", ".L", ".SI", ".SS", ".T", ".SZ"):
        if ticker.endswith(s):
            ticker = ticker[: -len(s)]
            break

    return f"{ticker}{suffix}"


def _needs_suffix(ticker: str) -> bool:
    """Check if a ticker already has a market suffix."""
    for s in (".JK", ".DE", ".HK", ".L", ".SI", ".SS", ".T", ".SZ"):
        if ticker.endswith(s):
            return True
    return False


def get_currency(ticker: str, market_mic: str = "XIDX") -> str:
    """Determine currency from ticker/market_mic.

    Args:
        ticker: yfinance ticker (e.g. ``BBCA.JK``, ``^GSPC``).
        market_mic: Market MIC code.

    Returns:
        Currency code (e.g. ``IDR``, ``USD``).
    """
    _CURRENCY_MAP = {
        "XIDX": "IDR",
        "XNYS": "USD",
        "XNAS": "USD",
        "XCEC": "USD",
        "XFXS": "USD",
        "XFRA": "EUR",
        "XHKG": "HKD",
        "XLON": "GBP",
        "XSGX": "SGD",
        "XSHG": "CNY",
        "XTSE": "JPY",
    }
    return _CURRENCY_MAP.get(market_mic, "USD")


def from_yf_ticker(yf_ticker: str) -> tuple[str, str]:
    """Convert a yfinance ticker back to (bare_ticker, market_mic).

    Args:
        yf_ticker: yfinance ticker (e.g. ``BBCA.JK``, ``^GSPC``).

    Returns:
        Tuple of (bare_ticker, market_mic).

    Examples:
        >>> from_yf_ticker("BBCA.JK")
        ('BBCA', 'XIDX')
        >>> from_yf_ticker("^GSPC")
        ('^GSPC', 'XNYS')
    """
    # Index
    if yf_ticker.startswith("^"):
        if yf_ticker == "^JKSE":
            return yf_ticker, "XIDX"
        return yf_ticker, "XNYS"

    # Futures (e.g. GC=F, CL=F) — must check before FX pair ("=" in)
    if yf_ticker.endswith("=F"):
        return yf_ticker, "XCEC"

    # FX pair (e.g. IDR=X, EURUSD=X)
    if "=" in yf_ticker:
        return yf_ticker, "XFXS"

    # Check known suffixes
    _SUFFIX_TO_MIC = {
        ".JK": "XIDX",
        ".DE": "XFRA",
        ".HK": "XHKG",
        ".L": "XLON",
        ".SI": "XSGX",
        ".SS": "XSHG",
        ".T": "XTSE",
        ".SZ": "XSHE",
    }
    for suffix, mic in _SUFFIX_TO_MIC.items():
        if yf_ticker.endswith(suffix):
            return yf_ticker[: -len(suffix)], mic

    # No suffix — US market
    return yf_ticker, "XNYS"


# ── Ticker rename resolver (BEI ticker change support, efektif Jan 2028) ──


def resolve_ticker(
    ticker: str,
    conn: object | None = None,
) -> str:
    """Resolve a ticker to its current active form.

    If the ticker has been renamed (former_ticker set in instrument_master),
    return the current ticker. If the input matches a former_ticker,
    return the current ticker that superseded it.

    Args:
        ticker: Ticker to resolve (e.g. ``BNLI.JK`` or ``BBPI.JK``).
        conn: Optional sqlite3.Connection or SQLAlchemy Session.
            If None, caller must handle DB access separately.

    Returns:
        Current active ticker (e.g. ``BBPI.JK`` if BNLI→BBPI rename happened).

    Examples:
        >>> resolve_ticker("BNLI.JK", conn=conn)  # if BNLI renamed to BBPI
        'BBPI.JK'
        >>> resolve_ticker("BBCA.JK", conn=conn)   # no rename
        'BBCA.JK'
    """
    if conn is None:
        return ticker

    try:
        # DBAPI2 connection (sqlite3 or psycopg2) — use cursor
        if hasattr(conn, 'cursor'):
            # Detect placeholder style: sqlite3 uses ?, psycopg2 uses %s
            _cls_mod = type(conn).__module__
            _ph = "?" if "sqlite3" in _cls_mod else "%s"

            cur = conn.cursor()
            # First: if ticker is a current ticker with former_ticker set, return as-is
            cur.execute(
                f"SELECT ticker FROM instrument_master WHERE ticker = {_ph} AND former_ticker IS NOT NULL",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                cur.close()
                return row[0]
            # Second: if ticker is a former_ticker, return the current ticker
            cur.execute(
                f"SELECT ticker FROM instrument_master WHERE former_ticker = {_ph}",
                (ticker,),
            )
            row = cur.fetchone()
            cur.close()
            if row:
                return row[0]
            return ticker
        # SQLAlchemy session
        else:
            from quant.db.models import InstrumentMaster

            result = conn.execute(
                select(InstrumentMaster.ticker).where(
                    InstrumentMaster.former_ticker == ticker
                )
            ).scalar_one_or_none()
            if result:
                return result
            return ticker
    except Exception:
        logger.debug("resolve_ticker: could not query DB for %s", ticker)
        return ticker


def resolve_ticker_batch(
    tickers: list[str],
    conn: object | None = None,
) -> dict[str, str]:
    """Resolve multiple tickers at once.

    Args:
        tickers: List of tickers to resolve.
        conn: sqlite3.Connection or SQLAlchemy Session.

    Returns:
        Dict mapping input ticker → current ticker.
        Only includes entries where ticker changed.
    """
    if conn is None:
        return {}

    result: dict[str, str] = {}
    try:
        if hasattr(conn, 'cursor'):
            cur = conn.cursor()
            cur.execute(
                "SELECT ticker, former_ticker FROM instrument_master WHERE former_ticker IS NOT NULL"
            )
            rows = cur.fetchall()
            cur.close()
            former_map = {r[1]: r[0] for r in rows}
            for t in tickers:
                if t in former_map:
                    result[t] = former_map[t]
        else:
            from quant.db.models import InstrumentMaster

            rows = conn.execute(
                select(InstrumentMaster.ticker, InstrumentMaster.former_ticker).where(
                    InstrumentMaster.former_ticker.isnot(None)
                )
            ).fetchall()
            former_map = {r[1]: r[0] for r in rows}
            for t in tickers:
                if t in former_map:
                    result[t] = former_map[t]
    except Exception:
        logger.debug("resolve_ticker_batch: could not query DB")

    return result
