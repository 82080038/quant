"""IDX Official Adapter — fetch data from idx.co.id API.

The idx.co.id website provides trading data via Umbraco Surface endpoints.
These endpoints return JSON data for daily stock summaries, index values,
and trading data. The API is protected by Cloudflare, so we need proper
headers and session handling.

Known endpoints (from idx.co.id scraping community):
  - GetStockSummary: daily OHLC for all stocks on a given date
    GET https://idx.co.id/umbraco/Surface/TradingSummary/GetStockSummary?Length=3&date=YYYYMMDD
  - GetIndexSummary: daily index values
    GET https://idx.co.id/umbraco/Surface/TradingSummary/GetIndexSummary?date=YYYYMMDD
  - GetTradingDaily: real-time price snapshots
    GET https://idx.co.id/umbraco/Surface/TradingSummary/GetTradingDaily?date=YYYYMMDD

Data format: JSON array of objects with fields like:
  - StockCode, StockName, OpenPrice, High, Low, Close, Volume, Value, Frequency

Usage:
    from quant.data.idx_adapter import IDXOfficialAdapter
    adapter = IDXOfficialAdapter()
    records = adapter.fetch_index_daily("IDX30", start_date="2026-08-01")
    records = adapter.fetch_stock_daily("BBCA", start_date="2026-08-01")

Note: idx.co.id requires a session with Cloudflare cookie. We use
requests.Session with browser-like headers. If Cloudflare blocks,
consider using curl_cffi (as Pirana does) or cloudscraper.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False
    import requests

if TYPE_CHECKING:
    from quant.data.yahoo_adapter import NormalizedOHLCV

logger = logging.getLogger(__name__)

# idx.co.id base URLs (updated 2026: /umbraco/Surface/ → /primary/)
IDX_BASE = "https://www.idx.co.id"
IDX_STOCK_SUMMARY = f"{IDX_BASE}/primary/TradingSummary/GetStockSummary"
IDX_INDEX_SUMMARY = f"{IDX_BASE}/primary/TradingSummary/GetIndexSummary"
IDX_TRADING_DAILY = f"{IDX_BASE}/primary/TradingSummary/GetTradingDaily"
IDX_BROKER_SUMMARY = f"{IDX_BASE}/primary/TradingSummary/GetBrokerSummary"
IDX_COMPANY_CALENDAR = f"{IDX_BASE}/primary/Home/GetCalendar"
IDX_EARNINGS_WEEK = f"{IDX_BASE}/primary/Calendar/GetEarningsThisWeek"

# Browser-like headers to bypass Cloudflare
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Referer": "https://idx.co.id/",
    "Origin": "https://idx.co.id",
}

# Adaptive rate limiter for idx.co.id (replaces static _RATE_LIMIT_SEC)
from quant.core.rate_limiter import get_limiter
_idx_limiter = get_limiter("idx", base_rate=0.5, burst=3, timeout=15)


class IDXOfficialAdapter:
    """Fetch market data from idx.co.id official endpoints.

    Use this for IDX indices and stocks that are NOT available on Yahoo Finance.
    Yahoo Finance only has ^JKSE and ^JKLQ45 for IDX indices — all other
    IDX indices (IDX30, LQ45, KOMPAS100, etc.) must be fetched from idx.co.id.
    """

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._limiter = _idx_limiter

    def _get_session(self):
        """Get or create a session with Cloudflare bypass."""
        if self._session is None:
            if _HAS_CURL_CFFI:
                # curl_cffi impersonates a real browser TLS fingerprint
                self._session = cffi_requests.Session(impersonate="chrome")
                logger.info("IDX adapter: using curl_cffi (Chrome impersonation)")
            else:
                self._session = requests.Session()
                self._session.headers.update(_BROWSER_HEADERS)
                logger.warning("IDX adapter: curl_cffi not available, using requests (may be blocked by Cloudflare)")
            # Visit main page to get Cloudflare cookie
            try:
                self._session.get(IDX_BASE, timeout=10)
            except Exception as e:
                logger.warning("Failed to get idx.co.id session cookie: %s", e)
        return self._session

    def _rate_limit(self) -> None:
        """Adaptive rate limiting — auto-adjusts based on server response."""
        self._limiter.acquire_sync()
        self._limiter.sleep_backoff_sync()

    def _fetch_json(self, url: str, params: dict) -> list[dict] | None:
        """Fetch JSON from idx.co.id with adaptive rate limiting and error handling."""
        self._rate_limit()
        session = self._get_session()

        try:
            if _HAS_CURL_CFFI:
                resp = session.get(url, params=params, timeout=15)
            else:
                resp = session.get(url, params=params, timeout=15, headers=_BROWSER_HEADERS)

            status = resp.status_code
            start = time.time()
            latency_ms = (time.time() - start) * 1000

            # Feed response back to limiter for adaptive adjustment
            if status == 429:
                self._limiter._async._total_429 += 1
                self._limiter._async._total_errors += 1
                self._limiter._async._apply_backoff()
                self._limiter._async._decrease_rate(0.5)
                logger.warning("idx.co.id returned 429 for %s — backing off", url)
                return None
            elif 500 <= status < 600:
                self._limiter._async._total_errors += 1
                self._limiter._async._apply_backoff()
                self._limiter._async._decrease_rate(0.75)
                logger.warning("idx.co.id returned %d for %s", status, url)
                return None
            elif status == 403:
                logger.warning("idx.co.id returned 403 (Cloudflare blocked) for %s", url)
                return None
            else:
                self._limiter._async._reset_backoff()
                self._limiter._async._update_latency(latency_ms)

            resp.raise_for_status()
            data = resp.json()
            # idx.co.id returns DataTables format: {"data": [...], "recordsTotal": N}
            # or plain array [...]
            if isinstance(data, dict):
                for key in ("data", "Items", "items", "result", "Results"):
                    if key in data:
                        return data[key]
                # Empty response
                if "recordsTotal" in data and data.get("recordsTotal", 0) == 0:
                    return []
                return [data] if data else []
            return data if isinstance(data, list) else None
        except Exception as e:
            logger.error("idx.co.id fetch failed for %s: %s", url, e)
            return None

    def fetch_index_daily(
        self,
        index_code: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> list[dict]:
        """Fetch daily index values from idx.co.id.

        Args:
            index_code: Index code without .JK suffix (e.g., "IDX30", "LQ45", "KOMPAS100")
            start_date: Start date (default: 5 days ago)
            end_date: End date (default: today)

        Returns:
            List of dicts with keys: date, open, high, low, close, volume
        """
        if end_date is None:
            end_date = date.today()
        elif isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        if start_date is None:
            start_date = end_date - timedelta(days=7)
        elif isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        # idx.co.id GetIndexSummary takes a single date, returns all indices for that day
        results: list[dict] = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                date_str = current.strftime("%Y%m%d")
                params = {"date": date_str, "length": 9999, "start": 0}
                data = self._fetch_json(IDX_INDEX_SUMMARY, params)

                if data:
                    for item in data:
                        item_code = item.get("IndexCode", "")
                        if index_code.upper() == item_code.upper():
                            results.append({
                                "date": current.isoformat(),
                                "open": float(item.get("Previous", 0) or 0),
                                "high": float(item.get("Highest", 0) or 0),
                                "low": float(item.get("Lowest", 0) or 0),
                                "close": float(item.get("Close", 0) or 0),
                                "volume": float(item.get("Volume", 0) or 0),
                                "change": float(item.get("Change", 0) or 0),
                            })
                            break
            current += timedelta(days=1)

        logger.info("IDX index %s: %d records from %s to %s",
                    index_code, len(results), start_date, end_date)
        return results

    def fetch_stock_daily(
        self,
        stock_code: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> list[dict]:
        """Fetch daily stock OHLC from idx.co.id.

        Args:
            stock_code: Stock code without .JK suffix (e.g., "BBCA", "TLKM")
            start_date: Start date (default: 5 days ago)
            end_date: End date (default: today)

        Returns:
            List of dicts with keys: date, open, high, low, close, volume
        """
        if end_date is None:
            end_date = date.today()
        elif isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        if start_date is None:
            start_date = end_date - timedelta(days=7)
        elif isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        results: list[dict] = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                date_str = current.strftime("%Y%m%d")
                params = {"date": date_str, "length": 9999, "start": 0}
                data = self._fetch_json(IDX_STOCK_SUMMARY, params)

                if data:
                    for item in data:
                        item_code = item.get("StockCode", "")
                        if stock_code.upper() == item_code.upper():
                            results.append({
                                "date": current.isoformat(),
                                "open": float(item.get("OpenPrice", 0) or 0),
                                "high": float(item.get("High", 0) or 0),
                                "low": float(item.get("Low", 0) or 0),
                                "close": float(item.get("Close", 0) or 0),
                                "volume": float(item.get("Volume", 0) or 0),
                                "value": float(item.get("Value", 0) or 0),
                                "frequency": int(item.get("Frequency", 0) or 0),
                            })
                            break
            current += timedelta(days=1)

        logger.info("IDX stock %s: %d records from %s to %s",
                    stock_code, len(results), start_date, end_date)
        return results

    def fetch_all_indices_for_date(self, target_date: str | date) -> list[dict]:
        """Fetch all index values for a single date from idx.co.id.

        This is more efficient than fetch_index_daily when you need
        multiple indices for the same date — one API call gets all.

        Args:
            target_date: Date to fetch (string YYYY-MM-DD or date object)

        Returns:
            List of dicts with IndexCode, Close, High, Low, etc.
        """
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        date_str = target_date.strftime("%Y%m%d")
        params = {"date": date_str, "length": 9999, "start": 0}
        data = self._fetch_json(IDX_INDEX_SUMMARY, params)

        if data:
            results = []
            for item in data:
                results.append({
                    "index_code": item.get("IndexCode", ""),
                    "date": target_date.isoformat(),
                    "previous": float(item.get("Previous", 0) or 0),
                    "high": float(item.get("Highest", 0) or 0),
                    "low": float(item.get("Lowest", 0) or 0),
                    "close": float(item.get("Close", 0) or 0),
                    "volume": float(item.get("Volume", 0) or 0),
                    "change": float(item.get("Change", 0) or 0),
                })
            logger.info("IDX all indices for %s: %d records", target_date, len(results))
            return results
        return []

    def fetch_all_stocks_for_date(self, target_date: str | date) -> list[dict]:
        """Fetch all stock OHLC for a single date from idx.co.id.

        One API call gets ~963 stocks for one trading day.
        This is the most efficient way to fetch IDX EOD data.

        Args:
            target_date: Date to fetch (string YYYY-MM-DD or date object)

        Returns:
            List of dicts with StockCode, Close, High, Low, etc.
        """
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        date_str = target_date.strftime("%Y%m%d")
        params = {"date": date_str, "length": 9999, "start": 0}
        data = self._fetch_json(IDX_STOCK_SUMMARY, params)

        if data:
            results = []
            for item in data:
                results.append({
                    "stock_code": item.get("StockCode", ""),
                    "name": item.get("StockName", ""),
                    "date": target_date.isoformat(),
                    "open": float(item.get("OpenPrice", 0) or 0),
                    "high": float(item.get("High", 0) or 0),
                    "low": float(item.get("Low", 0) or 0),
                    "close": float(item.get("Close", 0) or 0),
                    "volume": float(item.get("Volume", 0) or 0),
                    "value": float(item.get("Value", 0) or 0),
                    "frequency": int(item.get("Frequency", 0) or 0),
                })
            logger.info("IDX all stocks for %s: %d records", target_date, len(results))
            return results
        return []

    def fetch_foreign_flow_for_date(self, target_date: str | date) -> list[dict]:
        """Fetch foreign flow data (ForeignBuy/ForeignSell) for all stocks on a date.

        Uses the same GetStockSummary endpoint which returns ForeignBuy and
        ForeignSell fields per stock. This method extracts only the foreign
        flow fields and computes domestic flow from totals.

        Args:
            target_date: Date to fetch (string YYYY-MM-DD or date object).

        Returns:
            List of dicts with keys: ticker, date, foreign_buy, foreign_sell,
            foreign_net, domestic_buy, domestic_sell, domestic_net, source.
        """
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        date_str = target_date.strftime("%Y%m%d")
        params = {"date": date_str, "length": 9999, "start": 0}
        data = self._fetch_json(IDX_STOCK_SUMMARY, params)

        if not data:
            return []

        results = []
        for item in data:
            stock_code = item.get("StockCode", "")
            if not stock_code:
                continue

            fb = float(item.get("ForeignBuy", 0) or 0)
            fs = float(item.get("ForeignSell", 0) or 0)
            fn = fb - fs

            total_value = float(item.get("Value", 0) or 0)
            db = total_value - fb
            ds = total_value - fs
            dn = db - ds

            results.append({
                "ticker": f"{stock_code}.JK",
                "date": target_date.isoformat(),
                "foreign_buy": fb,
                "foreign_sell": fs,
                "foreign_net": fn,
                "domestic_buy": db,
                "domestic_sell": ds,
                "domestic_net": dn,
                "source": "idx_co_id",
            })

        logger.info("IDX foreign flow for %s: %d records", target_date, len(results))
        return results

    def fetch_broker_summary_for_date(self, target_date: str | date) -> list[dict]:
        """Fetch broker summary (aggregate per broker firm) for a date.

        Args:
            target_date: Date to fetch (string YYYY-MM-DD or date object).

        Returns:
            List of dicts with keys: broker_code, broker_name, volume,
            value, frequency, date.
        """
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        date_str = target_date.strftime("%Y%m%d")
        params = {"date": date_str, "length": 9999, "start": 0}
        data = self._fetch_json(IDX_BROKER_SUMMARY, params)

        if not data:
            return []

        # Response is {draw, recordsTotal, data: [...]} — extract data list
        if isinstance(data, dict):
            data = data.get("data", [])

        results = []
        for item in data:
            results.append({
                "broker_code": item.get("IDFirm", item.get("BrokerCode", "")),
                "broker_name": item.get("FirmName", item.get("BrokerName", "")),
                "date": target_date.isoformat(),
                "volume": float(item.get("Volume", 0) or 0),
                "value": float(item.get("Value", 0) or 0),
                "frequency": int(item.get("Frequency", 0) or 0),
            })

        logger.info("IDX broker summary for %s: %d records", target_date, len(results))
        return results

    def fetch_company_calendar(self, target_date: str | date, date_range: str = "m") -> list[dict]:
        """Fetch corporate event calendar (RUPS, dividends, splits) from idx.co.id.

        Uses /primary/Home/GetCalendar endpoint. Response format:
            {request: {...}, ResultCount: N, Results: [...]}

        Each result item has fields:
            title (ticker code), Jenis (event type: Rencana/RUPS/PE),
            description, start (ISO date), TglWaktuRups, location,
            AgendaTahun, Step, MonthName, MonthNumber, Year

        Args:
            target_date: Date to fetch (string YYYY-MM-DD or date object).
            date_range: 'm' for month, 'd' for day.

        Returns:
            List of dicts with calendar events.
        """
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)

        date_str = target_date.strftime("%Y%m%d")
        params = {"date": date_str, "range": date_range, "indexfrom": 0, "pagesize": 9999}
        data = self._fetch_json(IDX_COMPANY_CALENDAR, params)

        if not data:
            return []

        # _fetch_json already extracts Results list from dict response
        if isinstance(data, list):
            items = data
        else:
            return []

        results = []
        for item in items:
            ticker_code = item.get("title", "") or item.get("KodeEmiten", "")
            if not ticker_code:
                continue
            results.append({
                "ticker": f"{ticker_code}.JK",
                "event_date": item.get("start", item.get("TglWaktuRups", "")),
                "event_type": item.get("Jenis", ""),
                "description": item.get("description", ""),
                "agenda": item.get("AgendaTahun", ""),
                "location": item.get("location", ""),
                "step": item.get("Step", ""),
                "tgl_rups": item.get("TglWaktuRups", ""),
                "tgl_pe": item.get("TglWaktuPE", ""),
            })

        logger.info("IDX company calendar for %s (%s): %d records", target_date, date_range, len(results))
        return results
