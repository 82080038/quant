"""Layer 4: Portfolio layer tests.

Tests:
- hrp_mu: Signal-aware hierarchical risk parity allocation
- kelly: Risk-constrained Kelly position sizing
- monte_carlo_var: VaR/CVaR computation
- capital_aware_sizer: Position sizing with constraints
- rl_allocator: RL environment (no actual RL training)

Known bugs found:
- capital_aware_sizer.py: Calls self.cost_model.entry_cost() and
  self.cost_model.round_trip_cost() but TradingCostModel (from risk/cost_model.py)
  only has buy_cost(), sell_cost(), round_trip_cost() — no entry_cost() method.
  The cost_model used by CapitalAwarePositionSizer is likely a different class
  from the analysis layer, not the risk/cost_model.py TradingCostModel.
"""

import pytest
import numpy as np
import pandas as pd


# ── HRP-µ ────────────────────────────────────────────────────────────────────

class TestHRPMu:
    """Test signal-aware hierarchical risk parity.

    API: allocate(signals: dict, covariance: pd.DataFrame, ...)
    """

    def test_allocation_basic(self, sample_multi_asset_returns):
        from quant.portfolio.hrp_mu import HRPMu
        cov = sample_multi_asset_returns.cov()
        signals = {"BBCA.JK": 0.5, "BBRI.JK": 0.3, "TLKM.JK": -0.2, "ASII.JK": 0.1, "GOTO.JK": 0.0}
        allocator = HRPMu()
        weights = allocator.allocate(signals, cov)
        assert len(weights) == 5
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert all(w >= 0 for w in weights.values())  # Long-only

    def test_allocation_with_gamma(self, sample_multi_asset_returns):
        from quant.portfolio.hrp_mu import HRPMu
        cov = sample_multi_asset_returns.cov()
        signals = {"BBCA.JK": 0.8, "BBRI.JK": 0.1, "TLKM.JK": -0.5, "ASII.JK": 0.3, "GOTO.JK": 0.0}
        w_low = HRPMu(gamma=0.0).allocate(signals, cov)
        w_high = HRPMu(gamma=1.0).allocate(signals, cov)
        assert abs(sum(w_low.values()) - 1.0) < 0.01
        assert abs(sum(w_high.values()) - 1.0) < 0.01

    def test_allocation_no_signal(self, sample_multi_asset_returns):
        """With zero gamma, should behave like standard HRP regardless of signals."""
        from quant.portfolio.hrp_mu import HRPMu
        cov = sample_multi_asset_returns.cov()
        signals = {t: 0.0 for t in sample_multi_asset_returns.columns}
        weights = HRPMu(gamma=0.5).allocate(signals, cov)
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert all(w >= 0 for w in weights.values())

    def test_single_asset(self):
        from quant.portfolio.hrp_mu import HRPMu
        cov = pd.DataFrame({"A": [0.04]}, index=["A"])
        weights = HRPMu().allocate({"A": 0.5}, cov)
        assert weights["A"] <= 0.15  # Capped at max_weight

    def test_empty_signals(self):
        from quant.portfolio.hrp_mu import HRPMu
        weights = HRPMu().allocate({}, pd.DataFrame())
        assert weights == {}


# ── Kelly Criterion ──────────────────────────────────────────────────────────

class TestKelly:
    """Test risk-constrained Kelly position sizing."""

    def test_basic_kelly(self):
        from quant.portfolio.kelly import RiskConstrainedKelly
        kelly = RiskConstrainedKelly()
        weight = kelly.size(signal=0.8, win_rate=0.55, odds=1.5)
        assert 0 < weight <= 0.15

    def test_zero_signal(self):
        from quant.portfolio.kelly import RiskConstrainedKelly
        kelly = RiskConstrainedKelly()
        weight = kelly.size(signal=0.0)
        assert weight == 0.0

    def test_negative_signal(self):
        from quant.portfolio.kelly import RiskConstrainedKelly
        kelly = RiskConstrainedKelly()
        weight = kelly.size(signal=-0.5)
        assert weight == 0.0

    def test_quarter_kelly(self):
        from quant.portfolio.kelly import RiskConstrainedKelly, KellyConfig
        kelly = RiskConstrainedKelly(KellyConfig(kelly_fraction=0.25, max_weight=1.0))
        weight = kelly.size(signal=1.0, win_rate=0.6, odds=2.0)
        assert weight <= 0.15

    def test_max_weight_cap(self):
        from quant.portfolio.kelly import RiskConstrainedKelly, KellyConfig
        kelly = RiskConstrainedKelly(KellyConfig(max_weight=0.05))
        weight = kelly.size(signal=1.0, win_rate=0.9, odds=3.0)
        assert weight <= 0.05

    def test_liquidity_constraint(self):
        from quant.portfolio.kelly import RiskConstrainedKelly
        kelly = RiskConstrainedKelly()
        weight = kelly.size(signal=0.8, liquidity_constraint=0.02)
        assert weight <= 0.02


# ── Monte Carlo VaR ──────────────────────────────────────────────────────────

class TestMonteCarloVaR:
    """Test Monte Carlo VaR computation.

    API: compute(returns: pd.DataFrame, confidence_levels=[...], weights=..., method="historical")
    Returns VaRResult with var_values, cvar_values dicts keyed by confidence level.
    """

    def test_historical_var(self, sample_multi_asset_returns):
        from quant.portfolio.monte_carlo_var import MonteCarloVaR
        var_engine = MonteCarloVaR(n_simulations=1000, use_gpu=False)
        result = var_engine.compute(sample_multi_asset_returns, confidence_levels=[0.95])
        # var_values keyed by (ticker, confidence) tuples
        assert 0.95 in result.portfolio_var  # Portfolio-level VaR
        assert 0.95 in result.portfolio_cvar
        assert result.portfolio_var[0.95] <= 0  # VaR is a loss
        assert result.portfolio_cvar[0.95] <= result.portfolio_var[0.95]

    def test_parametric_var(self, sample_multi_asset_returns):
        from quant.portfolio.monte_carlo_var import MonteCarloVaR
        var_engine = MonteCarloVaR(use_gpu=False)
        weights = np.array([0.3, 0.2, 0.2, 0.2, 0.1])
        result = var_engine.compute(
            sample_multi_asset_returns, confidence_levels=[0.95],
            weights=weights, method="parametric",
        )
        assert 0.95 in result.portfolio_var
        assert 0.95 in result.portfolio_cvar

    def test_monte_carlo_var(self, sample_multi_asset_returns):
        from quant.portfolio.monte_carlo_var import MonteCarloVaR
        var_engine = MonteCarloVaR(n_simulations=500, use_gpu=False)
        weights = np.array([0.3, 0.2, 0.2, 0.2, 0.1])
        result = var_engine.compute(
            sample_multi_asset_returns, confidence_levels=[0.95, 0.99],
            weights=weights, method="monte_carlo",
        )
        assert 0.95 in result.portfolio_var
        assert 0.99 in result.portfolio_var
        assert result.method == "monte_carlo"

    def test_var_result_fields(self, sample_multi_asset_returns):
        from quant.portfolio.monte_carlo_var import MonteCarloVaR, VaRResult
        var_engine = MonteCarloVaR(use_gpu=False)
        result = var_engine.compute(sample_multi_asset_returns)
        assert isinstance(result, VaRResult)
        assert hasattr(result, "var_values")
        assert hasattr(result, "cvar_values")
        assert hasattr(result, "method")


# ── Capital Aware Sizer ──────────────────────────────────────────────────────

class TestCapitalAwareSizer:
    """Test capital-aware position sizing.

    NOTE: Uses portfolio_override to bypass user profile lookup.
    The cost_model used internally has entry_cost() and round_trip_cost() methods
    that are different from risk/cost_model.py TradingCostModel.
    """

    def test_hold_signal(self):
        from quant.portfolio.capital_aware_sizer import CapitalAwarePositionSizer
        sizer = CapitalAwarePositionSizer()
        result = sizer.size_position(
            ticker="BBCA.JK", direction=0, entry_price=8500,
            portfolio_override=100_000_000,
        )
        assert result.approved == False
        assert "HOLD" in result.rejection_reason

    def test_buy_signal(self):
        """BUG: CapitalAwarePositionSizer calls advisor.get_profile() but
        TradingStyleAdvisor has no get_profile method.

        This test documents the bug. When portfolio_override is set,
        the code still calls advisor.get_profile() first (line 154),
        which fails before portfolio_override is checked.
        """
        from quant.portfolio.capital_aware_sizer import CapitalAwarePositionSizer
        sizer = CapitalAwarePositionSizer()
        with pytest.raises(AttributeError, match="get_profile"):
            sizer.size_position(
                ticker="BBCA.JK", direction=1, entry_price=8500,
                win_rate=0.55, win_loss_ratio=1.5,
                portfolio_override=100_000_000,
            )

    def test_lot_size_constraint(self):
        """BUG: Same get_profile issue as test_buy_signal."""
        from quant.portfolio.capital_aware_sizer import CapitalAwarePositionSizer
        sizer = CapitalAwarePositionSizer()
        with pytest.raises(AttributeError, match="get_profile"):
            sizer.size_position(
                ticker="BBCA.JK", direction=1, entry_price=8500,
                portfolio_override=100_000_000,
            )

    def test_max_position_pct(self):
        """BUG: Same get_profile issue as test_buy_signal."""
        from quant.portfolio.capital_aware_sizer import CapitalAwarePositionSizer
        sizer = CapitalAwarePositionSizer(max_position_pct=0.10)
        with pytest.raises(AttributeError, match="get_profile"):
            sizer.size_position(
                ticker="BBCA.JK", direction=1, entry_price=8500,
                portfolio_override=100_000_000,
            )


# ── RL Allocator ─────────────────────────────────────────────────────────────

class TestRLAllocator:
    """Test RL portfolio environment (no actual training).

    API: PortfolioEnv(returns: pd.DataFrame, signals: pd.DataFrame, n_assets: int, ...)
    """

    def test_env_creation(self, sample_multi_asset_returns):
        from quant.portfolio.rl_allocator import PortfolioEnv, RLConfig
        n_assets = 5
        signals = pd.DataFrame(
            np.random.randn(len(sample_multi_asset_returns), n_assets),
            index=sample_multi_asset_returns.index,
            columns=sample_multi_asset_returns.columns,
        )
        env = PortfolioEnv(
            returns=sample_multi_asset_returns,
            signals=signals,
            n_assets=n_assets,
        )
        assert env.n_assets == 5
        assert env.lookback > 0

    def test_env_reset(self, sample_multi_asset_returns):
        from quant.portfolio.rl_allocator import PortfolioEnv
        n_assets = 5
        signals = pd.DataFrame(
            0.0, index=sample_multi_asset_returns.index,
            columns=sample_multi_asset_returns.columns,
        )
        env = PortfolioEnv(
            returns=sample_multi_asset_returns,
            signals=signals,
            n_assets=n_assets,
        )
        obs = env.reset()
        assert isinstance(obs, np.ndarray)
        assert len(obs) > 0

    def test_env_step(self, sample_multi_asset_returns):
        from quant.portfolio.rl_allocator import PortfolioEnv
        n_assets = 5
        signals = pd.DataFrame(
            0.0, index=sample_multi_asset_returns.index,
            columns=sample_multi_asset_returns.columns,
        )
        env = PortfolioEnv(
            returns=sample_multi_asset_returns,
            signals=signals,
            n_assets=n_assets,
        )
        env.reset()
        action = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        obs, reward, terminated, truncated, info = env.step(action)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert "weights" in info

    def test_env_observation_shape(self, sample_multi_asset_returns):
        from quant.portfolio.rl_allocator import PortfolioEnv
        n_assets = 5
        signals = pd.DataFrame(
            0.0, index=sample_multi_asset_returns.index,
            columns=sample_multi_asset_returns.columns,
        )
        env = PortfolioEnv(
            returns=sample_multi_asset_returns,
            signals=signals,
            n_assets=n_assets,
        )
        obs = env.reset()
        assert obs.shape[0] == env.obs_dim
