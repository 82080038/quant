"""Deflated Sharpe Ratio (DSR).

Corrects for selection bias (multiple testing) and non-normality.
Based on Bailey & López de Prado (2014).

DSR = Φ( (SR - E[max SR*]) · √(T-1) / √(1 - γ₃·SR + (γ₄-1)/4 · SR²) )

Where:
  SR = observed Sharpe ratio
  E[max SR*] = expected max Sharpe under null (all strategies have zero true SR)
  T = number of observations
  γ₃ = skewness of returns
  γ₄ = excess kurtosis of returns
  N = number of independent trials (strategies tested)

References:
  Bailey & López de Prado, "The Deflated Sharpe Ratio", JPM 2014
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass


@dataclass
class DSRResult:
    """Deflated Sharpe Ratio result."""
    observed_sr: float
    expected_max_sr: float
    deflated_sr: float
    psr: float          # Probabilistic Sharpe Ratio (probability true SR > 0)
    n_trials: int
    n_observations: int
    skewness: float
    kurtosis: float
    is_real: bool       # DSR > 0.95 → real edge


def sharpe_ratio(returns: np.ndarray, periods_per_year: int = 252, rf: float = 0.0) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    excess = returns - rf / periods_per_year
    std = excess.std(ddof=1)
    if std == 0:
        return 0.0
    return np.sqrt(periods_per_year) * excess.mean() / std


def expected_max_sharpe(n_trials: int, var_sharpe: float = 0.04) -> float:
    """E[max SR*] under null hypothesis that all N strategies have zero true SR.

    Based on the expected maximum of N i.i.d. standard normals:
    E[max] ≈ (1 - Φ) Φ⁻¹(1 - 1/N) + φ(Φ⁻¹(1 - 1/N))

    For large N: E[max] ≈ √(2·ln(N))

    Args:
        n_trials: Number of independent strategy variants tested
        var_sharpe: Variance of Sharpe ratio estimates across trials

    Returns:
        Expected maximum Sharpe ratio under null
    """
    if n_trials <= 1:
        return 0.0
    # Euler-Mascheroni constant approximation
    euler = 0.5772156649
    # Expected max of N standard normals
    e_max = np.sqrt(2 * np.log(n_trials)) - (np.log(np.pi) + euler) / (2 * np.sqrt(2 * np.log(n_trials)))
    # Scale by std of Sharpe estimates
    return e_max * np.sqrt(var_sharpe)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_trials: int = 1,
    periods_per_year: int = 252,
    rf: float = 0.0,
    var_sharpe: float = None,
) -> DSRResult:
    """Compute Deflated Sharpe Ratio.

    Args:
        returns: Array of strategy returns
        n_trials: Number of independent strategy variants tested
        periods_per_year: Annualization factor (252 for daily, 12 for monthly)
        rf: Risk-free rate (annual)
        var_sharpe: Variance of Sharpe across trials (auto-computed if None)

    Returns:
        DSRResult with all metrics
    """
    returns = np.asarray(returns, dtype=float)
    T = len(returns)

    if T < 2:
        return DSRResult(0, 0, 0, 0, n_trials, T, 0, 0, False)

    # Observed Sharpe
    sr = sharpe_ratio(returns, periods_per_year, rf)

    # Skewness and excess kurtosis
    from scipy.stats import skew, kurtosis
    skew_val = skew(returns, bias=False)
    kurt_val = kurtosis(returns, fisher=True, bias=False)  # excess kurtosis

    # Variance of Sharpe across trials
    if var_sharpe is None:
        # Default: variance of SR estimates ≈ (1 + γ₃·SR + (γ₄-1)/4 · SR²) / (T-1)
        var_sharpe = (1 + skew_val * sr + (kurt_val - 1) / 4 * sr**2) / (T - 1)

    # Expected max Sharpe under null
    e_max_sr = expected_max_sharpe(n_trials, var_sharpe)

    # Deflated Sharpe: PSR with benchmark = E[max SR*]
    # PSR = Φ( (SR - benchmark) · √(T-1) / √(1 - γ₃·SR + (γ₄-1)/4 · SR²) )
    denom = np.sqrt(1 - skew_val * sr + (kurt_val - 1) / 4 * sr**2)
    if denom == 0:
        psr = 0.5
    else:
        z = (sr - e_max_sr) * np.sqrt(T - 1) / denom
        psr = float(norm.cdf(z))

    # Deflated SR is the z-score itself
    deflated_sr = float((sr - e_max_sr) * np.sqrt(T - 1) / denom) if denom > 0 else 0.0

    return DSRResult(
        observed_sr=float(sr),
        expected_max_sr=float(e_max_sr),
        deflated_sr=deflated_sr,
        psr=psr,
        n_trials=n_trials,
        n_observations=T,
        skewness=float(skew_val),
        kurtosis=float(kurt_val),
        is_real=psr > 0.95,
    )


def min_track_record_length(sr: float, periods_per_year: int = 252, confidence: float = 0.95) -> float:
    """Minimum Track Record Length (MinTRL).

    How many observations are needed to have confidence that SR > 0?

    Based on Bailey & López de Prado (2014).
    """
    from scipy.stats import norm
    z = norm.ppf(confidence)
    return float((z / sr) ** 2) if sr > 0 else float('inf')


def min_backtest_length(sr: float, n_trials: int, periods_per_year: int = 252) -> float:
    """Minimum Backtest Length (MinBTL).

    How many observations are needed to have confidence that SR > E[max SR*]?
    """
    e_max = expected_max_sharpe(n_trials)
    if sr <= e_max:
        return float('inf')
    from scipy.stats import norm
    z = norm.ppf(0.95)
    return float((z / (sr - e_max)) ** 2)
