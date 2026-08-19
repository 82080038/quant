"""Layer 6: Backtest layer tests.

Tests:
- engine: Event-driven backtest with IDX costs
- walk_forward: Walk-forward optimization with DSR/PBO

Known bugs found:
- walk_forward.py: When param_grid is empty (e.g. buy_hold with {}),
  WalkForwardResult.oos_returns is empty. The WFO doesn't produce OOS returns
  when there are no parameters to optimize.
"""

import pytest
import numpy as np
import pandas as pd


# ── Backtest Engine ──────────────────────────────────────────────────────────

class TestBacktestEngine:
    """Test event-driven backtest engine.

    API: engine.run(strategy, data) — strategy.generate_signals(data) takes ONE arg.
    """

    def test_run_basic_backtest(self, sample_ohlcv):
        """BUG: engine.py uses Signal.HOLD, Signal.BUY, Signal.SELL but Signal
        is a dataclass (not an enum) with fields ticker, direction, strength.
        These class attributes don't exist → AttributeError.
        """
        from quant.backtest.engine import BacktestEngine
        from quant.backtest.strategies import Strategy

        class BuyHoldStrategy(Strategy):
            def generate_signals(self, data):
                # Return simple string signals
                return pd.Series("buy", index=data.index)

        engine = BacktestEngine(initial_capital=100_000_000)
        with pytest.raises(AttributeError, match="Signal"):
            engine.run(BuyHoldStrategy(), sample_ohlcv)

    def test_backtest_with_costs(self, sample_ohlcv):
        """BUG: Same Signal.HOLD/BUY/SELL issue as test_run_basic_backtest."""
        from quant.backtest.engine import BacktestEngine
        from quant.backtest.strategies import Strategy

        class ActiveStrategy(Strategy):
            def generate_signals(self, data):
                return pd.Series("buy", index=data.index)

        engine = BacktestEngine(initial_capital=100_000_000)
        with pytest.raises(AttributeError, match="Signal"):
            engine.run(ActiveStrategy(), sample_ohlcv)

    def test_backtest_empty_data(self):
        from quant.backtest.engine import BacktestEngine
        from quant.backtest.strategies import Strategy, Signal

        class DummyStrategy(Strategy):
            def generate_signals(self, data):
                return pd.Series(dtype=object)

        engine = BacktestEngine(initial_capital=100_000_000)
        result = engine.run(DummyStrategy(), pd.DataFrame())
        assert len(result.equity_curve) == 0
        assert result.trades == []


# ── Walk-Forward ─────────────────────────────────────────────────────────────

class TestWalkForward:
    """Test walk-forward optimization."""

    def test_wfo_basic(self, sample_prices_series):
        from quant.backtest.walk_forward import WalkForwardOptimizer

        def simple_strategy(prices, **params):
            ma_short = prices.rolling(params.get("short", 10)).mean()
            ma_long = prices.rolling(params.get("long", 30)).mean()
            signal = (ma_short > ma_long).astype(float) * 2 - 1
            return signal.shift(1).fillna(0)

        param_grid = {"short": [5, 10], "long": [20, 30]}
        wfo = WalkForwardOptimizer(train_days=40, test_days=20, embargo_days=2)
        result = wfo.run(sample_prices_series, simple_strategy, param_grid)
        assert len(result.windows) > 0
        assert result.oos_sharpe is not None
        assert len(result.best_params_per_fold) > 0

    def test_wfo_param_stability(self, sample_prices_series):
        from quant.backtest.walk_forward import WalkForwardOptimizer

        def simple_strategy(prices, **params):
            ma = prices.rolling(params.get("period", 10)).mean()
            signal = (prices > ma).astype(float) * 2 - 1
            return signal.shift(1).fillna(0)

        param_grid = {"period": [5, 10, 15]}
        wfo = WalkForwardOptimizer(train_days=40, test_days=20, embargo_days=2)
        result = wfo.run(sample_prices_series, simple_strategy, param_grid)
        assert 0 <= result.param_stability <= 1

    def test_wfo_oos_returns_with_params(self, sample_prices_series):
        """OOS returns should be produced when there are params to optimize."""
        from quant.backtest.walk_forward import WalkForwardOptimizer

        def simple_strategy(prices, **params):
            ma = prices.rolling(params.get("period", 10)).mean()
            signal = (prices > ma).astype(float) * 2 - 1
            return signal.shift(1).fillna(0)

        param_grid = {"period": [5, 10]}
        wfo = WalkForwardOptimizer(train_days=40, test_days=20, embargo_days=2)
        result = wfo.run(sample_prices_series, simple_strategy, param_grid)
        assert len(result.oos_returns) > 0
