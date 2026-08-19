"""Holiday Effect Analyzer — analisis dampang holiday bursa terhadap return.

Menganalisis 3 jenis holiday effect:
1. **Pre-holiday effect**: return pada hari terakhir trading sebelum holiday
   (sering positif karena window dressing / squaring position)
2. **Post-holiday effect**: return pada hari pertama trading setelah holiday
   (sering reversal atau continuation pattern)
3. **Spillover effect**: dampak holiday bursa global (NYSE, TSE, HKEX, dll)
   terhadap IDX hari berikutnya (global contagion)

Hasil disimpan ke tabel `holiday_effects` untuk digunakan oleh modul prediksi
sebagai feature (days_to_holiday, is_pre_holiday, is_post_holiday).

Sumber teori:
- Lakonishok & Smidt (1988): pre-holiday effect di NYSE (~+0.2% avg)
- Ariel (1990): holiday effect lebih kuat dari weekend effect
- Cadsby & Ratner (1992): holiday effect di global markets
- Chong et al. (2005): pre-holiday effect di Asian markets termasuk IDX
- pustaka/36-gap-data-timezone-global-idx.md

Usage:
    from quant.analysis.holiday_effect import HolidayEffectAnalyzer
    analyzer = HolidayEffectAnalyzer()
    analyzer.analyze_all()  # compute + save to DB
    features = analyzer.get_holiday_features("^JKSE", as_of=date(2026, 8, 25))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text

from quant.db.engine import get_engine

logger = logging.getLogger(__name__)

# Index tickers per exchange for spillover analysis
INDEX_TICKERS: dict[str, str] = {
    "XIDX": "^JKSE",
    "XNYS": "^GSPC",
    "XNAS": "^IXIC",
    "XTSE": "^N225",
    "XHKG": "^HSI",
    "XLON": "^FTSE",
    "XFRA": "^GDAXI",
    "XKRX": "^KS11",
    "XSES": "^STI",
    "XASX": "^AXJO",
    "XBKK": "^SET.BK",
    "XPHS": "^PSE",
    "XNSE": "^NSEI",
    "XBOM": "^BSESN",
    "XTAI": "^TWII",
    "XPAR": "^STOXX50E",
    "XMTA": "FTSEMIB.MI",
    "XMAD": "^IBEX",
    "BVMF": "^BVSP",
    "XTSX": "^GSPTSE",
    "XSAU": "^TASI.SR",
    "XJSE": "JSE.JO",
}


@dataclass
class HolidayEffectResult:
    """Hasil analisis holiday effect untuk satu (exchange, holiday_name)."""
    mic_code: str
    holiday_name: str
    pre_holiday_avg_return: float  # avg return hari sebelum holiday (%)
    post_holiday_avg_return: float  # avg return hari setelah holiday (%)
    pre_holiday_win_rate: float  # % positive pre-holiday
    post_holiday_win_rate: float  # % positive post-holiday
    n_occurrences: int  # jumlah holiday yang dianalisis
    pre_holiday_std: float  # std dev pre-holiday return
    post_holiday_std: float  # std dev post-holiday return
    is_significant: bool  # t-test p < 0.05


@dataclass
class SpilloverResult:
    """Hasil analisis spillover: holiday bursa global → IDX."""
    source_mic: str
    source_holiday_name: str
    idx_next_day_avg_return: float  # avg IDX return hari setelah source holiday
    idx_next_day_win_rate: float
    n_occurrences: int
    is_significant: bool


class HolidayEffectAnalyzer:
    """Analyze pre/post holiday effects and cross-market spillover."""

    def __init__(self, lookback_years: int = 10) -> None:
        self.lookback_years = lookback_years
        self._engine = get_engine()

    def _get_trading_days(
        self, ticker: str, start: date, end: date
    ) -> pd.DataFrame:
        """Get daily OHLCV for a ticker as DataFrame with date index."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT timestamp::date as date, close, adjusted_close, volume
                    FROM stock_prices
                    WHERE ticker = :ticker
                      AND timeframe = '1d'
                      AND timestamp::date BETWEEN :start AND :end
                    ORDER BY timestamp
                """),
                {"ticker": ticker, "start": start, "end": end},
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["date", "close", "adjusted_close", "volume"])
        df = pd.DataFrame(rows, columns=["date", "close", "adjusted_close", "volume"])
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def _get_holidays(self, mic_code: str, start: date, end: date) -> list[tuple[date, str]]:
        """Get holidays for an exchange within date range."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT eh.holiday_date, eh.name
                    FROM exchange_holidays eh
                    JOIN exchanges e ON eh.exchange_id = e.id
                    WHERE e.mic = :mic
                      AND eh.holiday_date BETWEEN :start AND :end
                      AND eh.holiday_date < :end
                    ORDER BY eh.holiday_date
                """),
                {"mic": mic_code, "start": start, "end": end},
            ).fetchall()
        return [(r[0], r[1] or "Market Holiday") for r in rows]

    def _compute_returns(self, df: pd.DataFrame) -> pd.Series:
        """Compute daily returns from adjusted_close."""
        if df.empty or len(df) < 2:
            return pd.Series(dtype=float)
        prices = df.set_index("date")["adjusted_close"].astype(float)
        returns = prices.pct_change() * 100  # in %
        return returns.dropna()

    def analyze_holiday_effect(
        self, mic_code: str, ticker: str | None = None
    ) -> list[HolidayEffectResult]:
        """Analyze pre/post holiday returns for a single exchange.

        Args:
            mic_code: Exchange MIC code (e.g. "XIDX")
            ticker: Index ticker for the exchange. If None, uses INDEX_TICKERS.

        Returns:
            List of HolidayEffectResult per holiday_name.
        """
        if ticker is None:
            ticker = INDEX_TICKERS.get(mic_code)
            if ticker is None:
                logger.warning("No index ticker for %s", mic_code)
                return []

        end = date.today()
        start = end - timedelta(days=self.lookback_years * 365)

        df = self._get_trading_days(ticker, start, end)
        if len(df) < 50:
            logger.warning("Insufficient data for %s: %d rows", ticker, len(df))
            return []

        holidays = self._get_holidays(mic_code, start, end)
        if not holidays:
            logger.warning("No holidays found for %s in range", mic_code)
            return []

        # Build date → return mapping
        df_sorted = df.sort_values("date").reset_index(drop=True)
        dates = df_sorted["date"].tolist()
        closes = df_sorted["adjusted_close"].astype(float).tolist()

        # Build date → index mapping for quick lookup
        date_idx = {d: i for i, d in enumerate(dates)}

        # Group holidays by name
        from collections import defaultdict
        holiday_groups: dict[str, list[date]] = defaultdict(list)
        for h_date, h_name in holidays:
            holiday_groups[h_name].append(h_date)

        results: list[HolidayEffectResult] = []
        for h_name, h_dates in holiday_groups.items():
            pre_returns: list[float] = []
            post_returns: list[float] = []

            for h_date in h_dates:
                # Find the trading day before holiday
                pre_idx = None
                for i in range(len(dates) - 1, -1, -1):
                    if dates[i] < h_date:
                        pre_idx = i
                        break
                # Find the trading day after holiday
                post_idx = None
                for i in range(len(dates)):
                    if dates[i] > h_date:
                        post_idx = i
                        break

                # Pre-holiday return: return on the last trading day before holiday
                if pre_idx is not None and pre_idx > 0:
                    pre_ret = (closes[pre_idx] / closes[pre_idx - 1] - 1) * 100
                    pre_returns.append(pre_ret)

                # Post-holiday return: return on the first trading day after holiday
                if post_idx is not None and post_idx > 0:
                    post_ret = (closes[post_idx] / closes[post_idx - 1] - 1) * 100
                    post_returns.append(post_ret)

            if len(pre_returns) < 3 and len(post_returns) < 3:
                continue

            import numpy as np
            from scipy import stats

            pre_arr = np.array(pre_returns) if pre_returns else np.array([0.0])
            post_arr = np.array(post_returns) if post_returns else np.array([0.0])

            # t-test: is mean return significantly different from 0?
            pre_pvalue = stats.ttest_1samp(pre_arr, 0).pvalue if len(pre_returns) >= 3 else 1.0
            post_pvalue = stats.ttest_1samp(post_arr, 0).pvalue if len(post_returns) >= 3 else 1.0
            is_sig = pre_pvalue < 0.05 or post_pvalue < 0.05

            results.append(HolidayEffectResult(
                mic_code=mic_code,
                holiday_name=h_name,
                pre_holiday_avg_return=float(pre_arr.mean()),
                post_holiday_avg_return=float(post_arr.mean()),
                pre_holiday_win_rate=float((pre_arr > 0).mean() * 100),
                post_holiday_win_rate=float((post_arr > 0).mean() * 100),
                n_occurrences=len(h_dates),
                pre_holiday_std=float(pre_arr.std()) if len(pre_returns) >= 2 else 0.0,
                post_holiday_std=float(post_arr.std()) if len(post_returns) >= 2 else 0.0,
                is_significant=is_sig,
            ))

        return results

    def analyze_spillover_to_idx(
        self, source_mics: list[str] | None = None
    ) -> list[SpilloverResult]:
        """Analyze spillover: holiday in global exchange → IDX next day return.

        When a global exchange (e.g. NYSE) is on holiday, does IDX react
        differently the next trading day? Tests global contagion hypothesis.

        Args:
            source_mics: List of source exchange MICs. Default: major global.

        Returns:
            List of SpilloverResult per (source_mic, holiday_name).
        """
        if source_mics is None:
            source_mics = ["XNYS", "XTSE", "XHKG", "XLON", "XFRA", "XKRX", "XSES", "XASX"]

        end = date.today()
        start = end - timedelta(days=self.lookback_years * 365)

        # Get IDX daily returns
        idx_df = self._get_trading_days("^JKSE", start, end)
        if len(idx_df) < 50:
            logger.warning("Insufficient IDX data for spillover analysis")
            return []

        idx_df = idx_df.sort_values("date").reset_index(drop=True)
        idx_dates = idx_df["date"].tolist()
        idx_closes = idx_df["adjusted_close"].astype(float).tolist()
        idx_date_idx = {d: i for i, d in enumerate(idx_dates)}

        from collections import defaultdict
        results: list[SpilloverResult] = []

        for src_mic in source_mics:
            holidays = self._get_holidays(src_mic, start, end)
            if not holidays:
                continue

            holiday_groups: dict[str, list[date]] = defaultdict(list)
            for h_date, h_name in holidays:
                holiday_groups[h_name].append(h_date)

            for h_name, h_dates in holiday_groups.items():
                idx_returns: list[float] = []

                for h_date in h_dates:
                    # Find IDX trading day AFTER the source holiday
                    post_idx = None
                    for i, d in enumerate(idx_dates):
                        if d > h_date:
                            post_idx = i
                            break

                    if post_idx is not None and post_idx > 0:
                        ret = (idx_closes[post_idx] / idx_closes[post_idx - 1] - 1) * 100
                        idx_returns.append(ret)

                if len(idx_returns) < 3:
                    continue

                import numpy as np
                from scipy import stats

                arr = np.array(idx_returns)
                pvalue = stats.ttest_1samp(arr, 0).pvalue

                results.append(SpilloverResult(
                    source_mic=src_mic,
                    source_holiday_name=h_name,
                    idx_next_day_avg_return=float(arr.mean()),
                    idx_next_day_win_rate=float((arr > 0).mean() * 100),
                    n_occurrences=len(h_dates),
                    is_significant=pvalue < 0.05,
                ))

        return results

    def analyze_all(self) -> dict[str, Any]:
        """Run full analysis for all exchanges + spillover. Save to DB.

        Returns summary dict with counts.
        """
        all_effects: list[HolidayEffectResult] = []
        all_spillovers: list[SpilloverResult] = []

        for mic_code in INDEX_TICKERS:
            logger.info("Analyzing holiday effect for %s...", mic_code)
            effects = self.analyze_holiday_effect(mic_code)
            all_effects.extend(effects)

        logger.info("Analyzing spillover to IDX...")
        spillovers = self.analyze_spillover_to_idx()
        all_spillovers.extend(spillovers)

        # Save to DB
        self._save_to_db(all_effects, all_spillovers)

        return {
            "exchanges_analyzed": len(INDEX_TICKERS),
            "holiday_effects": len(all_effects),
            "spillover_results": len(all_spillovers),
            "significant_effects": sum(1 for e in all_effects if e.is_significant),
            "significant_spillovers": sum(1 for s in all_spillovers if s.is_significant),
        }

    def _save_to_db(
        self,
        effects: list[HolidayEffectResult],
        spillovers: list[SpilloverResult],
    ) -> None:
        """Save results to holiday_effects and holiday_spillover tables."""
        from quant.db.raw import get_raw_connection

        with get_raw_connection() as conn:
            cur = conn.cursor()
            # Create tables if not exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS holiday_effects (
                    id SERIAL PRIMARY KEY,
                    mic_code VARCHAR(10) NOT NULL,
                    holiday_name VARCHAR(200) NOT NULL,
                    pre_holiday_avg_return FLOAT,
                    post_holiday_avg_return FLOAT,
                    pre_holiday_win_rate FLOAT,
                    post_holiday_win_rate FLOAT,
                    n_occurrences INTEGER,
                    pre_holiday_std FLOAT,
                    post_holiday_std FLOAT,
                    is_significant BOOLEAN DEFAULT FALSE,
                    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(mic_code, holiday_name)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS holiday_spillover (
                    id SERIAL PRIMARY KEY,
                    source_mic VARCHAR(10) NOT NULL,
                    source_holiday_name VARCHAR(200) NOT NULL,
                    idx_next_day_avg_return FLOAT,
                    idx_next_day_win_rate FLOAT,
                    n_occurrences INTEGER,
                    is_significant BOOLEAN DEFAULT FALSE,
                    analyzed_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(source_mic, source_holiday_name)
                )
            """)

            # Upsert holiday effects
            for e in effects:
                cur.execute("""
                    INSERT INTO holiday_effects
                        (mic_code, holiday_name, pre_holiday_avg_return,
                         post_holiday_avg_return, pre_holiday_win_rate,
                         post_holiday_win_rate, n_occurrences,
                         pre_holiday_std, post_holiday_std, is_significant)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (mic_code, holiday_name)
                    DO UPDATE SET
                        pre_holiday_avg_return = EXCLUDED.pre_holiday_avg_return,
                        post_holiday_avg_return = EXCLUDED.post_holiday_avg_return,
                        pre_holiday_win_rate = EXCLUDED.pre_holiday_win_rate,
                        post_holiday_win_rate = EXCLUDED.post_holiday_win_rate,
                        n_occurrences = EXCLUDED.n_occurrences,
                        pre_holiday_std = EXCLUDED.pre_holiday_std,
                        post_holiday_std = EXCLUDED.post_holiday_std,
                        is_significant = EXCLUDED.is_significant,
                        analyzed_at = NOW()
                """, (
                    e.mic_code, e.holiday_name,
                    float(e.pre_holiday_avg_return), float(e.post_holiday_avg_return),
                    float(e.pre_holiday_win_rate), float(e.post_holiday_win_rate),
                    int(e.n_occurrences), float(e.pre_holiday_std), float(e.post_holiday_std),
                    bool(e.is_significant),
                ))

            # Upsert spillover results
            for s in spillovers:
                cur.execute("""
                    INSERT INTO holiday_spillover
                        (source_mic, source_holiday_name,
                         idx_next_day_avg_return, idx_next_day_win_rate,
                         n_occurrences, is_significant)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_mic, source_holiday_name)
                    DO UPDATE SET
                        idx_next_day_avg_return = EXCLUDED.idx_next_day_avg_return,
                        idx_next_day_win_rate = EXCLUDED.idx_next_day_win_rate,
                        n_occurrences = EXCLUDED.n_occurrences,
                        is_significant = EXCLUDED.is_significant,
                        analyzed_at = NOW()
                """, (
                    s.source_mic, s.source_holiday_name,
                    float(s.idx_next_day_avg_return), float(s.idx_next_day_win_rate),
                    int(s.n_occurrences), bool(s.is_significant),
                ))

            conn.commit()
            cur.close()

        logger.info("Saved %d holiday effects + %d spillover results to DB",
                     len(effects), len(spillovers))

    # ── Feature builder for prediction modules ────────────────────────────

    def get_holiday_features(
        self, mic_code: str, as_of: date, look_forward: int = 5
    ) -> dict[str, Any]:
        """Build holiday-related features for prediction at a given date.

        Features:
        - days_to_next_holiday: days until next holiday (0 if today is holiday)
        - is_pre_holiday: True if tomorrow is holiday (last trading day before)
        - is_post_holiday: True if yesterday was holiday (first trading day after)
        - next_holiday_name: name of next holiday
        - pre_holiday_expected_return: avg pre-holiday return for this holiday type
        - post_holiday_expected_return: avg post-holiday return for this holiday type
        - is_holiday_today: True if today is a holiday

        Args:
            mic_code: Exchange MIC code
            as_of: Date to compute features for
            look_forward: Max days to look ahead for next holiday

        Returns:
            Dict of feature names → values.
        """
        features: dict[str, Any] = {
            "days_to_next_holiday": look_forward + 1,  # default: far away
            "is_pre_holiday": False,
            "is_post_holiday": False,
            "is_holiday_today": False,
            "next_holiday_name": "",
            "pre_holiday_expected_return": 0.0,
            "post_holiday_expected_return": 0.0,
        }

        with self._engine.connect() as conn:
            # Check if today is holiday
            today_hol = conn.execute(
                text("""
                    SELECT eh.name FROM exchange_holidays eh
                    JOIN exchanges e ON eh.exchange_id = e.id
                    WHERE e.mic = :mic AND eh.holiday_date = :d
                """),
                {"mic": mic_code, "d": as_of},
            ).first()
            if today_hol:
                features["is_holiday_today"] = True
                features["next_holiday_name"] = today_hol[0] or "Market Holiday"

            # Check if yesterday was holiday (post-holiday)
            yesterday = as_of - timedelta(days=1)
            # Look back up to 4 days to handle weekends
            for lookback in range(1, 5):
                check_date = as_of - timedelta(days=lookback)
                yest_hol = conn.execute(
                    text("""
                        SELECT eh.name FROM exchange_holidays eh
                        JOIN exchanges e ON eh.exchange_id = e.id
                        WHERE e.mic = :mic AND eh.holiday_date = :d
                    """),
                    {"mic": mic_code, "d": check_date},
                ).first()
                if yest_hol:
                    # Check if there's a trading day between check_date and as_of
                    # If no trading day between, then as_of is post-holiday
                    trading_between = conn.execute(
                        text("""
                            SELECT 1 FROM exchange_holidays eh
                            JOIN exchanges e ON eh.exchange_id = e.id
                            WHERE e.mic = :mic
                              AND eh.holiday_date > :check AND eh.holiday_date < :asof
                            LIMIT 1
                        """),
                        {"mic": mic_code, "check": check_date, "asof": as_of},
                    ).first()
                    if not trading_between and lookback <= 3:
                        features["is_post_holiday"] = True
                        # Get expected post-holiday return
                        post_ret = conn.execute(
                            text("""
                                SELECT post_holiday_avg_return FROM holiday_effects
                                WHERE mic_code = :mic AND holiday_name = :name
                            """),
                            {"mic": mic_code, "name": yest_hol[0] or "Market Holiday"},
                        ).first()
                        if post_ret:
                            features["post_holiday_expected_return"] = float(post_ret[0])
                    break

            # Check if tomorrow is holiday (pre-holiday)
            tomorrow = as_of + timedelta(days=1)
            for lookahead in range(1, 5):
                check_date = as_of + timedelta(days=lookahead)
                tom_hol = conn.execute(
                    text("""
                        SELECT eh.name FROM exchange_holidays eh
                        JOIN exchanges e ON eh.exchange_id = e.id
                        WHERE e.mic = :mic AND eh.holiday_date = :d
                    """),
                    {"mic": mic_code, "d": check_date},
                ).first()
                if tom_hol:
                    # Check no trading day between as_of and check_date
                    trading_between = conn.execute(
                        text("""
                            SELECT 1 FROM exchange_holidays eh
                            JOIN exchanges e ON eh.exchange_id = e.id
                            WHERE e.mic = :mic
                              AND eh.holiday_date > :asof AND eh.holiday_date < :check
                            LIMIT 1
                        """),
                        {"mic": mic_code, "asof": as_of, "check": check_date},
                    ).first()
                    if not trading_between and lookahead <= 3:
                        features["is_pre_holiday"] = True
                        features["days_to_next_holiday"] = lookahead
                        features["next_holiday_name"] = tom_hol[0] or "Market Holiday"
                        # Get expected pre-holiday return
                        pre_ret = conn.execute(
                            text("""
                                SELECT pre_holiday_avg_return FROM holiday_effects
                                WHERE mic_code = :mic AND holiday_name = :name
                            """),
                            {"mic": mic_code, "name": tom_hol[0] or "Market Holiday"},
                        ).first()
                        if pre_ret:
                            features["pre_holiday_expected_return"] = float(pre_ret[0])
                    break

            # If not pre-holiday, find next holiday within look_forward
            if not features["is_pre_holiday"]:
                next_hol = conn.execute(
                    text("""
                        SELECT eh.holiday_date, eh.name FROM exchange_holidays eh
                        JOIN exchanges e ON eh.exchange_id = e.id
                        WHERE e.mic = :mic AND eh.holiday_date > :d
                        ORDER BY eh.holiday_date LIMIT 1
                    """),
                    {"mic": mic_code, "d": as_of},
                ).first()
                if next_hol:
                    days_to = (next_hol[0] - as_of).days
                    if days_to <= look_forward:
                        features["days_to_next_holiday"] = days_to
                        features["next_holiday_name"] = next_hol[1] or "Market Holiday"

        return features

    def get_spillover_features(self, as_of: date) -> dict[str, float]:
        """Get spillover features: expected IDX return based on global holidays today.

        If any global exchange is on holiday today, what's the expected
        IDX return tomorrow?

        Returns:
            Dict with keys like `spillover_XNYS_return`, `spillover_XTSE_return`,
            and `spillover_total_expected_return`.
        """
        features: dict[str, float] = {}
        total_expected = 0.0
        count = 0

        with self._engine.connect() as conn:
            for src_mic in ["XNYS", "XTSE", "XHKG", "XLON", "XFRA"]:
                hol = conn.execute(
                    text("""
                        SELECT eh.name FROM exchange_holidays eh
                        JOIN exchanges e ON eh.exchange_id = e.id
                        WHERE e.mic = :mic AND eh.holiday_date = :d
                    """),
                    {"mic": src_mic, "d": as_of},
                ).first()
                if hol:
                    spillover = conn.execute(
                        text("""
                            SELECT idx_next_day_avg_return FROM holiday_spillover
                            WHERE source_mic = :mic AND source_holiday_name = :name
                        """),
                        {"mic": src_mic, "name": hol[0] or "Market Holiday"},
                    ).first()
                    if spillover:
                        val = float(spillover[0])
                        features[f"spillover_{src_mic}_return"] = val
                        total_expected += val
                        count += 1

        features["spillover_total_expected_return"] = total_expected
        features["spillover_active_count"] = count
        return features


__all__ = [
    "HolidayEffectAnalyzer",
    "HolidayEffectResult",
    "SpilloverResult",
    "INDEX_TICKERS",
]
