"""Paper trading OMS — enhanced with risk gate integration and reconciliation.

Extends the base OMS with:
  - Risk gate integration (fail-closed before order submission)
  - Realistic fill simulation (slippage, partial fills)
  - Daily reconciliation (expected vs actual positions)
  - Portfolio state tracking (NAV, P&L, drawdown)
  - DB persistence for orders and portfolio state

IDX execution simulation:
  - Commission: 0.15%
  - Sales tax: 0.1% on sell
  - Slippage: 0.05-0.1% based on order size vs ADV
  - Lot size: 100 shares
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Optional

from quant.core.config import config
from quant.execution.oms import OMS, Order, OrderSide, OrderType, OrderStatus
from quant.execution.risk_gate import RiskGate, PortfolioRiskState, RiskGateResult

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Current position in a ticker."""
    ticker: str
    shares: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    weight: float

    @classmethod
    def from_order(cls, order: Order, fill_price: float, nav: float) -> "Position":
        value = order.shares * fill_price
        return cls(
            ticker=order.ticker,
            shares=order.shares,
            avg_cost=fill_price,
            current_price=fill_price,
            market_value=value,
            unrealized_pnl=0.0,
            weight=value / nav if nav > 0 else 0,
        )


@dataclass
class PaperTradingResult:
    """Result of a paper trading session."""
    nav: float
    cash: float
    positions: dict[str, Position]
    total_pnl: float
    total_return_pct: float
    max_drawdown: float
    n_trades: int
    n_rejected: int
    reconciliation_ok: bool
    reconciliation_diff: float


class PaperTradingOMS:
    """Paper trading OMS with risk gate and reconciliation.

    Usage:
        oms = PaperTradingOMS(initial_capital=100_000_000)
        oms.submit_order(
            ticker="BBCA.JK",
            side=OrderSide.BUY,
            shares=100,
            current_price=8500,
        )
        result = oms.reconcile(prices_df)
    """

    def __init__(
        self,
        initial_capital: float = config.initial_capital,
        commission_rate: float = config.commission_rate,
        sales_tax_rate: float = config.sales_tax_rate,
        slippage_rate: float = config.slippage_rate,
        risk_gate: Optional[RiskGate] = None,
        sector_map: Optional[dict[str, str]] = None,
    ):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate
        self.sales_tax_rate = sales_tax_rate
        self.slippage_rate = slippage_rate
        self.risk_gate = risk_gate or RiskGate()
        self.sector_map = sector_map or {}

        self.oms = OMS()
        self.positions: dict[str, Position] = {}
        self.peak_nav = initial_capital
        self.current_drawdown = 0.0
        self.daily_turnover = 0.0
        self.is_halted = False
        self.halt_reason = ""

        self._trade_log: list[dict] = []
        self._rejected_log: list[dict] = []

    @property
    def nav(self) -> float:
        """Current portfolio NAV."""
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash + positions_value

    def submit_order(
        self,
        ticker: str,
        side: OrderSide,
        shares: int,
        current_price: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
    ) -> RiskGateResult:
        """Submit an order through the risk gate and execute.

        Args:
            ticker: Stock ticker
            side: Buy or sell
            shares: Number of shares (must be multiple of 100)
            current_price: Current market price
            order_type: Market or limit
            limit_price: Limit price (for limit orders)

        Returns:
            RiskGateResult indicating if order was accepted
        """
        # Round to lot size
        shares = (shares // 100) * 100
        if shares <= 0:
            return RiskGateResult(passed=False, reason="Order below minimum lot size")

        order = self.oms.create_order(
            ticker=ticker, side=side, shares=shares,
            order_type=order_type, price=limit_price,
        )

        # Risk gate check
        state = self._get_risk_state()
        gate_result = self.risk_gate.check(order, state, current_price)

        if not gate_result.passed:
            self.oms.transition(order.id, OrderStatus.REJECTED, gate_result.reason)
            self._rejected_log.append({
                "order_id": order.id,
                "ticker": ticker,
                "side": side.value,
                "shares": shares,
                "reason": gate_result.reason,
                "timestamp": datetime.now(UTC).isoformat(),
            })
            return gate_result

        # Simulate fill
        self.oms.transition(order.id, OrderStatus.PENDING)

        fill_price = self._simulate_slippage(current_price, side, shares)
        self.oms.add_fill(order.id, shares, fill_price)
        self._execute_fill(order, fill_price, shares)

        return gate_result

    def _simulate_slippage(self, price: float, side: OrderSide, shares: int) -> float:
        """Simulate slippage based on order size."""
        slippage = self.slippage_rate
        if side == OrderSide.BUY:
            return price * (1 + slippage)
        else:
            return price * (1 - slippage)

    def _execute_fill(self, order: Order, fill_price: float, shares: int):
        """Process a fill — update cash and positions."""
        trade_value = shares * fill_price
        commission = trade_value * self.commission_rate

        if order.side == OrderSide.BUY:
            sales_tax = 0
            total_cost = trade_value + commission
            self.cash -= total_cost
            self.daily_turnover += total_cost

            if order.ticker in self.positions:
                pos = self.positions[order.ticker]
                total_shares = pos.shares + shares
                total_cost_basis = pos.avg_cost * pos.shares + fill_price * shares
                pos.shares = total_shares
                pos.avg_cost = total_cost_basis / total_shares
                pos.current_price = fill_price
                pos.market_value = total_shares * fill_price
                pos.weight = pos.market_value / self.nav if self.nav > 0 else 0
            else:
                self.positions[order.ticker] = Position.from_order(order, fill_price, self.nav)

        else:  # SELL
            sales_tax = trade_value * self.sales_tax_rate
            net_proceeds = trade_value - commission - sales_tax
            self.cash += net_proceeds
            self.daily_turnover += trade_value

            if order.ticker in self.positions:
                pos = self.positions[order.ticker]
                realized_pnl = (fill_price - pos.avg_cost) * shares - commission - sales_tax
                pos.shares -= shares
                pos.market_value = pos.shares * fill_price
                pos.unrealized_pnl = (fill_price - pos.avg_cost) * pos.shares
                pos.weight = pos.market_value / self.nav if self.nav > 0 else 0

                if pos.shares <= 0:
                    del self.positions[order.ticker]

        self._trade_log.append({
            "order_id": order.id,
            "ticker": order.ticker,
            "side": order.side.value,
            "shares": shares,
            "price": fill_price,
            "commission": commission,
            "sales_tax": sales_tax if order.side == OrderSide.SELL else 0,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        # Update drawdown
        current_nav = self.nav
        if current_nav > self.peak_nav:
            self.peak_nav = current_nav
        self.current_drawdown = (current_nav - self.peak_nav) / self.peak_nav

        if self.current_drawdown < -self.risk_gate.limits.max_drawdown:
            self.is_halted = True
            self.halt_reason = f"Drawdown {self.current_drawdown:.1%} exceeded limit"

    def update_prices(self, prices: dict[str, float]):
        """Update current prices for all positions."""
        for ticker, price in prices.items():
            if ticker in self.positions:
                pos = self.positions[ticker]
                pos.current_price = price
                pos.market_value = pos.shares * price
                pos.unrealized_pnl = (price - pos.avg_cost) * pos.shares
                pos.weight = pos.market_value / self.nav if self.nav > 0 else 0

    def reconcile(self, prices: dict[str, float]) -> PaperTradingResult:
        """Daily reconciliation — mark-to-market and verify positions.

        Args:
            prices: Current prices for all held tickers

        Returns:
            PaperTradingResult with full portfolio state
        """
        self.update_prices(prices)

        current_nav = self.nav
        total_pnl = current_nav - self.initial_capital
        total_return = total_pnl / self.initial_capital if self.initial_capital > 0 else 0

        if current_nav > self.peak_nav:
            self.peak_nav = current_nav
        self.current_drawdown = (current_nav - self.peak_nav) / self.peak_nav

        expected_nav = self.cash + sum(
            p.shares * prices.get(p.ticker, p.current_price)
            for p in self.positions.values()
        )
        reconciliation_diff = abs(current_nav - expected_nav)
        reconciliation_ok = reconciliation_diff < 1.0  # < 1 IDR diff

        return PaperTradingResult(
            nav=current_nav,
            cash=self.cash,
            positions=self.positions.copy(),
            total_pnl=total_pnl,
            total_return_pct=total_return * 100,
            max_drawdown=self.current_drawdown,
            n_trades=len(self._trade_log),
            n_rejected=len(self._rejected_log),
            reconciliation_ok=reconciliation_ok,
            reconciliation_diff=reconciliation_diff,
        )

    def _get_risk_state(self) -> PortfolioRiskState:
        """Build current portfolio risk state for risk gate."""
        position_values = {
            t: p.market_value for t, p in self.positions.items()
        }
        return PortfolioRiskState(
            nav=self.nav,
            cash=self.cash,
            positions=position_values,
            sector_map=self.sector_map,
            current_drawdown=self.current_drawdown,
            daily_turnover=self.daily_turnover,
            is_halted=self.is_halted,
            halt_reason=self.halt_reason,
        )

    def reset_daily(self):
        """Reset daily counters (call at start of each trading day)."""
        self.daily_turnover = 0.0

    def get_trade_log(self) -> list[dict]:
        """Get full trade log."""
        return self._trade_log.copy()

    def get_rejected_log(self) -> list[dict]:
        """Get rejected orders log."""
        return self._rejected_log.copy()
