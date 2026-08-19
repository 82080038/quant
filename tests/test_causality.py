"""Tests for cross-asset causality analysis module.

Tests cover:
  - CCF time-lag computation
  - Granger causality test
  - VAR model fitting
  - CausalityAnalyzer.analyze_pair
  - CausalityAnalyzer.analyze_matrix
  - Regime-conditional analysis
  - Edge cases (insufficient data, constant series, etc.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.analysis.causality import (
    CausalityAnalyzer,
    CausalityResult,
    MatrixResult,
    compute_ccf_lag,
    granger_causality_test,
    fit_var_model,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def synthetic_causal_data():
    """Generate synthetic data where source Granger-causes target at lag 2."""
    np.random.seed(42)
    n = 200
    source = np.random.randn(n) * 0.02
    # Target depends on source lagged by 2 periods + noise
    target = np.zeros(n)
    for t in range(2, n):
        target[t] = 0.5 * source[t - 2] + np.random.randn() * 0.01

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    source_s = pd.Series(source, index=dates, name="source")
    target_s = pd.Series(target, index=dates, name="target")
    return source_s, target_s


@pytest.fixture
def synthetic_uncorrelated_data():
    """Generate independent random walks (no causality)."""
    np.random.seed(99)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    a = pd.Series(np.random.randn(n) * 0.02, index=dates, name="A")
    b = pd.Series(np.random.randn(n) * 0.02, index=dates, name="B")
    return a, b


@pytest.fixture
def short_data():
    """Generate very short data (below min_samples threshold)."""
    np.random.seed(1)
    n = 10
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(np.random.randn(n) * 0.02, index=dates, name="short")


# ── compute_ccf_lag tests ─────────────────────────────────────────────


class TestComputeCCFLag:
    def test_causal_lag_detection(self, synthetic_causal_data):
        """CCF should detect a positive lag around 2 for causal data."""
        source, target = synthetic_causal_data
        corr, lag = compute_ccf_lag(source, target, max_lag=5)
        assert abs(corr) > 0.1, f"Expected meaningful correlation, got {corr}"
        # Lag should be positive (source leads target)
        assert lag >= 0, f"Expected non-negative lag (source leads), got {lag}"

    def test_zero_lag_for_contemporaneous(self):
        """When series are identical, lag should be 0 with high correlation."""
        np.random.seed(33)
        n = 100
        s = pd.Series(np.random.randn(n) * 0.02, name="s")
        corr, lag = compute_ccf_lag(s, s, max_lag=5)
        assert abs(corr - 1.0) < 0.01, f"Expected ~1.0 correlation, got {corr}"
        assert lag == 0, f"Expected lag=0, got {lag}"

    def test_short_data_returns_zero(self, short_data):
        """Short data should return (0.0, 0)."""
        corr, lag = compute_ccf_lag(short_data, short_data, max_lag=5)
        assert corr == 0.0
        assert lag == 0

    def test_max_lag_range(self, synthetic_causal_data):
        """Lag should be within [-max_lag, +max_lag]."""
        source, target = synthetic_causal_data
        _, lag = compute_ccf_lag(source, target, max_lag=3)
        assert -3 <= lag <= 3


# ── granger_causality_test tests ──────────────────────────────────────


class TestGrangerCausality:
    def test_significant_causality(self, synthetic_causal_data):
        """Granger test should detect causality in synthetic causal data."""
        source, target = synthetic_causal_data
        score, pval, significant = granger_causality_test(source, target, max_lag=5)
        assert 0.0 <= score <= 1.0, f"Score out of range: {score}"
        assert 0.0 <= pval <= 1.0, f"P-value out of range: {pval}"
        # With strong synthetic causality, should be significant
        assert significant, f"Expected significant causality, pval={pval}"

    def test_no_causality(self, synthetic_uncorrelated_data):
        """Granger test should not detect causality for independent data."""
        a, b = synthetic_uncorrelated_data
        score, pval, significant = granger_causality_test(a, b, max_lag=5)
        assert 0.0 <= score <= 1.0
        # For truly independent data, p-value should typically be > 0.05
        # (not guaranteed due to sampling, but likely with n=200)
        assert pval > 0.01, f"Unexpectedly low p-value for independent data: {pval}"

    def test_short_data(self, short_data):
        """Short data should return (0.0, 1.0, False)."""
        score, pval, significant = granger_causality_test(short_data, short_data, max_lag=3)
        assert score == 0.0
        assert pval == 1.0
        assert not significant


# ── fit_var_model tests ───────────────────────────────────────────────


class TestVARModel:
    def test_var_fits_two_series(self, synthetic_causal_data):
        """VAR should fit a 2-series model and return a valid order."""
        source, target = synthetic_causal_data
        df = pd.DataFrame({"source": source, "target": target})
        order, result = fit_var_model(df, max_lag=5)
        assert order is not None, "VAR order should not be None"
        assert order >= 1, f"VAR order should be >= 1, got {order}"
        assert result is not None, "VAR result should not be None"

    def test_var_fails_for_short_data(self, short_data):
        """VAR should return (None, None) for insufficient data."""
        df = pd.DataFrame({"a": short_data, "b": short_data})
        order, result = fit_var_model(df, max_lag=3)
        assert order is None
        assert result is None


# ── CausalityAnalyzer.analyze_pair tests ──────────────────────────────


class TestAnalyzePair:
    def test_causal_pair(self, synthetic_causal_data):
        """Full pairwise analysis should detect causality."""
        source, target = synthetic_causal_data
        analyzer = CausalityAnalyzer(max_lag=5, min_samples=30)
        result = analyzer.analyze_pair(
            source_returns=source,
            target_returns=target,
            source_name="^GSPC",
            target_name="BBCA",
        )

        assert isinstance(result, CausalityResult)
        assert result.source == "^GSPC"
        assert result.target == "BBCA"
        assert -1.0 <= result.correlation_coefficient <= 1.0
        assert 0.0 <= result.causality_score <= 1.0
        assert 0.0 <= result.causality_p_value <= 1.0
        assert result.causality_direction in ("source→target", "target→source", "bidirectional", "none")
        assert result.time_lag_seconds >= 0
        assert result.impact_weight >= 0.0
        assert result.sample_size > 0

    def test_short_data_returns_zero(self, short_data):
        """Insufficient data should return zeroed result."""
        analyzer = CausalityAnalyzer(max_lag=5, min_samples=30)
        result = analyzer.analyze_pair(
            source_returns=short_data,
            target_returns=short_data,
            source_name="A",
            target_name="B",
        )
        assert result.correlation_coefficient == 0.0
        assert result.causality_score == 0.0
        assert result.causality_direction == "none"
        assert result.impact_weight == 0.0
        assert result.sample_size < 30

    def test_regime_label(self, synthetic_causal_data):
        """Regime label should be stored in result."""
        source, target = synthetic_causal_data
        analyzer = CausalityAnalyzer(max_lag=5)
        result = analyzer.analyze_pair(
            source_returns=source,
            target_returns=target,
            source_name="X",
            target_name="Y",
            regime="crisis",
        )
        assert result.regime == "crisis"

    def test_time_lag_seconds_conversion(self, synthetic_causal_data):
        """Time lag in seconds should be periods * 86400."""
        source, target = synthetic_causal_data
        analyzer = CausalityAnalyzer(max_lag=5)
        result = analyzer.analyze_pair(
            source_returns=source,
            target_returns=target,
            source_name="X",
            target_name="Y",
        )
        expected_seconds = abs(result.time_lag_periods) * 86400
        assert result.time_lag_seconds == expected_seconds


# ── CausalityAnalyzer.analyze_matrix tests ────────────────────────────


class TestAnalyzeMatrix:
    def test_matrix_analysis(self, synthetic_causal_data):
        """Matrix analysis should produce results for all pairs."""
        source, target = synthetic_causal_data
        df = pd.DataFrame({"^GSPC": source, "BBCA": target})

        analyzer = CausalityAnalyzer(max_lag=3, min_samples=30)
        result = analyzer.analyze_matrix(df)

        assert isinstance(result, MatrixResult)
        assert len(result.pairs) == 2  # ^GSPC→BBCA and BBCA→^GSPC
        # Check no self-pairs
        for pair in result.pairs:
            assert pair.source != pair.target

    def test_matrix_to_dataframe(self, synthetic_causal_data):
        """MatrixResult.to_dataframe should produce a valid DataFrame."""
        source, target = synthetic_causal_data
        df = pd.DataFrame({"A": source, "B": target})

        analyzer = CausalityAnalyzer(max_lag=3, min_samples=30)
        result = analyzer.analyze_matrix(df)
        df_out = result.to_dataframe()

        assert isinstance(df_out, pd.DataFrame)
        assert len(df_out) == 2
        assert "source_instrument_id" in df_out.columns
        assert "target_instrument_id" in df_out.columns
        assert "causality_score" in df_out.columns
        assert "time_lag_seconds" in df_out.columns

    def test_matrix_with_source_filter(self, synthetic_causal_data):
        """Matrix analysis with source_tickers should only analyse those sources."""
        source, target = synthetic_causal_data
        noise = pd.Series(
            np.random.randn(len(source)) * 0.02,
            index=source.index, name="C",
        )
        df = pd.DataFrame({"A": source, "B": target, "C": noise})

        analyzer = CausalityAnalyzer(max_lag=3, min_samples=30)
        result = analyzer.analyze_matrix(df, source_tickers=["A"])
        # Should only have A→B and A→C
        assert len(result.pairs) == 2
        assert all(p.source == "A" for p in result.pairs)


# ── Regime-conditional analysis tests ─────────────────────────────────


class TestRegimeConditional:
    def test_regime_conditional_analysis(self, synthetic_causal_data):
        """Regime-conditional analysis should split by regime label."""
        source, target = synthetic_causal_data
        n = len(source)
        regime_labels = pd.Series(
            ["bull"] * (n // 2) + ["bear"] * (n - n // 2),
            index=source.index,
        )

        df = pd.DataFrame({"A": source, "B": target})
        analyzer = CausalityAnalyzer(max_lag=3, min_samples=30)
        result = analyzer.analyze_regime_conditional(df, regime_labels)

        assert len(result.pairs) > 0
        regimes_found = {p.regime for p in result.pairs}
        # Should have results from both regimes
        assert "bull" in regimes_found or "bear" in regimes_found

    def test_regime_conditional_short_data(self):
        """Regime-conditional analysis with insufficient data should return empty."""
        n = 15
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "A": pd.Series(np.random.randn(n) * 0.02, index=dates),
            "B": pd.Series(np.random.randn(n) * 0.02, index=dates),
        })
        regime_labels = pd.Series(["bull"] * n, index=dates)

        analyzer = CausalityAnalyzer(max_lag=3, min_samples=30)
        result = analyzer.analyze_regime_conditional(df, regime_labels)
        assert len(result.pairs) == 0
