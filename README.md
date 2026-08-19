# Quant — Quantitative Trading System

> **Gigantic AI** untuk Pasar Modal Indonesia (IDX) & Global — Multi-Agent LLM + Deep Learning Ensemble + Academic-Grade Validation.

[![Tests](https://img.shields.io/badge/tests-160%20passed%2C%202%20skipped-brightgreen)](#testing)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](#prasyarat-sistem)
[![CUDA](https://img.shields.io/badge/CUDA-dynamic%20detection-orange)](#cuda-awareness)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-lightgrey)](#dukungan-cross-platform-windows--linux)

---

## Daftar Isi

1. [Ringkasan Proyek & Arsitektur](#1-ringkasan-proyek--arsitektur)
2. [Dukungan Cross-Platform (Windows & Linux)](#2-dukungan-cross-platform-windows--linux)
3. [Panduan Instalasi & Memulai](#3-panduan-instalasi--memulai-getting-started)
4. [Struktur Direktori Proyek](#4-struktur-direktori-proyek)
5. [Workflow Pengembangan](#5-workflow-pengembangan-development-guidelines)
6. [Catatan Penting & Penyelesaian Masalah](#6-catatan-penting--penyelesaian-masalah-troubleshooting)

---

## 1. Ringkasan Proyek & Arsitektur

### 1.1 Deskripsi Fungsional

**Quant** adalah sistem trading kuantitatif berbasis AI yang dirancang untuk pasar modal Indonesia (Bursa Efek Indonesia / IDX) dengan dukungan pasar global. Sistem ini mengintegrasikan multi-agent LLM pipeline, deep learning ensemble, dan validasi akademis (DSR/PBO) untuk menghasilkan sinyal trading kontinu yang dapat di-backtest dan di-deploy secara paper trading.

**Target trading**: Swing Trading (wajib) dan Day Trading (opsional).

#### Ruang Lingkup & Batasan

| Aspek | Keterangan |
|------|-----------|
| **Pengguna** | Aplikasi pribadi **single-user** — tidak ada multi-tenant, tidak ada sistem autentikasi publik |
| **Lisensi** | Private project — tidak untuk distribusi publik |
| **Bahasa UI** | Technical terms dalam Bahasa Inggris, narasi dalam Bahasa Indonesia |
| **Database** | PostgreSQL 16 (point-in-time native, bitemporal) |
| **GPU** | Opsional — aplikasi mendeteksi CUDA secara dinamis, fallback ke CPU jika tidak ada |

### 1.2 Arsitektur Teknologi

Sistem dibangun dengan **8-layer pipeline architecture** — setiap layer memiliki kontrak input/output yang jelas dan dapat di-swap tanpa memengaruhi layer lain.

```
┌─────────────────────────────────────────────────────────────────┐
│                     GIGANTIC AI CORE                            │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  MINER   │  │ SCREENER │  │  TRADER  │  │   RISK   │       │
│  │  Agent   │→ │  Agent   │→ │  Agent   │→ │ MANAGER  │       │
│  │ LLM-guided│  │ Regime-  │  │ Portfolio │  │ Fail-closed│     │
│  │ factor    │  │ conditioned│  │ + RL alloc │  │ VaR/ES    │   │
│  │ discovery │  │ ensemble  │  │            │  │ drawdown   │   │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘       │
│        └─────────────┴─────────────┴─────────────┘             │
│                              │                                  │
│                    ┌─────────┴─────────┐                       │
│                    │  SENTIMENT ANALYST │                       │
│                    │  Agent (IndoBERT)  │                       │
│                    └───────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │  WEIGHT VECTOR w_t │
                    │  (unified interface)│
                    └─────────┬─────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │ BACKTEST │      │ PAPER    │      │ MONITOR  │
    │ Engine   │      │ Trading  │      │ IC/DSR/  │
    │ WFA+DSR  │      │ OMS      │      │ PBO/Drift│
    └──────────┘      └──────────┘      └──────────┘
```

#### Weight-Centric Pipeline (FinRL-X Pattern)

```
w_t = R_t(T_t(A_t(S_t(X_≤t))))
```

- **S_t** = Stock Selection (ML scoring, liquidity filter, universe definition)
- **A_t** = Portfolio Allocation (HRP-µ, RL allocator, Kelly)
- **T_t** = Timing Adjustment (KAMA trend overlay, regime gate)
- **R_t** = Risk Overlay (VaR limit, drawdown control, concentration cap)

Setiap transformasi mempertahankan **weight vector contract** — swap modul mana pun tanpa menyentuh modul lain.

#### 8 Layer Pipeline

| # | Layer | Modul Utama | Deskripsi |
|---|-------|-------------|-----------|
| 1 | **Core & Data** | `core/`, `data/` | Config, DB, device dispatcher, point-in-time queries, fetch registry |
| 2 | **Features** | `features/` | Factor library (RSI, MACD, BB, ADX, OBV, MFI, ATR, KAMA, VWAP), feature store, recompute graph |
| 3 | **Signals** | `signals/` | 16 signal engines: technical, fundamental, macro, sentiment, global market, alpha, HMM regime, volume, policy event, astronacci, Fama-French, holiday effect, DL ensemble (VAE+Transformer+LSTM), XGBoost/LightGBM |
| 4 | **Portfolio** | `portfolio/` | HRP-µ (signal-aware), risk-constrained Kelly, Monte Carlo VaR, capital-aware position sizer, RL allocator (PPO/SAC) |
| 5 | **Execution** | `execution/` | OMS (state machine), validation, fail-closed risk gate, paper broker, mock broker, market impact (Almgren-Chiss), smart order router, event store |
| 6 | **Backtest** | `backtest/` | Event-driven engine dengan IDX costs, walk-forward optimization |
| 7 | **Evaluation & Monitoring** | `evaluation/`, `monitoring/` | IC tracking, Deflated Sharpe Ratio, PBO/CSCV, regime-conditional evaluation, drift detection (PSI), prediction vs reality, model retirement |
| 8 | **AI Agents** | `ai/` | LLM gateway (Ollama/OpenAI), Miner Agent, Screener Agent, Trader Agent, Risk Manager Agent, Sentiment Analyst Agent, orchestrator |

#### Technology Stack

| Kategori | Teknologi | Versi |
|----------|-----------|-------|
| **Backend** | Python | 3.12+ |
| **Database** | PostgreSQL | 16 |
| **ORM** | SQLAlchemy | 2.0+ |
| **Migration** | Alembic | 1.13+ |
| **API** | FastAPI + Uvicorn | 0.115+ / 0.30+ |
| **Computation** | NumPy, SciPy, pandas, scikit-learn | latest |
| **Deep Learning** | PyTorch (CUDA 12.1 / CPU) | 2.5.1+ |
| **Gradient Boosting** | XGBoost, LightGBM | 3.4+ / 4.7+ |
| **RL** | Stable-Baselines3, Gymnasium | 2.9+ / 1.3+ |
| **NLP** | HuggingFace Transformers | 5.15+ |
| **Econometrics** | statsmodels, hmmlearn | 0.14+ / 0.3+ |
| **Astronomy** | ephem (market session) | 4.2+ |
| **LLM** | Ollama (local: DeepSeek-R1, Llama 3.1) | — |
| **Frontend** | Next.js 16, React 18, TailwindCSS 3.4 | — |
| **Charts** | Recharts 2.12, Lucide React | — |

---

## 2. Dukungan Cross-Platform (Windows & Linux)

Aplikasi ini dikembangkan dan dijalankan di **dua OS**: Linux (Ubuntu/Debian) dan Windows (10/11). Semua modul, skrip, dan konfigurasi telah dirancang untuk kompatibel di kedua OS.

### 2.1 Penanganan Path File

Module `quant.paths` (`src/quant/paths.py`) menyediakan OS-aware path defaults:

```python
from quant.paths import default_parquet_archive, default_external_data

# Linux:  /media/petrick/Parquet/pustaka_data
# Windows: E:/pustaka_data
path = default_parquet_archive()
```

| Path | Linux | Windows |
|------|-------|---------|
| Parquet archive | `/media/petrick/Parquet/pustaka_data` | `E:/pustaka_data` |
| External data | `/media/petrick/Parquet/projects/market` | `E:/projects/market` |
| Project dir | `/opt/lampp/htdocs/market` | `C:/xampp/htdocs/market` |
| Dataset Saham IDX | `data/dataset-saham-idx` (relative) | `data/dataset-saham-idx` (relative) |

Semua path dapat di-override via environment variables (lihat `.env.example`) atau CLI flags.

### 2.2 Skrip Otomatisasi

| Skrip | OS | Fungsi |
|-------|----|--------|
| `activate.sh` | Linux/macOS | Venv activation + dependency install |
| `activate.ps1` | Windows (PowerShell) | Venv activation + dependency install |
| `activate.bat` | Windows (CMD) | Venv activation + dependency install |
| `scripts/run_daily_fetch.sh` | Linux | Daily data fetch (cron 17:00 WIB) |
| `scripts/run_daily_fetch.ps1` | Windows (Task Scheduler) | Daily data fetch |

#### Contoh: OS-aware venv path di skrip

```bash
# run_daily_fetch.sh — cross-platform detection
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OS" == "Windows_NT" ]]; then
    PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"
else
    PYTHON="$PROJECT_DIR/.venv/bin/python3"
fi
```

### 2.3 Line Endings (LF vs CRLF)

Repository menggunakan **`.gitattributes`** untuk memastikan konsistensi line endings:

```gitattributes
# .gitattributes (buat jika belum ada)
* text=auto eol=lf
*.bat text eol=crlf
*.ps1 text eol=crlf
*.sh text eol=lf
```

Git akan otomatis:
- Menyimpan semua file sebagai **LF** di repository
- Checkout **CRLF** untuk `.bat`/`.ps1` di Windows
- Checkout **LF** untuk `.sh` di semua OS

### 2.4 Virtual Environment (.venv) di Kedua OS

| OS | Command | Venv Python Path |
|----|---------|-----------------|
| **Linux** | `python3 -m venv .venv` | `.venv/bin/python3` |
| **Windows** | `python -m venv .venv` | `.venv/Scripts/python.exe` |

File `.venv/` sudah di-exclude di `.gitignore` — tidak akan ter-push ke GitHub.

---

## 3. Panduan Instalasi & Memulai (Getting Started)

### 3.1 Prasyarat Sistem

#### Linux (Ubuntu/Debian)

| Requirement | Versi | Install Command |
|-------------|-------|-----------------|
| Python | 3.12+ | `sudo apt install python3.12 python3.12-venv` |
| PostgreSQL | 16+ | `sudo apt install postgresql-16` |
| NVIDIA Driver | 535+ (opsional, untuk CUDA) | `sudo apt install nvidia-driver-535` |
| CUDA Toolkit | 12.1 (opsional) | Dari [NVIDIA Developer](https://developer.nvidia.com/cuda-12-1-0-download-archive) |
| Node.js | 20+ (frontend) | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo bash -` |
| Git | 2.40+ | `sudo apt install git` |

#### Windows

| Requirement | Versi | Download |
|-------------|-------|----------|
| Python | 3.12+ | [python.org](https://www.python.org/downloads/) (centang "Add to PATH") |
| PostgreSQL | 16+ | [postgresql.org](https://www.postgresql.org/download/windows/) |
| NVIDIA Driver | 535+ (opsional) | [NVIDIA.com](https://www.nvidia.com/Download/index.aspx) |
| CUDA Toolkit | 12.1 (opsional) | [NVIDIA Developer](https://developer.nvidia.com/cuda-12-1-0-download-archive) |
| Node.js | 20+ (frontend) | [nodejs.org](https://nodejs.org/) |
| Git | 2.40+ | [git-scm.com](https://git-scm.com/download/win) |
| Visual C++ Build Tools | 2022 | [visualstudio.microsoft.com](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (dibutuhkan untuk kompilasi psycopg2 dll.) |

### 3.2 Kloning Repositori

```bash
git clone https://github.com/82080038/quant.git
cd quant
```

### 3.3 Pembuatan .venv & Instalasi Dependency

#### Linux

```bash
# 1. Buat virtual environment
python3 -m venv .venv

# 2. Aktifkan
source .venv/bin/activate

# 3. Upgrade pip
pip install --upgrade pip setuptools wheel

# 4. Install core dependencies
pip install -r requirements.txt

# 5. Install optional dependencies (ML/RL/NLP)
pip install -r requirements-optional.txt

# 6. Install project dalam editable mode
pip install -e ".[dev]"
```

Atau gunakan skrip otomatis:
```bash
source activate.sh
```

#### Windows (PowerShell)

```powershell
# 1. Buat virtual environment
python -m venv .venv

# 2. Aktifkan
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip
pip install --upgrade pip setuptools wheel

# 4. Install core dependencies
pip install -r requirements.txt

# 5. Install optional dependencies
pip install -r requirements-optional.txt

# 6. Install project dalam editable mode
pip install -e ".[dev]"
```

Atau gunakan skrip otomatis:
```powershell
.\activate.ps1
```

> **Catatan Windows**: Jika eksekusi PowerShell diblokir, jalankan:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 3.4 Instalasi PyTorch (CUDA vs CPU)

PyTorch **tidak termasuk** di `requirements.txt` karena perbedaan index URL. Install secara terpisah:

#### Dengan CUDA (NVIDIA GPU tersedia)

```bash
# Linux & Windows — sama
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

#### CPU-only (tanpa NVIDIA GPU)

```bash
# Linux & Windows — sama
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Aplikasi akan otomatis mendeteksi apakah CUDA tersedia dan melakukan fallback ke CPU jika tidak. Lihat [CUDA-Awareness](#cuda-awareness).

### 3.5 Konfigurasi .env

Salin `.env.example` menjadi `.env` dan sesuaikan:

```bash
cp .env.example .env
```

```ini
# .env — Quant Trading Application

# Database
DATABASE_URL=postgresql://petrick:market_dev@localhost:5432/quant

# Data Sources
YF_TIMEOUT=30
IDX_BASE_URL=https://www.idx.co.id

# GPU
CUDA_DEVICE=cuda:1

# Timezone
TZ=Asia/Jakarta

# Trading
INITIAL_CAPITAL=100000000
COMMISSION_RATE=0.0015
SALES_TAX_RATE=0.001
SLIPPAGE_RATE=0.001

# Logging
LOG_LEVEL=INFO

# LLM (Phase 3 — opsional)
LLM_PROVIDER=ollama
LLM_MODEL=deepseek-r1:1.5b
LLM_BASE_URL=http://localhost:11434
LLM_API_KEY=
```

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `DATABASE_URL` | `postgresql://petrick:market_dev@localhost:5432/quant` | PostgreSQL connection string |
| `CUDA_DEVICE` | `cuda:1` | GPU yang dipakai untuk compute (GPU 0 = display) |
| `INITIAL_CAPITAL` | `100000000` | Modal awal (Rp 100 juta) |
| `COMMISSION_RATE` | `0.0015` | Komisi broker (0.15%) |
| `SALES_TAX_RATE` | `0.001` | PPh final (0.1%) |
| `SLIPPAGE_RATE` | `0.001` | Estimasi slippage (0.1%) |
| `TZ` | `Asia/Jakarta` | Timezone aplikasi |
| `LLM_PROVIDER` | `ollama` | LLM provider: `ollama`, `openai`, atau `unknown` |
| `LLM_MODEL` | `deepseek-r1:1.5b` | Model LLM untuk multi-agent pipeline |
| `LLM_BASE_URL` | `http://localhost:11434` | URL endpoint LLM (Ollama default) |

### 3.6 Setup Database

```bash
# 1. Buat database di PostgreSQL
createdb quant

# 2. Jalankan migrasi Alembic
alembic upgrade head

# 3. Atau import schema manual
psql -d quant -f docs/SCHEMA.sql
```

### 3.7 Setup Frontend (Opsional)

```bash
cd frontend
npm install
npm run dev    # http://localhost:3000
```

---

## 4. Struktur Direktori Proyek

```
quant/
├── .gitignore                    # Git ignore rules
├── .env.example                  # Template environment variables
├── README.md                     # Dokumentasi ini
├── MEGAPLAN.md                   # Master plan & arsitektur detail (700 lines)
├── pyproject.toml                # Python project config + dependency groups
├── requirements.txt              # Core dependencies (OS-agnostic)
├── requirements-optional.txt     # Optional ML/RL/NLP dependencies
├── alembic.ini                   # Alembic migration config
├── activate.sh                   # Linux/macOS venv activation script
├── activate.ps1                  # Windows PowerShell activation script
├── activate.bat                  # Windows CMD activation script
│
├── alembic/                      # Database migrations
│   ├── env.py                    # Alembic environment
│   ├── script.py.mako            # Migration template
│   └── versions/
│       └── 0001_baseline.py      # Baseline migration
│
├── docs/                         # Documentation
│   ├── ENGINE_AUDIT_MATRIX.md    # 7-layer pipeline audit (1893 lines)
│   └── SCHEMA.sql                # Point-in-time native database schema
│
├── frontend/                     # Next.js dashboard
│   ├── package.json              # Node dependencies
│   ├── next.config.js            # Next.js config
│   ├── tailwind.config.ts        # TailwindCSS config
│   ├── tsconfig.json             # TypeScript config
│   ├── postcss.config.js         # PostCSS config
│   └── src/
│       ├── app/                  # Next.js App Router pages
│       │   ├── layout.tsx        # Root layout
│       │   ├── page.tsx          # Dashboard
│       │   ├── globals.css       # Global styles
│       │   ├── signals/          # Signal display page
│       │   ├── screener/         # Factor screening page
│       │   ├── backtest/         # Backtest results page
│       │   ├── portfolio/        # Portfolio allocation page
│       │   ├── evaluation/       # DSR/PBO evaluation page
│       │   ├── monitoring/       # Drift & IC monitoring page
│       │   ├── automation/       # Paper trading & OMS page
│       │   ├── data/             # Data source status page
│       │   ├── stock/            # Stock detail page
│       │   ├── scan/             # Market scan page
│       │   ├── scheduler/        # Scheduler config page
│       │   ├── simulation/       # Simulation page
│       │   ├── reports/          # Reports page
│       │   ├── settings/         # Settings page
│       │   └── cosmos/           # Cosmos view (layout + page)
│       ├── components/           # React components
│       │   ├── header.tsx        # Top header bar
│       │   ├── sidebar.tsx       # Navigation sidebar
│       │   ├── market-context.tsx    # Market data context provider
│       │   ├── scheduler-context.tsx # Scheduler context provider
│       │   └── ui/
│       │       └── card.tsx      # Reusable card component
│       └── lib/
│           └── utils.ts          # Utility functions (cn, formatDate, etc.)
│
├── scripts/                      # Automation scripts
│   ├── run_daily_fetch.sh        # Daily data fetch (Linux, cron)
│   ├── run_daily_fetch.ps1       # Daily data fetch (Windows, Task Scheduler)
│   └── transfer_data.py          # Data transfer utility
│
├── src/quant/                    # Main Python package
│   ├── __init__.py
│   ├── paths.py                  # Cross-platform path defaults (OS-aware)
│   │
│   ├── core/                     # Layer 1a: Core infrastructure
│   │   ├── config.py             # Dataclass config (reads .env)
│   │   ├── db.py                 # SQLAlchemy engine, session, test_connection
│   │   ├── device.py             # CUDA-aware device dispatcher (626 lines)
│   │   └── market_session.py     # Exchange session manager (ephem-based)
│   │
│   ├── data/                     # Layer 1b: Data ingestion
│   │   ├── point_in_time.py      # Bitemporal query helper (no look-ahead)
│   │   ├── fetch_registry.py     # Multi-source data fetch registry
│   │   ├── idx_adapter.py        # IDX official data adapter
│   │   └── ticker_util.py        # Ticker utilities (yfinance format, currency)
│   │
│   ├── db/                       # Database models & engine (secondary)
│   │   ├── engine.py             # Engine factory (get_engine, get_sessionmaker)
│   │   ├── models.py             # SQLAlchemy ORM models
│   │   └── raw.py                # Raw connection for bulk operations
│   │
│   ├── features/                 # Layer 2: Feature engineering
│   │   ├── factor_library.py     # Technical indicators (RSI, MACD, BB, ADX, etc.)
│   │   ├── feature_store.py      # Versioned feature store with freshness
│   │   └── recompute_graph.py    # Selective recompute dependency graph
│   │
│   ├── signals/                  # Layer 3: Signal generation (16 engines)
│   │   ├── technical.py          # Technical analysis signals
│   │   ├── fundamental.py        # Fundamental factor signals
│   │   ├── macro.py              # Macroeconomic signals
│   │   ├── sentiment.py          # News sentiment signals (IndoBERT)
│   │   ├── global_market.py      # Cross-market correlation signals
│   │   ├── alpha_signals.py      # Alpha engines (mean reversion, reversal, etc.)
│   │   ├── hmm_regime.py         # HMM regime detection
│   │   ├── volume_features.py    # Volume microstructure signals
│   │   ├── policy_event_scorer.py # Policy event impact scoring
│   │   ├── astronacci.py         # Astronacci time cycle signals
│   │   ├── fama_french.py        # Fama-French 5-factor model
│   │   ├── holiday_effect.py     # Holiday effect signals
│   │   ├── tbl.py                # Triple Barrier Labeling
│   │   ├── lstm.py               # LSTM signal predictor
│   │   ├── transformer.py        # Transformer signal predictor
│   │   ├── vae.py                # VAE feature extractor
│   │   ├── xgb_lgbm.py           # XGBoost + LightGBM ensemble
│   │   ├── ensemble.py           # DL ensemble orchestrator
│   │   ├── strategy_selector.py  # Strategy selection per regime
│   │   ├── relationship.py       # Cross-asset relationship signals
│   │   └── aggregator.py         # Signal aggregation (continuous [-1, +1])
│   │
│   ├── portfolio/                # Layer 4: Portfolio construction
│   │   ├── hrp_mu.py             # HRP-µ (signal-aware risk parity)
│   │   ├── hrp.py                # Standard HRP
│   │   ├── kelly.py              # Risk-constrained Kelly criterion
│   │   ├── monte_carlo_var.py    # Monte Carlo VaR/CVaR
│   │   ├── capital_aware_sizer.py # Capital-aware position sizing
│   │   ├── rl_allocator.py       # RL portfolio allocator (PPO/SAC)
│   │   ├── alpha_hyper_tuner.py  # Alpha hyperparameter tuner
│   │   ├── alpha_rescue_pipeline.py # Alpha rescue pipeline
│   │   ├── audit_ai_advanced.py  # Advanced AI audit
│   │   └── audit_ai_utility.py   # AI utility audit
│   │
│   ├── execution/                # Layer 5: Execution
│   │   ├── oms.py                # Order Management System (state machine)
│   │   ├── validation.py         # Order validation rules
│   │   ├── risk_gate.py          # Fail-closed risk gate
│   │   ├── brokers.py            # PaperBroker, MockBroker adapters
│   │   ├── market_impact.py      # Almgren-Chiss market impact model
│   │   ├── smart_order_router.py # Smart order router (multi-venue)
│   │   ├── event_store.py        # Event sourcing store
│   │   ├── paper_trading.py      # Paper trading engine
│   │   └── automation.py         # Execution automation
│   │
│   ├── backtest/                 # Layer 6: Backtesting
│   │   ├── engine.py             # Event-driven backtest engine
│   │   ├── strategies.py         # Strategy base class & Signal dataclass
│   │   └── walk_forward.py       # Walk-forward optimization
│   │
│   ├── evaluation/               # Layer 7a: Evaluation
│   │   ├── ic_tracking.py        # Information Coefficient tracking
│   │   ├── dsr.py                # Deflated Sharpe Ratio
│   │   ├── pbo.py                # Probability of Backtest Overfitting
│   │   └── regime_conditional.py # Regime-conditional evaluation
│   │
│   ├── monitoring/               # Layer 7b: Monitoring
│   │   ├── drift.py              # PSI-based drift detection
│   │   ├── prediction_reality.py # Prediction vs actual tracking
│   │   ├── retirement.py         # Automated model retirement
│   │   ├── alerts.py             # Alert system (Telegram)
│   │   └── scheduler.py          # Task scheduler
│   │
│   ├── ai/                       # Layer 8: AI agents
│   │   ├── llm_gateway.py        # LLM gateway (Ollama/OpenAI/unknown)
│   │   ├── miner_agent.py        # Factor discovery agent
│   │   ├── screener_agent.py     # Regime-conditioned screening agent
│   │   ├── trader_agent.py       # Portfolio construction agent
│   │   ├── risk_agent.py         # Risk management agent
│   │   ├── sentiment_agent.py    # Sentiment analysis agent
│   │   └── orchestrator.py       # Multi-agent pipeline orchestrator
│   │
│   ├── advisory/                 # Advisory modules
│   │   └── trading_style_advisor.py # Trading style advisor
│   │
│   ├── analysis/                 # Analysis modules
│   │   ├── instrument_profiler.py # Instrument profiling
│   │   └── profiling.py          # Performance profiling
│   │
│   ├── api/                      # FastAPI REST API
│   │   └── app.py                # API endpoints (health, prices, signals, etc.)
│   │
│   ├── compute/                  # Compute utilities
│   │   └── device.py             # Re-exports from core.device + LightGBM helper
│   │
│   └── risk/                     # Risk models
│       └── cost_model.py         # Trading cost model
│
└── tests/                        # Test suite (8 layers)
    ├── conftest.py               # Shared fixtures (OHLCV, returns, mock DB)
    ├── test_layer1_core_data.py  # Core & Data tests (23 tests)
    ├── test_layer2_features.py   # Features tests (15+2 skipped)
    ├── test_layer3_signals.py    # Signals tests (29 tests)
    ├── test_layer4_portfolio.py  # Portfolio tests (23 tests)
    ├── test_layer5_execution.py  # Execution tests (28 tests)
    ├── test_layer6_backtest.py   # Backtest tests (6 tests)
    ├── test_layer7_eval_monitoring.py # Evaluation & Monitoring (22 tests)
    └── test_layer8_ai.py         # AI agent tests (14 tests)
```

---

## 5. Workflow Pengembangan (Development Guidelines)

### 5.1 Menjalankan Server Lokal

#### Backend API (FastAPI)

```bash
# Linux
.venv/bin/uvicorn quant.api.app:app --reload --host 0.0.0.0 --port 8000

# Windows
.venv\Scripts\uvicorn.exe quant.api.app:app --reload --host 0.0.0.0 --port 8000
```

Endpoint tersedia:
- `GET /api/health` — System health check
- `GET /api/db/stats` — Database statistics
- `GET /api/prices/movers` — Top gainers/losers
- `GET /api/prices/ihsg` — IHSG composite index
- `GET /api/instruments` — List instruments
- `GET /api/signals/attribution` — Signal attribution log
- `GET /api/evaluation/engines` — Engine evaluation summary
- `GET /api/evaluation/ic/{engine_name}` — Rolling IC per engine
- `POST /api/evaluation/dsr` — Compute Deflated Sharpe Ratio

#### Frontend (Next.js)

```bash
cd frontend
npm run dev    # http://localhost:3000
```

#### Daily Data Fetch

```bash
# Linux (manual atau via cron)
.venv/bin/python3 scripts/run_daily_fetch.sh

# Windows (manual atau via Task Scheduler)
.venv\Scripts\python.exe scripts\run_daily_fetch.ps1
```

Cron setup (Linux):
```cron
# Run at 17:00 WIB (10:00 UTC) Mon-Fri
0 10 * * 1-5 /home/petrick/projects/quant/scripts/run_daily_fetch.sh
```

### 5.2 Memantau Log & Debugging

#### Logging

Aplikasi menggunakan `structlog` untuk structured logging. Log level dikonfigurasi via `.env`:

```ini
LOG_LEVEL=INFO    # DEBUG, INFO, WARNING, ERROR
```

#### Debug CUDA Device Selection

```python
from quant.core.device import select_device, vram_available

# Cek device yang dipilih
print(select_device("lstm_training", data_size=50_000))
# → "cuda:1" (GPU) atau "cpu" (fallback)

# Cek VRAM
print(vram_available("cuda:1"))
# → (3909.875, 4031.875) = (free_mb, total_mb)
```

#### Debug Database Connection

```python
from quant.core.db import test_connection
print(test_connection())  # True/False
```

### 5.3 Protokol Pengujian

#### Menjalankan Test Suite

```bash
# Semua tests
.venv/bin/python3 -m pytest tests/ -v

# Per layer
.venv/bin/python3 -m pytest tests/test_layer1_core_data.py -v
.venv/bin/python3 -m pytest tests/test_layer3_signals.py -v

# Dengan coverage
.venv/bin/python3 -m pytest tests/ --cov=src/quant --cov-report=html
```

#### Test Methodology

| Aspek | Pendekatan |
|-------|-----------|
| **Data fixtures** | Synthetic OHLCV, returns, multi-asset returns (lihat `conftest.py`) |
| **DB-dependent modules** | Mock SQLAlchemy sessions — tidak butuh PostgreSQL running |
| **GPU tests** | CUDA-aware assertions — pass di both CPU-only dan CUDA machines |
| **No look-ahead bias** | Signal tests verify `.shift(1)` on output |
| **Bug-documenting tests** | Known bugs documented via `pytest.raises` dengan komentar |

#### Cross-OS Testing Protocol

Saat menambah fitur atau memperbaiki bug, pastikan:

1. **Jalankan test suite di kedua OS** (atau setidaknya di OS tempat development)
2. **Gunakan `pathlib.Path`** untuk semua path operations — jangan hardcode `/` atau `\\`
3. **Gunakan `os.path.join` atau `Path /`** — jangan string concatenation
4. **Test dengan CPU-only torch** untuk memastikan fallback bekerja:
   ```bash
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pytest tests/test_layer1_core_data.py -v
   ```
5. **Cek line endings** — pastikan `.sh` files menggunakan LF, `.bat`/`.ps1` menggunakan CRLF

#### Code Style

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/quant/
```

### 5.4 CUDA-Awareness

Module `quant.core.device` (`src/quant/core/device.py`) mengimplementasikan deteksi CUDA dinamis yang bekerja di **Windows dan Linux**:

```python
from quant.core.device import select_device, DeviceContext

# Pattern 1: Direct selection
device = select_device("lstm_training", data_size=50_000)
# → "cuda:1" if CUDA available + large data
# → "cpu" if no CUDA or small data

# Pattern 2: Context manager (auto-select + tensor movement)
with DeviceContext("monte_carlo", data_size=100_000) as ctx:
    x = ctx.to(my_tensor)    # moved to GPU only if ctx.device == "cuda:1"
    result = my_computation(x)
    # ctx.__exit__ calls torch.cuda.synchronize() if GPU was used
```

#### Decision Logic

| Step | Condition | Result |
|------|-----------|--------|
| 1 | CPU-native workload (`pandas_groupby`, `lightgbm`) | → `"cpu"` |
| 2 | Small data (below threshold) | → `"cpu"` (transfer overhead > compute savings) |
| 3 | No CUDA (torch missing or `cuda.is_available() == False`) | → `"cpu"` |
| 4 | VRAM insufficient (with 20% safety margin) | → `"cpu"` |
| 5 | All checks passed | → `"cuda:1"` |

#### Hardware Target

- 2x NVIDIA GeForce GTX 1050 Ti (4 GB VRAM, Pascal GP107, compute 6.1)
- GPU 0: display — **jangan dipakai untuk compute**
- GPU 1: compute — **PREFERRED** (`cuda:1`)

#### Verifikasi CUDA

```bash
.venv/bin/python3 -c "
import torch
print(f'torch: {torch.__version__}')
print(f'CUDA: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        print(f'  cuda:{i} = {torch.cuda.get_device_name(i)}')
"
```

---

## 6. Catatan Penting & Penyelesaian Masalah (Troubleshooting)

### 6.1 Masalah Cross-OS

#### Permission Issues (Linux)

| Masalah | Solusi |
|---------|--------|
| `Permission denied` saat eksekusi `.sh` | `chmod +x activate.sh scripts/run_daily_fetch.sh` |
| PostgreSQL connection refused | `sudo systemctl start postgresql` |
| Port 8000/3000 sudah dipakai | `lsof -i :8000` lalu kill process, atau gunakan port lain |
| `psycopg2` install error | `sudo apt install libpq-dev python3-dev` |
| CUDA driver mismatch | Cek `nvidia-smi` — driver harus >= yang dibutuhkan torch |

#### Path & Port Issues (Windows)

| Masalah | Solusi |
|---------|--------|
| PowerShell execution policy | `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `psycopg2` install error | Install [Visual C++ Build Tools 2022](https://visualstudio.microsoft.com/visual-cpp-build-tools/) |
| Port 8000/3000 sudah dipakai | `netstat -ano \| findstr :8000` lalu `taskkill /PID <pid> /F` |
| Path terlalu panjang (>260 char) | Enable long path support: `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1` |
| CUDA not detected padahal GPU ada | Pastikan install torch dari cu121 index, bukan default PyPI |
| Line ending error di `.sh` | `git config --global core.autocrlf input` atau gunakan WSL |

### 6.2 Masalah Umum

#### torch Import Error (`undefined symbol: ncclCommResume`)

**Penyebab**: torch dari default PyPI index bentrok dengan CUDA toolkit versi lain.

**Solusi**:
```bash
pip uninstall torch triton -y
pip install torch --index-url https://download.pytorch.org/whl/cu121 --force-reinstall --no-deps
```

#### Database Connection Failed

**Penyebaban umum**:
1. PostgreSQL service tidak running
2. Credential salah di `.env`
3. Database `quant` belum dibuat

**Solusi**:
```bash
# Linux
sudo systemctl start postgresql
createdb quant

# Windows
net start postgresql-x64-16
createdb -U postgres quant
```

#### Frontend `npm install` Error

```bash
# Hapus cache dan install ulang
cd frontend
rm -rf node_modules package-lock.json
npm cache clean --force
npm install
```

#### Alembic Migration Error

```bash
# Reset migrasi
alembic downgrade base
alembic upgrade head

# Atau import schema manual
psql -d quant -f docs/SCHEMA.sql
```

### 6.3 Known Bugs (Dari Test Suite)

| Bug | Lokasi | Status | Dampak |
|-----|--------|--------|--------|
| `Signal.HOLD/BUY/SELL` tidak ada (dataclass, bukan enum) | `backtest/engine.py:101,104,109,114,141` | Documented | Backtest engine crash saat `engine.run()` |
| `get_sessionmaker` tidak ada di `db/engine.py` | `features/recompute_graph.py:53-54` | Documented | RecomputeGraph tidak bisa di-import |
| `news_sentiment` module tidak ada | `signals/sentiment.py:163` | Documented | News NLP sentiment analysis broken |
| `get_profile` tidak ada di `TradingStyleAdvisor` | `portfolio/capital_aware_sizer.py:154` | Documented | Position sizing crash untuk non-HOLD signals |
| Drawdown check logic inverted | `execution/risk_gate.py:109` | Documented | Risk gate pass saat seharusnya fail |
| RSI returns 50 untuk all-up data | `features/factor_library.py:545-546` | Documented | RSI bug untuk constant uptrend |
| Regime returns lowercase | `signals/macro.py` | Documented | Inconsistency, bukan crash |

### 6.4 Performance Tips

| Tips | Efek |
|------|------|
| Gunakan `cuda:1` untuk data > 10K rows | 2-5x speedup untuk LSTM/Transformer |
| Set `CUDA_VISIBLE_DEVICES=1` | Paksa hanya GPU 1 yang visible |
| Batch size 100 untuk yfinance fetch | Hindari rate limit |
| `pool_pre_ping=True` di SQLAlchemy | Hindari stale connections |
| Gunakan CPU untuk small data (< 1K rows) | Transfer overhead > compute savings |

---

## Referensi Tambahan

- **`MEGAPLAN.md`** — Master plan 700-baris berisi arsitektur detail, fase implementasi, dan referensi akademis
- **`docs/ENGINE_AUDIT_MATRIX.md`** — Audit 7-layer pipeline (1893 baris)
- **`docs/SCHEMA.sql`** — Skema database point-in-time native
- **GitHub**: [https://github.com/82080038/quant](https://github.com/82080038/quant)

## License

Private project — tidak untuk distribusi publik.
