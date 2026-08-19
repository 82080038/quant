# Quant — Quantitative Trading System

Sistem trading kuantitatif untuk IDX (Bursa Efek Indonesia) dengan target **Swing Trading** (wajib) dan **Day Trading** (opsional).

## Arsitektur

Aplikasi ini dibangun berdasarkan audit menyeluruh dari aplikasi `market` (lihat `docs/ENGINE_AUDIT_MATRIX.md`). Menggunakan 7-layer pipeline architecture:

1. **Data Ingestion** — Point-in-time native, multi-source
2. **Feature Engineering** — Versioned factor library via FeatureStore
3. **Signal Generation** — 16 engines, continuous signals
4. **Portfolio Construction** — HRP Topdown, risk-constrained Kelly
5. **Execution** — Paper trading, fail-closed risk gate
6. **Backtesting** — Event-driven + vectorised, DSR/PBO validated
7. **Monitoring** — Per-engine IC tracking, automated retirement

Layer ke-8: **AI Agents** — Multi-agent LLM orchestration (Miner, Screener, Trader, Risk Manager, Sentiment Analyst).

## Quick Start

```bash
# Setup virtual environment
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows (PowerShell)
.\activate.ps1

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-optional.txt  # ML/RL/NLP (optional)

# CUDA torch (NVIDIA GPU)
pip install torch --index-url https://download.pytorch.org/whl/cu121

# CPU-only torch (no NVIDIA GPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install project in editable mode
pip install -e ".[dev]"
```

## CUDA-Awareness

Aplikasi mendeteksi CUDA secara dinamis. Jika GPU NVIDIA tersedia, workload berat (LSTM, Monte Carlo, correlation matrix) otomatis dijalankan di `cuda:1`. Jika tidak ada CUDA, fallback ke CPU.

```python
from quant.core.device import select_device, DeviceContext

# Auto-select: cuda:1 or cpu
device = select_device("lstm_training", data_size=50_000)

# Context manager with auto tensor movement
with DeviceContext("monte_carlo", data_size=100_000) as ctx:
    x = ctx.to(my_tensor)
```

## Cross-Platform Support

- **Linux**: `source activate.sh`
- **Windows (PowerShell)**: `.\activate.ps1`
- **Windows (CMD)**: `activate.bat`

Path defaults otomatis menyesuaikan OS via `quant.paths` module.

## Testing

```bash
.venv/bin/python3 -m pytest tests/ -v
```

160 tests passing, 2 skipped (DB-dependent modules).

## Project Structure

```
quant/
├── src/quant/
│   ├── core/           # Config, DB, Device dispatcher, Market session
│   ├── data/           # Point-in-time queries, fetch registry, IDX adapter
│   ├── features/       # Factor library, feature store, recompute graph
│   ├── signals/        # 16 signal engines (technical, fundamental, macro, etc.)
│   ├── portfolio/      # HRP-µ, Kelly, VaR, RL allocator, capital-aware sizer
│   ├── execution/      # OMS, validation, risk gate, brokers, smart order router
│   ├── backtest/       # Event-driven engine, walk-forward optimization
│   ├── evaluation/     # IC tracking, DSR, PBO, regime-conditional
│   ├── monitoring/     # Drift detection, prediction vs reality, retirement
│   ├── ai/             # LLM gateway, multi-agent orchestrator
│   └── paths.py        # Cross-platform path defaults
├── frontend/           # Next.js + TailwindCSS dashboard
├── tests/              # 8-layer test suite
├── alembic/            # Database migrations
├── scripts/            # Daily fetch scripts (Linux + Windows)
├── requirements.txt    # Core dependencies
└── requirements-optional.txt  # ML/RL/NLP dependencies
```

## License

Private project.
