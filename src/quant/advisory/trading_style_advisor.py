"""Trading style advisor stub — will be properly implemented in Phase 2."""

from dataclasses import dataclass


@dataclass
class TradingStyleAdvisor:
    """Minimal stub for trading style advisor."""
    initial_capital: float = 100_000_000
    risk_tolerance: str = "moderate"

    def recommend_style(self, **kwargs):
        return {"style": "swing", "confidence": 0.7}
