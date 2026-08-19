"""Point-in-time query layer — prevents look-ahead bias.

All data retrieval must go through this layer to ensure only data
available as of the simulation/decision date is returned.
"""

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text
from quant.core.db import get_db


class PointInTimeQuery:
    """Bitemporal query helper for point-in-time correct data retrieval."""

    def __init__(self, session=None):
        self._session = session

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def _execute(self, sql, params=None):
        """Execute SQL using existing or new session."""
        return self.session.execute(sql, params or {})

    def get_prices(
        self,
        ticker: str,
        as_of_date: date,
        lookback: int = 252,
    ) -> pd.DataFrame:
        """Get OHLCV data known as of as_of_date (no look-ahead).

        Args:
            ticker: Stock ticker (e.g. 'BBCA.JK')
            as_of_date: The decision date — only data known by this date returned
            lookback: Number of trading days to look back

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, adj_close
        """
        sql = text("""
            SELECT date, open, high, low, close, volume, adj_close
            FROM stock_prices
            WHERE ticker = :ticker
              AND date <= :as_of_date
              AND as_of_date <= :as_of_date
            ORDER BY date DESC
            LIMIT :limit
        """)
        result = self.session.execute(sql, {
            "ticker": ticker,
            "as_of_date": as_of_date,
            "limit": lookback,
        })
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_prices_batch(
        self,
        tickers: list[str],
        as_of_date: date,
        lookback: int = 252,
    ) -> dict[str, pd.DataFrame]:
        """Get prices for multiple tickers (batch)."""
        return {t: self.get_prices(t, as_of_date, lookback) for t in tickers}

    def get_fundamentals(
        self,
        ticker: str,
        as_of_date: date,
    ) -> Optional[pd.Series]:
        """Get latest fundamental data known as of as_of_date."""
        sql = text("""
            SELECT * FROM fundamental_data
            WHERE ticker = :ticker
              AND date <= :as_of_date
              AND as_of_date <= :as_of_date
            ORDER BY date DESC
            LIMIT 1
        """)
        result = self.session.execute(sql, {
            "ticker": ticker,
            "as_of_date": as_of_date,
        })
        row = result.fetchone()
        if row:
            return pd.Series(row._mapping)
        return None

    def get_macro(
        self,
        series_name: str,
        as_of_date: date,
        lookback: int = 252,
    ) -> pd.DataFrame:
        """Get macro data known as of as_of_date."""
        sql = text("""
            SELECT date, value, unit, source
            FROM macro_data
            WHERE series_name = :series
              AND date <= :as_of_date
              AND as_of_date <= :as_of_date
            ORDER BY date DESC
            LIMIT :limit
        """)
        result = self.session.execute(sql, {
            "series": series_name,
            "as_of_date": as_of_date,
            "limit": lookback,
        })
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_foreign_flow(
        self,
        ticker: str,
        as_of_date: date,
        lookback: int = 60,
    ) -> pd.DataFrame:
        """Get foreign flow data known as of as_of_date."""
        sql = text("""
            SELECT date, foreign_buy, foreign_sell, foreign_net,
                   domestic_buy, domestic_sell, domestic_net
            FROM foreign_flow
            WHERE ticker = :ticker
              AND date <= :as_of_date
            ORDER BY date DESC
            LIMIT :limit
        """)
        result = self.session.execute(sql, {
            "ticker": ticker,
            "as_of_date": as_of_date,
            "limit": lookback,
        })
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        if not df.empty:
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_news_sentiment(
        self,
        ticker: Optional[str],
        as_of_date: date,
        lookback: int = 30,
    ) -> pd.DataFrame:
        """Get news sentiment known as of as_of_date."""
        if ticker:
            sql = text("""
                SELECT date, headline, sentiment_score, sentiment_label, source
                FROM news_sentiment
                WHERE (ticker = :ticker OR ticker IS NULL)
                  AND date <= :as_of_date
                ORDER BY date DESC
                LIMIT :limit
            """)
            result = self.session.execute(sql, {
                "ticker": ticker,
                "as_of_date": as_of_date,
                "limit": lookback,
            })
        else:
            sql = text("""
                SELECT date, headline, sentiment_score, sentiment_label, source
                FROM news_sentiment
                WHERE date <= :as_of_date
                ORDER BY date DESC
                LIMIT :limit
            """)
            result = self.session.execute(sql, {
                "as_of_date": as_of_date,
                "limit": lookback,
            })
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        return df

    def get_active_tickers(self, as_of_date: date) -> list[str]:
        """Get list of active tickers as of as_of_date."""
        sql = text("""
            SELECT ticker FROM instruments
            WHERE is_active = TRUE
              AND is_delisted = FALSE
              AND asset_class = 'equity'
              AND (listed_date IS NULL OR listed_date <= :as_of_date)
              AND (delisted_date IS NULL OR delisted_date > :as_of_date)
            ORDER BY ticker
        """)
        result = self.session.execute(sql, {"as_of_date": as_of_date})
        return [r[0] for r in result.fetchall()]

    def get_trading_days(self, start: date, end: date) -> list[date]:
        """Get list of trading days (dates with stock price data)."""
        sql = text("""
            SELECT DISTINCT date FROM stock_prices
            WHERE date BETWEEN :start AND :end
            ORDER BY date
        """)
        result = self.session.execute(sql, {"start": start, "end": end})
        return [r[0] for r in result.fetchall()]

    def is_trading_day(self, check_date: date) -> bool:
        """Check if a date is a trading day (has price data)."""
        sql = text("""
            SELECT 1 FROM stock_prices WHERE date = :check_date LIMIT 1
        """)
        result = self.session.execute(sql, {"check_date": check_date})
        return result.fetchone() is not None

    def get_feature_values(
        self,
        feature_name: str,
        ticker: str,
        as_of_date: date,
        lookback: int = 252,
    ) -> pd.Series:
        """Get versioned feature values with PIT protection."""
        sql = text("""
            SELECT fv.date, fv.value
            FROM feature_values fv
            JOIN feature_definitions fd ON fv.feature_def_id = fd.id
            WHERE fd.name = :feature_name
              AND fv.ticker = :ticker
              AND fv.date <= :as_of_date
              AND fv.as_of_date <= :as_of_date
              AND fd.is_active = TRUE
            ORDER BY fv.date DESC
            LIMIT :limit
        """)
        result = self.session.execute(sql, {
            "feature_name": feature_name,
            "ticker": ticker,
            "as_of_date": as_of_date,
            "limit": lookback,
        })
        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        if df.empty:
            return pd.Series(dtype=float)
        return df.set_index("date")["value"].sort_index()
