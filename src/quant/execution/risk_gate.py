"""Fail-closed risk gate for production execution.

Hard risk limits — blocks orders that violate constraints.
This is the production execution-layer risk gate, separate from
the Risk Manager Agent (which operates at the portfolio decision level).

The risk gate operates at order submission time:
  submit_order → validate → RISK GATE → fill simulation

If any check fails, the order is REJECTED (not delayed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from quant.core.config import config
from quant.execution.oms import Order, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Hard risk limits — all orders must satisfy."""
    max_position_pct: float = 0.15       # max 15% per ticker
    max_sector_pct: float = 0.40         # max 40% per sector
    max_portfolio_var: float = 0.03      # max 3% daily VaR
    max_drawdown: float = 0.15           # max 15% drawdown → halt
    min_cash_reserve: float = 0.05       # min 5% cash
    max_single_order_value: float = 0.10 # max 10% of NAV per single order
    max_daily_turnover: float = 0.50     # max 50% of portfolio per day
    max_open_orders: int = 20            # max concurrent open orders


@dataclass
class RiskGateResult:
    """Result of risk gate check."""
    passed: bool
    reason: str
    violations: list[str] = field(default_factory=list)


@dataclass
class PortfolioRiskState:
    """Current portfolio state for risk checks."""
    nav: float
    cash: float
    positions: dict[str, float]  # ticker → market_value
    sector_map: dict[str, str]
    current_drawdown: float = 0.0
    daily_turnover: float = 0.0
    is_halted: bool = False
    halt_reason: str = ""


class RiskGate:
    """Fail-closed risk gate for order execution.

    Usage:
        gate = RiskGate()
        result = gate.check(
            order=Order(id="ORD-001", ticker="BBCA.JK", side=OrderSide.BUY, shares=100, order_type=OrderType.MARKET),
            state=portfolio_state,
            current_price=8500,
        )
        if not result.passed:
            print(f"REJECTED: {result.reason}")
    """

    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits(
            max_position_pct=config.max_position_pct,
            max_sector_pct=config.max_sector_pct,
            max_portfolio_var=config.max_portfolio_var,
            max_drawdown=config.max_drawdown,
            min_cash_reserve=config.min_cash_reserve,
        )

    def check(
        self,
        order: Order,
        state: PortfolioRiskState,
        current_price: float,
    ) -> RiskGateResult:
        """Check if an order passes all risk constraints.

        Args:
            order: Order to check
            state: Current portfolio state
            current_price: Current price of the order's ticker

        Returns:
            RiskGateResult with pass/fail and reason
        """
        violations = []

        # 0. Halt check
        if state.is_halted:
            return RiskGateResult(
                passed=False,
                reason=f"Portfolio HALTED: {state.halt_reason}",
                violations=["Portfolio is halted — all orders blocked"],
            )

        # 1. Drawdown check
        if state.current_drawdown < -self.limits.max_drawdown:
            violations.append(
                f"Drawdown {state.current_drawdown:.1%} exceeds limit -{self.limits.max_drawdown:.1%}"
            )

        # 2. Order value check
        order_value = order.shares * current_price
        if state.nav > 0 and order_value / state.nav > self.limits.max_single_order_value:
            violations.append(
                f"Order value {order_value:,.0f} ({order_value/state.nav:.1%} of NAV) "
                f"exceeds max {self.limits.max_single_order_value:.1%}"
            )

        # 3. Cash check for buy orders
        if order.side == OrderSide.BUY:
            if order_value > state.cash:
                violations.append(
                    f"Insufficient cash: need {order_value:,.0f}, have {state.cash:,.0f}"
                )
            # Cash reserve check
            remaining_cash = state.cash - order_value
            if state.nav > 0 and remaining_cash / state.nav < self.limits.min_cash_reserve:
                violations.append(
                    f"Cash reserve {remaining_cash/state.nav:.1%} below min {self.limits.min_cash_reserve:.1%}"
                )

        # 4. Position concentration check
        new_position_value = state.positions.get(order.ticker, 0)
        if order.side == OrderSide.BUY:
            new_position_value += order_value
        else:
            new_position_value -= order_value

        if state.nav > 0:
            position_pct = new_position_value / state.nav
            if position_pct > self.limits.max_position_pct:
                violations.append(
                    f"Position {order.ticker} at {position_pct:.1%} exceeds max {self.limits.max_position_pct:.1%}"
                )

        # 5. Sector concentration check
        sector = state.sector_map.get(order.ticker, "unknown")
        sector_total = sum(
            v for t, v in state.positions.items()
            if state.sector_map.get(t, "unknown") == sector
        )
        if order.side == OrderSide.BUY:
            sector_total += order_value

        if state.nav > 0 and sector_total / state.nav > self.limits.max_sector_pct:
            violations.append(
                f"Sector {sector} at {sector_total/state.nav:.1%} exceeds max {self.limits.max_sector_pct:.1%}"
            )

        # 6. Daily turnover check
        new_turnover = state.daily_turnover + order_value
        if state.nav > 0 and new_turnover / state.nav > self.limits.max_daily_turnover:
            violations.append(
                f"Daily turnover {new_turnover/state.nav:.1%} exceeds max {self.limits.max_daily_turnover:.1%}"
            )

        if violations:
            reason = violations[0]
            logger.warning("Risk gate REJECTED order %s: %s", order.id, reason)
            return RiskGateResult(passed=False, reason=reason, violations=violations)

        return RiskGateResult(passed=True, reason="All checks passed")
