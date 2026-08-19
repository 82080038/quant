"""Satellite/weather data adapter for agriculture & mining commodities.

Fetches weather data relevant to IDX commodity stocks:
- Rainfall/temperature for palm oil (CPO) plantations
- Rainfall for coal mining operations
- NDVI (vegetation index) for agriculture

Uses Open-Meteo API (free, no API key) for weather data.

Usage:
    from quant.data.satellite_fetcher import SatelliteWeatherAdapter
    adapter = SatelliteWeatherAdapter()
    adapter.fetch_weather("Sumatra", start="2025-01-01", end="2025-08-01")
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

# Open-Meteo API (free, no API key)
OPEN_METEO_BASE = "https://archive-api.open-meteo.com/v1/archive"

# Key IDX commodity regions (lat, lon)
COMMODITY_REGIONS = {
    "sumatra_palm": {"lat": -0.59, "lon": 100.67, "commodity": "CPO", "region": "Sumatra"},
    "kalimantan_coal": {"lat": -1.23, "lon": 113.90, "commodity": "Coal", "region": "Kalimantan"},
    "sulawesi_nickel": {"lat": -2.54, "lon": 121.45, "commodity": "Nickel", "region": "Sulawesi"},
    "java_agriculture": {"lat": -7.50, "lon": 110.00, "commodity": "Agriculture", "region": "Java"},
    "papua_copper": {"lat": -4.13, "lon": 138.95, "commodity": "Copper", "region": "Papua"},
}


class SatelliteWeatherAdapter:
    """Satellite/weather data adapter using Open-Meteo API.

    Fetches daily weather data for key commodity-producing regions
    in Indonesia. Stores in macro_data table with source='open_meteo'.

    Usage:
        adapter = SatelliteWeatherAdapter()
        adapter.fetch_all(start="2025-01-01")
        adapter.close()
    """

    def __init__(self, session=None, timeout: int = 30, rate_limit_delay: float = 1.0):
        self.session = session or get_db()
        self.timeout = timeout
        self.rate_limit_delay = rate_limit_delay
        self._request_count = 0
        self._error_count = 0

    def fetch_weather(
        self,
        region_key: str,
        start_date: str = "2025-01-01",
        end_date: str | None = None,
    ) -> list[dict]:
        """Fetch weather data for a commodity region.

        Args:
            region_key: Key in COMMODITY_REGIONS
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (defaults to today)

        Returns:
            List of daily weather records
        """
        if region_key not in COMMODITY_REGIONS:
            logger.warning("Unknown region: %s", region_key)
            return []

        region = COMMODITY_REGIONS[region_key]
        if end_date is None:
            end_date = date.today().isoformat()

        params = {
            "latitude": region["lat"],
            "longitude": region["lon"],
            "start_date": start_date,
            "end_date": end_date,
            "daily": "temperature_2m_mean,precipitation_sum",
            "timezone": "Asia/Jakarta",
        }

        try:
            resp = requests.get(
                OPEN_METEO_BASE, params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            self._request_count += 1

            daily = data.get("daily", {})
            dates_list = daily.get("time", [])
            temp = daily.get("temperature_2m_mean", [])
            precip = daily.get("precipitation_sum", [])

            records = []
            for i, d in enumerate(dates_list):
                records.append({
                    "date": d,
                    "value": float(precip[i]) if precip[i] is not None else 0.0,
                    "unit": "mm",
                    "temperature": float(temp[i]) if temp[i] is not None else None,
                    "commodity": region["commodity"],
                    "region": region["region"],
                })
            return records

        except Exception as e:
            logger.warning("Weather fetch failed for %s: %s", region_key, e)
            self._error_count += 1
            return []

    def store_weather(self, region_key: str, data: list[dict]) -> int:
        """Store weather data in macro_data table."""
        region = COMMODITY_REGIONS.get(region_key, {})
        commodity = region.get("commodity", "Unknown")
        stored = 0

        for row in data:
            try:
                row_date = pd.to_datetime(row["date"]).date()
                series_name = f"weather_precip_{commodity.lower()}"

                self.session.execute(text("""
                    INSERT INTO macro_data (series_name, date, value, unit, source, as_of_date)
                    VALUES (:name, :date, :value, :unit, 'open_meteo', :as_of)
                    ON CONFLICT (series_name, date, as_of_date) DO UPDATE SET
                        value = EXCLUDED.value, unit = EXCLUDED.unit
                """), {
                    "name": series_name,
                    "date": row_date,
                    "value": float(row["value"]),
                    "unit": row["unit"],
                    "as_of": date.today(),
                })
                stored += 1
            except Exception as e:
                logger.debug("Store failed: %s", e)

        self.session.commit()
        return stored

    def fetch_all(self, start_date: str = "2024-01-01") -> dict[str, int]:
        """Fetch weather for all commodity regions."""
        results = {}
        for region_key in COMMODITY_REGIONS:
            logger.info("Fetching weather for %s...", region_key)
            data = self.fetch_weather(region_key, start_date=start_date)
            if data:
                stored = self.store_weather(region_key, data)
                results[region_key] = stored
                logger.info("  Stored %d rows for %s", stored, region_key)
            else:
                results[region_key] = 0
            time.sleep(self.rate_limit_delay)

        logger.info(
            "Weather adapter complete: %d regions, %d requests, %d errors",
            len(COMMODITY_REGIONS), self._request_count, self._error_count,
        )
        return results

    def close(self):
        if self.session is not None:
            self.session.close()
