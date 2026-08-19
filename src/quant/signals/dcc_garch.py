"""DCC-GARCH cross-market volatility model.

Implements Dynamic Conditional Correlation GARCH(1,1) for modeling
time-varying correlations between IDX sectors and global markets.

Uses arch package for univariate GARCH, then computes DCC correlations
following Engle (2002).

Usage:
    from quant.signals.dcc_garch import DCCGARCHModel
    model = DCCGARCHModel()
    model.fit(returns_df)
    correlations = model.get_conditional_correlations()
    forecast = model.forecast_correlation(horizon=5)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class DCCGARCHResult:
    """Result of DCC-GARCH fitting."""
    conditional_correlations: pd.DataFrame  # Time-varying correlation matrix
    conditional_volatilities: pd.DataFrame  # Time-varying volatilities
    garch_params: dict[str, dict]  # Per-asset GARCH parameters
    dcc_alpha: float  # DCC alpha parameter
    dcc_beta: float  # DCC beta parameter
    log_likelihood: float
    n_assets: int
    n_observations: int


class DCCGARCHModel:
    """DCC-GARCH(1,1) model for cross-market correlation modeling.

    Steps:
    1. Fit univariate GARCH(1,1) to each asset's returns
    2. Compute standardized residuals
    3. Estimate DCC parameters (alpha, beta) via QMLE
    4. Compute dynamic conditional correlations

    Usage:
        model = DCCGARCHModel()
        model.fit(returns_df)
        corr = model.get_conditional_correlations()
    """

    def __init__(self, garch_p: int = 1, garch_q: int = 1, dcc_window: int = 252):
        self.garch_p = garch_p
        self.garch_q = garch_q
        self.dcc_window = dcc_window
        self._result: DCCGARCHResult | None = None
        self._returns: pd.DataFrame | None = None

    def fit(self, returns: pd.DataFrame) -> DCCGARCHResult:
        """Fit DCC-GARCH model to returns data.

        Args:
            returns: DataFrame of asset returns (T × N)

        Returns:
            DCCGARCHResult with correlations and parameters
        """
        try:
            from arch import arch_model
        except ImportError:
            logger.warning("arch package not available — using simple EWMA fallback")
            return self._fit_ewma_fallback(returns)

        n_assets = returns.shape[1]
        tickers = returns.columns.tolist()
        T = len(returns)

        # Step 1: Fit univariate GARCH(1,1) for each asset
        garch_params = {}
        standardized_residuals = np.zeros((T, n_assets))
        conditional_volatilities = np.zeros((T, n_assets))

        for i, ticker in enumerate(tickers):
            try:
                am = arch_model(
                    returns[ticker].dropna() * 100,  # Scale for numerical stability
                    vol="Garch", p=self.garch_p, q=self.garch_q,
                    dist="normal", rescale=False,
                )
                res = am.fit(disp="off")
                garch_params[ticker] = {
                    "mu": res.params.get("mu", 0),
                    "omega": res.params.get("omega", 0),
                    "alpha": res.params.get("alpha[1]", 0),
                    "beta": res.params.get("beta[1]", 0),
                }
                cond_vol = res.conditional_volatility / 100  # Unscale
                std_resid = res.resid / res.conditional_volatility

                # Align to original index
                aligned_vol = pd.Series(index=returns.index, dtype=float)
                aligned_vol.loc[returns[ticker].dropna().index] = cond_vol
                aligned_resid = pd.Series(index=returns.index, dtype=float)
                aligned_resid.loc[returns[ticker].dropna().index] = std_resid

                conditional_volatilities[:, i] = aligned_vol.fillna(0).values
                standardized_residuals[:, i] = aligned_resid.fillna(0).values
            except Exception as e:
                logger.warning("GARCH fit failed for %s: %s — using rolling std", ticker, e)
                rolling_vol = returns[ticker].rolling(self.dcc_window, min_periods=20).std()
                conditional_volatilities[:, i] = rolling_vol.fillna(returns[ticker].std()).values
                standardized_residuals[:, i] = (returns[ticker] / rolling_vol).fillna(0).values
                garch_params[ticker] = {"omega": 0, "alpha": 0.1, "beta": 0.9}

        # Step 2: Estimate DCC parameters
        dcc_alpha, dcc_beta = self._estimate_dcc_params(standardized_residuals)

        # Step 3: Compute dynamic conditional correlations
        dcc_corr = self._compute_dcc_correlations(standardized_residuals, dcc_alpha, dcc_beta)

        # Convert to DataFrames
        corr_frames = []
        for t in range(T):
            corr_frames.append(pd.DataFrame(dcc_corr[t], index=tickers, columns=tickers))

        # Average correlation over last window
        recent_corrs = dcc_corr[-self.dcc_window:]
        avg_corr = np.mean(recent_corrs, axis=0)
        avg_corr_df = pd.DataFrame(avg_corr, index=tickers, columns=tickers)

        vol_df = pd.DataFrame(conditional_volatilities, index=returns.index, columns=tickers)

        self._result = DCCGARCHResult(
            conditional_correlations=avg_corr_df,
            conditional_volatilities=vol_df,
            garch_params=garch_params,
            dcc_alpha=dcc_alpha,
            dcc_beta=dcc_beta,
            log_likelihood=0.0,  # Would need full QMLE for this
            n_assets=n_assets,
            n_observations=T,
        )
        self._returns = returns
        logger.info("DCC-GARCH fitted: %d assets, alpha=%.3f, beta=%.3f", n_assets, dcc_alpha, dcc_beta)
        return self._result

    def _estimate_dcc_params(self, std_resid: np.ndarray) -> tuple[float, float]:
        """Estimate DCC alpha and beta via method of moments."""
        T, N = std_resid.shape
        # Use sample correlation of standardized residuals
        Q_bar = np.cov(std_resid.T)
        if Q_bar.ndim == 0:
            Q_bar = np.array([[Q_bar]])
        elif Q_bar.ndim == 1:
            Q_bar = np.diag(Q_bar)

        # Simple grid search for alpha, beta
        best_ll = -np.inf
        best_alpha, best_beta = 0.05, 0.9

        for alpha in [0.01, 0.05, 0.1, 0.15]:
            for beta in [0.85, 0.9, 0.95]:
                if alpha + beta >= 1.0:
                    continue
                Q = Q_bar.copy()
                ll = 0
                for t in range(1, T):
                    eps = std_resid[t].reshape(-1, 1)
                    Q = Q_bar * (1 - alpha - beta) + alpha * (eps @ eps.T) + beta * Q
                    Q_inv = np.linalg.inv(Q + np.eye(N) * 1e-8)
                    ll -= 0.5 * (np.log(np.linalg.det(Q) + 1e-8) + eps.T @ Q_inv @ eps)
                if ll > best_ll:
                    best_ll = ll
                    best_alpha, best_beta = alpha, beta

        return best_alpha, best_beta

    def _compute_dcc_correlations(
        self, std_resid: np.ndarray, alpha: float, beta: float
    ) -> np.ndarray:
        """Compute time-varying conditional correlations."""
        T, N = std_resid.shape
        Q_bar = np.cov(std_resid.T)
        if Q_bar.ndim == 0:
            Q_bar = np.array([[Q_bar]])
        elif Q_bar.ndim == 1:
            Q_bar = np.diag(Q_bar)

        Q = Q_bar.copy()
        correlations = np.zeros((T, N, N))

        for t in range(T):
            eps = std_resid[t].reshape(-1, 1)
            Q = Q_bar * (1 - alpha - beta) + alpha * (eps @ eps.T) + beta * Q
            # Convert Q to correlation matrix
            D_inv = np.diag(1.0 / np.sqrt(np.diag(Q) + 1e-8))
            R = D_inv @ Q @ D_inv
            correlations[t] = R

        return correlations

    def _fit_ewma_fallback(self, returns: pd.DataFrame) -> DCCGARCHResult:
        """EWMA fallback when arch package unavailable."""
        T, N = returns.shape
        tickers = returns.columns.tolist()
        lambda_ = 0.94

        vol = np.zeros((T, N))
        vol[0] = returns.iloc[0].abs().values
        for t in range(1, T):
            vol[t] = np.sqrt(lambda_ * vol[t-1]**2 + (1-lambda_) * returns.iloc[t].values**2)

        std_resid = returns.values / (vol + 1e-8)

        # Simple correlation
        corr = np.corrcoef(std_resid.T)
        if corr.ndim == 0:
            corr = np.array([[corr]])
        elif corr.ndim == 1:
            corr = np.diag(corr)

        corr_df = pd.DataFrame(corr, index=tickers, columns=tickers)
        vol_df = pd.DataFrame(vol, index=returns.index, columns=tickers)

        self._result = DCCGARCHResult(
            conditional_correlations=corr_df,
            conditional_volatilities=vol_df,
            garch_params={t: {"alpha": 0.06, "beta": 0.94} for t in tickers},
            dcc_alpha=0.05,
            dcc_beta=0.94,
            log_likelihood=0.0,
            n_assets=N,
            n_observations=T,
        )
        logger.info("DCC-GARCH fitted (EWMA fallback): %d assets", N)
        return self._result

    def get_conditional_correlations(self) -> pd.DataFrame:
        """Get latest conditional correlation matrix."""
        if self._result is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        return self._result.conditional_correlations

    def forecast_correlation(self, horizon: int = 5) -> pd.DataFrame:
        """Forecast correlation for given horizon.

        Under DCC, the forecast converges to the unconditional correlation.
        """
        if self._result is None:
            raise RuntimeError("Model not fitted. Call fit() first.")
        # DCC forecast: R_forecast = rho^h * R_t + (1 - rho^h) * R_bar
        rho = self._result.dcc_alpha + self._result.dcc_beta
        current = self._result.conditional_correlations
        # For long horizon, converges to unconditional
        forecast = (rho ** horizon) * current + (1 - rho ** horizon) * current
        return forecast
