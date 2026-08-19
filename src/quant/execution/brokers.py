"""Broker adapters (pustaka/40, pustaka/76).

Implements:
- MockBroker: instant fill at requested price (for testing).
- PaperBroker: simulated fill with slippage and IDX costs.
- RealBroker: stub for live broker integration (Sinarmas/BNI).

All brokers implement the BrokerAdapter interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quant.execution.oms import Order, OrderSide


@dataclass
class BrokerFill:
    """Broker fill result."""

    shares: int
    price: float
    commission: float
    sales_tax: float


class BrokerAdapter(Protocol):
    """Broker adapter interface."""

    def submit(self, order: Order) -> BrokerFill | None:
        """Submit an order to the broker.

        Args:
            order: Order to submit.

        Returns:
            BrokerFill if filled, None if rejected/pending.
        """
        ...

    def cancel(self, order_id: str) -> bool:
        """Cancel an order.

        Args:
            order_id: Order ID to cancel.

        Returns:
            True if cancelled successfully.
        """
        ...


class MockBroker:
    """Mock broker — instant fill at requested or last-known price, no costs.

    For market orders (price=None), uses last_prices lookup.
    Call set_prices() before submitting market orders.
    """

    def __init__(self) -> None:
        self.last_prices: dict[str, float] = {}

    def set_prices(self, prices: dict[str, float]) -> None:
        """Set reference prices for market-order fills."""
        self.last_prices.update(prices)

    def submit(self, order: Order) -> BrokerFill | None:
        if order.price is not None:
            fill_price = order.price
        else:
            fill_price = self.last_prices.get(order.ticker, 0.0)
            if fill_price <= 0:
                return None  # No reference price available

        return BrokerFill(
            shares=order.shares,
            price=fill_price,
            commission=0.0,
            sales_tax=0.0,
        )

    def cancel(self, order_id: str) -> bool:
        return True


class PaperBroker:
    """Paper broker — simulated fill with volume-adjusted slippage and IDX costs.

    Slippage model:
    - Base slippage: 0.05% (configurable)
    - Volume impact: if order value > 1% of ADV, slippage scales non-linearly
    - Requires avg_daily_volume dict for volume-aware slippage;
      falls back to flat slippage if not provided
    """

    def __init__(
        self,
        commission_rate: float = 0.0015,
        sales_tax_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        volume_impact_coeff: float = 0.10,
    ) -> None:
        self.commission_rate = commission_rate
        self.sales_tax_rate = sales_tax_rate
        self.slippage_rate = slippage_rate
        self.volume_impact_coeff = volume_impact_coeff
        self.avg_daily_volumes: dict[str, float] = {}

    def set_volumes(self, volumes: dict[str, float]) -> None:
        """Set average daily volumes (shares) for volume-adjusted slippage."""
        self.avg_daily_volumes.update(volumes)

    def _compute_slippage(self, order: Order) -> float:
        """Compute effective slippage rate based on order size vs ADV."""
        base = self.slippage_rate
        adv = self.avg_daily_volumes.get(order.ticker, 0.0)
        if adv > 0 and order.price and order.price > 0:
            order_value = order.shares * order.price
            adv_value = adv * order.price
            participation = order_value / adv_value if adv_value > 0 else 0.0
            volume_impact = participation * self.volume_impact_coeff
            return base + volume_impact
        return base

    def submit(self, order: Order) -> BrokerFill | None:
        if order.price is None or order.price <= 0:
            return None

        slippage = self._compute_slippage(order)

        if order.side == OrderSide.BUY:
            fill_price = order.price * (1 + slippage)
        else:
            fill_price = order.price * (1 - slippage)

        trade_value = order.shares * fill_price
        commission = trade_value * self.commission_rate
        sales_tax = (
            trade_value * self.sales_tax_rate
            if order.side == OrderSide.SELL
            else 0.0
        )

        return BrokerFill(
            shares=order.shares,
            price=round(fill_price, 4),
            commission=round(commission, 2),
            sales_tax=round(sales_tax, 2),
        )

    def cancel(self, order_id: str) -> bool:
        return True


class RealBroker:
    """Real broker stub — placeholder for live integration.

    This should be replaced with actual broker API calls
    (Sinarmas, BNI, etc.) when going live.

    WARNING: This is a non-functional stub. All submit() calls will return None
    (order rejected). Do NOT use in production until properly implemented.
    """

    _STUB_WARNING = (
        "RealBroker is a STUB — submit() will reject all orders. "
        "Implement actual broker API integration before live use."
    )

    def __init__(self, broker_name: str = "sinarmas") -> None:
        import warnings

        warnings.warn(self._STUB_WARNING, stacklevel=2)
        self.broker_name = broker_name
        self._connected = False

    def connect(self, api_key: str, api_secret: str) -> bool:
        """Connect to broker API.

        Args:
            api_key: API key from broker.
            api_secret: API secret from broker.

        Returns:
            True if connected successfully.
        """
        # Stub: always returns False (not implemented)
        self._connected = False
        return False

    def submit(self, order: Order) -> BrokerFill | None:
        if not self._connected:
            return None
        # Real implementation would submit to broker API
        return None

    def cancel(self, order_id: str) -> bool:
        if not self._connected:
            return False
        return False
