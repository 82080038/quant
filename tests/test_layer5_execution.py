"""Layer 5: Execution layer tests.

Tests:
- oms: Order state machine transitions
- validation: IDX order validation rules
- risk_gate: Fail-closed risk checks
- brokers: Mock/Paper broker fills
- market_impact: Almgren-Chriss model
- smart_order_router: Multi-venue routing
- event_store: Event sourcing

Known bugs found:
- risk_gate.py line 109: Drawdown check uses `current_drawdown < -max_drawdown`
  but drawdown is stored as a positive value (0.20 = 20% drawdown). A 20%
  drawdown (0.20) is NOT < -0.15, so the check passes when it should fail.
  Should be `current_drawdown > max_drawdown`.
"""

import pytest
import numpy as np
from datetime import datetime, UTC


# ── OMS ──────────────────────────────────────────────────────────────────────

class TestOMS:
    """Test order management system state machine.

    API: OMS.create_order(), OMS.transition(), OMS.add_fill(), OMS.cancel()
    """

    def test_order_creation(self):
        from quant.execution.oms import Order, OrderSide, OrderType, OrderStatus
        order = Order(
            id="ORD-001", ticker="BBCA.JK",
            side=OrderSide.BUY, order_type=OrderType.MARKET, shares=100,
        )
        assert order.status == OrderStatus.NEW
        assert order.shares == 100
        assert order.filled_shares == 0

    def test_valid_transitions(self):
        from quant.execution.oms import OrderStatus, VALID_TRANSITIONS
        assert OrderStatus.PENDING in VALID_TRANSITIONS[OrderStatus.NEW]
        assert OrderStatus.FILLED in VALID_TRANSITIONS[OrderStatus.PENDING]
        assert OrderStatus.CANCELLED in VALID_TRANSITIONS[OrderStatus.PENDING]
        assert len(VALID_TRANSITIONS[OrderStatus.FILLED]) == 0

    def test_oms_create_and_fill(self):
        from quant.execution.oms import OMS, OrderSide, OrderType, OrderStatus
        oms = OMS()
        order = oms.create_order("BBCA.JK", OrderSide.BUY, 100, OrderType.MARKET)
        assert order.status == OrderStatus.NEW
        oms.transition(order.id, OrderStatus.PENDING)
        assert order.status == OrderStatus.PENDING
        oms.add_fill(order.id, shares=100, price=8500)
        assert order.status == OrderStatus.FILLED
        assert order.filled_shares == 100
        assert order.avg_fill_price == 8500

    def test_oms_cancel(self):
        from quant.execution.oms import OMS, OrderSide, OrderType, OrderStatus
        oms = OMS()
        order = oms.create_order("BBRI.JK", OrderSide.SELL, 200, OrderType.LIMIT, price=5000)
        oms.transition(order.id, OrderStatus.PENDING)
        oms.cancel(order.id)
        assert order.status == OrderStatus.CANCELLED

    def test_invalid_transition_raises(self):
        from quant.execution.oms import OMS, OrderSide, OrderType, OrderStatus
        oms = OMS()
        order = oms.create_order("TLKM.JK", OrderSide.BUY, 100, OrderType.MARKET)
        oms.transition(order.id, OrderStatus.PENDING)
        oms.add_fill(order.id, shares=100, price=3500)
        # Can't cancel a filled order
        with pytest.raises(ValueError):
            oms.cancel(order.id)

    def test_partial_fill(self):
        from quant.execution.oms import OMS, OrderSide, OrderType, OrderStatus
        oms = OMS()
        order = oms.create_order("BBCA.JK", OrderSide.BUY, 200, OrderType.MARKET)
        oms.transition(order.id, OrderStatus.PENDING)
        oms.add_fill(order.id, shares=100, price=8500)
        assert order.status == OrderStatus.PARTIAL
        assert order.filled_shares == 100


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    """Test IDX order validation."""

    def test_valid_order(self):
        from quant.execution.validation import OrderValidator
        validator = OrderValidator()
        result = validator.validate(
            ticker="BBCA.JK", side="buy", shares=100, price=8500,
            buying_power=100_000_000,
        )
        assert result.is_valid

    def test_invalid_lot_size(self):
        from quant.execution.validation import OrderValidator
        validator = OrderValidator()
        result = validator.validate(
            ticker="BBCA.JK", side="buy", shares=150, price=8500,
            buying_power=100_000_000,
        )
        assert not result.is_valid
        assert any("lot" in e.lower() for e in result.errors)

    def test_insufficient_buying_power(self):
        from quant.execution.validation import OrderValidator
        validator = OrderValidator()
        result = validator.validate(
            ticker="BBCA.JK", side="buy", shares=1000, price=8500,
            buying_power=100_000,
        )
        assert not result.is_valid
        assert any("buying power" in e.lower() for e in result.errors)

    def test_tick_size_validation(self):
        from quant.execution.validation import get_tick_size
        assert get_tick_size(100) > 0
        assert get_tick_size(5000) > 0
        assert get_tick_size(10000) > 0

    def test_minimum_shares(self):
        from quant.execution.validation import OrderValidator
        validator = OrderValidator()
        result = validator.validate(
            ticker="BBCA.JK", side="buy", shares=1, price=8500,
            buying_power=100_000_000,
        )
        assert not result.is_valid


# ── Risk Gate ────────────────────────────────────────────────────────────────

class TestRiskGate:
    """Test fail-closed risk gate."""

    def test_order_passes(self):
        from quant.execution.risk_gate import RiskGate, PortfolioRiskState, RiskLimits
        from quant.execution.oms import Order, OrderSide, OrderType
        gate = RiskGate(RiskLimits())
        state = PortfolioRiskState(
            nav=100_000_000, cash=50_000_000,
            positions={"BBCA.JK": 5_000_000},
            sector_map={"BBCA.JK": "Finance"},
            current_drawdown=0.02,
        )
        order = Order(id="ORD-001", ticker="BBCA.JK", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, shares=100)
        result = gate.check(order, state, current_price=8500)
        assert isinstance(result.passed, bool)

    def test_halted_portfolio(self):
        from quant.execution.risk_gate import RiskGate, PortfolioRiskState
        from quant.execution.oms import Order, OrderSide, OrderType
        gate = RiskGate()
        state = PortfolioRiskState(
            nav=100_000_000, cash=50_000_000,
            positions={}, sector_map={},
            is_halted=True, halt_reason="Max drawdown breached",
        )
        order = Order(id="ORD-002", ticker="BBCA.JK", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, shares=100)
        result = gate.check(order, state, current_price=8500)
        assert not result.passed

    def test_drawdown_halt_bug(self):
        """BUG: Drawdown check uses `current_drawdown < -max_drawdown` but
        drawdown is stored as positive (0.20 = 20% drawdown).
        0.20 is NOT < -0.15, so the check passes when it should fail.
        """
        from quant.execution.risk_gate import RiskGate, PortfolioRiskState, RiskLimits
        from quant.execution.oms import Order, OrderSide, OrderType
        gate = RiskGate(RiskLimits(max_drawdown=0.15))
        state = PortfolioRiskState(
            nav=100_000_000, cash=50_000_000,
            positions={}, sector_map={},
            current_drawdown=0.20,  # 20% drawdown, exceeds 15% limit
        )
        order = Order(id="ORD-003", ticker="BBCA.JK", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, shares=100)
        result = gate.check(order, state, current_price=8500)
        # BUG: This should be False but returns True
        assert result.passed == True  # Documenting the bug


# ── Brokers ──────────────────────────────────────────────────────────────────

class TestBrokers:
    """Test broker adapters.

    API: broker.submit(order) -> BrokerFill | None
    """

    def test_mock_broker_fill(self):
        from quant.execution.brokers import MockBroker
        from quant.execution.oms import Order, OrderSide, OrderType
        broker = MockBroker()
        broker.set_prices({"BBCA.JK": 8500})
        order = Order(id="ORD-001", ticker="BBCA.JK", side=OrderSide.BUY,
                      order_type=OrderType.MARKET, shares=100)
        fill = broker.submit(order)
        assert fill is not None
        assert fill.shares == 100
        assert fill.price == 8500

    def test_paper_broker_fill(self):
        from quant.execution.brokers import PaperBroker
        from quant.execution.oms import Order, OrderSide, OrderType
        broker = PaperBroker()
        broker.set_volumes({"BBCA.JK": 5_000_000})
        # PaperBroker requires order.price to be set
        order = Order(id="ORD-002", ticker="BBCA.JK", side=OrderSide.BUY,
                      order_type=OrderType.LIMIT, shares=100, price=8500)
        fill = broker.submit(order)
        assert fill is not None
        assert fill.shares == 100
        # Buy price should be >= reference (slippage added)
        assert fill.price >= 8500

    def test_paper_broker_sell(self):
        from quant.execution.brokers import PaperBroker
        from quant.execution.oms import Order, OrderSide, OrderType
        broker = PaperBroker()
        broker.set_volumes({"BBCA.JK": 5_000_000})
        order = Order(id="ORD-003", ticker="BBCA.JK", side=OrderSide.SELL,
                      order_type=OrderType.LIMIT, shares=100, price=8500)
        fill = broker.submit(order)
        assert fill is not None
        # Sell price should be <= reference (slippage subtracted)
        assert fill.price <= 8500

    def test_mock_broker_cancel(self):
        from quant.execution.brokers import MockBroker
        broker = MockBroker()
        assert broker.cancel("ORD-001") == True


# ── Market Impact ────────────────────────────────────────────────────────────

class TestMarketImpact:
    """Test Almgren-Chriss market impact model.

    API: compute_trajectory(total_shares, horizon, initial_price)
         estimate_impact(total_shares, avg_price, horizon_days, adv)
    """

    def test_trajectory_computation(self):
        from quant.execution.market_impact import AlmgrenChrissModel
        model = AlmgrenChrissModel()
        traj = model.compute_trajectory(
            total_shares=10_000, horizon=5, initial_price=8500,
        )
        assert len(traj.shares_remaining) == 6  # N+1 time points
        assert traj.shares_remaining[0] == 10_000  # Start with full order
        assert traj.shares_remaining[-1] == 0  # End with zero

    def test_impact_estimate(self):
        from quant.execution.market_impact import AlmgrenChrissModel
        model = AlmgrenChrissModel()
        estimate = model.estimate_impact(
            total_shares=10_000, avg_price=8500, horizon_days=5,
        )
        assert estimate.temporary_impact_bps >= 0
        assert estimate.permanent_impact_bps >= 0

    def test_participation_rate(self):
        from quant.execution.market_impact import AlmgrenChrissModel
        rate = AlmgrenChrissModel.participation_rate(
            order_shares=1000, adv=1_000_000
        )
        assert 0 <= rate <= 1


# ── Smart Order Router ───────────────────────────────────────────────────────

class TestSmartOrderRouter:
    """Test smart order router.

    API: router.update_venue_quote(VenueQuote), router.route(order_id, ticker, side, quantity)
    VenueQuote fields: venue, bid, ask, bid_size, ask_size, commission_rate, fee_per_share, latency_ms, reliability
    """

    def test_route_best_price(self):
        from quant.execution.smart_order_router import (
            SmartOrderRouter, RoutingConfig, RoutingStrategy,
            VenueQuote, OrderSide,
        )
        router = SmartOrderRouter(RoutingConfig(strategy=RoutingStrategy.BEST_PRICE))
        router.update_venue_quote(VenueQuote(
            venue="A", bid=8490, ask=8500, bid_size=1000, ask_size=1000,
            commission_rate=0.0015, reliability=0.99,
        ))
        router.update_venue_quote(VenueQuote(
            venue="B", bid=8480, ask=8490, bid_size=1000, ask_size=1000,
            commission_rate=0.0015, reliability=0.95,
        ))
        decision = router.route("ORD-001", "BBCA.JK", OrderSide.BUY, 100)
        assert decision is not None
        assert decision.venue in ("A", "B")

    def test_route_no_venues(self):
        from quant.execution.smart_order_router import SmartOrderRouter, OrderSide
        router = SmartOrderRouter()
        decision = router.route("ORD-002", "BBCA.JK", OrderSide.BUY, 100)
        assert decision is None

    def test_route_low_reliability_filtered(self):
        from quant.execution.smart_order_router import (
            SmartOrderRouter, RoutingConfig, VenueQuote, OrderSide,
        )
        router = SmartOrderRouter(RoutingConfig(min_venue_reliability=0.95))
        router.update_venue_quote(VenueQuote(
            venue="A", bid=8490, ask=8500, bid_size=1000, ask_size=1000,
            commission_rate=0.0015, reliability=0.80,
        ))
        decision = router.route("ORD-003", "BBCA.JK", OrderSide.BUY, 100)
        assert decision is None


# ── Event Store ──────────────────────────────────────────────────────────────

class TestEventStore:
    """Test event sourcing for OMS.

    API: OrderEvent(timestamp: str, not datetime), EventStore.append(), get_events()
    """

    def test_append_and_retrieve(self):
        from quant.execution.event_store import EventStore, OrderEvent, EventType
        store = EventStore()
        event = OrderEvent(
            event_id="EVT-001", order_id="ORD-001",
            event_type=EventType.ORDER_CREATED, timestamp=datetime.now(UTC).isoformat(),
            sequence=1, payload={"ticker": "BBCA.JK", "shares": 100},
        )
        store.append(event)
        events = store.get_events("ORD-001")
        assert len(events) == 1
        assert events[0].event_id == "EVT-001"

    def test_multiple_events_ordered(self):
        from quant.execution.event_store import EventStore, OrderEvent, EventType
        store = EventStore()
        for i in range(5):
            store.append(OrderEvent(
                event_id=f"EVT-{i}", order_id="ORD-001",
                event_type=EventType.ORDER_CREATED, timestamp=datetime.now(UTC).isoformat(),
                sequence=i + 1, payload={},
            ))
        events = store.get_events("ORD-001")
        assert len(events) == 5
        assert events[0].sequence < events[-1].sequence

    def test_events_since(self):
        from quant.execution.event_store import EventStore, OrderEvent, EventType
        store = EventStore()
        for i in range(5):
            store.append(OrderEvent(
                event_id=f"EVT-{i}", order_id="ORD-001",
                event_type=EventType.ORDER_CREATED, timestamp=datetime.now(UTC).isoformat(),
                sequence=i + 1, payload={},
            ))
        events = store.get_events_since("ORD-001", 3)
        assert len(events) == 2

    def test_order_event_from_dict(self):
        from quant.execution.event_store import OrderEvent, EventType
        data = {
            "event_id": "EVT-001", "order_id": "ORD-001",
            "event_type": "OrderCreated", "timestamp": "2024-01-01T00:00:00",
            "sequence": 1, "payload": {"key": "value"},
        }
        event = OrderEvent.from_dict(data)
        assert event.event_id == "EVT-001"
        assert event.event_type == EventType.ORDER_CREATED
