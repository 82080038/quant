"""Prediction vs Reality tracker.

Tracks prediction accuracy: predicted signals vs actual forward returns.
Provides calibration metrics and prediction-reality gap analysis.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional

from quant.core.db import get_db
from sqlalchemy import text


@dataclass
class PredictionRealityResult:
    """Prediction vs reality evaluation result."""
    engine_name: str
    n_predictions: int
    directional_accuracy: float    # % of correct direction predictions
    calibration_error: float       # Mean absolute prediction-reality gap
    mean_predicted: float
    mean_actual: float
    correlation: float
    horizon: int


class PredictionRealityTracker:
    """Track prediction accuracy over time."""

    def __init__(self, session=None):
        self._session = session

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def evaluate(
        self,
        engine_name: str,
        horizon: int = 5,
        lookback_days: int = 30,
    ) -> PredictionRealityResult:
        """Evaluate predictions vs reality for an engine.

        Args:
            engine_name: Engine to evaluate
            horizon: Forward return horizon in days
            lookback_days: Number of recent days to evaluate

        Returns:
            PredictionRealityResult with calibration metrics
        """
        result = self.session.execute(text("""
            SELECT predicted_magnitude, actual_forward_return_5d,
                   predicted_direction, actual_direction, directional_correct
            FROM prediction_evaluation
            WHERE engine_name = :engine
              AND actual_forward_return_5d IS NOT NULL
              AND date >= CURRENT_DATE - :lookback
            ORDER BY date DESC
        """), {"engine": engine_name, "lookback": lookback_days})

        rows = result.fetchall()
        if not rows:
            return PredictionRealityResult(
                engine_name=engine_name, n_predictions=0,
                directional_accuracy=0, calibration_error=0,
                mean_predicted=0, mean_actual=0, correlation=0, horizon=horizon,
            )

        predicted = np.array([float(r[0]) if r[0] else 0 for r in rows])
        actual = np.array([float(r[1]) if r[1] else 0 for r in rows])
        correct = np.array([r[4] if r[4] is not None else False for r in rows])

        dir_accuracy = float(correct.mean())
        calib_error = float(np.abs(predicted - actual).mean())
        mean_pred = float(predicted.mean())
        mean_actual = float(actual.mean())

        if len(predicted) > 2 and predicted.std() > 0 and actual.std() > 0:
            corr = float(np.corrcoef(predicted, actual)[0, 1])
            if np.isnan(corr):
                corr = 0.0
        else:
            corr = 0.0

        return PredictionRealityResult(
            engine_name=engine_name,
            n_predictions=len(rows),
            directional_accuracy=dir_accuracy,
            calibration_error=calib_error,
            mean_predicted=mean_pred,
            mean_actual=mean_actual,
            correlation=corr,
            horizon=horizon,
        )

    def calibration_report(self, engine_name: str = None) -> pd.DataFrame:
        """Generate calibration report for all engines or a specific one.

        Returns:
            DataFrame with calibration metrics per engine
        """
        if engine_name:
            engines = [engine_name]
        else:
            result = self.session.execute(text("""
                SELECT DISTINCT engine_name FROM prediction_evaluation
                WHERE actual_forward_return_5d IS NOT NULL
            """))
            engines = [r[0] for r in result.fetchall()]

        rows = []
        for e in engines:
            r = self.evaluate(e)
            rows.append({
                "engine": r.engine_name,
                "n_predictions": r.n_predictions,
                "directional_accuracy": r.directional_accuracy,
                "calibration_error": r.calibration_error,
                "mean_predicted": r.mean_predicted,
                "mean_actual": r.mean_actual,
                "correlation": r.correlation,
            })

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("directional_accuracy", ascending=False)

    def prediction_gap_timeseries(
        self,
        engine_name: str,
        lookback_days: int = 60,
    ) -> pd.DataFrame:
        """Get time series of prediction-reality gaps.

        Useful for detecting systematic bias in predictions.
        """
        result = self.session.execute(text("""
            SELECT date,
                   AVG(predicted_magnitude) as mean_predicted,
                   AVG(actual_forward_return_5d) as mean_actual,
                   AVG(CASE WHEN directional_correct THEN 1.0 ELSE 0.0 END) as daily_accuracy,
                   COUNT(*) as n_predictions
            FROM prediction_evaluation
            WHERE engine_name = :engine
              AND actual_forward_return_5d IS NOT NULL
              AND date >= CURRENT_DATE - :lookback
            GROUP BY date
            ORDER BY date
        """), {"engine": engine_name, "lookback": lookback_days})

        df = pd.DataFrame(result.fetchall(), columns=result.keys())
        if not df.empty:
            df["gap"] = df["mean_predicted"] - df["mean_actual"]
            df["gap_zscore"] = (df["gap"] - df["gap"].mean()) / df["gap"].std().replace(0, np.nan)
        return df
