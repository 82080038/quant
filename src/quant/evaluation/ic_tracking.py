"""Information Coefficient (IC) tracking per engine.

IC = Spearman rank correlation between predicted signal and actual forward returns.
ICIR = IC mean / IC std (Information Ratio of the signal).

Decay detection: rolling IC with trend analysis.
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr
from dataclasses import dataclass
from typing import Optional
from datetime import date

from quant.core.db import get_db
from sqlalchemy import text


@dataclass
class ICResult:
    """IC computation result."""
    ic: float           # Spearman rank IC
    rank_ic: float      # Same as IC (Spearman)
    pearson_ic: float   # Pearson IC
    icir: float         # IC / std(IC) over rolling window
    n_pairs: int
    p_value: float


class ICTracker:
    """Track IC per engine per day."""

    def __init__(self, session=None):
        self._session = session

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def compute_ic(
        self,
        predictions: np.ndarray,
        actual_returns: np.ndarray,
    ) -> ICResult:
        """Compute IC from predictions and actual returns.

        Args:
            predictions: Signal values [-1, 1] for each ticker
            actual_returns: Forward returns for each ticker

        Returns:
            ICResult with IC, ICIR, p-value
        """
        if len(predictions) < 3 or len(actual_returns) < 3:
            return ICResult(0, 0, 0, 0, len(predictions), 1.0)

        mask = ~(np.isnan(predictions) | np.isnan(actual_returns))
        pred = predictions[mask]
        ret = actual_returns[mask]

        if len(pred) < 3:
            return ICResult(0, 0, 0, 0, len(pred), 1.0)

        # Spearman rank IC
        rho, p_val = spearmanr(pred, ret)
        if np.isnan(rho):
            rho = 0.0

        # Pearson IC
        r, _ = pearsonr(pred, ret)
        if np.isnan(r):
            r = 0.0

        return ICResult(
            ic=float(rho),
            rank_ic=float(rho),
            pearson_ic=float(r),
            icir=0.0,  # Computed from rolling history
            n_pairs=len(pred),
            p_value=float(p_val),
        )

    def update(
        self,
        engine_name: str,
        date: date,
        predictions: dict[str, float],
        actual_returns: dict[str, float],
        horizon: int = 5,
    ) -> ICResult:
        """Compute and store IC for an engine on a given date.

        Args:
            engine_name: Name of the signal engine
            date: The signal date
            predictions: ticker → signal value
            actual_returns: ticker → forward return
            horizon: Forward return horizon in days

        Returns:
            ICResult
        """
        tickers = sorted(set(predictions.keys()) & set(actual_returns.keys()))
        pred_arr = np.array([predictions[t] for t in tickers])
        ret_arr = np.array([actual_returns[t] for t in tickers])

        result = self.compute_ic(pred_arr, ret_arr)

        # Store per-ticker in prediction_evaluation
        try:
            for ticker in tickers:
                pred = predictions[ticker]
                actual = actual_returns[ticker]
                direction = "up" if pred > 0.1 else "down" if pred < -0.1 else "flat"
                actual_dir = "up" if actual > 0 else "down" if actual < 0 else "flat"
                correct = direction == actual_dir

                self.session.execute(text("""
                    INSERT INTO prediction_evaluation
                        (date, ticker, engine_name, predicted_direction,
                         predicted_magnitude, confidence, actual_forward_return_5d,
                         actual_direction, directional_correct, ic_contribution, evaluated_at)
                    VALUES
                        (:date, :ticker, :engine, :pred_dir,
                         :pred_mag, :confidence, :actual_ret,
                         :actual_dir, :correct, :ic, NOW())
                    ON CONFLICT (date, ticker, engine_name) DO UPDATE
                    SET predicted_direction = EXCLUDED.predicted_direction,
                        predicted_magnitude = EXCLUDED.predicted_magnitude,
                        actual_forward_return_5d = EXCLUDED.actual_forward_return_5d,
                        actual_direction = EXCLUDED.actual_direction,
                        directional_correct = EXCLUDED.directional_correct,
                        ic_contribution = EXCLUDED.ic_contribution,
                        evaluated_at = NOW()
                """), {
                    "date": date,
                    "ticker": ticker,
                    "engine": engine_name,
                    "pred_dir": direction,
                    "pred_mag": float(pred),
                    "confidence": abs(float(pred)),
                    "actual_ret": float(actual),
                    "actual_dir": actual_dir,
                    "correct": correct,
                    "ic": result.ic,
                })
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            print(f"IC store error: {e}")

        return result

    def rolling_ic(
        self,
        engine_name: str,
        window: int = 60,
        horizon: int = 5,
    ) -> pd.DataFrame:
        """Get rolling IC for an engine.

        Returns:
            DataFrame with columns: date, ic, rolling_mean, rolling_std, icir
        """
        result = self.session.execute(text("""
            SELECT date, ic_contribution as ic, ic_contribution as rank_ic, 1 as n_pairs
            FROM prediction_evaluation
            WHERE engine_name = :engine
            ORDER BY date DESC
            LIMIT :limit
        """), {"engine": engine_name, "limit": window * 2})

        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        if df.empty:
            return df

        df = df.sort_values("date").reset_index(drop=True)
        df["rolling_mean"] = df["ic"].rolling(window, min_periods=10).mean()
        df["rolling_std"] = df["ic"].rolling(window, min_periods=10).std()
        df["icir"] = df["rolling_mean"] / df["rolling_std"].replace(0, np.nan)

        return df

    def ic_decay(
        self,
        engine_name: str,
        recent_window: int = 30,
        historical_window: int = 60,
        horizon: int = 5,
    ) -> float:
        """Compute IC decay ratio.

        Compares recent IC average to historical IC average.
        Decay > 0.5 → significant degradation.

        Returns:
            Decay ratio (0 = no decay, 1 = complete decay)
        """
        rolling = self.rolling_ic(engine_name, recent_window + historical_window, horizon)
        if len(rolling) < recent_window + 10:
            return 0.0

        recent_ic = rolling["ic"].tail(recent_window).mean()
        historical_ic = rolling["ic"].head(historical_window).mean()

        if historical_ic == 0:
            return 0.0

        decay = 1.0 - (recent_ic / historical_ic) if historical_ic > 0 else 0.0
        return float(max(0.0, min(1.0, decay)))

    def engine_summary(self) -> pd.DataFrame:
        """Get IC summary for all engines."""
        result = self.session.execute(text("""
            SELECT engine_name,
                   COUNT(*) as n_days,
                   AVG(ic_contribution) as avg_ic,
                   STDDEV(ic_contribution) as std_ic,
                   AVG(ic_contribution) / NULLIF(STDDEV(ic_contribution), 0) as icir,
                   MAX(date) as latest_date
            FROM prediction_evaluation
            GROUP BY engine_name
            ORDER BY avg_ic DESC
        """))
        return pd.DataFrame(result.fetchall(), columns=result.keys())
