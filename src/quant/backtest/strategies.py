"""Backtest strategies — minimal stubs."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Signal:
    """Trading signal."""
    ticker: str
    direction: str  # "long" / "short" / "neutral"
    strength: float = 0.0
    confidence: float = 0.0
    rationale: str = ""


class Strategy:
    """Base strategy class."""
    def generate_signals(self, date, universe):
        raise NotImplementedError
