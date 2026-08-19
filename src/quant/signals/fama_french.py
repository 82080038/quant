"""Fama-French 5-Factor Model for IDX equities.

Implements the Fama-French (2015) five-factor model:
  1. Market factor (MKT): market excess return
  2. Size factor (SMB): small minus big (market cap)
  3. Value factor (HML): high minus low (book-to-market)
  4. Profitability factor (RMW): robust minus weak (operating profitability)
  5. Investment factor (CMA): conservative minus aggressive (asset growth)

For IDX, we compute factor mimicking portfolios from the stock universe
using daily OHLCV data. The signal is the predicted return from factor
exposures (factor loadings × factor returns).

References:
  - Fama, E.F. & French, K.R. (2015). "A five-factor asset pricing model."
    Journal of Financial Economics, 116(1), 1-22.
  - Fama, E.F. & French, K.R. (1992). "The Cross-Section of Expected
    Stock Returns." Journal of Finance, 47(2), 427-465.
  - Hou, K., Mo, H., Xue, C., Zhang, L. (2019). "Which Factors?"
    Review of Finance, 23(1), 1-35.

Note: For a single-user personal app with IDX data, we use simplified
factor construction:
  - MKT: ^JKSE excess return (market return - risk-free proxy)
  - SMB: Median split by market cap (proxy: share price × volume)
  - HML: Median split by P/B ratio (from fundamental_data)
  - RMW: Median split by ROE (from fundamental_data)
  - CMA: Asset growth proxy (revenue_growth from fundamental_data)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FactorExposure:
    """Factor exposure result for a single ticker."""
    ticker: str
    beta_mkt: float = 0.0
    beta_smb: float = 0.0
    beta_hml: float = 0.0
    beta_rmw: float = 0.0
    beta_cma: float = 0.0
    predicted_return: float = 0.0
    confidence: float = 0.0


class FamaFrench5Factor:
    """Fama-French 5-Factor model for signal generation.

    Generates a directional signal [-1, +1] based on predicted excess return
    from factor exposures.
    """

    def __init__(
        self,
        market_ticker: str = "^JKSE",
        lookback: int = 60,
        min_history: int = 30,
    ) -> None:
        self.market_ticker = market_ticker
        self.lookback = lookback
        self.min_history = min_history

    def compute_signal(
        self,
        ticker: str,
        df: pd.DataFrame,
        market_df: pd.DataFrame | None = None,
        fundamentals: dict | None = None,
        universe_returns: pd.DataFrame | None = None,
    ) -> FactorExposure:
        """Compute Fama-French factor signal for a ticker.

        Args:
            ticker: Stock ticker.
            df: OHLCV DataFrame for the ticker.
            market_df: OHLCV DataFrame for market index (^JKSE).
            fundamentals: Dict with keys like pe_ratio, pb_ratio, roe,
                revenue_growth, market_cap.
            universe_returns: DataFrame of returns for all stocks (for
                factor portfolio construction). If None, uses simplified
                approach with just market factor.

        Returns:
            FactorExposure with betas and predicted return.
        """
        close = df["close"].astype(float)
        returns = close.pct_change().dropna()

        if len(returns) < self.min_history:
            return FactorExposure(ticker=ticker)

        # Market factor
        if market_df is not None and len(market_df) >= self.min_history:
            mkt_close = market_df["close"].astype(float)
            mkt_returns = mkt_close.pct_change().dropna()
            # Align
            common = returns.index.intersection(mkt_returns.index)
            if len(common) >= self.min_history:
                ret_aligned = returns.loc[common]
                mkt_aligned = mkt_returns.loc[common]
                # Rolling regression for beta
                window = min(self.lookback, len(common) - 1)
                if window >= 20:
                    cov = ret_aligned.rolling(window).cov(mkt_aligned)
                    var = mkt_aligned.rolling(window).var()
                    beta_mkt = float(cov.iloc[-1] / var.iloc[-1]) if var.iloc[-1] > 0 else 0.0
                    # Recent market momentum as factor return proxy
                    mkt_recent_ret = float(mkt_aligned.iloc[-5:].sum())
                else:
                    beta_mkt = 0.0
                    mkt_recent_ret = 0.0
            else:
                beta_mkt = 0.0
                mkt_recent_ret = 0.0
        else:
            beta_mkt = 0.0
            mkt_recent_ret = 0.0

        # Fundamental factors (simplified: use fundamentals dict if available)
        beta_smb = 0.0
        beta_hml = 0.0
        beta_rmw = 0.0
        beta_cma = 0.0

        if fundamentals:
            # Size factor: small companies (low market cap) tend to outperform
            market_cap = fundamentals.get("market_cap", 0)
            if market_cap and market_cap > 0:
                # Small cap → positive SMB exposure
                beta_smb = -np.tanh(np.log(market_cap) / 20)  # normalize

            # Value factor: high P/B → low HML exposure (growth stock)
            pb_ratio = fundamentals.get("pb_ratio")
            if pb_ratio and pb_ratio > 0:
                beta_hml = -np.tanh((pb_ratio - 1.5) / 2)  # high PB → negative HML

            # Profitability factor: high ROE → positive RMW
            roe = fundamentals.get("roe")
            if roe is not None:
                beta_rmw = np.tanh(roe / 20)  # high ROE → positive RMW

            # Investment factor: high revenue growth → negative CMA (aggressive)
            rev_growth = fundamentals.get("revenue_growth")
            if rev_growth is not None:
                beta_cma = -np.tanh(rev_growth / 30)

        # Factor return estimates (simplified: use recent market momentum)
        # In production, these would come from factor mimicking portfolios
        factor_returns = {
            "mkt": mkt_recent_ret,
            "smb": 0.001,  # small historical premium
            "hml": 0.0005,  # small historical premium
            "rmw": 0.0008,
            "cma": 0.0003,
        }

        # Predicted excess return
        predicted = (
            beta_mkt * factor_returns["mkt"]
            + beta_smb * factor_returns["smb"]
            + beta_hml * factor_returns["hml"]
            + beta_rmw * factor_returns["rmw"]
            + beta_cma * factor_returns["cma"]
        )

        # Confidence based on data quality
        confidence = 0.3
        if beta_mkt != 0:
            confidence += 0.2
        if fundamentals:
            confidence += 0.2

        return FactorExposure(
            ticker=ticker,
            beta_mkt=round(beta_mkt, 4),
            beta_smb=round(beta_smb, 4),
            beta_hml=round(beta_hml, 4),
            beta_rmw=round(beta_rmw, 4),
            beta_cma=round(beta_cma, 4),
            predicted_return=round(predicted, 6),
            confidence=min(0.8, confidence),
        )

    def signal_from_exposure(self, exposure: FactorExposure) -> tuple[float, float, str]:
        """Convert factor exposure to directional signal.

        Returns:
            (signal_value [-1, +1], confidence [0, 1], rationale)
        """
        pred = exposure.predicted_return
        # Normalize predicted return to [-1, 1]
        sig = max(-1.0, min(1.0, pred * 100))  # scale up
        direction = "UP" if sig > 0.05 else "DOWN" if sig < -0.05 else "FLAT"
        rationale = (
            f"beta_mkt={exposure.beta_mkt:.2f}, "
            f"beta_smb={exposure.beta_smb:.2f}, "
            f"beta_hml={exposure.beta_hml:.2f}, "
            f"pred_ret={pred:.5f}"
        )
        return sig, exposure.confidence, rationale
