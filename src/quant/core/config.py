"""Quant application configuration."""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://petrick:market_dev@localhost:5432/quant")

    # GPU
    cuda_device: str = os.getenv("CUDA_DEVICE", "cuda:1")

    # Data fetching
    yf_timeout: int = int(os.getenv("YF_TIMEOUT", "30"))
    idx_base_url: str = os.getenv("IDX_BASE_URL", "https://www.idx.co.id")

    # Trading
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "100000000"))
    commission_rate: float = float(os.getenv("COMMISSION_RATE", "0.0015"))
    sales_tax_rate: float = float(os.getenv("SALES_TAX_RATE", "0.001"))
    slippage_rate: float = float(os.getenv("SLIPPAGE_RATE", "0.001"))

    # Timezone
    tz: str = os.getenv("TZ", "Asia/Jakarta")

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # LLM (Phase 3)
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-r1:1.5b")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")

    # Risk limits
    max_position_pct: float = 0.15
    max_sector_pct: float = 0.40
    max_portfolio_var: float = 0.03
    max_drawdown: float = 0.15
    min_cash_reserve: float = 0.05

    # Backtesting
    walk_forward_train: int = 252
    walk_forward_test: int = 63
    dsr_threshold: float = 0.95
    pbo_threshold: float = 0.50

    # Signal
    signal_min_confidence: float = 0.3
    signal_max_engines: int = 16


config = Config()
