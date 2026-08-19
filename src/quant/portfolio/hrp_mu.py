"""HRP-µ — Signal-Aware Hierarchical Risk Parity.

Based on "Beyond De Prado and Cotton" (arXiv:2604.23833).

Standard HRP is signal-blind — it allocates based on covariance structure only.
HRP-µ integrates signals into the allocation:

  1. Compute covariance matrix from returns
  2. Compute signal-adjusted expected returns: μ_adj = signals * confidence
  3. Interpolate between diagonal (risk parity) and full Markowitz:
     w = (1-γ) * w_diag + γ * w_markowitz
  4. Apply hierarchical clustering for stability
  5. Enforce position limits

The γ parameter controls the signal-awareness:
  γ=0: Pure risk parity (signal-blind, like standard HRP)
  γ=0.5: Balanced (default)
  γ=1: Full Markowitz (signal-driven, may be unstable)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.spatial.distance import squareform


class HRPMu:
    """Signal-Aware Hierarchical Risk Parity.

    Usage:
        allocator = HRPMu()
        weights = allocator.allocate(
            signals={"BBCA.JK": 0.8, "BBRI.JK": 0.6, "TLKM.JK": -0.3},
            covariance=cov_df,
            gamma=0.5,
            max_weight=0.15,
        )
    """

    def __init__(self, gamma: float = 0.5):
        self.gamma = gamma

    def allocate(
        self,
        signals: dict[str, float],
        covariance: pd.DataFrame,
        gamma: Optional[float] = None,
        max_weight: float = 0.15,
        min_weight: float = 0.0,
    ) -> dict[str, float]:
        """Allocate weights using HRP-µ.

        Args:
            signals: ticker → signal value [-1, 1]
            covariance: ticker × ticker covariance matrix
            gamma: Interpolation parameter (0=diagonal, 1=Markowitz)
            max_weight: Maximum weight per ticker
            min_weight: Minimum weight per ticker (0 = no short)

        Returns:
            ticker → weight [0, 1]
        """
        g = gamma if gamma is not None else self.gamma
        tickers = list(signals.keys())
        n = len(tickers)

        if n == 0:
            return {}

        if n == 1:
            return {tickers[0]: min(max_weight, 1.0)}

        cov = covariance.loc[tickers, tickers].values.astype(float)
        signal_vec = np.array([signals[t] for t in tickers])

        # ── Step 1: Quasi-diagonalize via hierarchical clustering ──
        corr = self._cov_to_corr(cov)
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist, 0)

        try:
            condensed = squareform(dist, checks=False)
            link = linkage(condensed, method="single")
            order = self._get_quasi_diag(link, n)
        except Exception:
            order = list(range(n))

        # ── Step 2: Recursive bisection (HRP core) ────────────────
        w_diag = self._recursive_bisection(cov, order)

        # ── Step 3: Signal-aware Markowitz (µ-adjusted) ───────────
        w_markowitz = self._signal_markowitz(cov, signal_vec)

        # ── Step 4: Interpolate ───────────────────────────────────
        w = (1 - g) * w_diag + g * w_markowitz

        # ── Step 5: Apply constraints ─────────────────────────────
        w = np.clip(w, min_weight, max_weight)

        # Normalize
        total = w.sum()
        if total > 0:
            w = w / total
        else:
            w = np.ones(n) / n

        # Re-apply max weight after normalization
        w = np.clip(w, 0, max_weight)
        total = w.sum()
        if total > 0:
            w = w / total

        return dict(zip(tickers, w))

    @staticmethod
    def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
        """Convert covariance to correlation matrix."""
        std = np.sqrt(np.diag(cov))
        std[std == 0] = 1e-8
        corr = cov / np.outer(std, std)
        # Clip to valid range to avoid NaN from floating point errors
        corr = np.nan_to_num(corr, nan=0.0)
        corr = np.clip(corr, -1.0, 1.0)
        return corr

    @staticmethod
    def _get_quasi_diag(link: np.ndarray, n: int) -> list[int]:
        """Get quasi-diagonal ordering from linkage matrix."""
        link = link.astype(int)
        root = to_tree(link)

        def _get_leaves(node):
            if node.is_leaf():
                return [node.id]
            return _get_leaves(node.left) + _get_leaves(node.right)

        return _get_leaves(root)

    @staticmethod
    def _recursive_bisection(cov: np.ndarray, order: list[int]) -> np.ndarray:
        """Recursive bisection for HRP weight allocation."""
        n = len(order)
        w = np.ones(n)
        clusters = [order]

        while len(clusters) > 0:
            clusters = [c for c in clusters if len(c) > 0]
            if not clusters:
                break

            new_clusters = []
            for cluster in clusters:
                if len(cluster) <= 1:
                    new_clusters.append(cluster)
                    continue

                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]

                left_var = HRPMu._cluster_variance(cov, left)
                right_var = HRPMu._cluster_variance(cov, right)

                alpha = 1 - left_var / (left_var + right_var + 1e-10)

                for i in left:
                    w[i] *= alpha
                for i in right:
                    w[i] *= (1 - alpha)

                if len(left) > 1:
                    new_clusters.append(left)
                if len(right) > 1:
                    new_clusters.append(right)

            clusters = new_clusters

        return w

    @staticmethod
    def _cluster_variance(cov: np.ndarray, indices: list[int]) -> float:
        """Compute variance of a cluster."""
        if len(indices) == 0:
            return 0.0
        sub_cov = cov[np.ix_(indices, indices)]
        ivp = 1 / np.diag(sub_cov)
        ivp = ivp / ivp.sum()
        return float(ivp @ sub_cov @ ivp)

    @staticmethod
    def _signal_markowitz(cov: np.ndarray, signals: np.ndarray) -> np.ndarray:
        """Signal-aware Markowitz allocation.

        w ∝ Σ⁻¹ · μ_signal
        where μ_signal = signals * confidence
        """
        n = len(signals)
        if n == 0:
            return np.ones(0)

        # Signal-adjusted expected returns
        mu = signals.copy()
        # Only long signals (no shorting for now)
        mu[mu < 0] = 0

        if mu.sum() == 0:
            return np.ones(n) / n

        # Regularized inverse covariance
        try:
            cov_reg = cov + 1e-6 * np.eye(n)
            inv_cov = np.linalg.inv(cov_reg)
            w = inv_cov @ mu
            w = np.clip(w, 0, None)
            total = w.sum()
            if total > 0:
                w = w / total
            else:
                w = np.ones(n) / n
            return w
        except np.linalg.LinAlgError:
            return np.ones(n) / n
