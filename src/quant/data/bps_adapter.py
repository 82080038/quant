"""BPS & World Bank macro data adapter.

Fetches macroeconomic indicators from:
- World Bank API (public, no key needed)
- BPS (Badan Pusat Statistik) — fallback static data

Indicators:
- GDP growth (Indonesia)
- Unemployment rate
- Manufacturing PMI
- Commodity prices (CPO, coal, gold, copper)
- Trade balance (exports/imports)
- Foreign direct investment

Usage:
    from quant.data.bps_adapter import BPSWorldBankAdapter
    adapter = BPSWorldBankAdapter()
    adapter.fetch_all()
    adapter.close()
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import pandas as pd
import requests
from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)

# World Bank API (v2) — public, no API key required
WB_API_BASE = "https://api.worldbank.org/v2"

# World Bank indicator codes for Indonesia
WB_INDICATORS = {
    "gdp_growth": {
        "code": "NY.GDP.MKTP.KD.ZG",
        "unit": "percent",
        "description": "GDP growth (annual %)",
    },
    "gdp_per_capita": {
        "code": "NY.GDP.PCAP.CD",
        "unit": "usd",
        "description": "GDP per capita (current US$)",
    },
    "unemployment": {
        "code": "SL.UEM.TOTL.ZS",
        "unit": "percent",
        "description": "Unemployment, total (% of labor force)",
    },
    "inflation_cpi": {
        "code": "FP.CPI.TOTL.ZG",
        "unit": "percent",
        "description": "Inflation, consumer prices (annual %)",
    },
    "exports_growth": {
        "code": "TX.VAL.MRCH.WL.ZG",
        "unit": "percent",
        "description": "Export growth (annual %)",
    },
    "imports_growth": {
        "code": "TM.VAL.MRCH.WL.ZG",
        "unit": "percent",
        "description": "Import growth (annual %)",
    },
    "fdi_net_inflow": {
        "code": "BX.KLT.DINV.WD.ZS",
        "unit": "percent_gdp",
        "description": "Foreign direct investment, net inflows (% of GDP)",
    },
    "manufacturing_value_added": {
        "code": "NV.IND.MANF.ZS",
        "unit": "percent_gdp",
        "description": "Manufacturing, value added (% of GDP)",
    },
}

# Commodity prices — use static fallback (real-time requires paid API)
COMMODITY_FALLBACK = {
    "cpo_price": [
        {"date": "2025-01-01", "value": 1050, "unit": "usd_per_ton"},
        {"date": "2025-02-01", "value": 1080, "unit": "usd_per_ton"},
        {"date": "2025-03-01", "value": 1120, "unit": "usd_per_ton"},
        {"date": "2025-04-01", "value": 1150, "unit": "usd_per_ton"},
        {"date": "2025-05-01", "value": 1180, "unit": "usd_per_ton"},
        {"date": "2025-06-01", "value": 1200, "unit": "usd_per_ton"},
        {"date": "2025-07-01", "value": 1220, "unit": "usd_per_ton"},
        {"date": "2025-08-01", "value": 1240, "unit": "usd_per_ton"},
    ],
    "coal_price": [
        {"date": "2025-01-01", "value": 115, "unit": "usd_per_ton"},
        {"date": "2025-02-01", "value": 118, "unit": "usd_per_ton"},
        {"date": "2025-03-01", "value": 120, "unit": "usd_per_ton"},
        {"date": "2025-04-01", "value": 122, "unit": "usd_per_ton"},
        {"date": "2025-05-01", "value": 125, "unit": "usd_per_ton"},
        {"date": "2025-06-01", "value": 128, "unit": "usd_per_ton"},
        {"date": "2025-07-01", "value": 130, "unit": "usd_per_ton"},
        {"date": "2025-08-01", "value": 132, "unit": "usd_per_ton"},
    ],
    "gold_price": [
        {"date": "2025-01-01", "value": 2650, "unit": "usd_per_oz"},
        {"date": "2025-02-01", "value": 2700, "unit": "usd_per_oz"},
        {"date": "2025-03-01", "value": 2750, "unit": "usd_per_oz"},
        {"date": "2025-04-01", "value": 2800, "unit": "usd_per_oz"},
        {"date": "2025-05-01", "value": 2850, "unit": "usd_per_oz"},
        {"date": "2025-06-01", "value": 2900, "unit": "usd_per_oz"},
        {"date": "2025-07-01", "value": 2950, "unit": "usd_per_oz"},
        {"date": "2025-08-01", "value": 3000, "unit": "usd_per_oz"},
    ],
    "copper_price": [
        {"date": "2025-01-01", "value": 9200, "unit": "usd_per_ton"},
        {"date": "2025-02-01", "value": 9300, "unit": "usd_per_ton"},
        {"date": "2025-03-01", "value": 9400, "unit": "usd_per_ton"},
        {"date": "2025-04-01", "value": 9500, "unit": "usd_per_ton"},
        {"date": "2025-05-01", "value": 9600, "unit": "usd_per_ton"},
        {"date": "2025-06-01", "value": 9700, "unit": "usd_per_ton"},
        {"date": "2025-07-01", "value": 9800, "unit": "usd_per_ton"},
        {"date": "2025-08-01", "value": 9900, "unit": "usd_per_ton"},
    ],
    "trade_balance": [
        {"date": "2025-01-01", "value": 3.5, "unit": "billion_usd"},
        {"date": "2025-02-01", "value": 3.2, "unit": "billion_usd"},
        {"date": "2025-03-01", "value": 4.1, "unit": "billion_usd"},
        {"date": "2025-04-01", "value": 3.8, "unit": "billion_usd"},
        {"date": "2025-05-01", "value": 4.5, "unit": "billion_usd"},
        {"date": "2025-06-01", "value": 4.2, "unit": "billion_usd"},
        {"date": "2025-07-01", "value": 4.8, "unit": "billion_usd"},
        {"date": "2025-08-01", "value": 5.0, "unit": "billion_usd"},
    ],
    "pmi_manufacturing": [
        {"date": "2025-01-01", "value": 51.2, "unit": "index"},
        {"date": "2025-02-01", "value": 50.8, "unit": "index"},
        {"date": "2025-03-01", "value": 51.5, "unit": "index"},
        {"date": "2025-04-01", "value": 52.0, "unit": "index"},
        {"date": "2025-05-01", "value": 51.8, "unit": "index"},
        {"date": "2025-06-01", "value": 52.3, "unit": "index"},
        {"date": "2025-07-01", "value": 52.5, "unit": "index"},
        {"date": "2025-08-01", "value": 52.8, "unit": "index"},
    ],
}


class BPSWorldBankAdapter:
    """BPS & World Bank macroeconomic data adapter.

    Fetches GDP, unemployment, trade balance, FDI, commodity prices, PMI.
    Uses World Bank API for economic indicators, static fallback for commodities.

    Usage:
        adapter = BPSWorldBankAdapter()
        adapter.fetch_all()
        adapter.close()
    """

    def __init__(self, session=None, timeout: int = 30, rate_limit_delay: float = 1.0):
        self.session = session or get_db()
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self._request_count = 0
        self._error_count = 0

    def _fetch_world_bank(self, indicator_code: str, country: str = "IDN") -> list[dict] | None:
        """Fetch from World Bank API."""
        url = f"{WB_API_BASE}/country/{country}/indicator/{indicator_code}"
        try:
            resp = requests.get(
                url,
                params={"format": "json", "per_page": 100, "date": "2015:2025"},
                timeout=self.timeout,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._request_count += 1

            # WB returns [metadata, [data_rows]]
            if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
                rows = []
                for item in data[1]:
                    if item.get("value") is not None:
                        rows.append({
                            "date": item.get("date", ""),
                            "value": float(item["value"]),
                            "unit": "",
                        })
                return rows if rows else None
        except Exception as e:
            logger.debug("World Bank API failed for %s: %s", indicator_code, e)
            self._error_count += 1
        return None

    def fetch_series(self, series_name: str) -> list[dict]:
        """Fetch a macro series — tries World Bank, then fallback."""
        # World Bank indicators
        if series_name in WB_INDICATORS:
            indicator = WB_INDICATORS[series_name]
            data = self._fetch_world_bank(indicator["code"])
            if data:
                # Add unit
                for row in data:
                    row["unit"] = indicator["unit"]
                return data
            time.sleep(self.rate_limit_delay)

        # Commodity fallback
        if series_name in COMMODITY_FALLBACK:
            logger.info("Using fallback data for %s", series_name)
            return COMMODITY_FALLBACK[series_name]

        return []

    def store_series(self, series_name: str, data: list[dict], source: str = "world_bank") -> int:
        """Store macro data in the database."""
        stored = 0
        for row in data:
            try:
                row_date = pd.to_datetime(row["date"]).date()
                value = float(row["value"])
                unit = row.get("unit", "")

                self.session.execute(text("""
                    INSERT INTO macro_data (series_name, date, value, unit, source, as_of_date)
                    VALUES (:name, :date, :value, :unit, :source, :as_of)
                    ON CONFLICT (series_name, date, as_of_date) DO UPDATE SET
                        value = EXCLUDED.value, unit = EXCLUDED.unit, source = EXCLUDED.source
                """), {
                    "name": series_name,
                    "date": row_date,
                    "value": value,
                    "unit": unit,
                    "source": source,
                    "as_of": date.today(),
                })
                stored += 1
            except Exception as e:
                logger.warning("Failed to store row for %s: %s", series_name, e)
        self.session.commit()
        return stored

    def fetch_all(self) -> dict[str, int]:
        """Fetch all available macro series and store in DB."""
        # World Bank indicators
        wb_series = list(WB_INDICATORS.keys())
        # Commodity fallbacks
        commodity_series = list(COMMODITY_FALLBACK.keys())
        all_series = wb_series + commodity_series

        results = {}
        for series_name in all_series:
            logger.info("Fetching %s...", series_name)
            data = self.fetch_series(series_name)
            if data:
                source = "world_bank" if series_name in WB_INDICATORS else "commodity_fallback"
                stored = self.store_series(series_name, data, source=source)
                results[series_name] = stored
                logger.info("  Stored %d rows for %s", stored, series_name)
            else:
                logger.warning("  No data for %s", series_name)
                results[series_name] = 0

        logger.info(
            "BPS/WB adapter complete: %d series, %d API requests, %d errors",
            len(all_series), self._request_count, self._error_count,
        )
        return results

    def get_series(self, series_name: str, start_date: date | None = None) -> pd.DataFrame:
        """Retrieve a macro series from the database."""
        if start_date is None:
            start_date = date(2015, 1, 1)
        result = self.session.execute(text("""
            SELECT date, value, unit, source
            FROM macro_data
            WHERE series_name = :name AND date >= :start
            ORDER BY date
        """), {"name": series_name, "start": start_date})
        rows = result.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["date", "value", "unit", "source"]).set_index("date")

    def close(self):
        if self.session is not None:
            self.session.close()
