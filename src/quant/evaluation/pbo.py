"""Probability of Backtest Overfitting (PBO) via CSCV.

Combinatorially Symmetric Cross-Validation (CSCV) to detect overfitting
in strategy selection procedures.

Based on Bailey, Borwein, López de Prado & Zhu (2014).

PBO = fraction of combinations where the in-sample winner
      ranks below median out-of-sample.

PBO > 0.5 → overfit (IS winner doesn't generalize)
PBO < 0.2 → good generalization
"""

import numpy as np
from itertools import combinations
from dataclasses import dataclass
from typing import Optional


@dataclass
class PBOResult:
    """PBO result."""
    pbo: float               # Probability of backtest overfitting
    n_strategies: int
    n_observations: int
    n_partitions: int
    n_combinations: int
    degradation_slope: float  # Performance degradation IS→OOS
    is_overfit: bool          # PBO > 0.5


def _sharpe(returns: np.ndarray) -> float:
    """Sharpe ratio for a returns array."""
    if returns.shape[0] < 2:
        return 0.0
    std = returns.std(axis=0, ddof=1)
    mean = returns.mean(axis=0)
    # Avoid division by zero
    with np.errstate(divide='ignore', invalid='ignore'):
        sr = np.where(std > 0, mean / std, 0.0)
    return sr


def probability_of_backtest_overfit(
    returns_matrix: np.ndarray,
    n_partitions: int = 16,
    max_combinations: int = 500,
    rng: Optional[np.random.Generator] = None,
) -> PBOResult:
    """Compute PBO via Combinatorially Symmetric Cross-Validation.

    Args:
        returns_matrix: Shape (n_observations, n_strategies) — returns for each strategy
        n_partitions: Split into 2*S chunks (S = n_partitions/2). Common: 16 (S=8)
        max_combinations: Maximum number of combinations to sample (full enumeration is C(2S,S))
        rng: Random number generator for sampling

    Returns:
        PBOResult with PBO and degradation metrics
    """
    if rng is None:
        rng = np.random.default_rng(42)

    n_obs, n_strategies = returns_matrix.shape
    S = n_partitions // 2  # number of IS/OOS partitions each

    if n_obs < n_partitions:
        raise ValueError(f"Need at least {n_partitions} observations, got {n_obs}")

    # Split into 2*S chunks
    chunk_size = n_obs // n_partitions
    chunks = [returns_matrix[i * chunk_size:(i + 1) * chunk_size] for i in range(n_partitions)]

    # Enumerate or sample combinations
    all_combos = list(combinations(range(n_partitions), S))
    n_total = len(all_combos)

    if n_total <= max_combinations:
        sampled = all_combos
    else:
        # Sample randomly
        indices = rng.choice(n_total, size=max_combinations, replace=False)
        sampled = [all_combos[i] for i in indices]

    below_count = 0
    is_sharpes = []
    oos_sharpes = []
    is_best_oos_ranks = []

    for is_idx in sampled:
        is_set = set(is_idx)
        is_mat = np.concatenate([chunks[i] for i in is_idx], axis=0)
        oos_mat = np.concatenate([chunks[i] for i in range(n_partitions) if i not in is_set], axis=0)

        is_sr = _sharpe(is_mat)
        oos_sr = _sharpe(oos_mat)

        # Find IS winner
        best_is = int(np.argmax(is_sr))

        # Rank of IS winner in OOS
        oos_best_sr = oos_sr[best_is]
        rank = np.sum(oos_sr < oos_best_sr) / (n_strategies - 1) if n_strategies > 1 else 0.5

        # Logit of rank
        clamped = max(0.001, min(0.999, rank))
        logit = np.log(clamped / (1 - clamped))

        if logit < 0:
            below_count += 1

        is_sharpes.append(is_sr[best_is])
        oos_sharpes.append(oos_best_sr)
        is_best_oos_ranks.append(rank)

    pbo = below_count / len(sampled)

    # Performance degradation: slope of OOS Sharpe vs IS Sharpe
    is_arr = np.array(is_sharpes)
    oos_arr = np.array(oos_sharpes)
    if len(is_arr) > 1 and is_arr.std() > 0:
        degradation_slope = float(np.polyfit(is_arr, oos_arr, 1)[0])
    else:
        degradation_slope = 0.0

    return PBOResult(
        pbo=float(pbo),
        n_strategies=n_strategies,
        n_observations=n_obs,
        n_partitions=n_partitions,
        n_combinations=len(sampled),
        degradation_slope=degradation_slope,
        is_overfit=pbo > 0.5,
    )


def haircut_sharpe(sr: float, n_trials: int, var_sharpe: float = 0.04) -> float:
    """Harvey-Liu haircut Sharpe ratio.

    Adjusts Sharpe for multiple testing by subtracting the expected max.

    Args:
        sr: Observed Sharpe ratio
        n_trials: Number of strategies tested
        var_sharpe: Variance of Sharpe estimates

    Returns:
        Haircut Sharpe (observed - expected max under null)
    """
    from quant.evaluation.dsr import expected_max_sharpe
    e_max = expected_max_sharpe(n_trials, var_sharpe)
    return float(sr - e_max)
