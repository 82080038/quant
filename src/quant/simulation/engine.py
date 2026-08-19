"""Simulation engine — realistic synthetic market data without look-ahead bias.

Generates OHLCV data for IDX stocks using:
  - Geometric Brownian Motion (GBM) as the base price process
  - Regime shifts (bull/bear/sideways) with Markov chain transitions
  - Jump diffusion (fat tails) for realistic crash/rally events
  - Volume correlated with absolute returns + intraday U-shape
  - Sector correlation structure (e.g., banking stocks move together)

Key anti-look-ahead-bias design:
  - Data is generated strictly chronologically, one tick at a time
  - Each tick's parameters (volatility, drift) depend ONLY on the current
    regime state, which is determined by PAST data — never future
  - No fitting to future prices; the process is forward-simulated
  - The simulation clock advances at real-time speed (1 tick = N seconds
    of simulated market time), so the frontend sees data arriving as it
    would in live trading

Usage:
    from quant.simulation.engine import SimulationEngine
    engine = SimulationEngine(n_ticks=5000, speed=1.0)
    engine.start()  # starts async tick generator
    tick = engine.get_latest_tick("^JKSE")  # latest IHSG tick
    bar = engine.get_latest_bar("BBCA.JK")  # latest OHLCV bar
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────

# 20 focus stocks for IDX (liquid, representative)
FOCUS_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK",
    "GOTO.JK", "PBID.JK", "ICBP.JK", "UNVR.JK", "ADRO.JK",
    "ANTM.JK", "MDKA.JK", "INDF.JK", "KLBF.JK", "SMGR.JK",
    "JPFA.JK", "CTRA.JK", "AKRA.JK", "TPIA.JK", "EMTK.JK",
]

SECTOR_MAP = {
    "BBCA.JK": "Finance", "BBRI.JK": "Finance", "BMRI.JK": "Finance",
    "TLKM.JK": "Telecom", "ASII.JK": "Automotive",
    "GOTO.JK": "Technology", "PBID.JK": "Infrastructure",
    "ICBP.JK": "Consumer", "UNVR.JK": "Consumer",
    "ADRO.JK": "Mining", "ANTM.JK": "Mining", "MDKA.JK": "Mining",
    "INDF.JK": "Consumer", "KLBF.JK": "Healthcare",
    "SMGR.JK": "Basic Materials", "JPFA.JK": "Consumer",
    "CTRA.JK": "Property", "AKRA.JK": "Energy",
    "TPIA.JK": "Energy", "EMTK.JK": "Media",
}

# Regime transition matrix (Markov chain)
# States: 0=bull, 1=bear, 2=sideways
# P[next | current] — rows sum to 1
REGIME_TRANSITION = np.array([
    [0.97, 0.02, 0.01],  # bull → bull/bear/sideways
    [0.03, 0.95, 0.02],  # bear → bull/bear/sideways
    [0.05, 0.03, 0.92],  # sideways → bull/bear/sideways
])

# Per-regime parameters: (annual_drift, annual_vol)
REGIME_PARAMS = {
    0: (0.15, 0.18),   # bull: positive drift, moderate vol
    1: (-0.12, 0.28),  # bear: negative drift, high vol
    2: (0.01, 0.12),   # sideways: near-zero drift, low vol
}

# Sector betas (relative to market)
SECTOR_BETA = {
    "Finance": 1.15, "Telecom": 0.85, "Automotive": 1.20,
    "Technology": 1.40, "Infrastructure": 1.05,
    "Consumer": 0.90, "Mining": 1.35, "Healthcare": 0.75,
    "Basic Materials": 1.10, "Property": 1.25,
    "Energy": 1.30, "Media": 1.15,
}

# Initial prices (approximate real-world values in IDR)
INITIAL_PRICES = {
    "BBCA.JK": 9800, "BBRI.JK": 5200, "BMRI.JK": 6800,
    "TLKM.JK": 3200, "ASII.JK": 5100, "GOTO.JK": 65,
    "PBID.JK": 1450, "ICBP.JK": 12000, "UNVR.JK": 4200,
    "ADRO.JK": 2850, "ANTM.JK": 1850, "MDKA.JK": 3200,
    "INDF.JK": 7600, "KLBF.JK": 1650, "SMGR.JK": 5800,
    "JPFA.JK": 7200, "CTRA.JK": 1100, "AKRA.JK": 1800,
    "TPIA.JK": 350, "EMTK.JK": 520,
}

# Trading hours: 09:00 - 15:50 WIB
TRADING_START_MIN = 9 * 60   # 540
TRADING_END_MIN = 15 * 60 + 50  # 950
TRADING_MINUTES = TRADING_END_MIN - TRADING_START_MIN  # 410

# Tick interval in simulated seconds (1 tick = 15 seconds of market time)
TICK_SECONDS = 15
# Number of ticks per trading day
TICKS_PER_DAY = TRADING_MINUTES * 60 // TICK_SECONDS  # ~1640


@dataclass
class Tick:
    """A single price tick."""
    ticker: str
    timestamp: str  # ISO format
    price: float
    volume: int
    bid: float
    ask: float
    change_pct: float


@dataclass
class OHLCVBar:
    """A 1-minute OHLCV bar."""
    ticker: str
    date: str
    minute_of_day: int
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class SimState:
    """Internal simulation state for one ticker."""
    ticker: str
    price: float
    prev_close: float
    day_open: float
    day_high: float
    day_low: float
    day_volume: int
    sector: str
    beta: float
    bars: list[OHLCVBar] = field(default_factory=list)
    current_bar: OHLCVBar | None = None
    bar_minute: int = -1


class SimulationEngine:
    """Realistic market simulation engine without look-ahead bias.

    Generates synthetic OHLCV + tick data for IDX stocks using:
      - GBM with regime-dependent drift/volatility
      - Markov chain regime transitions (bull/bear/sideways)
      - Jump diffusion for fat tails
      - Sector correlation via beta loading on market factor
      - Intradaday U-shaped volume profile

    The simulation advances a virtual clock at configurable speed.
    Each tick is generated using ONLY past information (current regime,
    past prices) — no future data is used.

    Args:
        n_ticks: Total number of ticks to generate (default 5000)
        speed: Simulation speed multiplier (1.0 = real-time, 10.0 = 10x)
        seed: Random seed for reproducibility (default 42)
        start_date: Starting date for the simulation (default: today)
    """

    def __init__(
        self,
        n_ticks: int = 5000,
        speed: float = 10.0,
        seed: int = 42,
        start_date: datetime | None = None,
    ):
        self.n_ticks = n_ticks
        self.speed = speed
        self.rng = np.random.default_rng(seed)
        self.random = random.Random(seed)

        self.start_date = start_date or datetime.now()
        self.current_tick = 0
        self.current_regime = 0  # start in bull
        self.sim_time = self.start_date.replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        self.trading_day = 0

        # Market factor (IHSG) state
        self.ihsg_price = 7800.0
        self.ihsg_prev_close = 7800.0
        self.ihsg_open = 7800.0
        self.ihsg_high = 7800.0
        self.ihsg_low = 7800.0
        self.ihsg_volume = 0

        # Per-ticker state
        self.states: dict[str, SimState] = {}
        for ticker in FOCUS_TICKERS:
            price = INITIAL_PRICES.get(ticker, 1000.0)
            sector = SECTOR_MAP.get(ticker, "Other")
            self.states[ticker] = SimState(
                ticker=ticker,
                price=price,
                prev_close=price,
                day_open=price,
                day_high=price,
                day_low=price,
                day_volume=0,
                sector=sector,
                beta=SECTOR_BETA.get(sector, 1.0),
            )

        # Latest data caches (for API reads)
        self.latest_ticks: dict[str, Tick] = {}
        self.latest_bars: dict[str, OHLCVBar] = {}
        self.tick_history: list[Tick] = []
        self.ihsg_history: list[dict] = []

        # Running flag
        self._running = False
        self._task: asyncio.Task | None = None

    def _advance_regime(self) -> None:
        """Advance the regime state using Markov transition matrix.

        Called once per trading day — NOT per tick — to avoid
        high-frequency regime flipping.
        """
        probs = REGIME_TRANSITION[self.current_regime]
        self.current_regime = int(self.rng.choice(3, p=probs))
        regime_names = {0: "bull", 1: "bear", 2: "sideways"}
        logger.info("Regime shift to %s on day %d", regime_names[self.current_regime], self.trading_day)

    def _intraday_volume_factor(self, minute_of_day: int) -> float:
        """U-shaped intraday volume profile.

        Higher volume at open and close, lower at midday.
        Normalized to [0.3, 1.0].
        """
        t = (minute_of_day - TRADING_START_MIN) / TRADING_MINUTES
        if t < 0 or t > 1:
            return 0.3
        # U-shape: 1.0 at edges, 0.3 at center
        return 0.3 + 0.7 * (2 * abs(t - 0.5)) ** 1.5

    def _generate_tick(self) -> list[Tick]:
        """Generate one tick for all tickers + IHSG.

        Uses GBM with regime-dependent parameters:
          dS = S * (mu * dt + sigma * dW) + jump_component

        Where:
          mu = regime_drift + beta * (market_drift - risk_free)
          sigma = regime_vol * sqrt(beta)
          dW = standard normal * sqrt(dt)
          jump = Poisson(lambda) * lognormal shock

        All parameters use ONLY current/past state — no look-ahead.
        """
        dt = TICK_SECONDS / (252 * TRADING_MINUTES * 60)  # fraction of year
        regime_drift, regime_vol = REGIME_PARAMS[self.current_regime]

        # Market factor (IHSG) — drives all stocks via beta
        market_dW = self.rng.standard_normal()
        market_ret = (
            regime_drift * dt
            + regime_vol * math.sqrt(dt) * market_dW
        )

        # Jump component (Poisson, lambda=0.003 per tick — rare events)
        jump_lambda = 0.003
        if self.rng.random() < jump_lambda:
            market_ret += self.rng.normal(0, 0.005)  # ±0.5% jump

        self.ihsg_price *= (1 + market_ret)
        self.ihsg_high = max(self.ihsg_high, self.ihsg_price)
        self.ihsg_low = min(self.ihsg_low, self.ihsg_price)

        minute_of_day = self.sim_time.hour * 60 + self.sim_time.minute
        vol_factor = self._intraday_volume_factor(minute_of_day)
        ihsg_tick_vol = int(self.rng.poisson(5000) * vol_factor)
        self.ihsg_volume += ihsg_tick_vol

        ihsg_change = ((self.ihsg_price - self.ihsg_prev_close) / self.ihsg_prev_close) * 100

        ihsg_tick = Tick(
            ticker="^JKSE",
            timestamp=self.sim_time.isoformat(),
            price=round(self.ihsg_price, 2),
            volume=ihsg_tick_vol,
            bid=round(self.ihsg_price - 0.5, 2),
            ask=round(self.ihsg_price + 0.5, 2),
            change_pct=round(ihsg_change, 2),
        )
        self.latest_ticks["^JKSE"] = ihsg_tick
        self.tick_history.append(ihsg_tick)
        self.ihsg_history.append({
            "t": self.sim_time.isoformat(),
            "p": round(self.ihsg_price, 2),
            "v": ihsg_tick_vol,
        })

        ticks = [ihsg_tick]

        # Per-stock ticks
        for ticker, state in self.states.items():
            # Idiosyncratic component
            idio_dW = self.rng.standard_normal()
            idio_vol = regime_vol * 0.6  # 60% idiosyncratic, 40% market

            # Stock return = market component (via beta) + idiosyncratic
            stock_ret = (
                state.beta * market_ret  # market factor loading
                + idio_vol * math.sqrt(dt) * idio_dW * 0.4  # idiosyncratic
            )

            # Jump component per stock (rare, small)
            if self.rng.random() < jump_lambda * 0.3:
                stock_ret += self.rng.normal(0, 0.005)  # ±0.5% jump

            state.price *= (1 + stock_ret)
            state.price = max(state.price, 1.0)  # floor at 1 IDR

            state.day_high = max(state.day_high, state.price)
            state.day_low = min(state.day_low, state.price)

            tick_vol = int(self.rng.poisson(2000) * vol_factor * state.beta)
            state.day_volume += tick_vol

            change_pct = ((state.price - state.prev_close) / state.prev_close) * 100

            spread = max(1.0, state.price * 0.0005)  # 0.05% spread

            tick = Tick(
                ticker=ticker,
                timestamp=self.sim_time.isoformat(),
                price=round(state.price, 2),
                volume=tick_vol,
                bid=round(state.price - spread, 2),
                ask=round(state.price + spread, 2),
                change_pct=round(change_pct, 2),
            )
            self.latest_ticks[ticker] = tick
            ticks.append(tick)

            # Build 1-minute bars
            if state.bar_minute != minute_of_day:
                # Close previous bar
                if state.current_bar:
                    state.current_bar.close = round(state.price, 2)
                    state.bars.append(state.current_bar)
                    self.latest_bars[ticker] = state.current_bar

                # Open new bar
                state.current_bar = OHLCVBar(
                    ticker=ticker,
                    date=self.sim_time.strftime("%Y-%m-%d"),
                    minute_of_day=minute_of_day,
                    open=round(state.price, 2),
                    high=round(state.price, 2),
                    low=round(state.price, 2),
                    close=round(state.price, 2),
                    volume=tick_vol,
                )
                state.bar_minute = minute_of_day
            else:
                # Update current bar
                if state.current_bar:
                    state.current_bar.high = max(state.current_bar.high, round(state.price, 2))
                    state.current_bar.low = min(state.current_bar.low, round(state.price, 2))
                    state.current_bar.close = round(state.price, 2)
                    state.current_bar.volume += tick_vol

        return ticks

    def _advance_time(self) -> None:
        """Advance the simulation clock by one tick interval."""
        self.sim_time += timedelta(seconds=TICK_SECONDS)
        self.current_tick += 1

        # Check for new trading day
        minute_of_day = self.sim_time.hour * 60 + self.sim_time.minute
        if minute_of_day >= TRADING_END_MIN or self.sim_time.weekday() >= 5:
            # Close current day
            self.ihsg_prev_close = self.ihsg_price
            for state in self.states.values():
                state.prev_close = state.price
                state.day_open = state.price
                state.day_high = state.price
                state.day_low = state.price
                state.day_volume = 0
                # Close last bar
                if state.current_bar:
                    state.current_bar.close = round(state.price, 2)
                    state.bars.append(state.current_bar)
                    self.latest_bars[state.ticker] = state.current_bar
                    state.current_bar = None

            # Advance to next trading day (skip weekends)
            self.sim_time += timedelta(days=1)
            while self.sim_time.weekday() >= 5:
                self.sim_time += timedelta(days=1)
            self.sim_time = self.sim_time.replace(hour=9, minute=0, second=0, microsecond=0)

            self.trading_day += 1
            self._advance_regime()

    async def _run_loop(self) -> None:
        """Main async simulation loop."""
        logger.info("Simulation started: %d ticks, speed=%.1fx", self.n_ticks, self.speed)

        delay = TICK_SECONDS / self.speed if self.speed > 0 else 0

        while self._running and self.current_tick < self.n_ticks:
            ticks = self._generate_tick()
            self._advance_time()

            if delay > 0:
                await asyncio.sleep(delay)

        self._running = False
        logger.info("Simulation finished after %d ticks", self.current_tick)

    def start(self) -> asyncio.Task:
        """Start the simulation as an async task."""
        if self._task and not self._task.done():
            return self._task
        self._running = True  # set immediately so status reflects
        self._task = asyncio.create_task(self._run_loop())
        return self._task

    def stop(self) -> None:
        """Stop the simulation."""
        self._running = False
        if self._task:
            self._task.cancel()

    # ── Data accessors (for API endpoints) ──────────────────────────────

    def get_latest_tick(self, ticker: str) -> dict | None:
        """Get the latest tick for a ticker."""
        t = self.latest_ticks.get(ticker)
        if not t:
            return None
        return {
            "ticker": t.ticker, "timestamp": t.timestamp,
            "price": t.price, "volume": t.volume,
            "bid": t.bid, "ask": t.ask, "change_pct": t.change_pct,
        }

    def get_all_latest_ticks(self) -> list[dict]:
        """Get latest ticks for all tickers."""
        return [self.get_latest_tick(t) for t in self.latest_ticks if self.get_latest_tick(t)]

    def get_movers(self, limit: int = 10) -> dict:
        """Get top gainers and losers from latest ticks."""
        ticks = []
        for ticker in FOCUS_TICKERS:
            t = self.latest_ticks.get(ticker)
            if t:
                ticks.append({
                    "ticker": t.ticker,
                    "close": t.price,
                    "prev_close": self.states[ticker].prev_close,
                    "pct_change": t.change_pct,
                })
        gainers = sorted(ticks, key=lambda x: x["pct_change"], reverse=True)[:limit]
        losers = sorted(ticks, key=lambda x: x["pct_change"])[:limit]
        return {
            "gainers": gainers,
            "losers": losers,
            "as_of": self.sim_time.isoformat(),
            "count": len(ticks),
        }

    def get_ihsg(self) -> dict:
        """Get IHSG (composite index) data."""
        t = self.latest_ticks.get("^JKSE")
        return {
            "ticker": "^JKSE",
            "price": t.price if t else self.ihsg_price,
            "change": round(self.ihsg_price - self.ihsg_prev_close, 2),
            "change_pct": round(
                ((self.ihsg_price - self.ihsg_prev_close) / self.ihsg_prev_close) * 100, 2
            ) if self.ihsg_prev_close else 0,
            "open": round(self.ihsg_open, 2),
            "high": round(self.ihsg_high, 2),
            "low": round(self.ihsg_low, 2),
            "volume": self.ihsg_volume,
            "timestamp": self.sim_time.isoformat(),
            "history": self.ihsg_history[-60:],  # last 60 ticks
        }

    def get_portfolio(self) -> dict:
        """Get simulated portfolio (paper trading with 3 positions)."""
        positions = {}
        # Simulate 3 open positions
        held = ["BBCA.JK", "BBRI.JK", "TLKM.JK"]
        for ticker in held:
            state = self.states.get(ticker)
            if not state:
                continue
            shares = 1000 if ticker == "BBCA.JK" else 2000 if ticker == "BBRI.JK" else 3000
            avg_cost = state.prev_close * 0.98  # bought slightly below prev close
            market_value = state.price * shares
            unrealized = (state.price - avg_cost) * shares
            weight = market_value / (config_initial_capital())
            positions[ticker] = {
                "shares": shares,
                "avg_cost": round(avg_cost, 2),
                "current_price": round(state.price, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized, 2),
                "weight_pct": round(weight * 100, 2),
            }

        total_nav = config_initial_capital()
        invested = sum(p["market_value"] for p in positions.values())
        cash = total_nav - invested

        # Sector exposure
        sector_exp = {}
        for ticker, p in positions.items():
            sector = SECTOR_MAP.get(ticker, "Other")
            sector_exp[sector] = sector_exp.get(sector, 0) + p["weight_pct"]

        return {
            "total_nav": round(total_nav, 2),
            "cash": round(cash, 2),
            "positions": positions,
            "sector_exposure": sector_exp,
            "market_exposure": {"IDX": round(sum(p["weight_pct"] for p in positions.values()), 2)},
            "largest_position_pct": max((p["weight_pct"] for p in positions.values()), default=0),
            "n_positions": len(positions),
        }

    def get_signals(self) -> list[dict]:
        """Get simulated signal attribution data."""
        signals = []
        for i, ticker in enumerate(FOCUS_TICKERS[:10]):
            state = self.states.get(ticker)
            if not state:
                continue
            change = state.price - state.prev_close
            signal = 1 if change > 0 else -1 if change < 0 else 0
            signals.append({
                "ticker": ticker,
                "signal": signal,
                "signal_label": "BUY" if signal > 0 else "SELL" if signal < 0 else "HOLD",
                "close_price": round(state.price, 2),
                "change_pct": round(
                    ((state.price - state.prev_close) / state.prev_close) * 100, 2
                ) if state.prev_close else 0,
                "sector": state.sector,
                "weight": round(1 / 10, 4),
            })
        return signals

    def get_sim_status(self) -> dict:
        """Get simulation status."""
        regime_names = {0: "bull", 1: "bear", 2: "sideways"}
        return {
            "running": self._running,
            "current_tick": self.current_tick,
            "total_ticks": self.n_ticks,
            "speed": self.speed,
            "sim_time": self.sim_time.isoformat(),
            "trading_day": self.trading_day,
            "regime": regime_names[self.current_regime],
            "tickers": len(self.states),
        }


def config_initial_capital() -> float:
    """Get initial capital from config (with fallback)."""
    try:
        from quant.core.config import config
        return float(config.initial_capital)
    except Exception:
        return 100_000_000.0


# ── Global singleton ──────────────────────────────────────────────────────

_engine: SimulationEngine | None = None


def get_simulation_engine() -> SimulationEngine | None:
    """Get the global simulation engine instance (or None if not running)."""
    return _engine


def start_simulation(
    n_ticks: int = 5000,
    speed: float = 10.0,
    seed: int = 42,
) -> SimulationEngine:
    """Start the global simulation engine."""
    global _engine
    if _engine and _engine._running:
        return _engine
    _engine = SimulationEngine(n_ticks=n_ticks, speed=speed, seed=seed)
    _engine.start()
    return _engine


def stop_simulation() -> None:
    """Stop the global simulation engine."""
    global _engine
    if _engine:
        _engine.stop()
        _engine = None
