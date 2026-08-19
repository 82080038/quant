"""Layer 7: Evaluation & Monitoring layer tests.

Tests:
- ic_tracking: Information Coefficient computation
- dsr: Deflated Sharpe Ratio
- pbo: Probability of Backtest Overfitting
- regime_conditional: Per-regime evaluation
- drift: Model drift detection (PSI)
- prediction_reality: Prediction vs actual tracking
- retirement: Model retirement verdicts
"""

import pytest
import numpy as np
import pandas as pd


# ── IC Tracking ──────────────────────────────────────────────────────────────

class TestICTracking:
    """Test Information Coefficient tracking."""

    def test_compute_ic(self):
        from quant.evaluation.ic_tracking import ICTracker
        tracker = ICTracker()
        np.random.seed(42)
        predictions = np.random.randn(50)
        actual_returns = predictions * 0.5 + np.random.randn(50) * 0.5
        result = tracker.compute_ic(predictions, actual_returns)
        assert -1 <= result.ic <= 1
        assert -1 <= result.pearson_ic <= 1
        assert result.n_pairs == 50
        assert 0 <= result.p_value <= 1

    def test_ic_perfect_correlation(self):
        from quant.evaluation.ic_tracking import ICTracker
        tracker = ICTracker()
        predictions = np.array([1, 2, 3, 4, 5], dtype=float)
        actual = np.array([2, 4, 6, 8, 10], dtype=float)
        result = tracker.compute_ic(predictions, actual)
        assert result.ic > 0.9

    def test_ic_insufficient_data(self):
        from quant.evaluation.ic_tracking import ICTracker
        tracker = ICTracker()
        result = tracker.compute_ic(np.array([1.0]), np.array([1.0]))
        assert result.ic == 0.0

    def test_ic_with_nan(self):
        from quant.evaluation.ic_tracking import ICTracker
        tracker = ICTracker()
        predictions = np.array([1, np.nan, 3, 4, 5], dtype=float)
        actual = np.array([2, 4, 6, 8, 10], dtype=float)
        result = tracker.compute_ic(predictions, actual)
        assert result.n_pairs == 4


# ── DSR ──────────────────────────────────────────────────────────────────────

class TestDSR:
    """Test Deflated Sharpe Ratio.

    NOTE: deflated_sr is the deflated Sharpe ratio VALUE (not a probability).
    It can be > 1. PSR (probabilistic Sharpe ratio) is in [0, 1].
    """

    def test_sharpe_ratio(self):
        from quant.evaluation.dsr import sharpe_ratio
        returns = np.random.normal(0.001, 0.02, 252)
        sr = sharpe_ratio(returns)
        assert isinstance(sr, float)

    def test_expected_max_sharpe(self):
        from quant.evaluation.dsr import expected_max_sharpe
        emax = expected_max_sharpe(n_trials=100)
        assert emax > 0
        assert expected_max_sharpe(1000) > emax

    def test_dsr_single_trial(self):
        from quant.evaluation.dsr import deflated_sharpe_ratio
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        result = deflated_sharpe_ratio(returns, n_trials=1)
        assert isinstance(result.deflated_sr, float)
        assert 0 <= result.psr <= 1  # PSR is a probability
        assert result.n_trials == 1

    def test_dsr_multiple_trials(self):
        from quant.evaluation.dsr import deflated_sharpe_ratio
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        result = deflated_sharpe_ratio(returns, n_trials=100)
        assert result.n_trials == 100
        assert result.expected_max_sr > 0
        assert 0 <= result.psr <= 1

    def test_dsr_result_fields(self):
        from quant.evaluation.dsr import deflated_sharpe_ratio, DSRResult
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 252)
        result = deflated_sharpe_ratio(returns, n_trials=50)
        assert isinstance(result, DSRResult)
        assert hasattr(result, "observed_sr")
        assert hasattr(result, "deflated_sr")
        assert hasattr(result, "psr")
        assert hasattr(result, "is_real")


# ── PBO ──────────────────────────────────────────────────────────────────────

class TestPBO:
    """Test Probability of Backtest Overfitting."""

    def test_pbo_computation(self):
        from quant.evaluation.pbo import probability_of_backtest_overfit
        np.random.seed(42)
        returns_matrix = np.random.normal(0.001, 0.02, (100, 5))
        result = probability_of_backtest_overfit(returns_matrix, n_partitions=16)
        assert 0 <= result.pbo <= 1
        assert result.n_strategies == 5
        assert result.n_observations == 100
        assert isinstance(result.is_overfit, bool)

    def test_pbo_overfit_detection(self):
        from quant.evaluation.pbo import probability_of_backtest_overfit
        np.random.seed(42)
        returns_matrix = np.random.normal(0, 0.02, (200, 10))
        result = probability_of_backtest_overfit(returns_matrix, n_partitions=16)
        assert 0 <= result.pbo <= 1

    def test_pbo_result_fields(self):
        from quant.evaluation.pbo import probability_of_backtest_overfit, PBOResult
        np.random.seed(42)
        returns_matrix = np.random.normal(0.001, 0.02, (100, 3))
        result = probability_of_backtest_overfit(returns_matrix, n_partitions=10)
        assert isinstance(result, PBOResult)
        assert hasattr(result, "pbo")
        assert hasattr(result, "degradation_slope")
        assert hasattr(result, "is_overfit")


# ── Regime Conditional ───────────────────────────────────────────────────────

class TestRegimeConditional:
    """Test regime-conditional evaluation."""

    def test_classify_regime(self, sample_returns):
        from quant.evaluation.regime_conditional import RegimeConditionalEvaluator
        evaluator = RegimeConditionalEvaluator()
        regimes = evaluator.classify_regime(sample_returns)
        assert len(regimes) == len(sample_returns)
        valid = set(regimes.unique())
        assert valid.issubset({"bull", "bear", "sideways", "crisis"})

    def test_evaluate_per_regime(self, sample_returns):
        from quant.evaluation.regime_conditional import RegimeConditionalEvaluator
        evaluator = RegimeConditionalEvaluator()
        results = evaluator.evaluate(sample_returns)
        assert "bull" in results
        assert "bear" in results
        assert "sideways" in results
        assert "crisis" in results
        for regime, r in results.items():
            assert r.regime == regime
            assert isinstance(r.sharpe, (float, int))
            assert isinstance(r.max_drawdown, (float, int))
            assert isinstance(r.win_rate, (float, int))

    def test_summary_table(self, sample_returns):
        from quant.evaluation.regime_conditional import RegimeConditionalEvaluator
        evaluator = RegimeConditionalEvaluator()
        results = evaluator.evaluate(sample_returns)
        table = evaluator.summary_table(results)
        assert len(table) == 4
        assert "regime" in table.columns
        assert "sharpe" in table.columns


# ── Drift Detection ──────────────────────────────────────────────────────────

class TestDrift:
    """Test model drift detection."""

    def test_psi_no_change(self):
        from quant.monitoring.drift import population_stability_index
        np.random.seed(42)
        baseline = np.random.normal(0, 1, 1000)
        current = np.random.normal(0, 1, 1000)
        psi = population_stability_index(baseline, current)
        assert psi < 0.1

    def test_psi_significant_change(self):
        from quant.monitoring.drift import population_stability_index
        np.random.seed(42)
        baseline = np.random.normal(0, 1, 1000)
        current = np.random.normal(2, 1, 1000)
        psi = population_stability_index(baseline, current)
        assert psi > 0.25

    def test_drift_result(self):
        from quant.monitoring.drift import DriftResult
        result = DriftResult(
            metric_name="ic", baseline_value=0.05,
            current_value=0.02, drift_pct=0.4,
            is_drifted=True, threshold=0.3,
        )
        assert result.is_drifted
        assert result.metric_name == "ic"


# ── Prediction Reality ───────────────────────────────────────────────────────

class TestPredictionReality:
    """Test prediction vs reality tracker (mock session)."""

    def test_result_creation(self):
        from quant.monitoring.prediction_reality import PredictionRealityResult
        result = PredictionRealityResult(
            engine_name="technical", n_predictions=100,
            directional_accuracy=0.65, calibration_error=0.02,
            mean_predicted=0.03, mean_actual=0.025,
            correlation=0.45, horizon=5,
        )
        assert result.engine_name == "technical"
        assert result.directional_accuracy == 0.65

    def test_evaluate_empty(self, mock_session):
        from quant.monitoring.prediction_reality import PredictionRealityTracker
        mock_session.execute.return_value.fetchall.return_value = []
        tracker = PredictionRealityTracker(session=mock_session)
        result = tracker.evaluate("nonexistent_engine")
        assert result.n_predictions == 0
        assert result.directional_accuracy == 0


# ── Retirement ───────────────────────────────────────────────────────────────

class TestRetirement:
    """Test model retirement manager."""

    def test_retirement_criteria(self):
        from quant.monitoring.retirement import RetirementCriteria
        criteria = RetirementCriteria()
        assert criteria.min_track_record_days > 0
        assert 0 < criteria.min_dsr < 1
        assert 0 < criteria.max_pbo < 1

    def test_verdict_creation(self):
        from quant.monitoring.retirement import RetirementVerdict
        verdict = RetirementVerdict(
            engine_name="technical", verdict="KEEP",
            score=0.85, reasons=["Good IC", "Stable performance"],
        )
        assert verdict.verdict == "KEEP"
        assert verdict.score == 0.85
        assert len(verdict.reasons) == 2

    def test_evaluate_no_data(self, mock_session):
        from quant.monitoring.retirement import ModelRetirementManager
        mock_session.execute.return_value.fetchone.return_value = (None, None, 0)
        mgr = ModelRetirementManager(session=mock_session)
        verdict = mgr.evaluate("nonexistent")
        assert verdict.verdict == "WATCH"
        assert "No evaluation data" in verdict.reasons[0]
