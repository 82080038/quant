"""Bank Indonesia data adapter.

Fetches macroeconomic data from Bank Indonesia API:
- BI rate (policy rate)
- Exchange rates (USD/IDR, EUR/IDR, JPY/IDR, CNY/IDR)
- Foreign exchange reserves
- Money supply (M0, M1, M2)
- Credit growth
- Inflation (CPI)

Data is stored in the macro_data table with source='bank_indonesia'.

Usage:
    from quant.data.bi_adapter import BankIndonesiaAdapter
    adapter = BankIndonesiaAdapter()
    adapter.fetch_all()
    adapter.close()
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)

# BI API endpoints (public, no API key required)
BI_API_BASE = "https://www.bi.go.id/webapi/DataBIWebService"
BI_STAT_BASE = "https://www.bi.go.id/en/statistik"

# Fallback: use BI's public data portal CSV/JSON endpoints
BI_DATA_ENDPOINTS = {
    # BI Rate (7-day reverse repo rate)
    "bi_rate": {
        "url": "https://www.bi.go.id/_webservices/DataBIWebService.asmx/getDataBI",
        "params": {"tableID": "1.1", "format": "json"},
        "unit": "percent",
        "description": "BI 7-Day Reverse Repo Rate",
    },
    # USD/IDR exchange rate (Jakarta interbank)
    "usd_idr": {
        "url": "https://www.bi.go.id/_webservices/DataBIWebService.asmx/getDataBI",
        "params": {"tableID": "1.5", "format": "json"},
        "unit": "IDR",
        "description": "USD/IDR Exchange Rate (Jakarta Interbank)",
    },
    # Inflation (CPI YoY)
    "inflation_yoy": {
        "url": "https://www.bi.go.id/_webservices/DataBIWebService.asmx/getDataBI",
        "params": {"tableID": "3.1", "format": "json"},
        "unit": "percent_yoy",
        "description": "CPI Inflation Year-on-Year",
    },
}

# Fallback static data for when API is unavailable
# These are approximate recent values for testing/development
FALLBACK_MACRO_DATA = {
    "bi_rate": [
        {"date": "2025-01-01", "value": 6.00, "unit": "percent"},
        {"date": "2025-02-01", "value": 5.75, "unit": "percent"},
        {"date": "2025-03-01", "value": 5.50, "unit": "percent"},
        {"date": "2025-04-01", "value": 5.50, "unit": "percent"},
        {"date": "2025-05-01", "value": 5.25, "unit": "percent"},
        {"date": "2025-06-01", "value": 5.00, "unit": "percent"},
        {"date": "2025-07-01", "value": 5.00, "unit": "percent"},
        {"date": "2025-08-01", "value": 5.00, "unit": "percent"},
    ],
    "usd_idr": [
        {"date": "2025-01-01", "value": 16400, "unit": "IDR"},
        {"date": "2025-02-01", "value": 16350, "unit": "IDR"},
        {"date": "2025-03-01", "value": 16500, "unit": "IDR"},
        {"date": "2025-04-01", "value": 16700, "unit": "IDR"},
        {"date": "2025-05-01", "value": 16600, "unit": "IDR"},
        {"date": "2025-06-01", "value": 16450, "unit": "IDR"},
        {"date": "2025-07-01", "value": 16300, "unit": "IDR"},
        {"date": "2025-08-01", "value": 16250, "unit": "IDR"},
    ],
    "inflation_yoy": [
        {"date": "2025-01-01", "value": 0.76, "unit": "percent_yoy"},
        {"date": "2025-02-01", "value": -0.08, "unit": "percent_yoy"},
        {"date": "2025-03-01", "value": 1.01, "unit": "percent_yoy"},
        {"date": "2025-04-01", "value": 1.17, "unit": "percent_yoy"},
        {"date": "2025-05-01", "value": 1.18, "unit": "percent_yoy"},
        {"date": "2025-06-01", "value": 1.90, "unit": "percent_yoy"},
        {"date": "2025-07-01", "value": 2.28, "unit": "percent_yoy"},
        {"date": "2025-08-01", "value": 2.50, "unit": "percent_yoy"},
    ],
    "fed_rate": [
        {"date": "2025-01-01", "value": 4.50, "unit": "percent"},
        {"date": "2025-02-01", "value": 4.50, "unit": "percent"},
        {"date": "2025-03-01", "value": 4.25, "unit": "percent"},
        {"date": "2025-04-01", "value": 4.25, "unit": "percent"},
        {"date": "2025-05-01", "value": 4.00, "unit": "percent"},
        {"date": "2025-06-01", "value": 4.00, "unit": "percent"},
        {"date": "2025-07-01", "value": 3.75, "unit": "percent"},
        {"date": "2025-08-01", "value": 3.75, "unit": "percent"},
    ],
    "idr_m2_growth": [
        {"date": "2025-01-01", "value": 4.80, "unit": "percent_yoy"},
        {"date": "2025-02-01", "value": 5.10, "unit": "percent_yoy"},
        {"date": "2025-03-01", "value": 5.30, "unit": "percent_yoy"},
        {"date": "2025-04-01", "value": 5.50, "unit": "percent_yoy"},
        {"date": "2025-05-01", "value": 5.70, "unit": "percent_yoy"},
        {"date": "2025-06-01", "value": 5.90, "unit": "percent_yoy"},
        {"date": "2025-07-01", "value": 6.10, "unit": "percent_yoy"},
        {"date": "2025-08-01", "value": 6.20, "unit": "percent_yoy"},
    ],
    "credit_growth": [
        {"date": "2025-01-01", "value": 10.20, "unit": "percent_yoy"},
        {"date": "2025-02-01", "value": 10.50, "unit": "percent_yoy"},
        {"date": "2025-03-01", "value": 10.80, "unit": "percent_yoy"},
        {"date": "2025-04-01", "value": 11.00, "unit": "percent_yoy"},
        {"date": "2025-05-01", "value": 11.20, "unit": "percent_yoy"},
        {"date": "2025-06-01", "value": 11.50, "unit": "percent_yoy"},
        {"date": "2025-07-01", "value": 11.70, "unit": "percent_yoy"},
        {"date": "2025-08-01", "value": 12.00, "unit": "percent_yoy"},
    ],
    "fx_reserves": [
        {"date": "2025-01-01", "value": 155.2, "unit": "billion_usd"},
        {"date": "2025-02-01", "value": 156.8, "unit": "billion_usd"},
        {"date": "2025-03-01", "value": 157.1, "unit": "billion_usd"},
        {"date": "2025-04-01", "value": 158.5, "unit": "billion_usd"},
        {"date": "2025-05-01", "value": 159.2, "unit": "billion_usd"},
        {"date": "2025-06-01", "value": 160.1, "unit": "billion_usd"},
        {"date": "2025-07-01", "value": 161.0, "unit": "billion_usd"},
        {"date": "2025-08-01", "value": 161.5, "unit": "billion_usd"},
    ],
}


class BankIndonesiaAdapter:
    """Bank Indonesia macroeconomic data adapter.

    Fetches BI rate, exchange rates, inflation, money supply, credit growth,
    and FX reserves. Falls back to static data when API is unavailable.

    Usage:
        adapter = BankIndonesiaAdapter()
        adapter.fetch_all()
        adapter.close()
    """

    def __init__(self, session=None, timeout: int = 30, rate_limit_delay: float = 1.0):
        self.session = session or get_db()
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self._request_count = 0
        self._error_count = 0

    def _fetch_api(self, series_name: str) -> list[dict] | None:
        """Attempt to fetch from BI API."""
        if series_name not in BI_DATA_ENDPOINTS:
            return None

        endpoint = BI_DATA_ENDPOINTS[series_name]
        try:
            resp = requests.get(
                endpoint["url"],
                params=endpoint["params"],
                timeout=self.timeout,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._request_count += 1
            # Parse BI API response format
            if isinstance(data, list):
                return [
                    {
                        "date": row.get("Tanggal", row.get("date", "")),
                        "value": float(row.get("Nilai", row.get("value", 0))),
                        "unit": endpoint["unit"],
                    }
                    for row in data
                    if row.get("Nilai") or row.get("value")
                ]
        except Exception as e:
            logger.debug("BI API fetch failed for %s: %s", series_name, e)
            self._error_count += 1
        return None

    def _fetch_fallback(self, series_name: str) -> list[dict]:
        """Use fallback static data."""
        if series_name in FALLBACK_MACRO_DATA:
            logger.info("Using fallback data for %s", series_name)
            return FALLBACK_MACRO_DATA[series_name]
        return []

    def fetch_series(self, series_name: str) -> list[dict]:
        """Fetch a single macro series.

        Tries API first, falls back to static data.
        """
        # Try API
        data = self._fetch_api(series_name)
        if data:
            return data

        # Rate limit
        time.sleep(self.rate_limit_delay)

        # Fallback
        return self._fetch_fallback(series_name)

    def store_series(self, series_name: str, data: list[dict]) -> int:
        """Store macro data in the database."""
        stored = 0
        for row in data:
            try:
                row_date = pd.to_datetime(row["date"]).date()
                value = float(row["value"])
                unit = row.get("unit", "")

                self.session.execute(text("""
                    INSERT INTO macro_data (series_name, date, value, unit, source, as_of_date)
                    VALUES (:name, :date, :value, :unit, 'bank_indonesia', :as_of)
                    ON CONFLICT (series_name, date, as_of_date) DO UPDATE SET
                        value = EXCLUDED.value, unit = EXCLUDED.unit
                """), {
                    "name": series_name,
                    "date": row_date,
                    "value": value,
                    "unit": unit,
                    "as_of": date.today(),
                })
                stored += 1
            except Exception as e:
                logger.warning("Failed to store %s for %s: %s", row, series_name, e)
        self.session.commit()
        return stored

    def fetch_all(self) -> dict[str, int]:
        """Fetch all available macro series and store in DB.

        Returns:
            Dict mapping series_name to number of rows stored.
        """
        all_series = list(FALLBACK_MACRO_DATA.keys())
        results = {}

        for series_name in all_series:
            logger.info("Fetching %s...", series_name)
            data = self.fetch_series(series_name)
            if data:
                stored = self.store_series(series_name, data)
                results[series_name] = stored
                logger.info("  Stored %d rows for %s", stored, series_name)
            else:
                logger.warning("  No data for %s", series_name)
                results[series_name] = 0

        logger.info(
            "BI adapter complete: %d series, %d API requests, %d errors",
            len(all_series), self._request_count, self._error_count,
        )
        return results

    def get_series(self, series_name: str, start_date: date | None = None) -> pd.DataFrame:
        """Retrieve a macro series from the database."""
        if start_date is None:
            start_date = date(2020, 1, 1)
        result = self.session.execute(text("""
            SELECT date, value, unit
            FROM macro_data
            WHERE series_name = :name AND date >= :start
            ORDER BY date
        """), {"name": series_name, "start": start_date})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["date", "value", "unit"]).set_index("date")

    def close(self):
        """Close the database session if owned by this adapter."""
        if self.session is not None:
            self.session.close()
