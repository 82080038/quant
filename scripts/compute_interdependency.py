"""Compute Global Cross-Asset Interdependency & Causality Matrix.

Reads daily closing prices for major global indices and IDX stocks,
computes pairwise correlation, Granger causality (F-test), and optimal
time-lag, then writes results to `global_market_interdependencies` and
`global_market_interdependency_history` tables.

Run weekly or on-demand:
    python scripts/compute_interdependency.py
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from quant.core.db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GLOBAL_INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^DJI": "Dow Jones",
    "^HSI": "Hang Seng",
    "^N225": "Nikkei 225",
    "^FTSE": "FTSE 100",
    "^GDAXI": "DAX 40",
}

IDX_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK",
    "ICBP.JK", "UNVR.JK", "ADRO.JK", "ANTM.JK", "MDKA.JK",
    "INDF.JK", "KLBF.JK", "SMGR.JK", "JPFA.JK", "CTRA.JK",
    "AKRA.JK", "TPIA.JK", "EMTK.JK", "GOTO.JK", "PBID.JK",
]


def _load_close_prices(session, tickers: list[str], lookback_days: int = 252) -> pd.DataFrame:
    """Load daily closing prices for multiple tickers into a DataFrame."""
    end = date.today()
    start = end - timedelta(days=lookback_days + 60)

    placeholders = ",".join([f"'{t}'" for t in tickers])
    rows = session.execute(text(f"""
        SELECT date, ticker, close
        FROM stock_prices
        WHERE ticker IN ({placeholders})
        AND date BETWEEN :start AND :end
        ORDER BY date, ticker
    """), {"start": start, "end": end}).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "ticker", "close"])
    df["date"] = pd.to_datetime(df["date"])
    pivot = df.pivot(index="date", columns="ticker", values="close").sort_index()
    returns = pivot.pct_change().dropna()
    return returns


def _granger_causality(source: pd.Series, target: pd.Series, max_lag: int = 5) -> tuple[float, int]:
    """Simplified Granger causality F-test.

    Returns (p_value, optimal_lag). Lower p-value = stronger causality.
    """
    from scipy import stats

    best_p = 1.0
    best_lag = 1

    for lag in range(1, max_lag + 1):
        try:
            src_lagged = source.shift(lag).dropna()
            tgt_aligned = target.loc[src_lagged.index].dropna()
            src_aligned = src_lagged.loc[tgt_aligned.index]

            if len(tgt_aligned) < 20:
                continue

            # Simple OLS: target = a + b * source_lagged
            X = np.column_stack([np.ones(len(src_aligned)), src_aligned.values])
            y = tgt_aligned.values

            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            residuals = y - X @ beta
            rss = np.sum(residuals ** 2)

            # Null model (mean only)
            X_null = np.ones((len(y), 1))
            beta_null, _, _, _ = np.linalg.lstsq(X_null, y, rcond=None)
            residuals_null = y - X_null @ beta_null
            tss = np.sum(residuals_null ** 2)

            if tss == 0 or rss == tss:
                continue

            # F-test
            n = len(y)
            f_stat = ((tss - rss) / 1) / (rss / (n - 2))
            p_value = 1 - stats.f.cdf(f_stat, 1, n - 2)

            if p_value < best_p:
                best_p = p_value
                best_lag = lag
        except Exception:
            continue

    return best_p, best_lag


def compute_interdependency_matrix():
    """Compute and store the cross-asset interdependency matrix."""
    session = get_db()
    try:
        all_tickers = list(GLOBAL_INDICES.keys()) + IDX_TICKERS
        logger.info("Loading price data for %d tickers...", len(all_tickers))
        returns = _load_close_prices(session, all_tickers, lookback_days=252)

        if returns.empty:
            logger.warning("No price data found — skipping interdependency computation")
            return

        logger.info("Returns matrix: %d days x %d tickers", len(returns), returns.shape[1])

        # Clear existing matrix
        session.execute(text("DELETE FROM global_market_interdependencies"))
        session.commit()

        as_of = date.today()
        results = []

        # Compute pairwise: global index → IDX stock
        for src_ticker in GLOBAL_INDICES:
            if src_ticker not in returns.columns:
                continue
            src_returns = returns[src_ticker].dropna()

            for tgt_ticker in IDX_TICKERS:
                if tgt_ticker not in returns.columns:
                    continue
                tgt_returns = returns[tgt_ticker].dropna()

                # Align dates
                common = src_returns.index.intersection(tgt_returns.index)
                if len(common) < 30:
                    continue

                src_aligned = src_returns.loc[common]
                tgt_aligned = tgt_returns.loc[common]

                # Correlation
                corr = float(src_aligned.corr(tgt_aligned))
                if np.isnan(corr):
                    continue

                # Granger causality
                p_value, lag = _granger_causality(src_aligned, tgt_aligned, max_lag=5)
                causality_score = max(0.0, 1.0 - p_value)  # 0..1, higher = stronger

                # Impact weight = |correlation| * causality_score
                impact_weight = abs(corr) * causality_score

                # Direction: positive or negative
                direction = "positive" if corr > 0 else "negative"

                # Time lag in seconds (1 trading day ≈ 86400 seconds)
                time_lag_seconds = lag * 86400

                results.append({
                    "source_ticker": src_ticker,
                    "target_ticker": tgt_ticker,
                    "correlation": corr,
                    "causality_score": causality_score,
                    "impact_weight": impact_weight,
                    "direction": direction,
                    "lag_periods": lag,
                    "time_lag_seconds": time_lag_seconds,
                })

        logger.info("Computed %d interdependency pairs", len(results))

        # Write to DB
        for r in results:
            # Get instrument IDs
            src_id = session.execute(text(
                "SELECT id FROM instruments WHERE ticker = :t"
            ), {"t": r["source_ticker"]}).scalar()
            tgt_id = session.execute(text(
                "SELECT id FROM instruments WHERE ticker = :t"
            ), {"t": r["target_ticker"]}).scalar()

            if not src_id or not tgt_id:
                continue

            # Determine regime
            regime = "normal"

            session.execute(text("""
                INSERT INTO global_market_interdependencies
                    (source_instrument_id, target_instrument_id,
                     correlation_coefficient, causality_score, impact_weight,
                     causality_direction, time_lag_periods, time_lag_seconds,
                     regime, as_of_date)
                VALUES (:src, :tgt, :corr, :caus, :impact, :dir, :lag, :lag_s, :regime, :as_of)
                ON CONFLICT (source_instrument_id, target_instrument_id, regime) DO UPDATE
                SET correlation_coefficient = EXCLUDED.correlation_coefficient,
                    causality_score = EXCLUDED.causality_score,
                    impact_weight = EXCLUDED.impact_weight,
                    causality_direction = EXCLUDED.causality_direction,
                    time_lag_periods = EXCLUDED.time_lag_periods,
                    time_lag_seconds = EXCLUDED.time_lag_seconds,
                    as_of_date = EXCLUDED.as_of_date
            """), {
                "src": src_id, "tgt": tgt_id,
                "corr": r["correlation"],
                "caus": r["causality_score"],
                "impact": r["impact_weight"],
                "dir": r["direction"],
                "lag": r["lag_periods"],
                "lag_s": r["time_lag_seconds"],
                "regime": regime,
                "as_of": as_of,
            })

            # Also write to history table
            session.execute(text("""
                INSERT INTO global_market_interdependency_history
                    (source_instrument_id, target_instrument_id,
                     correlation_coefficient, causality_score, impact_weight,
                     causality_direction, time_lag_periods, time_lag_seconds,
                     regime, snapshot_date)
                VALUES (:src, :tgt, :corr, :caus, :impact, :dir, :lag, :lag_s, :regime, :as_of)
            """), {
                "src": src_id, "tgt": tgt_id,
                "corr": r["correlation"],
                "caus": r["causality_score"],
                "impact": r["impact_weight"],
                "dir": r["direction"],
                "lag": r["lag_periods"],
                "lag_s": r["time_lag_seconds"],
                "regime": regime,
                "as_of": as_of,
            })

        session.commit()
        count = session.execute(text("SELECT count(*) FROM global_market_interdependencies")).scalar()
        logger.info("✅ Interdependency matrix populated: %d rows", count)

    except Exception as e:
        logger.error("Failed to compute interdependency: %s", e)
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    compute_interdependency_matrix()
