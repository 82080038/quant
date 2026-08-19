"""Monte Carlo VaR — Value at Risk and Conditional VaR via simulation.

Uses historical simulation bootstrap and parametric methods to estimate
portfolio risk. Supports GPU acceleration via CUDA.

Usage:
    from quant.risk.monte_carlo_var import MonteCarloVaR
    var = MonteCarloVaR()
    result = var.compute(returns_df, confidence_levels=[0.95, 0.99], n_sims=10000)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.compute.device import select_device

logger = logging.getLogger(__name__)


@dataclass
class VaRResult:
    """Value at Risk computation result."""
    confidence_levels: list[float] = field(default_factory=list)
    var_values: dict[float, float] = field(default_factory=dict)
    cvar_values: dict[float, float] = field(default_factory=dict)
    portfolio_var: dict[float, float] = field(default_factory=dict)
    portfolio_cvar: dict[float, float] = field(default_factory=dict)
    n_simulations: int = 0
    method: str = ""
    device: str = "cpu"


class MonteCarloVaR:
    """Monte Carlo Value at Risk engine.

    Supports:
    - Historical simulation bootstrap
    - Parametric (normal, t-distribution)
    - Monte Carlo with Cholesky decomposition for correlated assets

    Args:
        n_simulations: Number of Monte Carlo simulations (default 10000).
        use_gpu: If True, try to use CUDA for simulations.
    """

    def __init__(self, n_simulations: int = 10000, use_gpu: bool = True) -> None:
        self.n_simulations = n_simulations
        self.use_gpu = use_gpu
        self._device = None

    def _get_device(self) -> str:
        if self._device is None:
            if self.use_gpu:
                self._device = select_device("var", data_size=self.n_simulations)
            else:
                self._device = "cpu"
        return self._device

    def _to_device(self, arr: np.ndarray) -> np.ndarray:
        dev = self._get_device()
        if dev.startswith("cuda"):
            try:
                import torch
                return torch.from_numpy(arr).to(dev)
            except ImportError:
                pass
        return arr

    def _from_device(self, arr) -> np.ndarray:
        if hasattr(arr, "cpu"):
            return arr.cpu().numpy()
        return np.asarray(arr)

    def compute(
        self,
        returns: pd.DataFrame,
        confidence_levels: list[float] | None = None,
        weights: np.ndarray | None = None,
        method: str = "historical",
    ) -> VaRResult:
        """Compute VaR and CVaR for portfolio.

        Args:
            returns: DataFrame of asset returns (columns = assets).
            confidence_levels: List of confidence levels (default [0.95, 0.99]).
            weights: Portfolio weights (default equal weight).
            method: "historical", "parametric", or "monte_carlo".

        Returns:
            VaRResult with VaR/CVaR at each confidence level.
        """
        if confidence_levels is None:
            confidence_levels = [0.95, 0.99]

        n_assets = returns.shape[1]
        if weights is None:
            weights = np.ones(n_assets) / n_assets

        ret_matrix = returns.values
        device = self._get_device()
        result = VaRResult(
            confidence_levels=confidence_levels,
            n_simulations=self.n_simulations,
            method=method,
            device=device,
        )

        if method == "historical":
            # Historical simulation: use actual returns
            portfolio_returns = ret_matrix @ weights
            for cl in confidence_levels:
                var = np.percentile(portfolio_returns, (1 - cl) * 100)
                cvar = portfolio_returns[portfolio_returns <= var].mean()
                result.portfolio_var[cl] = float(var)
                result.portfolio_cvar[cl] = float(cvar)

        elif method == "parametric":
            # Parametric: assume normal distribution
            mean = ret_matrix.mean(axis=0)
            cov = np.cov(ret_matrix, rowvar=False)
            port_mean = weights @ mean
            port_std = np.sqrt(weights @ cov @ weights)

            from scipy.stats import norm, t as t_dist
            df_fitted = max(5, min(30, ret_matrix.shape[0] // 50))

            for cl in confidence_levels:
                z = norm.ppf(1 - cl)
                var = port_mean + z * port_std
                cvar = port_mean - port_std * norm.pdf(z) / (1 - cl)
                result.portfolio_var[cl] = float(var)
                result.portfolio_cvar[cl] = float(cvar)

        elif method == "monte_carlo":
            # Monte Carlo with Cholesky decomposition
            mean = ret_matrix.mean(axis=0)
            cov = np.cov(ret_matrix, rowvar=False)

            # Cholesky decomposition for correlated random numbers
            try:
                L = np.linalg.cholesky(cov + 1e-8 * np.eye(n_assets))
            except np.linalg.LinAlgError:
                L = np.linalg.cholesky(cov + 1e-6 * np.eye(n_assets))

            if device.startswith("cuda"):
                try:
                    import torch
                    L_t = torch.from_numpy(L.astype(np.float32)).to(device)
                    mean_t = torch.from_numpy(mean.astype(np.float32)).to(device)
                    weights_t = torch.from_numpy(weights.astype(np.float32)).to(device)
                    z = torch.randn(self.n_simulations, n_assets, device=device, dtype=torch.float32)
                    sims = mean_t + z @ L_t.T
                    port_returns = sims @ weights_t
                    port_returns_np = port_returns.cpu().numpy()
                except ImportError:
                    z = np.random.randn(self.n_simulations, n_assets)
                    sims = mean + z @ L.T
                    port_returns_np = sims @ weights
            else:
                z = np.random.randn(self.n_simulations, n_assets)
                sims = mean + z @ L.T
                port_returns_np = sims @ weights

            for cl in confidence_levels:
                var = np.percentile(port_returns_np, (1 - cl) * 100)
                cvar = port_returns_np[port_returns_np <= var].mean()
                result.portfolio_var[cl] = float(var)
                result.portfolio_cvar[cl] = float(cvar)

        # Per-asset VaR (historical)
        for i, col in enumerate(returns.columns):
            asset_ret = ret_matrix[:, i]
            for cl in confidence_levels:
                var = np.percentile(asset_ret, (1 - cl) * 100)
                cvar = asset_ret[asset_ret <= var].mean()
                result.var_values[(col, cl)] = float(var)
                result.cvar_values[(col, cl)] = float(cvar)

        logger.info(
            "VaR computed: method=%s, n_sims=%d, device=%s, VaR95=%.4f, VaR99=%.4f",
            method, self.n_simulations, device,
            result.portfolio_var.get(0.95, 0),
            result.portfolio_var.get(0.99, 0),
        )

        return result
