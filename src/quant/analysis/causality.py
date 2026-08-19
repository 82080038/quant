"""Cross-Asset Causality & Time-Lag Analysis Module.

Implements three complementary econometric methods for detecting and quantifying
cross-asset interdependencies:

1. **Granger Causality Test** — Determines whether past values of asset A
   statistically improve the prediction of asset B's future values beyond
   what B's own history provides. Uses `statsmodels.tsa.stattools.grangercausalitytests`.

2. **Vector Autoregression (VAR)** — Fits a joint linear model where each
   asset is regressed on its own lags and the lags of all other assets.
   The VAR coefficient matrix reveals directional impact magnitudes.
   Uses `statsmodels.tsa.vector_ar.var_model.VAR`.

3. **Cross-Correlation Function (CCF) with Time-Lag** — Computes the
   Pearson correlation between two return series at various lag offsets.
   The lag with the maximum |correlation| identifies the temporal delay
   in the propagation of shocks from source to target.

The module also supports **regime-conditional analysis** — splitting the
time series into sub-periods based on detected market regimes (trending,
ranging, crisis) and computing causality metrics separately for each.
This captures the empirical fact that cross-asset relationships are
non-stationary and vary with market conditions.

References (from internet research):
  - Granger, C.W.J. (1969). "Investigating Causal Relations by Econometric
    Models and Cross-Spectral Methods." Econometrica, 37(3), 424-438.
  - Billio et al. (2012). "Econometric measures of connectedness and
    systemic risk in the finance and insurance sectors." JFE, 104(3).
  - Diebold & Yilmaz (2009/2012). Connectedness framework using VAR
    variance decomposition.
  - Ando et al. (2018). Quantile VAR (QVAR) for tail-dependent causality.
  - Balcilar et al. (2016). Causality-in-quantiles for regime-dependent
    Granger causality testing.
  - Feldhütter & Lundén (2025). Robust Granger test correcting for
    microstructure noise (CEPR DP20898).
  - Pakrooh & Manera (2024). Time-Varying parameter VAR with Stochastic
    Volatility for cross-market spillover analysis.

Usage:
    from quant.analysis.causality import CausalityAnalyzer

    analyzer = CausalityAnalyzer(max_lag=5, significance_level=0.05)
    result = analyzer.analyze_pair(
        source_returns=sp500_returns,
        target_returns=bbc_returns,
        source_name="^GSPC",
        target_name="BBCA",
    )
    # result.causality_score, result.correlation, result.time_lag_periods, ...

    # Batch analysis for all pairs:
    results = analyzer.analyze_matrix(returns_df, target_tickers=["BBCA", "BBRI"])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = [
    "CausalityResult",
    "CausalityAnalyzer",
    "compute_ccf_lag",
    "granger_causality_test",
    "fit_var_model",
]


@dataclass
class CausalityResult:
    """Result of a single pairwise causality analysis.

    Attributes:
        source: Source instrument identifier (leading indicator).
        target: Target instrument identifier (lagging indicator).
        correlation_coefficient: Pearson correlation at optimal lag [-1, 1].
        causality_score: Normalised Granger causality F-statistic → [0, 1].
        causality_p_value: P-value from the Granger causality test.
        causality_direction: "source→target", "target→source", "bidirectional", or "none".
        time_lag_periods: Optimal lag in number of periods (days for EOD data).
        time_lag_seconds: Time lag converted to seconds (assumes EOD = 86400s per period).
        impact_weight: Combined influence magnitude = |correlation| * causality_score.
        var_order: Selected VAR lag order (via AIC).
        sample_size: Number of observations used.
        regime: Market regime label for this result.
    """

    source: str
    target: str
    correlation_coefficient: float
    causality_score: float
    causality_p_value: float
    causality_direction: str
    time_lag_periods: int
    time_lag_seconds: int
    impact_weight: float
    var_order: Optional[int] = None
    sample_size: int = 0
    regime: str = "unknown"


@dataclass
class MatrixResult:
    """Result of batch causality analysis across multiple pairs."""

    pairs: list[CausalityResult] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in self.pairs:
            rows.append({
                "source_instrument_id": r.source,
                "target_instrument_id": r.target,
                "correlation_coefficient": r.correlation_coefficient,
                "causality_score": r.causality_score,
                "causality_p_value": r.causality_p_value,
                "causality_direction": r.causality_direction,
                "time_lag_periods": r.time_lag_periods,
                "time_lag_seconds": r.time_lag_seconds,
                "impact_weight": r.impact_weight,
                "var_order": r.var_order,
                "sample_size": r.sample_size,
                "regime": r.regime,
            })
        return pd.DataFrame(rows)


# ── Standalone functions ──────────────────────────────────────────────


def compute_ccf_lag(
    source: pd.Series,
    target: pd.Series,
    max_lag: int = 10,
) -> tuple[float, int]:
    """Compute cross-correlation function and find the optimal lag.

    For each lag k in [-max_lag, +max_lag], computes:
        corr(target_t, source_{t-k})

    A **positive** lag k means the source leads the target by k periods
    (source movements are observed k periods before the target responds).

    Args:
        source: Return series of the source (potential leading) asset.
        target: Return series of the target (potential lagging) asset.
        max_lag: Maximum absolute lag to test.

    Returns:
        (max_correlation, optimal_lag) — the correlation value and lag
        at which |correlation| is maximised.
    """
    combined = pd.DataFrame({"source": source, "target": target}).dropna()
    if len(combined) < 20:
        return 0.0, 0

    source_clean = combined["source"].values
    target_clean = combined["target"].values
    n = len(target_clean)

    best_corr = 0.0
    best_lag = 0

    for lag in range(-max_lag, max_lag + 1):
        if lag == 0:
            corr = float(np.corrcoef(source_clean, target_clean)[0, 1])
        elif lag > 0:
            # source leads target by 'lag' periods
            if n - lag < 20:
                continue
            corr = float(np.corrcoef(source_clean[:n - lag], target_clean[lag:])[0, 1])
        else:
            # target leads source by |lag| periods
            abs_lag = -lag
            if n - abs_lag < 20:
                continue
            corr = float(np.corrcoef(source_clean[abs_lag:], target_clean[:n - abs_lag])[0, 1])

        if not np.isnan(corr) and abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag

    return best_corr, best_lag


def granger_causality_test(
    source: pd.Series,
    target: pd.Series,
    max_lag: int = 5,
    significance_level: float = 0.05,
) -> tuple[float, float, bool]:
    """Perform Granger causality test: does source Granger-cause target?

    Uses `statsmodels.tsa.stattools.grangercausalitytests` which fits
    restricted (target on its own lags) vs unrestricted (target on its
    own lags + source lags) VAR models and computes an F-test.

    The null hypothesis H0: source does NOT Granger-cause target.

    Args:
        source: Return series of the source asset.
        target: Return series of the target asset.
        max_lag: Maximum lag order to test.
        significance_level: P-value threshold for rejection.

    Returns:
        (causality_score, p_value, is_significant)
        causality_score is normalised to [0, 1] from the F-statistic.
    """
    try:
        from statsmodels.tsa.stattools import grangercausalitytests

        combined = pd.DataFrame({"target": target, "source": source}).dropna()
        if len(combined) < 30:
            return 0.0, 1.0, False

        # grangercausalitytests expects [target, source] ordering
        # and tests whether the second column Granger-causes the first
        data = combined[["target", "source"]].values

        results = grangercausalitytests(data, maxlag=max_lag, verbose=False)

        # Extract the minimum p-value across all lag orders
        min_p_value = 1.0
        best_f_stat = 0.0

        for lag in results:
            try:
                test_results = results[lag]
                # ssr_ftest is the F-test; also available: lrtest, params_ftest, chi2test
                f_test = test_results[0]["ssr_ftest"]
                f_stat = float(f_test[0])
                p_val = float(f_test[1])

                if p_val < min_p_value:
                    min_p_value = p_val
                    best_f_stat = f_stat
            except (KeyError, IndexError, TypeError):
                continue

        # Normalise F-statistic to [0, 1] using a sigmoid-like transform
        # F-statistic > ~4 typically indicates significance at 5% level
        causality_score = float(1.0 / (1.0 + np.exp(-(best_f_stat - 4.0) / 2.0)))
        is_significant = min_p_value < significance_level

        return causality_score, min_p_value, is_significant

    except ImportError:
        logger.warning("statsmodels not available for Granger causality test")
        return 0.0, 1.0, False
    except Exception as e:
        logger.debug("Granger causality test failed: %s", e)
        return 0.0, 1.0, False


def fit_var_model(
    returns: pd.DataFrame,
    max_lag: int = 5,
) -> tuple[Optional[int], Optional[object]]:
    """Fit a Vector Autoregression (VAR) model to multi-asset returns.

    Selects the optimal lag order via Akaike Information Criterion (AIC).

    Args:
        returns: DataFrame of return series (T × N assets).
        max_lag: Maximum lag order to consider.

    Returns:
        (selected_order, var_result) or (None, None) if fitting fails.
    """
    try:
        from statsmodels.tsa.api import VAR

        combined = returns.dropna()
        if len(combined) < 30 or combined.shape[1] < 2:
            return None, None

        model = VAR(combined)
        # Select order by AIC
        order_select = model.select_order(maxlags=max_lag)
        selected = order_select.aic
        if selected is None or selected < 1:
            selected = 1

        result = model.fit(selected)
        return int(selected), result

    except ImportError:
        logger.warning("statsmodels not available for VAR fitting")
        return None, None
    except Exception as e:
        logger.debug("VAR fitting failed: %s", e)
        return None, None


# ── Main analyzer class ───────────────────────────────────────────────


class CausalityAnalyzer:
    """Cross-asset causality and time-lag analyzer.

    Combines Granger causality, VAR, and CCF-lag into a unified
    pairwise analysis pipeline. Supports regime-conditional computation
    for detecting non-stationary (time-varying) causal relationships.

    Usage:
        analyzer = CausalityAnalyzer(max_lag=5)
        result = analyzer.analyze_pair(
            source_returns=sp500_ret,
            target_returns=bbca_ret,
            source_name="^GSPC",
            target_name="BBCA",
        )
    """

    SECONDS_PER_PERIOD = 86400  # EOD data: 1 period = 1 day = 86400 seconds

    def __init__(
        self,
        max_lag: int = 5,
        significance_level: float = 0.05,
        min_samples: int = 30,
    ) -> None:
        self.max_lag = max_lag
        self.significance_level = significance_level
        self.min_samples = min_samples

    def analyze_pair(
        self,
        source_returns: pd.Series,
        target_returns: pd.Series,
        source_name: str,
        target_name: str,
        regime: str = "unknown",
    ) -> CausalityResult:
        """Perform full causality analysis for a single source→target pair.

        Steps:
        1. Align and validate the return series.
        2. Compute CCF to find optimal time-lag and correlation.
        3. Run Granger causality test (source→target and target→source).
        4. Determine causality direction (unidirectional or bidirectional).
        5. Compute impact weight = |correlation| × causality_score.
        6. Optionally fit VAR for lag-order selection.

        Args:
            source_returns: Daily returns of the source asset.
            target_returns: Daily returns of the target asset.
            source_name: Identifier for the source asset.
            target_name: Identifier for the target asset.
            regime: Market regime label (e.g. "bull", "bear", "crisis").

        Returns:
            CausalityResult with all metrics.
        """
        combined = pd.DataFrame({
            "source": source_returns,
            "target": target_returns,
        }).dropna()

        n = len(combined)
        if n < self.min_samples:
            return CausalityResult(
                source=source_name,
                target=target_name,
                correlation_coefficient=0.0,
                causality_score=0.0,
                causality_p_value=1.0,
                causality_direction="none",
                time_lag_periods=0,
                time_lag_seconds=0,
                impact_weight=0.0,
                var_order=None,
                sample_size=n,
                regime=regime,
            )

        src = combined["source"]
        tgt = combined["target"]

        # Step 1: CCF for time-lag and correlation
        corr, lag = compute_ccf_lag(src, tgt, max_lag=self.max_lag)

        # Step 2: Granger causality — source → target
        s2t_score, s2t_pval, s2t_sig = granger_causality_test(
            src, tgt, max_lag=self.max_lag, significance_level=self.significance_level,
        )

        # Step 3: Granger causality — target → source (reverse)
        t2s_score, t2s_pval, t2s_sig = granger_causality_test(
            tgt, src, max_lag=self.max_lag, significance_level=self.significance_level,
        )

        # Step 4: Determine direction
        if s2t_sig and not t2s_sig:
            direction = "source→target"
            causality_score = s2t_score
            p_value = s2t_pval
        elif t2s_sig and not s2t_sig:
            direction = "target→source"
            causality_score = t2s_score
            p_value = t2s_pval
        elif s2t_sig and t2s_sig:
            direction = "bidirectional"
            causality_score = max(s2t_score, t2s_score)
            p_value = min(s2t_pval, t2s_pval)
        else:
            direction = "none"
            causality_score = max(s2t_score, t2s_score) * 0.5  # dampen
            p_value = min(s2t_pval, t2s_pval)

        # Step 5: Impact weight
        impact_weight = abs(corr) * causality_score

        # Step 6: VAR for lag order (optional, on the 2-variable system)
        var_order = None
        try:
            var_data = combined.copy()
            order, _ = fit_var_model(var_data, max_lag=self.max_lag)
            var_order = order
        except Exception:
            pass

        # Convert lag to seconds
        # Positive lag = source leads target by 'lag' periods
        time_lag_seconds = abs(lag) * self.SECONDS_PER_PERIOD

        return CausalityResult(
            source=source_name,
            target=target_name,
            correlation_coefficient=round(corr, 6),
            causality_score=round(causality_score, 6),
            causality_p_value=round(p_value, 8),
            causality_direction=direction,
            time_lag_periods=lag,
            time_lag_seconds=time_lag_seconds,
            impact_weight=round(impact_weight, 6),
            var_order=var_order,
            sample_size=n,
            regime=regime,
        )

    def analyze_matrix(
        self,
        returns_df: pd.DataFrame,
        source_tickers: Optional[list[str]] = None,
        target_tickers: Optional[list[str]] = None,
        regime: str = "unknown",
    ) -> MatrixResult:
        """Analyze causality for all source×target pairs.

        Args:
            returns_df: DataFrame where each column is an asset's return series.
            source_tickers: List of source (leading indicator) tickers.
                If None, all columns are used as sources.
            target_tickers: List of target (lagging indicator) tickers.
                If None, all columns are used as targets.
            regime: Market regime label.

        Returns:
            MatrixResult containing all pairwise CausalityResult objects.
        """
        all_tickers = returns_df.columns.tolist()
        sources = source_tickers or all_tickers
        targets = target_tickers or all_tickers

        pairs: list[CausalityResult] = []

        for src_ticker in sources:
            for tgt_ticker in targets:
                if src_ticker == tgt_ticker:
                    continue
                if src_ticker not in returns_df.columns or tgt_ticker not in returns_df.columns:
                    continue

                result = self.analyze_pair(
                    source_returns=returns_df[src_ticker],
                    target_returns=returns_df[tgt_ticker],
                    source_name=src_ticker,
                    target_name=tgt_ticker,
                    regime=regime,
                )
                pairs.append(result)

        return MatrixResult(pairs=pairs)

    def analyze_regime_conditional(
        self,
        returns_df: pd.DataFrame,
        regime_labels: pd.Series,
        source_tickers: Optional[list[str]] = None,
        target_tickers: Optional[list[str]] = None,
    ) -> MatrixResult:
        """Analyze causality separately for each market regime.

        This captures the empirical fact that cross-asset relationships
        are non-stationary — correlations and causal links strengthen
        during crises and weaken during calm periods.

        Args:
            returns_df: DataFrame of return series.
            regime_labels: Series of regime labels indexed by date.
                Values like "trending", "ranging", "crisis".
            source_tickers: Source tickers (None = all).
            target_tickers: Target tickers (None = all).

        Returns:
            MatrixResult with regime-tagged pairwise results.
        """
        all_pairs: list[CausalityResult] = []
        aligned = returns_df.join(regime_labels.rename("_regime"), how="inner").dropna()

        if aligned.empty:
            return MatrixResult(pairs=[])

        regimes = aligned["_regime"].unique()

        for regime in regimes:
            regime_data = aligned[aligned["_regime"] == regime].drop(columns=["_regime"])
            if len(regime_data) < self.min_samples:
                continue

            matrix = self.analyze_matrix(
                regime_data,
                source_tickers=source_tickers,
                target_tickers=target_tickers,
                regime=str(regime),
            )
            all_pairs.extend(matrix.pairs)

        return MatrixResult(pairs=all_pairs)
