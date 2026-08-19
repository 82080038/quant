"""Order Management System (OMS) state machine.

(pustaka/40, pustaka/76)

State transitions:
    NEW → PENDING → PARTIAL → FILLED
    NEW → PENDING → CANCELLED
    NEW → PENDING → REJECTED
    PENDING → PARTIAL → CANCELLED (partial fill then cancel)

IDX order types: market, limit.
IDX session: pre-open, regular, closing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class OrderSide(Enum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    """Order lifecycle status."""

    NEW = "new"
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# Valid state transitions
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.PENDING, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.PENDING: {
        OrderStatus.PARTIAL,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    },
    OrderStatus.PARTIAL: {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


@dataclass
class Order:
    """OMS order with lifecycle tracking."""

    id: str
    ticker: str
    side: OrderSide
    order_type: OrderType
    shares: int
    price: float | None = None
    filled_shares: int = 0
    avg_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.NEW
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    rejection_reason: str | None = None
    fills: list[Fill] = field(default_factory=list)

    @property
    def remaining_shares(self) -> int:
        return self.shares - self.filled_shares


@dataclass
class Fill:
    """A single fill event."""

    shares: int
    price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class OMS:
    """Order Management System with state machine."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._next_id = 1

    def create_order(
        self,
        ticker: str,
        side: OrderSide,
        shares: int,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
    ) -> Order:
        """Create a new order.

        Args:
            ticker: Stock ticker.
            side: Buy or sell.
            shares: Number of shares.
            order_type: Market or limit.
            price: Limit price (required for limit orders).

        Returns:
            The created Order in NEW status.
        """
        order_id = f"ORD-{self._next_id:06d}"
        self._next_id += 1

        order = Order(
            id=order_id,
            ticker=ticker,
            side=side,
            order_type=order_type,
            shares=shares,
            price=price,
        )
        self._orders[order_id] = order
        return order

    def transition(
        self,
        order_id: str,
        new_status: OrderStatus,
        rejection_reason: str | None = None,
    ) -> Order:
        """Transition an order to a new status.

        Args:
            order_id: Order ID.
            new_status: Target status.
            rejection_reason: Reason if rejected.

        Returns:
            Updated Order.

        Raises:
            ValueError: If order not found or transition invalid.
        """
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        if new_status not in VALID_TRANSITIONS.get(order.status, set()):
            raise ValueError(
                f"Invalid transition: {order.status.value} → {new_status.value}",
            )

        order.status = new_status
        order.updated_at = datetime.now(UTC)
        if rejection_reason:
            order.rejection_reason = rejection_reason
        return order

    def add_fill(
        self,
        order_id: str,
        shares: int,
        price: float,
    ) -> Order:
        """Record a fill (partial or full) on an order.

        Args:
            order_id: Order ID.
            shares: Number of shares filled.
            price: Fill price.

        Returns:
            Updated Order.
        """
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        if order.status not in (OrderStatus.PENDING, OrderStatus.PARTIAL):
            raise ValueError(
                f"Cannot fill order in status {order.status.value}",
            )

        fill = Fill(shares=shares, price=price)
        order.fills.append(fill)

        # Update filled shares and avg price
        total_filled_value = (
            order.avg_fill_price * order.filled_shares + shares * price
        )
        order.filled_shares += shares
        order.avg_fill_price = (
            total_filled_value / order.filled_shares
            if order.filled_shares > 0
            else 0.0
        )

        # Transition status
        if order.filled_shares >= order.shares:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL
        order.updated_at = datetime.now(UTC)

        return order

    def cancel(self, order_id: str) -> Order:
        """Cancel an order.

        Args:
            order_id: Order ID.

        Returns:
            Updated Order.
        """
        return self.transition(order_id, OrderStatus.CANCELLED)

    def get_order(self, order_id: str) -> Order | None:
        """Get an order by ID."""
        return self._orders.get(order_id)

    def get_all_orders(self) -> list[Order]:
        """Get all orders."""
        return list(self._orders.values())

    def get_open_orders(self) -> list[Order]:
        """Get all orders that are not in a terminal state."""
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
        return [o for o in self._orders.values() if o.status not in terminal]
