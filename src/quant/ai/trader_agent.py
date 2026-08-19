"""Trader Agent — risk-constrained portfolio execution.

Inspired by FinRL-X + ATLAS. The Trader Agent:
  1. Receives screened tickers + composite signals from Screener
  2. Constructs optimal portfolio via HRP-µ or RL allocator
  3. Applies timing adjustment (KAMA trend overlay, regime gate)
  4. Outputs a weight vector w_t for execution

Weight-centric pipeline position:
  w_t = R_t(T_t(A_t(S_t(X_≤t))))
  A_t = Trader Agent output (portfolio allocation)
  T_t = Trader Agent timing adjustment
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from quant.ai.llm_gateway import LLMGateway
from quant.ai.screener_agent import ScreeningResult

logger = logging.getLogger(__name__)


@dataclass
class TradingDecision:
    """Output of the Trader Agent."""
    weights: dict[str, float]
    timing_adjusted: dict[str, float]
    regime: str
    method: str  # "hrp_mu" | "rl" | "kelly" | "equal_weight"
    confidence: float
    llm_rationale: str
    rejected: list[str] = field(default_factory=list)


TRADER_SYSTEM_PROMPT = """You are a portfolio trader for the Indonesian stock market (IDX).

Given screened stocks with signals and current market conditions, your task is to:
1. Determine optimal position sizing
2. Apply timing adjustments based on trend and regime
3. Consider liquidity constraints and transaction costs

IDX-specific constraints:
- Lot size: 100 shares
- Commission: 0.15%
- Sales tax: 0.1% on sell
- Max position: 15% per ticker
- Max sector: 40%

Respond in JSON with weights and rationale."""


class TraderAgent:
    """Risk-constrained portfolio execution agent.

    Usage:
        trader = TraderAgent()
        decision = trader.execute(
            screening=result,
            as_of_date=date(2024, 6, 1),
            covariance=cov_matrix,
        )
        for ticker, weight in decision.weights.items():
            print(f"{ticker}: {weight:.2%}")
    """

    def __init__(
        self,
        gateway: Optional[LLMGateway] = None,
        allocation_method: str = "hrp_mu",
    ):
        self.gateway = gateway or LLMGateway()
        self.allocation_method = allocation_method

    def execute(
        self,
        screening: ScreeningResult,
        as_of_date: date,
        covariance: Optional[pd.DataFrame] = None,
        signals: Optional[dict[str, float]] = None,
        max_position: float = 0.15,
        use_llm: bool = True,
    ) -> TradingDecision:
        """Construct portfolio from screening results.

        Args:
            screening: Screener Agent output
            as_of_date: Decision date
            covariance: Ticker × ticker covariance matrix
            signals: Override signals (ticker → [-1, 1])
            max_position: Maximum weight per ticker
            use_llm: Use LLM for execution reasoning

        Returns:
            TradingDecision with final weights
        """
        tickers = screening.selected_tickers
        if not tickers:
            return TradingDecision(
                weights={}, timing_adjusted={}, regime=screening.regime,
                method="none", confidence=0, llm_rationale="No tickers selected",
            )

        scores = signals or screening.scores
        signal_vec = np.array([scores.get(t, 0.0) for t in tickers])

        if self.allocation_method == "hrp_mu" and covariance is not None:
            weights = self._allocate_hrp_mu(tickers, signal_vec, covariance, max_position)
            method = "hrp_mu"
        elif self.allocation_method == "kelly":
            weights = self._allocate_kelly(tickers, signal_vec, max_position)
            method = "kelly"
        else:
            weights = self._allocate_equal_weight(tickers, signal_vec, max_position)
            method = "equal_weight"

        timing_adj = self._apply_timing(tickers, weights, screening.regime)

        llm_rationale = ""
        if use_llm:
            llm_rationale = self._llm_reasoning(tickers, weights, screening)

        return TradingDecision(
            weights=weights,
            timing_adjusted=timing_adj,
            regime=screening.regime,
            method=method,
            confidence=screening.regime_confidence,
            llm_rationale=llm_rationale,
        )

    def _allocate_hrp_mu(
        self,
        tickers: list[str],
        signals: np.ndarray,
        cov: pd.DataFrame,
        max_pos: float,
    ) -> dict[str, float]:
        """Allocate using HRP-µ (signal-aware HRP)."""
        try:
            from quant.portfolio.hrp_mu import HRPMu
            allocator = HRPMu()
            return allocator.allocate(
                signals=dict(zip(tickers, signals)),
                covariance=cov.loc[tickers, tickers] if all(t in cov.index for t in tickers) else cov,
                max_weight=max_pos,
            )
        except Exception as e:
            logger.warning("HRP-µ failed, falling back to equal weight: %s", e)
            return self._allocate_equal_weight(tickers, signals, max_pos)

    def _allocate_kelly(
        self,
        tickers: list[str],
        signals: np.ndarray,
        max_pos: float,
    ) -> dict[str, float]:
        """Allocate using risk-constrained Kelly."""
        try:
            from quant.portfolio.kelly import RiskConstrainedKelly
            kelly = RiskConstrainedKelly()
            weights = {}
            for ticker, signal in zip(tickers, signals):
                w = kelly.size(signal=signal, max_weight=max_pos)
                weights[ticker] = w
            return weights
        except Exception as e:
            logger.warning("Kelly failed, falling back to equal weight: %s", e)
            return self._allocate_equal_weight(tickers, signals, max_pos)

    def _allocate_equal_weight(
        self,
        tickers: list[str],
        signals: np.ndarray,
        max_pos: float,
    ) -> dict[str, float]:
        """Signal-weighted equal allocation with position cap."""
        abs_signals = np.abs(signals)
        total = abs_signals.sum()
        if total == 0:
            n = len(tickers)
            return {t: min(1.0 / n, max_pos) for t in tickers}

        weights = {}
        for ticker, signal, abs_s in zip(tickers, signals, abs_signals):
            w = (abs_s / total) * np.sign(signal)
            weights[ticker] = float(np.clip(w, 0, max_pos))

        total_w = sum(weights.values())
        if total_w > 1.0:
            weights = {k: v / total_w for k, v in weights.items()}

        return weights

    def _apply_timing(
        self,
        tickers: list[str],
        weights: dict[str, float],
        regime: str,
    ) -> dict[str, float]:
        """Apply timing adjustment based on regime.

        - Bull: Full weights, trend-following
        - Bear: Reduce exposure by 50%
        - Sideways: Full weights
        - Crisis: Reduce to 25% (de-risk)
        """
        regime_mult = {
            "bull": 1.0,
            "bear": 0.5,
            "sideways": 1.0,
            "crisis": 0.25,
        }
        mult = regime_mult.get(regime, 1.0)

        return {t: w * mult for t, w in weights.items()}

    def _llm_reasoning(
        self,
        tickers: list[str],
        weights: dict[str, float],
        screening: ScreeningResult,
    ) -> str:
        """Get LLM reasoning for trading decision."""
        weight_str = ", ".join(f"{t}: {w:.2%}" for t, w in weights.items())
        user_prompt = f"""Regime: {screening.regime} (confidence: {screening.regime_confidence:.2f})
Allocated weights: {weight_str}
Method: {self.allocation_method}

Briefly explain (2-3 sentences) the rationale for this allocation."""

        resp = self.gateway.complete(
            system=TRADER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.3,
            max_tokens=512,
        )

        if resp.success:
            return resp.text
        return ""
