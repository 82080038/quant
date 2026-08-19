"""OMS Event Sourcing (Gap #6).

Implements event sourcing for the Order Management System:
- Event store: append-only log of all order events
- Event replay: reconstruct order state from event history
- Aggregate root: OrderAggregate that applies events to build state

Events:
    OrderCreated      — order was created
    OrderSubmitted    — order submitted to broker
    OrderPending      — order acknowledged by broker
    OrderPartiallyFilled — partial fill received
    OrderFilled       — order fully filled
    OrderCancelled    — order cancelled
    OrderRejected     — order rejected by broker
    OrderModified     — order modified (price/quantity)

This pattern provides:
- Full audit trail of every state change
- Time-travel debugging (replay to any point in time)
- Event-driven architecture for downstream consumers
- Immutable history (events are never deleted/modified)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Order event types for event sourcing."""

    ORDER_CREATED = "OrderCreated"
    ORDER_SUBMITTED = "OrderSubmitted"
    ORDER_PENDING = "OrderPending"
    ORDER_PARTIALLY_FILLED = "OrderPartiallyFilled"
    ORDER_FILLED = "OrderFilled"
    ORDER_CANCELLED = "OrderCancelled"
    ORDER_REJECTED = "OrderRejected"
    ORDER_MODIFIED = "OrderModified"


class OrderStatus(str, Enum):
    """Order status (derived from events)."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class OrderEvent:
    """An immutable order event in the event store."""

    event_id: str
    order_id: str
    event_type: EventType
    timestamp: str
    sequence: int
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "order_id": self.order_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrderEvent:
        return cls(
            event_id=data["event_id"],
            order_id=data["order_id"],
            event_type=EventType(data["event_type"]),
            timestamp=data["timestamp"],
            sequence=data["sequence"],
            payload=data.get("payload", {}),
        )


@dataclass
class OrderState:
    """Reconstructed order state from events (aggregate root state)."""

    order_id: str
    ticker: str = ""
    side: str = ""
    order_type: str = ""
    quantity: float = 0.0
    price: float | None = None
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    status: OrderStatus = OrderStatus.DRAFT
    rejection_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""
    commission: float = 0.0
    sales_tax: float = 0.0
    version: int = 0  # Number of events applied


class EventStore:
    """Append-only event store for OMS (Gap #6).

    Events are stored in order and never modified or deleted.
    Each order has its own event stream identified by order_id.
    """

    def __init__(self) -> None:
        self._events: list[OrderEvent] = []
        self._by_order: dict[str, list[OrderEvent]] = {}
        self._counter = 0

    def append(self, event: OrderEvent) -> None:
        """Append an event to the store.

        Args:
            event: Event to append.
        """
        self._events.append(event)
        if event.order_id not in self._by_order:
            self._by_order[event.order_id] = []
        self._by_order[event.order_id].append(event)

    def get_events(self, order_id: str) -> list[OrderEvent]:
        """Get all events for an order, in sequence order.

        Args:
            order_id: Order ID.

        Returns:
            List of events for the order.
        """
        return list(self._by_order.get(order_id, []))

    def get_all_events(self) -> list[OrderEvent]:
        """Get all events in the store."""
        return list(self._events)

    def get_events_since(
        self, order_id: str, sequence: int,
    ) -> list[OrderEvent]:
        """Get events for an order after a given sequence number.

        Args:
            order_id: Order ID.
            sequence: Minimum sequence (exclusive).

        Returns:
            Events with sequence > given number.
        """
        return [
            e for e in self._by_order.get(order_id, [])
            if e.sequence > sequence
        ]

    def next_sequence(self, order_id: str) -> int:
        """Get the next sequence number for an order.

        Args:
            order_id: Order ID.

        Returns:
            Next sequence number (starts at 1).
        """
        events = self._by_order.get(order_id, [])
        return len(events) + 1

    def next_event_id(self) -> str:
        """Generate a unique event ID."""
        self._counter += 1
        return f"evt_{self._counter:08d}"

    def count(self) -> int:
        """Total number of events in the store."""
        return len(self._events)

    def order_count(self) -> int:
        """Number of unique orders in the store."""
        return len(self._by_order)

    def to_json(self) -> str:
        """Serialize event store to JSON string."""
        return json.dumps([e.to_dict() for e in self._events])

    @classmethod
    def from_json(cls, data: str) -> EventStore:
        """Deserialize event store from JSON string."""
        store = cls()
        events = json.loads(data)
        for e_data in events:
            store.append(OrderEvent.from_dict(e_data))
        return store


class OrderAggregate:
    """Aggregate root for an order (Gap #6).

    Reconstructs order state by replaying events from the event store.
    Provides methods to create new events that transition the order state.
    """

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        self.state = OrderState(order_id=order_id)
        self._uncommitted: list[OrderEvent] = []

    @classmethod
    def from_events(cls, order_id: str, events: list[OrderEvent]) -> OrderAggregate:
        """Reconstruct an order aggregate from its event history.

        Args:
            order_id: Order ID.
            events: List of events for this order.

        Returns:
            OrderAggregate with replayed state.
        """
        agg = cls(order_id)
        for event in events:
            agg._apply(event)
        return agg

    def _apply(self, event: OrderEvent) -> None:
        """Apply an event to update state (internal)."""
        p = event.payload
        if event.event_type == EventType.ORDER_CREATED:
            self.state.ticker = p.get("ticker", "")
            self.state.side = p.get("side", "")
            self.state.order_type = p.get("order_type", "")
            self.state.quantity = p.get("quantity", 0.0)
            self.state.price = p.get("price")
            self.state.status = OrderStatus.DRAFT
            self.state.created_at = event.timestamp
        elif event.event_type == EventType.ORDER_SUBMITTED:
            self.state.status = OrderStatus.SUBMITTED
        elif event.event_type == EventType.ORDER_PENDING:
            self.state.status = OrderStatus.PENDING
        elif event.event_type == EventType.ORDER_PARTIALLY_FILLED:
            fill_qty = p.get("fill_quantity", 0.0)
            fill_price = p.get("fill_price", 0.0)
            self.state.filled_quantity += fill_qty
            self.state.filled_price = fill_price
            self.state.commission += p.get("commission", 0.0)
            self.state.sales_tax += p.get("sales_tax", 0.0)
            self.state.status = OrderStatus.PARTIALLY_FILLED
        elif event.event_type == EventType.ORDER_FILLED:
            fill_qty = p.get("fill_quantity", 0.0)
            fill_price = p.get("fill_price", 0.0)
            self.state.filled_quantity += fill_qty
            self.state.filled_price = fill_price
            self.state.commission += p.get("commission", 0.0)
            self.state.sales_tax += p.get("sales_tax", 0.0)
            self.state.status = OrderStatus.FILLED
        elif event.event_type == EventType.ORDER_CANCELLED:
            self.state.status = OrderStatus.CANCELLED
        elif event.event_type == EventType.ORDER_REJECTED:
            self.state.status = OrderStatus.REJECTED
            self.state.rejection_reason = p.get("reason", "")
        elif event.event_type == EventType.ORDER_MODIFIED:
            if "price" in p:
                self.state.price = p["price"]
            if "quantity" in p:
                self.state.quantity = p["quantity"]

        self.state.updated_at = event.timestamp
        self.state.version += 1

    # ── Command methods (create events) ────────────────────────────────────

    def create(
        self,
        store: EventStore,
        ticker: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
    ) -> OrderEvent:
        """Create a new order (emits OrderCreated event)."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_CREATED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
            payload={
                "ticker": ticker, "side": side,
                "order_type": order_type,
                "quantity": quantity, "price": price,
            },
        )
        store.append(event)
        self._apply(event)
        return event

    def submit(self, store: EventStore) -> OrderEvent:
        """Submit order to broker (emits OrderSubmitted event)."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_SUBMITTED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
        )
        store.append(event)
        self._apply(event)
        return event

    def mark_pending(self, store: EventStore) -> OrderEvent:
        """Mark order as pending (broker acknowledged)."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_PENDING,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
        )
        store.append(event)
        self._apply(event)
        return event

    def partial_fill(
        self,
        store: EventStore,
        fill_quantity: float,
        fill_price: float,
        commission: float = 0.0,
        sales_tax: float = 0.0,
    ) -> OrderEvent:
        """Record a partial fill."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_PARTIALLY_FILLED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
            payload={
                "fill_quantity": fill_quantity,
                "fill_price": fill_price,
                "commission": commission,
                "sales_tax": sales_tax,
            },
        )
        store.append(event)
        self._apply(event)
        return event

    def fill(
        self,
        store: EventStore,
        fill_quantity: float,
        fill_price: float,
        commission: float = 0.0,
        sales_tax: float = 0.0,
    ) -> OrderEvent:
        """Record a full fill."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_FILLED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
            payload={
                "fill_quantity": fill_quantity,
                "fill_price": fill_price,
                "commission": commission,
                "sales_tax": sales_tax,
            },
        )
        store.append(event)
        self._apply(event)
        return event

    def cancel(self, store: EventStore) -> OrderEvent:
        """Cancel the order."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_CANCELLED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
        )
        store.append(event)
        self._apply(event)
        return event

    def reject(self, store: EventStore, reason: str) -> OrderEvent:
        """Reject the order."""
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_REJECTED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
            payload={"reason": reason},
        )
        store.append(event)
        self._apply(event)
        return event

    def modify(
        self,
        store: EventStore,
        price: float | None = None,
        quantity: float | None = None,
    ) -> OrderEvent:
        """Modify the order."""
        payload: dict[str, Any] = {}
        if price is not None:
            payload["price"] = price
        if quantity is not None:
            payload["quantity"] = quantity
        event = OrderEvent(
            event_id=store.next_event_id(),
            order_id=self.order_id,
            event_type=EventType.ORDER_MODIFIED,
            timestamp=datetime.now(UTC).isoformat(),
            sequence=store.next_sequence(self.order_id),
            payload=payload,
        )
        store.append(event)
        self._apply(event)
        return event

    @property
    def is_terminal(self) -> bool:
        """True if order is in a terminal state (FILLED, CANCELLED, REJECTED)."""
        return self.state.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize current state to dict."""
        return {
            "order_id": self.state.order_id,
            "ticker": self.state.ticker,
            "side": self.state.side,
            "order_type": self.state.order_type,
            "quantity": self.state.quantity,
            "price": self.state.price,
            "filled_quantity": self.state.filled_quantity,
            "filled_price": self.state.filled_price,
            "status": self.state.status.value,
            "rejection_reason": self.state.rejection_reason,
            "commission": self.state.commission,
            "sales_tax": self.state.sales_tax,
            "version": self.state.version,
            "created_at": self.state.created_at,
            "updated_at": self.state.updated_at,
        }


def replay_order(order_id: str, store: EventStore) -> OrderAggregate:
    """Replay events to reconstruct an order aggregate (Gap #6).

    Args:
        order_id: Order ID to replay.
        store: Event store containing the order's events.

    Returns:
        OrderAggregate with replayed state.
    """
    events = store.get_events(order_id)
    return OrderAggregate.from_events(order_id, events)


def replay_all_orders(store: EventStore) -> dict[str, OrderAggregate]:
    """Replay all orders from the event store.

    Args:
        store: Event store.

    Returns:
        Dict mapping order_id to OrderAggregate.
    """
    order_ids = {e.order_id for e in store.get_all_events()}
    return {oid: replay_order(oid, store) for oid in order_ids}
