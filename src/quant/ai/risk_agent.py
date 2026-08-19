"""Risk Manager Agent — fail-closed risk gate with VaR/ES monitoring.

Inspired by FinRL-DeepSeek risk-sensitive RL. The Risk Manager Agent:
  1. Monitors portfolio VaR (Value at Risk) and ES (Expected Shortfall)
  2. Enforces hard limits: max position, max sector, max drawdown
  3. Blocks orders that violate risk constraints (fail-closed)
  4. Triggers portfolio halt on drawdown breach
  5. Provides risk attribution per position

Weight-centric pipeline position:
  w_t = R_t(T_t(A_t(S_t(X_≤t))))
  R_t = Risk Manager Agent output (risk overlay)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from quant.ai.trader_agent import TradingDecision
from quant.core.config import config

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """Result of a risk check on a proposed trade."""
    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    var_95: float = 0.0
    es_95: float = 0.0
    portfolio_var: float = 0.0
    current_drawdown: float = 0.0


@dataclass
class RiskState:
    """Current portfolio risk state."""
    nav: float
    positions: dict[str, float]  # ticker → weight
    sector_exposure: dict[str, float]
    current_drawdown: float
    peak_nav: float
    is_halted: bool = False
    halt_reason: str = ""


RISK_SYSTEM_PROMPT = """You are a risk manager for an Indonesian stock market (IDX) portfolio.

Your job is to FAIL-CLOSED: if any risk limit is breached, block the trade.
You monitor:
- VaR (95% confidence, 1-day horizon)
- Expected Shortfall (ES)
- Maximum drawdown
- Position concentration
- Sector concentration

IDX-specific risk limits:
- Max 15% per ticker
- Max 40% per sector
- Max 3% daily portfolio VaR
- Max 15% drawdown → halt trading
- Min 5% cash reserve

Respond in JSON with risk assessment and any violations."""


class RiskManagerAgent:
    """Fail-closed risk gate agent.

    Usage:
        risk_mgr = RiskManagerAgent()
        check = risk_mgr.check_decision(
            decision=trading_decision,
            risk_state=current_risk_state,
            returns_history=returns_df,
        )
        if not check.passed:
            print(f"BLOCKED: {check.violations}")
    """

    def __init__(
        self,
        gateway=None,
        limits: Optional[dict] = None,
    ):
        self.gateway = gateway
        self.limits = limits or {
            "max_position_pct": config.max_position_pct,
            "max_sector_pct": config.max_sector_pct,
            "max_portfolio_var": config.max_portfolio_var,
            "max_drawdown": config.max_drawdown,
            "min_cash_reserve": config.min_cash_reserve,
        }

    def check_decision(
        self,
        decision: TradingDecision,
        risk_state: RiskState,
        returns_history: Optional[pd.DataFrame] = None,
        sector_map: Optional[dict[str, str]] = None,
    ) -> RiskCheckResult:
        """Run fail-closed risk checks on a trading decision.

        Args:
            decision: Proposed trading decision from Trader Agent
            risk_state: Current portfolio risk state
            returns_history: Historical returns for VaR computation
            sector_map: ticker → sector mapping

        Returns:
            RiskCheckResult with pass/fail and violations
        """
        violations = []
        warnings = []

        weights = decision.timing_adjusted or decision.weights

        # 1. Position concentration check
        for ticker, weight in weights.items():
            if weight > self.limits["max_position_pct"]:
                violations.append(
                    f"Position {ticker} at {weight:.1%} exceeds max {self.limits['max_position_pct']:.1%}"
                )

        # 2. Sector concentration check
        if sector_map:
            sector_exposure: dict[str, float] = {}
            for ticker, weight in weights.items():
                sector = sector_map.get(ticker, "unknown")
                sector_exposure[sector] = sector_exposure.get(sector, 0) + weight

            for sector, exposure in sector_exposure.items():
                if exposure > self.limits["max_sector_pct"]:
                    violations.append(
                        f"Sector {sector} at {exposure:.1%} exceeds max {self.limits['max_sector_pct']:.1%}"
                    )

        # 3. Cash reserve check
        total_invested = sum(weights.values())
        cash_reserve = 1.0 - total_invested
        if cash_reserve < self.limits["min_cash_reserve"]:
            violations.append(
                f"Cash reserve {cash_reserve:.1%} below min {self.limits['min_cash_reserve']:.1%}"
            )

        # 4. Drawdown check
        if risk_state.current_drawdown < -self.limits["max_drawdown"]:
            violations.append(
                f"Drawdown {risk_state.current_drawdown:.1%} exceeds max -{self.limits['max_drawdown']:.1%} — HALT"
            )

        # 5. VaR check
        var_95 = 0.0
        es_95 = 0.0
        portfolio_var = 0.0

        if returns_history is not None and not returns_history.empty:
            portfolio_returns = self._compute_portfolio_returns(weights, returns_history)
            var_95, es_95 = self._compute_var_es(portfolio_returns)
            portfolio_var = var_95

            if abs(var_95) > self.limits["max_portfolio_var"]:
                violations.append(
                    f"Portfolio VaR {abs(var_95):.2%} exceeds max {self.limits['max_portfolio_var']:.2%}"
                )

        # 6. Halt state check
        if risk_state.is_halted:
            violations.append(f"Portfolio is HALTED: {risk_state.halt_reason}")

        passed = len(violations) == 0

        if not passed:
            logger.warning("Risk gate BLOCKED decision: %s", violations)

        return RiskCheckResult(
            passed=passed,
            violations=violations,
            warnings=warnings,
            var_95=var_95,
            es_95=es_95,
            portfolio_var=portfolio_var,
            current_drawdown=risk_state.current_drawdown,
        )

    def update_risk_state(
        self,
        current_nav: float,
        positions: dict[str, float],
        sector_map: Optional[dict[str, str]] = None,
        peak_nav: Optional[float] = None,
    ) -> RiskState:
        """Update and return current risk state.

        Args:
            current_nav: Current portfolio NAV
            positions: ticker → weight
            sector_map: ticker → sector
            peak_nav: Historical peak NAV (auto-computed if None)

        Returns:
            Updated RiskState
        """
        peak = peak_nav or current_nav
        drawdown = (current_nav - peak) / peak if peak > 0 else 0

        sector_exposure = {}
        if sector_map:
            for ticker, weight in positions.items():
                sector = sector_map.get(ticker, "unknown")
                sector_exposure[sector] = sector_exposure.get(sector, 0) + weight

        is_halted = drawdown < -self.limits["max_drawdown"]
        halt_reason = ""
        if is_halted:
            halt_reason = f"Drawdown {drawdown:.1%} exceeded limit -{self.limits['max_drawdown']:.1%}"

        return RiskState(
            nav=current_nav,
            positions=positions,
            sector_exposure=sector_exposure,
            current_drawdown=drawdown,
            peak_nav=peak,
            is_halted=is_halted,
            halt_reason=halt_reason,
        )

    @staticmethod
    def _compute_portfolio_returns(
        weights: dict[str, float],
        returns_history: pd.DataFrame,
    ) -> pd.Series:
        """Compute portfolio returns from weights and asset returns."""
        tickers = [t for t in weights if t in returns_history.columns]
        if not tickers:
            return pd.Series(dtype=float)

        w = np.array([weights[t] for t in tickers])
        R = returns_history[tickers].values
        port_returns = R @ w
        return pd.Series(port_returns, index=returns_history.index)

    @staticmethod
    def _compute_var_es(returns: pd.Series, confidence: float = 0.95) -> tuple[float, float]:
        """Compute VaR and Expected Shortfall.

        Args:
            returns: Portfolio return series
            confidence: Confidence level (95%)

        Returns:
            (VaR, ES) as negative returns (losses are negative)
        """
        if returns.empty or len(returns) < 20:
            return 0.0, 0.0

        clean = returns.dropna()
        if clean.empty:
            return 0.0, 0.0

        percentile = (1 - confidence) * 100
        var = float(np.percentile(clean, percentile))
        tail = clean[clean <= var]
        es = float(tail.mean()) if len(tail) > 0 else var

        return var, es
