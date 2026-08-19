"""Simulation module — realistic synthetic market data without look-ahead bias.

Generates OHLCV + tick data for IDX stocks using:
  - GBM with regime-dependent drift/volatility (Markov chain)
  - Jump diffusion for fat tails
  - Sector correlation via beta loading
  - Intraday U-shaped volume profile

All data is forward-simulated — no future information is used at any point.
"""

from quant.simulation.engine import (
    SimulationEngine,
    Tick,
    OHLCVBar,
    start_simulation,
    stop_simulation,
    get_simulation_engine,
    FOCUS_TICKERS,
    SECTOR_MAP,
)

__all__ = [
    "SimulationEngine", "Tick", "OHLCVBar",
    "start_simulation", "stop_simulation", "get_simulation_engine",
    "FOCUS_TICKERS", "SECTOR_MAP",
]
