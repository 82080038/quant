"""Smart Order Router (SOR) — multi-broker routing (Gap #7).

Routes orders to the best available broker/venue based on:
- Price (best bid/ask across venues)
- Liquidity (available volume at each venue)
- Cost (commission + fees + slippage estimate)
- Latency (faster venues for time-sensitive orders)
- Reliability (venue uptime/success rate)

Routing strategies:
- BEST_PRICE: Route to venue with best price
- LEAST_COST: Route to venue with lowest total cost
- BEST_EXECUTION: Balance price, cost, and reliability (default)
- TWAP: Split order across time for large orders
- VWAP: Track volume-weighted average price

Note: This is for paper/simulation only. Real broker routing
requires broker API integration (excluded from current scope).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class RoutingStrategy(str, Enum):
    """Order routing strategies."""

    BEST_PRICE = "best_price"
    LEAST_COST = "least_cost"
    BEST_EXECUTION = "best_execution"
    TWAP = "twap"
    VWAP = "vwap"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class VenueQuote:
    """A quote from a trading venue."""

    venue: str
    bid: float  # Best bid price
    ask: float  # Best ask price
    bid_size: int  # Available shares at bid
    ask_size: int  # Available shares at ask
    commission_rate: float = 0.0015  # 0.15% commission
    fee_per_share: float = 0.0
    latency_ms: float = 100.0
    reliability: float = 0.99  # 99% success rate
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class RoutingDecision:
    """Result of a routing decision."""

    order_id: str
    venue: str
    strategy: RoutingStrategy
    side: OrderSide
    quantity: int
    expected_price: float
    expected_cost: float
    estimated_commission: float
    estimated_slippage: float
    confidence: float  # 0-1, how confident in execution
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    child_orders: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RoutingConfig:
    """Configuration for the Smart Order Router."""

    strategy: RoutingStrategy = RoutingStrategy.BEST_EXECUTION
    max_venue_ratio: float = 0.5  # Max % of order to single venue
    min_venue_reliability: float = 0.90
    slippage_tolerance_bps: float = 50.0  # 50 bps max slippage
    twap_slices: int = 5  # Number of time slices for TWAP
    twap_interval_minutes: int = 15  # Minutes between TWAP slices


class SmartOrderRouter:
    """Smart Order Router for multi-venue order routing (Gap #7).

    Routes orders to achieve best execution across multiple venues.
    Designed for paper/simulation; real broker routing requires
    broker API integration.
    """

    def __init__(self, config: RoutingConfig | None = None) -> None:
        self.config = config or RoutingConfig()
        self._venues: dict[str, VenueQuote] = {}
        self._decision_counter = 0

    def update_venue_quote(self, quote: VenueQuote) -> None:
        """Update the current quote for a venue.

        Args:
            quote: Latest quote from the venue.
        """
        self._venues[quote.venue] = quote

    def route(
        self,
        order_id: str,
        ticker: str,
        side: OrderSide,
        quantity: int,
    ) -> RoutingDecision | None:
        """Route an order to the best venue.

        Args:
            order_id: Unique order ID.
            ticker: Stock ticker.
            side: Buy or sell.
            quantity: Number of shares.

        Returns:
            RoutingDecision with selected venue and details, or None if no venue available.
        """
        # Filter venues by reliability
        eligible = [
            q for q in self._venues.values()
            if q.reliability >= self.config.min_venue_reliability
        ]

        if not eligible:
            return None

        strategy = self.config.strategy

        if strategy == RoutingStrategy.BEST_PRICE:
            return self._route_best_price(order_id, side, quantity, eligible)
        elif strategy == RoutingStrategy.LEAST_COST:
            return self._route_least_cost(order_id, side, quantity, eligible)
        elif strategy == RoutingStrategy.TWAP:
            return self._route_twap(order_id, side, quantity, eligible)
        elif strategy == RoutingStrategy.VWAP:
            return self._route_vwap(order_id, side, quantity, eligible)
        else:  # BEST_EXECUTION
            return self._route_best_execution(order_id, side, quantity, eligible)

    def _route_best_price(
        self,
        order_id: str,
        side: OrderSide,
        quantity: int,
        venues: list[VenueQuote],
    ) -> RoutingDecision:
        """Route to venue with best price (lowest ask for buy, highest bid for sell)."""
        if side == OrderSide.BUY:
            best = min(venues, key=lambda q: q.ask)
            price = best.ask
        else:
            best = max(venues, key=lambda q: q.bid)
            price = best.bid

        commission = quantity * price * best.commission_rate + quantity * best.fee_per_share
        slippage = self._estimate_slippage(best, quantity, side)

        return RoutingDecision(
            order_id=order_id,
            venue=best.venue,
            strategy=RoutingStrategy.BEST_PRICE,
            side=side,
            quantity=quantity,
            expected_price=price,
            expected_cost=quantity * price + commission + slippage,
            estimated_commission=commission,
            estimated_slippage=slippage,
            confidence=best.reliability,
            reason=f"Best price at {best.venue}: {price}",
        )

    def _route_least_cost(
        self,
        order_id: str,
        side: OrderSide,
        quantity: int,
        venues: list[VenueQuote],
    ) -> RoutingDecision:
        """Route to venue with lowest total cost (price + commission + slippage)."""
        scored = []
        for q in venues:
            price = q.ask if side == OrderSide.BUY else q.bid
            commission = quantity * price * q.commission_rate + quantity * q.fee_per_share
            slippage = self._estimate_slippage(q, quantity, side)
            total_cost = quantity * price + commission + slippage
            scored.append((total_cost, q, price, commission, slippage))

        scored.sort(key=lambda x: x[0])
        total_cost, best, price, commission, slippage = scored[0]

        return RoutingDecision(
            order_id=order_id,
            venue=best.venue,
            strategy=RoutingStrategy.LEAST_COST,
            side=side,
            quantity=quantity,
            expected_price=price,
            expected_cost=total_cost,
            estimated_commission=commission,
            estimated_slippage=slippage,
            confidence=best.reliability,
            reason=f"Lowest total cost at {best.venue}: {total_cost:.2f}",
        )

    def _route_best_execution(
        self,
        order_id: str,
        side: OrderSide,
        quantity: int,
        venues: list[VenueQuote],
    ) -> RoutingDecision:
        """Route to venue with best execution score (balanced price + cost + reliability)."""
        scored = []
        for q in venues:
            price = q.ask if side == OrderSide.BUY else q.bid
            commission = quantity * price * q.commission_rate + quantity * q.fee_per_share
            slippage = self._estimate_slippage(q, quantity, side)
            total_cost = quantity * price + commission + slippage

            # Score: lower cost is better, higher reliability is better, lower latency is better
            # Normalize: cost score = 1 / (1 + cost), reliability score = reliability
            cost_score = 1.0 / (1.0 + total_cost / 1_000_000)  # Scale by 1M
            latency_score = 1.0 / (1.0 + q.latency_ms / 1000)
            exec_score = (
                cost_score * 0.5
                + q.reliability * 0.3
                + latency_score * 0.2
            )
            scored.append((exec_score, q, price, commission, slippage, total_cost))

        scored.sort(key=lambda x: -x[0])  # Highest score first
        score, best, price, commission, slippage, total_cost = scored[0]

        return RoutingDecision(
            order_id=order_id,
            venue=best.venue,
            strategy=RoutingStrategy.BEST_EXECUTION,
            side=side,
            quantity=quantity,
            expected_price=price,
            expected_cost=total_cost,
            estimated_commission=commission,
            estimated_slippage=slippage,
            confidence=score,
            reason=f"Best execution score at {best.venue}: {score:.4f}",
        )

    def _route_twap(
        self,
        order_id: str,
        side: OrderSide,
        quantity: int,
        venues: list[VenueQuote],
    ) -> RoutingDecision:
        """Split order across time slices (TWAP)."""
        slices = self.config.twap_slices
        qty_per_slice = quantity // slices
        remainder = quantity % slices

        # Use best execution for each slice
        child_orders: list[dict[str, Any]] = []
        total_cost = 0.0
        total_commission = 0.0
        total_slippage = 0.0
        weighted_price = 0.0

        for i in range(slices):
            slice_qty = qty_per_slice + (1 if i < remainder else 0)
            if slice_qty == 0:
                continue
            decision = self._route_best_execution(
                f"{order_id}_slice_{i}", side, slice_qty, venues,
            )
            if decision is None:
                continue
            child_orders.append({
                "slice": i,
                "venue": decision.venue,
                "quantity": slice_qty,
                "expected_price": decision.expected_price,
                "delay_minutes": i * self.config.twap_interval_minutes,
            })
            total_cost += decision.expected_cost
            total_commission += decision.estimated_commission
            total_slippage += decision.estimated_slippage
            weighted_price += decision.expected_price * slice_qty

        avg_price = weighted_price / quantity if quantity > 0 else 0

        return RoutingDecision(
            order_id=order_id,
            venue="multi_venue",
            strategy=RoutingStrategy.TWAP,
            side=side,
            quantity=quantity,
            expected_price=avg_price,
            expected_cost=total_cost,
            estimated_commission=total_commission,
            estimated_slippage=total_slippage,
            confidence=0.85,
            reason=f"TWAP split into {slices} slices over {slices * self.config.twap_interval_minutes}min",
            child_orders=child_orders,
        )

    def _route_vwap(
        self,
        order_id: str,
        side: OrderSide,
        quantity: int,
        venues: list[VenueQuote],
    ) -> RoutingDecision:
        """Route based on volume-weighted pricing (simplified)."""
        # Weight venues by available size
        if side == OrderSide.BUY:
            total_size = sum(q.ask_size for q in venues)
            if total_size == 0:
                return self._route_best_execution(order_id, side, quantity, venues)
            weighted_price = sum(q.ask * q.ask_size for q in venues) / total_size
        else:
            total_size = sum(q.bid_size for q in venues)
            if total_size == 0:
                return self._route_best_execution(order_id, side, quantity, venues)
            weighted_price = sum(q.bid * q.bid_size for q in venues) / total_size

        # Find venue with most liquidity
        if side == OrderSide.BUY:
            best = max(venues, key=lambda q: q.ask_size)
        else:
            best = max(venues, key=lambda q: q.bid_size)

        commission = quantity * weighted_price * best.commission_rate
        slippage = self._estimate_slippage(best, quantity, side)

        return RoutingDecision(
            order_id=order_id,
            venue=best.venue,
            strategy=RoutingStrategy.VWAP,
            side=side,
            quantity=quantity,
            expected_price=weighted_price,
            expected_cost=quantity * weighted_price + commission + slippage,
            estimated_commission=commission,
            estimated_slippage=slippage,
            confidence=0.80,
            reason=f"VWAP routing to {best.venue} (highest liquidity)",
        )

    @staticmethod
    def _estimate_slippage(
        quote: VenueQuote, quantity: int, side: OrderSide,
    ) -> float:
        """Estimate slippage based on order size vs available liquidity.

        Simplified model: if order > available size, slippage increases.
        """
        available = quote.ask_size if side == OrderSide.BUY else quote.bid_size
        if available <= 0:
            return quantity * quote.spread * 0.5  # Half spread as slippage

        impact_ratio = max(0, (quantity - available) / max(available, 1))
        base_slippage = quote.spread * 0.5 * quantity
        impact_slippage = impact_ratio * (quote.ask if side == OrderSide.BUY else quote.bid) * 0.001
        return base_slippage + impact_slippage

    @property
    def venues(self) -> list[str]:
        """List of registered venue names."""
        return list(self._venues.keys())
