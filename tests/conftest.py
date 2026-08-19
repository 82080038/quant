"""Shared test fixtures and configuration.

Testing methodology:
- Pure logic tests (no DB, no network) for all computable modules
- Mock DB sessions for data-access modules
- Skip GPU-dependent tests when torch/CUDA unavailable
- Skip optional-dependency tests (hmmlearn, lightgbm, etc.) when not installed
"""

import sys
import os
from pathlib import Path

# Ensure src/ is on the path
_src = Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# Set env vars for test config BEFORE importing quant modules
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_quant")
os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.setdefault("LLM_MODEL", "test-model")

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


# ── Synthetic OHLCV data fixture ─────────────────────────────────────────────

@pytest.fixture
def sample_ohlcv():
    """Generate 100 days of synthetic OHLCV data for testing."""
    np.random.seed(42)
    n = 100
    dates = pd.bdate_range(start="2024-01-01", periods=n)
    base = 8500  # Starting price ~BBCA.JK
    returns = np.random.normal(0.001, 0.02, n)
    close = base * np.cumprod(1 + returns)
    high = close * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = close * (1 - np.abs(np.random.normal(0, 0.01, n)))
    opn = close * (1 + np.random.normal(0, 0.005, n))
    volume = np.random.randint(1_000_000, 10_000_000, n).astype(float)

    df = pd.DataFrame({
        "open": opn,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)
    return df


@pytest.fixture
def sample_returns():
    """Generate 252 days of synthetic daily returns."""
    np.random.seed(42)
    return pd.Series(np.random.normal(0.001, 0.015, 252), 
                     index=pd.bdate_range("2024-01-01", periods=252))


@pytest.fixture
def sample_multi_asset_returns():
    """Generate returns for 5 assets over 252 days."""
    np.random.seed(42)
    n_assets = 5
    n_days = 252
    data = np.random.normal(0.001, 0.02, (n_days, n_assets))
    return pd.DataFrame(
        data,
        columns=["BBCA.JK", "BBRI.JK", "TLKM.JK", "ASII.JK", "GOTO.JK"],
        index=pd.bdate_range("2024-01-01", periods=n_days),
    )


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy session for DB-dependent modules."""
    session = MagicMock()
    return session


@pytest.fixture
def sample_prices_series():
    """Simple close price series for signal testing."""
    np.random.seed(123)
    n = 60
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = pd.Series(np.cumprod(1 + np.random.normal(0.001, 0.02, n)) * 1000, index=dates)
    return close
