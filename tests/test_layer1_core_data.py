"""Layer 1: Core & Data layer tests.

Tests:
- config: Config loads correctly with defaults
- device: CPU/GPU device selection logic (no GPU required)
- market_session: Exchange schedule and status logic
- ticker_util: Ticker suffix standardization
- cost_model: IDX trading cost calculations
"""

import pytest
import numpy as np
from datetime import datetime, timezone


# ── Config ───────────────────────────────────────────────────────────────────

class TestConfig:
    """Test application configuration."""

    def test_config_loads(self):
        from quant.core.config import config
        assert config.database_url is not None
        assert config.initial_capital > 0
        assert 0 < config.commission_rate < 0.01
        assert 0 < config.sales_tax_rate < 0.01
        assert config.max_position_pct > 0
        assert config.max_sector_pct > 0
        assert config.max_drawdown > 0

    def test_config_risk_limits(self):
        from quant.core.config import config
        assert config.max_position_pct == 0.15
        assert config.max_sector_pct == 0.40
        assert config.max_portfolio_var == 0.03
        assert config.max_drawdown == 0.15
        assert config.min_cash_reserve == 0.05

    def test_config_llm_defaults(self):
        from quant.core.config import config
        assert config.llm_provider in ("ollama", "openai")
        assert config.llm_model is not None
        assert config.llm_base_url is not None


# ── Device ───────────────────────────────────────────────────────────────────

class TestDevice:
    """Test compute device dispatcher (CPU-only environment)."""

    def test_select_device_cpu_native(self):
        from quant.core.device import select_device
        # CPU-native workloads should always return cpu
        assert select_device("pandas_groupby", data_size=100_000) == "cpu"
        assert select_device("lightgbm", data_size=100_000) == "cpu"

    def test_select_device_small_data(self):
        from quant.core.device import select_device
        # Small data should use CPU even for GPU-friendly workloads
        assert select_device("lstm_training", data_size=100) == "cpu"
        assert select_device("lstm_inference", data_size=10) == "cpu"

    def test_select_device_large_data(self):
        from quant.core.device import select_device, _TORCH_AVAILABLE
        import torch
        # Large data on GPU-friendly workload
        result = select_device("lstm_training", data_size=100_000)
        if _TORCH_AVAILABLE and torch.cuda.is_available():
            assert result == "cuda:1"
        else:
            assert result == "cpu"

    def test_device_context(self):
        from quant.core.device import DeviceContext
        with DeviceContext("lstm_training", data_size=100) as ctx:
            assert ctx.device == "cpu"

    def test_device_context_to_passthrough(self):
        from quant.core.device import DeviceContext
        with DeviceContext("pandas_groupby", data_size=100) as ctx:
            obj = {"key": "value"}
            result = ctx.to(obj)
            assert result == obj  # CPU context returns unchanged

    def test_estimate_vram(self):
        from quant.core.device import estimate_vram
        vram = estimate_vram(1000)  # 1000 elements, float32
        assert vram > 0
        # 1000 * 4 bytes = 4000 bytes ≈ 0.0038 MB
        assert vram < 0.01

    def test_vram_available(self):
        from quant.core.device import vram_available, _TORCH_AVAILABLE
        import torch
        free, total = vram_available("cuda:1")
        if _TORCH_AVAILABLE and torch.cuda.is_available():
            assert free > 0
            assert total > 0
        else:
            assert free == 0.0
            assert total == 0.0


# ── Market Session ───────────────────────────────────────────────────────────

class TestMarketSession:
    """Test market session manager."""

    def test_exchange_schedules_loaded(self):
        from quant.core.market_session import _EXCHANGES
        assert "XIDX" in _EXCHANGES
        assert "XNYS" in _EXCHANGES
        assert "XNAS" in _EXCHANGES
        idx = _EXCHANGES["XIDX"]
        assert idx.open_local == (9, 0)
        assert idx.close_local == (15, 50)

    def test_session_status_enum(self):
        from quant.core.market_session import SessionStatus
        assert SessionStatus.OPEN == "OPEN"
        assert SessionStatus.CLOSED == "CLOSED"

    def test_get_status_idx_weekend(self):
        """IDX should be CLOSED on weekends."""
        from quant.core.market_session import MarketSessionManager, SessionStatus
        # Saturday 10:00 UTC
        sat = datetime(2024, 6, 8, 10, 0, tzinfo=timezone.utc)
        mgr = MarketSessionManager(now_utc=sat)
        status = mgr.get_status("XIDX")
        assert status == SessionStatus.CLOSED

    def test_get_status_idx_open(self):
        """IDX should be OPEN during trading hours (09:00-15:50 WIB = 02:00-08:50 UTC)."""
        from quant.core.market_session import MarketSessionManager, SessionStatus
        # Wednesday 03:00 UTC = 10:00 WIB → OPEN
        wed = datetime(2024, 6, 5, 3, 0, tzinfo=timezone.utc)
        mgr = MarketSessionManager(now_utc=wed)
        status = mgr.get_status("XIDX")
        assert status == SessionStatus.OPEN

    def test_get_status_idx_closed_after_hours(self):
        """IDX should be CLOSED after trading hours."""
        from quant.core.market_session import MarketSessionManager, SessionStatus
        # Wednesday 09:00 UTC = 16:00 WIB → CLOSED
        wed = datetime(2024, 6, 5, 9, 0, tzinfo=timezone.utc)
        mgr = MarketSessionManager(now_utc=wed)
        status = mgr.get_status("XIDX")
        assert status == SessionStatus.CLOSED


# ── Ticker Util ──────────────────────────────────────────────────────────────

class TestTickerUtil:
    """Test ticker suffix standardization."""

    def test_to_yf_ticker_idx(self):
        from quant.data.ticker_util import to_yf_ticker
        assert to_yf_ticker("BBCA", "XIDX") == "BBCA.JK"
        assert to_yf_ticker("BBCA.JK", "XIDX") == "BBCA.JK"

    def test_to_yf_ticker_us(self):
        from quant.data.ticker_util import to_yf_ticker
        assert to_yf_ticker("AAPL", "XNYS") == "AAPL"
        assert to_yf_ticker("^GSPC", "XNYS") == "^GSPC"

    def test_to_yf_ticker_frankfurt(self):
        from quant.data.ticker_util import to_yf_ticker
        assert to_yf_ticker("SAP", "XFRA") == "SAP.DE"

    def test_get_suffix_fallback(self):
        from quant.data.ticker_util import get_suffix
        assert get_suffix("XIDX") == ".JK"
        assert get_suffix("XNYS") is None
        assert get_suffix("XFRA") == ".DE"


# ── Cost Model ───────────────────────────────────────────────────────────────

class TestCostModel:
    """Test IDX trading cost model."""

    def test_buy_cost(self):
        from quant.risk.cost_model import TradingCostModel
        model = TradingCostModel()
        cost = model.buy_cost(1_000_000)
        # commission 0.15% + slippage 0.1% + spread 0.05% = 0.30%
        assert abs(cost - 3000) < 0.01

    def test_sell_cost(self):
        from quant.risk.cost_model import TradingCostModel
        model = TradingCostModel()
        cost = model.sell_cost(1_000_000)
        # commission 0.15% + tax 0.1% + slippage 0.1% + spread 0.05% = 0.40%
        assert abs(cost - 4000) < 0.01

    def test_round_trip_cost(self):
        from quant.risk.cost_model import TradingCostModel
        model = TradingCostModel()
        cost = model.round_trip_cost(1_000_000)
        # 0.30% + 0.40% = 0.70%
        assert abs(cost - 7000) < 0.01

    def test_custom_rates(self):
        from quant.risk.cost_model import TradingCostModel
        model = TradingCostModel(commission_rate=0.002, sales_tax_rate=0.0, slippage_rate=0.0, bid_ask_spread=0.0)
        assert model.buy_cost(1_000_000) == 2000
        assert model.sell_cost(1_000_000) == 2000
