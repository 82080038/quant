"""Model drift detection (pustaka/51 §5).

Detects when model performance degrades in production:
- Prediction drift: distribution of predictions changes
- Feature drift: input feature distributions change
- Performance drift: evaluation metrics degrade
- Population Stability Index (PSI) for feature monitoring
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class DriftResult:
    """Result of a drift check."""

    metric_name: str
    baseline_value: float
    current_value: float
    drift_pct: float
    is_drifted: bool
    threshold: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class DriftReport:
    """Full drift assessment report."""

    is_drifted: bool
    drifted_metrics: list[DriftResult] = field(default_factory=list)
    all_metrics: list[DriftResult] = field(default_factory=list)
    psi_scores: dict[str, float] = field(default_factory=dict)
    assessed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def population_stability_index(
    baseline: np.ndarray[Any, np.dtype[Any]],
    current: np.ndarray[Any, np.dtype[Any]],
    n_bins: int = 10,
) -> float:
    """Calculate Population Stability Index (PSI).

    PSI < 0.1: no significant change
    PSI 0.1-0.25: slight change, monitor
    PSI > 0.25: significant change, investigate

    Args:
        baseline: Baseline distribution values.
        current: Current distribution values.
        n_bins: Number of bins for comparison.

    Returns:
        PSI value.
    """
    # Use baseline to define bins
    bins = np.linspace(
        min(baseline.min(), current.min()),
        max(baseline.max(), current.max()),
        n_bins + 1,
    )

    baseline_counts, _ = np.histogram(baseline, bins=bins)
    current_counts, _ = np.histogram(current, bins=bins)

    # Convert to proportions
    baseline_pct = baseline_counts / len(baseline) + 1e-6
    current_pct = current_counts / len(current) + 1e-6

    psi = np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct))
    return float(psi)


class DriftDetector:
    """Model drift detection engine."""

    def __init__(
        self,
        metric_threshold: float = 0.15,
        psi_threshold: float = 0.25,
    ) -> None:
        self.metric_threshold = metric_threshold
        self.psi_threshold = psi_threshold
        self._baseline_metrics: dict[str, float] = {}
        self._baseline_predictions: np.ndarray[Any, np.dtype[Any]] | None = None
        self._baseline_features: pd.DataFrame | None = None

    def set_baseline_metrics(self, metrics: dict[str, float]) -> None:
        """Set baseline model metrics for comparison.

        Args:
            metrics: Dict of metric name to value.
        """
        self._baseline_metrics = metrics

    def set_baseline_predictions(self, predictions: np.ndarray[Any, np.dtype[Any]]) -> None:
        """Set baseline prediction distribution.

        Args:
            predictions: Array of baseline predictions.
        """
        self._baseline_predictions = predictions

    def set_baseline_features(self, features: pd.DataFrame) -> None:
        """Set baseline feature distributions.

        Args:
            features: DataFrame of baseline features.
        """
        self._baseline_features = features

    def check_metric_drift(
        self,
        current_metrics: dict[str, float],
    ) -> list[DriftResult]:
        """Check if model metrics have drifted.

        Args:
            current_metrics: Current model metrics.

        Returns:
            List of DriftResult for each metric.
        """
        results = []
        for name, baseline_val in self._baseline_metrics.items():
            current_val = current_metrics.get(name, 0.0)
            if baseline_val != 0:
                drift_pct = abs(current_val - baseline_val) / abs(baseline_val)
            else:
                drift_pct = abs(current_val)

            is_drifted = drift_pct > self.metric_threshold
            results.append(DriftResult(
                metric_name=name,
                baseline_value=baseline_val,
                current_value=current_val,
                drift_pct=round(drift_pct, 4),
                is_drifted=is_drifted,
                threshold=self.metric_threshold,
            ))

        return results

    def check_prediction_drift(
        self,
        current_predictions: np.ndarray[Any, np.dtype[Any]],
    ) -> DriftResult:
        """Check if prediction distribution has drifted using PSI.

        Args:
            current_predictions: Current model predictions.

        Returns:
            DriftResult with PSI score.
        """
        if self._baseline_predictions is None:
            return DriftResult(
                metric_name="prediction_psi",
                baseline_value=0.0,
                current_value=0.0,
                drift_pct=0.0,
                is_drifted=False,
                threshold=self.psi_threshold,
            )

        psi = population_stability_index(self._baseline_predictions, current_predictions)
        return DriftResult(
            metric_name="prediction_psi",
            baseline_value=0.0,
            current_value=psi,
            drift_pct=psi,
            is_drifted=psi > self.psi_threshold,
            threshold=self.psi_threshold,
        )

    def check_feature_drift(
        self,
        current_features: pd.DataFrame,
    ) -> dict[str, float]:
        """Check feature distributions for drift using PSI.

        Args:
            current_features: Current feature DataFrame.

        Returns:
            Dict mapping feature name to PSI score.
        """
        if self._baseline_features is None:
            return {}

        psi_scores = {}
        for col in self._baseline_features.columns:
            if col in current_features.columns:
                psi = population_stability_index(
                    self._baseline_features[col].dropna().values,
                    current_features[col].dropna().values,
                )
                psi_scores[col] = round(psi, 4)

        return psi_scores

    def assess(
        self,
        current_metrics: dict[str, float] | None = None,
        current_predictions: np.ndarray[Any, np.dtype[Any]] | None = None,
        current_features: pd.DataFrame | None = None,
    ) -> DriftReport:
        """Full drift assessment.

        Args:
            current_metrics: Current model metrics.
            current_predictions: Current predictions.
            current_features: Current features.

        Returns:
            DriftReport with all drift checks.
        """
        all_results: list[DriftResult] = []
        drifted: list[DriftResult] = []

        if current_metrics:
            metric_results = self.check_metric_drift(current_metrics)
            all_results.extend(metric_results)
            drifted.extend(r for r in metric_results if r.is_drifted)

        if current_predictions is not None:
            pred_result = self.check_prediction_drift(current_predictions)
            all_results.append(pred_result)
            if pred_result.is_drifted:
                drifted.append(pred_result)

        psi_scores = {}
        if current_features is not None:
            psi_scores = self.check_feature_drift(current_features)
            for feature, psi in psi_scores.items():
                if psi > self.psi_threshold:
                    drifted.append(DriftResult(
                        metric_name=f"feature_psi_{feature}",
                        baseline_value=0.0,
                        current_value=psi,
                        drift_pct=psi,
                        is_drifted=True,
                        threshold=self.psi_threshold,
                    ))

        return DriftReport(
            is_drifted=len(drifted) > 0,
            drifted_metrics=drifted,
            all_metrics=all_results,
            psi_scores=psi_scores,
        )
