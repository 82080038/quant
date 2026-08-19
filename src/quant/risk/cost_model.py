"""Trading cost model for IDX."""

from dataclasses import dataclass


@dataclass
class TradingCostModel:
    """IDX trading cost model."""
    commission_rate: float = 0.0015  # 0.15% broker commission
    sales_tax_rate: float = 0.001    # 0.1% final income tax (sell only)
    slippage_rate: float = 0.001     # 0.1% slippage
    bid_ask_spread: float = 0.0005   # 0.05% bid-ask spread

    def buy_cost(self, value: float) -> float:
        return value * (self.commission_rate + self.slippage_rate + self.bid_ask_spread)

    def sell_cost(self, value: float) -> float:
        return value * (self.commission_rate + self.sales_tax_rate + self.slippage_rate + self.bid_ask_spread)

    def round_trip_cost(self, value: float) -> float:
        return self.buy_cost(value) + self.sell_cost(value)
