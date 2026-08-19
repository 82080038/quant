# Sistem Analisis & Rekayasa Balik (Reverse-Engineering) Report
## Aplikasi Quant Trading System — "Gigantic AI"

**Tanggal:** 2026-08-19
**Analyst:** Lead AI Software Architect & Principal Systems Analyst
**Lokasi:** `/home/petrick/projects/quant/`

---

## [EXECUTIVE SUMMARY: APPLICATION INTENT]

### Apakah Aplikasi Ini?

`quant` adalah sistem **trading kuantitatif berbasis multi-agent LLM** yang dirancang untuk **penggunaan pribadi (single-user)** oleh seorang trader/peneliti kuantitatif Indonesia. Sistem ini mengintegrasikan:

1. **Data saham asli IDX (Bursa Efek Indonesia)** — 1,137 ticker aktif, 3.58M baris OHLCV, 1.13M baris foreign flow, data fundamental, makro, dan sentimen berita.
2. **16+ signal engine** yang menghasilkan sinyal kontinu [-1, +1] (bukan biner) untuk screening, prediksi, dan keputusan trading.
3. **Multi-agent AI pipeline** (Miner → Screener → Trader → Risk Manager → Sentiment Analyst) yang terinspirasi dari AlphaCrafter, FinRL-X, dan ATLAS.
4. **Deep learning ensemble** (VAE + Transformer + LSTM + XGBoost/LightGBM) dengan Triple Barrier Labeling untuk volatilitas IDX.
5. **Backtest engine** dengan validasi akademis (DSR, PBO/CSCV, Walk-Forward Analysis).
6. **Paper trading OMS** dengan fail-closed risk gate dan simulasi eksekusi realistis (komisi 0.15%, tax 0.1%, slippage).
7. **Frontend Next.js** dengan dashboard real-time (WebSocket + SSE), tampilan tata surya (Astronacci/cosmos), dan observability console.

### Untuk Siapa?

**Pengguna tunggal (pribadi)** — seorang quant researcher/trader Indonesia yang membangun sistem penunjang keputusan trading algoritmik untuk pasar IDX (Bursa Efek Indonesia) dengan ekspansi ke pasar global. Sistem ini bukan untuk multi-tenant atau institutional deployment — ini adalah **personal algorithmic trading workstation**.

### Tujuan Akhir

Membangun sistem **"Gigantic AI"** — sebuah platform trading kuantitatif otomatis yang:

1. **Mengotomatisasi seluruh pipeline** dari ingestion data → feature engineering → signal generation → portfolio construction → risk management → eksekusi paper trading.
2. **Menggunakan AI/LLM untuk factor discovery** — Miner Agent menemukan faktor baru secara otomatis via LLM reasoning.
3. **Adaptif terhadap regime pasar** — Screener Agent menyesuaikan bobot engine berdasarkan kondisi (bull/bear/sideways/crisis).
4. **Self-healing** — pipeline state machine melacak status per-ticker per-step, dengan error tracking dan retry untuk Agentic AI recovery.
5. **Academic-grade validation** — DSR + PBO mencegah overfitting, walk-forward analysis menjamin honest backtesting.
6. **Production-ready** — fail-closed risk gate, paper trading graduation, monitoring drift, automated model retirement.

### Skala Sistem Saat Ini

| Metrik | Nilai |
|--------|-------|
| **Python source files** | 109 file, 24,602 baris |
| **Frontend files** | 32 file, 7,897 baris |
| **Database tables** | 30 tabel |
| **Database indexes** | 73 index |
| **Database size** | 1,290 MB |
| **stock_prices rows** | 3,580,156 |
| **foreign_flow rows** | 1,132,945 |
| **instruments** | 1,137 ticker (1,030 IDX + 107 global) |
| **Signal engines** | 22 file, 6,680 baris |
| **Portfolio modules** | 11 file, 2,718 baris |
| **AI/Agentic modules** | 15 file, 3,556 baris |
| **GPU** | 2x NVIDIA GTX 1050 Ti (4 GB VRAM each, Pascal GP107, compute 6.1) |
| **Display** | HDMI-0 1920x1080 (primary), HDMI-1-0 1440x900, DVI-D-1-0 1280x800 |

---

## [TECHNICAL WORKFLOW MAP]

### 1. Arsitektur 7-Layer Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                        LAYER 1: DATA INGESTION                       │
│                                                                      │
│  Cron (17:00 WIB)                                                    │
│    ↓                                                                 │
│  run_daily_fetch.sh                                                  │
│    ↓                                                                 │
│  yfinance API → batch 50 tickers → stock_prices (UPSERT)            │
│    ↓                                                                 │
│  FetchRegistry: get_pending_fetches('idx_equity')                    │
│    → filter: fetch_status IN ('STALE','NEVER_FETCHED','FAILED')     │
│    → mark_fetched() → fetch_status='OK', last_fetch_at=now()        │
│                                                                      │
│  Data Sources:                                                       │
│    - yfinance (EOD OHLCV, IDX + global) — ✅ ACTIVE                  │
│    - idx.co.id (broker summary, corporate calendar) — ✅ Adapter    │
│    - RSS feeds (CNBC, Detik, Kontan) — ⬜ TODO                       │
│    - BPS/World Bank (macro) — ⬜ TODO                                 │
│    - Bank Indonesia (BI Rate, forex) — ⬜ TODO                        │
│                                                                      │
│  DB as State Machine:                                                │
│    instruments.fetch_status: NEVER_FETCHED → STALE → OK → STALE     │
│    pipeline_state: pending → ingested → screened → analyzed → done  │
│    recompute_watermark: (ticker, table) → last_processed_date        │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (event: data.ingested)
┌─────────────────────────────────────────────────────────────────────┐
│                  LAYER 2: FEATURE ENGINEERING                        │
│                                                                      │
│  FactorLibrary (637 baris, 3 class, 24 method)                       │
│    → register(name, version, func, dependencies, description)       │
│    → compute(factor_name, ticker, date, as_of_date) — PIT-safe      │
│    → validate(factor_name, universe, date_range) — IC, ICIR         │
│    → prune(threshold_ic=0.02) — remove decayed factors              │
│                                                                      │
│  FeatureStore (382 baris)                                            │
│    → compute_and_store(factor_name, ticker, date) → feature_values  │
│    → get_features(ticker, date, factor_names, as_of_date)           │
│    → freshness_report() — stale feature detection                   │
│                                                                      │
│  Incremental Processing (pipeline/incremental.py):                   │
│    → get_watermark(ticker, table) → last_processed_date             │
│    → load_ohlcv_since(ticker, wm_date - buffer_days) → bounded DF   │
│    → bulk_upsert(table, df, conflict_cols) — idempotent write       │
│    → set_watermark(ticker, table, new_date, row_count)              │
│                                                                      │
│  Factor Categories:                                                  │
│    Technical: RSI, MACD, BB, ADX, OBV, MFI, ATR, KAMA               │
│    Volume: OFI proxy, VWAP dev, OBV divergence, foreign flow        │
│    Fundamental: P/E, P/B, ROE, ROA, debt ratio, dividend yield      │
│    Macro: BI Rate, USD/IDR, CPO, gold, S&P 500, VIX                 │
│    Sentiment: IndoBERT news sentiment, sentiment momentum           │
│    Global: Cross-market correlation, overnight IDX, DCC-GARCH       │
│    Causality: Granger causality, VAR, CCF time-lag, impact weight   │
│    Alpha: Mean reversion, reversal, EWMA momentum, regime switch    │
│    Astronacci: Planetary cycles, zodiac, Fibonacci confluence       │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (event: features.computed)
┌─────────────────────────────────────────────────────────────────────┐
│              LAYER 3: SIGNAL GENERATION (16+ ENGINES)                │
│                                                                      │
│  Each engine produces: SignalResult(engine_name, ticker,            │
│    signal_value ∈ [-1,+1], confidence ∈ [0,1], direction,           │
│    rationale)                                                        │
│                                                                      │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ Technical   │ │ Fundamental │ │   Macro     │ │  Sentiment  │   │
│  │ Analysis    │ │ Analysis    │ │ Economic    │ │ (IndoBERT)  │   │
│  │ Engine      │ │ Engine      │ │ Engine      │ │ Engine      │   │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘   │
│         └───────────────┴───────────────┴───────────────┘           │
│                         ↓                                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ Global      │ │ Causality   │ │ Alpha (4x)  │ │ HMM Regime  │   │
│  │ Market      │ │ Analyzer    │ │ MeanRev,    │ │ Detector    │   │
│  │ Engine      │ │ (Granger+   │ │ Reversal,   │ │             │   │
│  │             │ │  VAR+CCF)   │ │ Momentum,   │ │             │   │
│  │             │ │             │ │ RegimeSwitch│ │             │   │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬──────┘   │
│         └───────────────┴───────────────┴───────────────┘           │
│                         ↓                                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                   │
│  │ Policy      │ │ Holiday     │ │ Fama-French │                   │
│  │ Event       │ │ Effect      │ │ 5-Factor    │                   │
│  │ Scorer      │ │ Analyzer    │ │             │                   │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘                   │
│         └───────────────┴───────────────┘                           │
│                         ↓                                           │
│  ┌─────────────┐ ┌─────────────┐                                    │
│  │ Astronacci  │ │ Strategy    │                                    │
│  │ Engine      │ │ Selector    │                                    │
│  │ (989 baris) │ │             │                                    │
│  └──────┬──────┘ └──────┬──────┘                                    │
│         └───────────────┘                                           │
│                         ↓                                           │
│  SignalAggregator (causality-weighted)                              │
│    → regime-conditional weights (bull/bear/sideways/crisis)         │
│    → interdependency_matrix boost for global_market/relationship   │
│    → composite_signal = Σ(engine.signal × engine.weight)           │
│    → log_attribution() → signal_attribution_log table              │
│                                                                      │
│  Deep Learning Stack (Phase 2):                                      │
│    VAE → Transformer → LSTM → XGB+LGBM → TBL → ensemble            │
│    Device: cuda:1 (GTX 1050 Ti, 4GB VRAM)                          │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (event: signals.generated)
┌─────────────────────────────────────────────────────────────────────┐
│            LAYER 4: PORTFOLIO CONSTRUCTION & RISK                    │
│                                                                      │
│  Weight-Centric Pipeline (FinRL-X pattern):                          │
│    w_t = R_t(T_t(A_t(S_t(X_≤t))))                                  │
│                                                                      │
│  S_t: Stock Selection (signal > threshold, liquidity filter)        │
│  A_t: Portfolio Allocation                                           │
│    → HRP-µ (signal-aware Hierarchical Risk Parity, 222 baris)       │
│    → Risk-Constrained Kelly (quarter-Kelly with caps)               │
│    → RL Allocator (PPO/SAC, 328 baris) — Phase 3                    │
│    → Capital-Aware Sizer (421 baris)                                │
│  T_t: Timing Adjustment (KAMA trend overlay, regime gate)           │
│  R_t: Risk Overlay (VaR limit, drawdown control, concentration)     │
│                                                                      │
│  Monte Carlo VaR (portfolio/monte_carlo_var.py)                      │
│  HRP (1053 baris — full implementation with Garman-Klass,          │
│       cross-sectional kappa, baseline optimization)                 │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (event: portfolio.constructed)
┌─────────────────────────────────────────────────────────────────────┐
│              LAYER 5: EXECUTION & ORDER MANAGEMENT                   │
│                                                                      │
│  PaperTradingOMS (320 baris)                                         │
│    → submit_order() → RiskGate.check() → fill simulation            │
│    → slippage model (proportional to order size vs ADV)             │
│    → daily reconciliation (expected vs actual positions)            │
│                                                                      │
│  OMS State Machine (243 baris):                                      │
│    NEW → PENDING → PARTIAL → FILLED                                 │
│    NEW → PENDING → CANCELLED                                        │
│    NEW → PENDING → REJECTED                                         │
│                                                                      │
│  RiskGate (175 baris — fail-closed):                                 │
│    max_position_pct: 15% per ticker                                  │
│    max_sector_pct: 40% per sector                                    │
│    max_portfolio_var: 3% daily VaR                                   │
│    max_drawdown: 15% → halt all trading                             │
│    min_cash_reserve: 5%                                              │
│    max_single_order_value: 10% of NAV                                │
│    max_daily_turnover: 50% of portfolio                              │
│                                                                      │
│  Smart Order Router (384 baris — VWAP/TWAP algorithms)              │
│  Market Impact Model (332 baris)                                     │
│  Event Store (491 baris — append-only order/trade event log)        │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (event: orders.executed)
┌─────────────────────────────────────────────────────────────────────┐
│           LAYER 6: BACKTESTING & VALIDATION                          │
│                                                                      │
│  BacktestEngine (311 baris):                                         │
│    → next-bar-open execution (no look-ahead)                        │
│    → IDX costs: commission 0.15%, sales tax 0.1%, slippage 0.05%   │
│    → lot size 100 shares                                             │
│    → metrics: Sharpe, Sortino, max DD, win rate, DSR               │
│    → run_walk_forward() with purged train/test splits              │
│                                                                      │
│  WalkForwardOptimizer (289 baris):                                   │
│    → rolling train/test folds (252/63 days default)                 │
│    → embargo days (5) to prevent leakage                            │
│    → parameter stability analysis                                    │
│    → run_with_validation() → DSR + PBO                              │
│                                                                      │
│  DSR (Deflated Sharpe Ratio):                                        │
│    → corrects for multiple-testing bias and non-normality           │
│    → DSR > 0.95 = real edge                                          │
│                                                                      │
│  PBO (Probability of Backtest Overfitting):                          │
│    → CSCV-based overfitting detection                               │
│    → PBO < 0.5 = not overfit                                         │
│                                                                      │
│  RegimeConditionalEvaluator:                                         │
│    → per-regime: Sharpe, max DD, win rate, IC                       │
│    → regimes: bull, bear, sideways, crisis                          │
└─────────────────────────────────────────────────────────────────────┘
                    ↓ (event: backtest.validated)
┌─────────────────────────────────────────────────────────────────────┐
│         LAYER 7: EVALUATION, MONITORING & FEEDBACK LOOP              │
│                                                                      │
│  ICTracker (228 baris):                                              │
│    → IC = Spearman rank correlation (predicted vs actual returns)   │
│    → rolling IC with decay detection                                 │
│    → engine_summary() — per-engine IC/ICIR table                    │
│                                                                      │
│  DriftDetector (260 baris):                                          │
│    → PSI-based feature drift (PSI > 0.25 = significant)             │
│    → model drift (IC decay > 50% = retirement candidate)            │
│                                                                      │
│  ModelRetirementManager:                                             │
│    → criteria: min_track_record 126 days, min DSR 0.50,            │
│      max PBO 0.50, min IC 0.02, max IC decay 50%                    │
│    → evaluate() → KEEP / WATCH / RETIRE                              │
│                                                                      │
│  PredictionRealityTracker:                                           │
│    → track predicted vs actual N-day forward returns                │
│                                                                      │
│  TaskScheduler (243 baris):                                          │
│    → daily: data fetch (17:00), causality computation (17:15),      │
│      factor compute, signal generation (17:30), reconciliation      │
│    → weekly: backtest validation, model retirement check            │
│    → persistent state in scheduler_state table                       │
│                                                                      │
│  Alerts (monitoring/alerts.py):                                      │
│    → Telegram bot notifications                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. Aliran Data (Data Flow) — End-to-End

```
[External Sources]
    │
    ├── yfinance API ──── OHLCV (EOD + intraday 15min)
    ├── idx.co.id ─────── broker summary, corporate calendar, holidays
    ├── RSS feeds ─────── CNBC Indonesia, Detik, Kontan, Bisnis (TODO)
    ├── BPS/World Bank ── macro indicators (TODO)
    └── Bank Indonesia ── BI Rate, forex (TODO)
    │
    ▼
[Ingestion Layer]
    │
    ├── run_daily_fetch.sh (cron 17:00 WIB)
    │     └── yfinance → batch 50 → stock_prices (UPSERT ON CONFLICT)
    │
    ├── FetchRegistry
    │     └── get_pending_fetches() → filter by fetch_status
    │     └── mark_fetched() / mark_failed() → update instruments
    │
    └── PointInTimeQuery
          └── get_prices(ticker, as_of_date) — bitemporal, no look-ahead
          └── get_fundamentals(ticker, as_of_date)
          └── get_macro(series, as_of_date)
    │
    ▼
[Database — State Machine]
    │
    ├── instruments (1,137 rows)
    │     fetch_status: NEVER_FETCHED → STALE → OK → STALE (daily cycle)
    │     data_layer: idx_equity, global_index, commodity, fx, macro_rate
    │
    ├── stock_prices (3.58M rows, bitemporal with as_of_date)
    ├── foreign_flow (1.13M rows — IDX-specific)
    ├── macro_data (72,786 rows)
    ├── fundamental_data (10,839 rows)
    ├── news_sentiment (3,689 rows — IndoBERT scored)
    │
    ├── pipeline_state (NEW — per-ticker per-step tracking)
    │     status: pending → ingested → screened → analyzed → done
    │     error tracking: error_message, error_traceback, retry_count
    │
    ├── recompute_watermark (NEW — incremental checkpoint)
    │     (ticker, table_name) → last_processed_date
    │
    ├── global_market_interdependencies (NEW — causality matrix)
    │     source→target: correlation, Granger score, time-lag, impact
    │
    ├── global_market_interdependency_history (NEW — daily snapshots)
    │     historical causality metrics for time-series analysis
    │
    ├── feature_values (0 rows — awaiting first computation)
    ├── feature_definitions (0 rows — awaiting registration)
    ├── signal_attribution_log (0 rows — awaiting first signals)
    ├── prediction_evaluation (0 rows — awaiting first IC tracking)
    │
    └── scheduler_state (0 rows — awaiting task registration)
    │
    ▼
[Feature Engineering]
    │
    ├── FactorLibrary.compute() → feature_values table
    ├── Incremental: load_ohlcv_since(watermark) → bounded compute
    └── FeatureStore.freshness_report() → stale detection
    │
    ▼
[Signal Generation]
    │
    ├── 16+ engines produce SignalResult [-1, +1]
    ├── CausalityAnalyzer → Granger/VAR/CCF → interdependency matrix
    ├── SignalAggregator → regime-conditional + causality-weighted composite
    ├── log_attribution() → signal_attribution_log
    └── StrategySelector → best strategy per ticker
    │
    ▼
[Portfolio Construction]
    │
    ├── HRP-µ (signal-aware allocation)
    ├── Risk-Constrained Kelly (position sizing)
    ├── Monte Carlo VaR (risk estimation)
    └── Weight vector w_t output
    │
    ▼
[Execution]
    │
    ├── PaperTradingOMS → RiskGate → fill simulation
    ├── Smart Order Router (VWAP/TWAP)
    └── Event Store (append-only audit trail)
    │
    ▼
[Monitoring & Feedback]
    │
    ├── ICTracker → prediction_evaluation table
    ├── DriftDetector → PSI + IC decay
    ├── ModelRetirementManager → KEEP/WATCH/RETIRE
    └── PredictionRealityTracker → forward return comparison
    │
    ▼
[Frontend Visualization]
    │
    ├── Dashboard (page.tsx) — NAV, movers, IHSG chart, signals feed
    ├── Cosmos (cosmos/page.tsx) — Astronacci tata surya visualization
    ├── Signals page — signal display with attribution
    ├── Screener page — factor-based screening
    ├── Stock detail — per-engine attribution
    ├── Backtest page — walk-forward results, DSR/PBO
    ├── Portfolio page — HRP-µ allocation, VaR/ES
    ├── Data page — data source status
    ├── Scheduler page — task management
    ├── Reports page — performance reports
    └── Settings page — configuration
    │
    ├── WebSocket (/ws) — real-time ticks, signals, observability
    └── SSE (/api/observability/stream) — log stream
```

### 3. Ketergantungan Antar-Engine (Inter-engine Dependencies)

```
Data Ingestion
    ↓ depends_on: none
Feature Engineering (FactorLibrary)
    ↓ depends_on: stock_prices, fundamental_data, macro_data
Signal Generation (16 engines)
    ↓ depends_on: feature_values, news_sentiment, policy_events
    ↓ parallel execution — engines are independent
Signal Aggregation
    ↓ depends_on: all engine outputs + regime detection
Portfolio Construction (HRP-µ)
    ↓ depends_on: composite signals, covariance matrix
Risk Gate
    ↓ depends_on: portfolio weights, current positions, VaR
Paper Trading OMS
    ↓ depends_on: risk gate approval, market prices
IC Tracking
    ↓ depends_on: predictions, actual forward returns (T+5)
Drift Detection
    ↓ depends_on: rolling IC history, feature distributions
Model Retirement
    ↓ depends_on: DSR, PBO, IC decay, track record length
```

### 4. Batasan Sistem (System Constraints)

#### 4.1 Hardware Constraints

| Komponen | Spesifikasi | Implikasi |
|----------|-------------|-----------|
| **GPU** | 2x GTX 1050 Ti (4 GB VRAM, Pascal GP107, compute 6.1) | cuda:1 untuk compute, cuda:0 untuk display. VRAM terbatas → batch size kecil, mixed precision |
| **Display** | HDMI-0 1920x1080 (primary), HDMI-1-0 1440x900, DVI-D-1-0 1280x800 | Multi-monitor setup. Frontend harus ringan untuk rendering di layar Epson |
| **RAM** | ~16 GB (estimated) | Cukup untuk single-user, tidak untuk parallel backtest |
| **Storage** | PostgreSQL 1.29 GB | Masih kecil, akan tumbuh dengan feature_values & signal logs |

#### 4.2 Cross-Platform (Windows/Linux)

- `run_daily_fetch.sh` mendeteksi OS via `$OSTYPE` dan menggunakan path venv yang berbeda
- `quant.core.device` memilih CPU vs GPU berdasarkan workload size dan VRAM availability
- Forward-slash paths di semua Python modules (SQLAlchemy, psycopg2)
- Frontend Next.js berjalan di `localhost:3000` (dev mode)

#### 4.3 UI Rendering di Layar Epson

- Frontend menggunakan **CSS grid fixed layout** (no page scroll) — 7 widget zones
- `useFpsGuard` memantau FPS dan mengirim backpressure ke WebSocket server
- `useWsLatest` coalesces WS messages per animation frame (rAF)
- Recharts untuk visualisasi (ringan, SVG-based)
- Cosmos page menggunakan **Canvas 2D** untuk rendering tata surya (planet orbits, zodiac)
- Lucide icons (tree-shakeable, lightweight)

#### 4.4 CUDA Awareness

- `quant.core.device` (625 baris) — dynamic device dispatcher:
  - `select_device(workload_type, data_size)` → CPU or cuda:1
  - `vram_available()` → check free VRAM with 20% safety margin
  - `DeviceContext` — context manager untuk automatic tensor transfer
  - Benchmark: small data → CPU faster (transfer overhead), large data → GPU
- Config: `CUDA_DEVICE=cuda:1` (GPU 0 untuk display)
- PyTorch models (VAE, Transformer, LSTM) menggunakan `DeviceContext`

---

## [AI ROADMAP TO COMPLETION]

### Gap Analysis: Current State vs. Ideal State

| # | Komponen | Status Saat Ini | Target Ideal | Gap |
|---|----------|----------------|--------------|-----|
| 1 | **Data Ingestion** | yfinance only, cron script manual | Multi-source pipeline (yfinance + idx.co.id + RSS + BI + BPS) | Tambah adapter RSS, BI, BPS; integrasi FetchRegistry ke cron |
| 2 | **Feature Store** | FactorLibrary + FeatureStore code ready, 0 rows | feature_values terisi untuk semua ticker, incremental recompute | Jalankan compute_and_store() untuk 1,030 IDX tickers; isi feature_definitions |
| 3 | **Signal Engines** | 22 file, 6,680 baris — CausalityAnalyzer added (Granger+VAR+CCF) | Semua engine importable, causality-weighted aggregation | ✅ Causality engine implemented; fix remaining import issues |
| 4 | **DL Ensemble** | VAE, Transformer, LSTM, XGB-LGBM code ada | Trained models dengan IC > 0.02 | Train models pada cuda:1; validasi IC; integrate ke ensemble |
| 5 | **Portfolio** | HRP (1,053 baris), HRP-µ, Kelly, RL Allocator | HRP-µ terhubung ke signal aggregator | Wire HRP-µ ke composite signal output; test allocation |
| 6 | **Backtest** | Engine + WFO + DSR + PBO ready | Walk-forward results untuk semua strategies | Run backtest untuk top strategies; generate DSR/PBO report |
| 7 | **Execution** | PaperTradingOMS + RiskGate + Smart Order Router | Paper trading running daily dengan reconciliation | Wire OMS ke portfolio output; start daily paper trading loop |
| 8 | **Monitoring** | ICTracker, DriftDetector, Retirement, PredictionReality | IC tracking running, drift alerts active | Wire ICTracker ke signal output; start drift monitoring |
| 9 | **Scheduler** | TaskScheduler code ready, 0 rows in scheduler_state | Registered tasks running on schedule | Register tasks; start scheduler; persist state |
| 10 | **Pipeline State** | pipeline_state + recompute_watermark tables created | Active state tracking for all tickers | Integrate PipelineTracker into each pipeline step |
| 11 | **Frontend** | 10 pages, 7,897 baris — dashboard + cosmos working | All pages connected to API endpoints | Connect signals, backtest, portfolio, monitoring pages |
| 12 | **Alerts** | monitoring/alerts.py exists | Telegram alerts for risk breaches, drift, signal changes | Configure Telegram bot; wire alert triggers |
| 13 | **Sentiment** | SentimentEngine + SentimentAnalystAgent code ada | IndoBERT model loaded, news sentiment scored | Load IndoBERT model; score news_sentiment rows; integrate |
| 14 | **LLM Gateway** | LLMGateway (246 baris) — Ollama integration | LLM agents reasoning on market data | Configure Ollama model; test agent prompts; integrate to orchestrator |
| 15 | **Agentic AI** | 7 file, 1,643 baris — BaseAgent, CoderAgent, QAAgent, ArchitectAgent, MLMeta | Self-healing pipeline dengan AI debugging | Wire agentic agents to pipeline error tracking; test self-healing |

### Action Plan: 100% Benar & Siap Produksi

#### Phase A: Fix & Wire (Week 1) — P0

| # | Task | Module | Est. Effort |
|---|------|--------|-------------|
| A1 | Fix 12 signal engine import failures (class name mismatches) | `signals/*.py` | 2h |
| A2 | Register all signal engines in SignalAggregator | `signals/aggregator.py` | 1h |
| A3 | Wire FactorLibrary → FeatureStore → feature_values table | `features/` | 4h |
| A4 | Run initial feature computation for top 100 IDX tickers | `features/feature_store.py` | 2h |
| A5 | Register pipeline tasks in TaskScheduler | `monitoring/scheduler.py` | 2h |
| A6 | Wire PipelineTracker into each pipeline step | `pipeline/state_machine.py` | 3h |
| A7 | Connect HRP-µ to SignalAggregator output | `portfolio/hrp_mu.py` | 2h |
| A8 | Wire PaperTradingOMS to portfolio weight output | `execution/paper_trading.py` | 2h |
| A9 | Wire ICTracker to signal output + actual returns | `evaluation/ic_tracking.py` | 2h |
| A10 | Fix FetchRegistry integration with run_daily_fetch.sh | `scripts/`, `data/` | 1h |

#### Phase B: Data & Models (Week 2) — P1

| # | Task | Module | Est. Effort |
|---|------|--------|-------------|
| B1 | Build RSS feed adapter (CNBC, Detik, Kontan) | `data/rss_adapter.py` | 4h |
| B2 | Load IndoBERT model, score existing news_sentiment | `signals/sentiment.py` | 3h |
| B3 | Train VAE feature extractor on cuda:1 | `signals/vae.py` | 4h |
| B4 | Train LSTM predictor on cuda:1 | `signals/lstm.py` | 4h |
| B5 | Train XGBoost+LightGBM ensemble | `signals/xgb_lgbm.py` | 3h |
| B6 | Run Triple Barrier Labeling for IDX tickers | `signals/tbl.py` | 2h |
| B7 | Compute feature_values for all 1,030 IDX tickers | `features/` | 4h |
| B8 | Run initial signal generation for latest trading day | `signals/` | 2h |
| B9 | Run walk-forward backtest for top 5 strategies | `backtest/` | 4h |
| B10 | Compute DSR + PBO for backtest results | `evaluation/` | 2h |

#### Phase C: Production Hardening (Week 3) — P2

| # | Task | Module | Est. Effort |
|---|------|--------|-------------|
| C1 | Configure Ollama LLM model (deepseek-r1:1.5b or llama 3.1) | `ai/llm_gateway.py` | 1h |
| C2 | Test multi-agent pipeline (GiganticAI orchestrator) | `ai/orchestrator.py` | 3h |
| C3 | Start daily paper trading loop | `execution/` | 2h |
| C4 | Configure Telegram alerts | `monitoring/alerts.py` | 2h |
| C5 | Start drift detection monitoring | `monitoring/drift.py` | 2h |
| C6 | Start model retirement monitoring | `monitoring/retirement.py` | 1h |
| C7 | Connect all frontend pages to API endpoints | `frontend/` | 6h |
| C8 | Add pipeline status dashboard to frontend | `frontend/` | 2h |
| C9 | Write integration tests for end-to-end pipeline | `tests/` | 4h |
| C10 | Write production deployment guide | `docs/` | 2h |

#### Phase D: Advanced Features (Week 4+) — P3

| # | Task | Module | Est. Effort |
|---|------|--------|-------------|
| D1 | Build Bank Indonesia data adapter | `data/bi_adapter.py` | 3h |
| D2 | Build BPS/World Bank macro adapter | `data/bps_adapter.py` | 3h |
| D3 | Train RL Portfolio Allocator (PPO/SAC) | `portfolio/rl_allocator.py` | 6h |
| D4 | Implement LLM-guided factor discovery (Miner Agent) | `ai/miner_agent.py` | 4h |
| D5 | Wire Agentic AI self-healing to pipeline errors | `agentic/` | 4h |
| D6 | Implement DCC-GARCH cross-market model | `signals/dcc_garch.py` | 4h |
| D7 | Add satellite/weather data adapter (CPO, mining) | `data/satellite_fetcher.py` | 4h |
| D8 | Social media sentiment (Stockbit, X) | `data/social_fetcher.py` | 4h |

### Riset Internet: Benchmark Arsitektur SOTA

Dari riset arsitektur trading SOTA 2025-2026:

| Referensi | Insight | Relevansi ke `quant` |
|-----------|---------|---------------------|
| **AlphaCrafter** (arXiv:2605.05580) | Multi-agent: Miner → Screener → Trader dengan LLM-guided factor discovery | ✅ Sudah diadopsi di `ai/orchestrator.py` |
| **FinRL-X** (arXiv:2603.21330) | Weight-centric interface: w_t = R_t(T_t(A_t(S_t(X)))) | ✅ Sudah diadopsi sebagai design principle |
| **ATLAS** (arXiv:2510.15949) | Adaptive-OPRO: dynamic prompt optimization dari market feedback | ⬜ Tambahkan ke LLM Gateway |
| **AgenticAITA** (arXiv:2605.12532) | Z-Score trigger engine, mutex-based agent scheduling, deterministic safety gate | ⬜ Tambahkan inference gating |
| **Thales** (GitHub: BekOsu/Thales) | LSTM+XGBoost ensemble <300ms via gRPC, paper trading graduation system | ✅ LSTM+XGB ada; ⬜ tambah graduation criteria |
| **FinRL-DeepSeek** (arXiv:2502.07393) | CPPO for bear regime, PPO for bull | ⬜ Implement di RL Allocator |

### Key Gaps vs. SOTA

1. **No inference gating** — AgenticAITA menggunakan Z-Score trigger untuk gate LLM inference hanya pada anomali pasar. `quant` saat ini selalu menjalankan LLM jika available.
2. **No paper trading graduation** — Thales mensyaratkan Sharpe > 1.5, 50+ trades, win rate > 45%, max DD < 20% sebelum live trading. `quant` belum punya graduation system.
3. **No semantic caching** — Thales menggunakan semantic cache di LLM gateway. `quant` LLMGateway belum punya caching.
4. **No gRPC inference server** — Thales menggunakan gRPC untuk ML inference <300ms. `quant` menggunakan direct Python imports.
5. **No adaptive prompt optimization** — ATLAS menggunakan Adaptive-OPRO. `quant` menggunakan static system prompts.

### Estimated Completion

| Phase | Duration | Output |
|-------|----------|--------|
| **Phase A: Fix & Wire** | 1 week | All modules importable, pipeline wired end-to-end |
| **Phase B: Data & Models** | 1 week | Feature values computed, DL models trained, signals generated |
| **Phase C: Production Hardening** | 1 week | Paper trading running, monitoring active, frontend connected |
| **Phase D: Advanced** | 1-2 weeks | LLM agents active, RL allocator trained, self-healing pipeline |
| **Total** | 4-5 weeks | 100% production-ready |

---

### Arsitektur Target (Post-Completion)

```
┌──────────────────────────────────────────────────────────────────────┐
│                     GIGANTIC AI — PRODUCTION                          │
│                                                                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  │ MINER   │  │SCREENER │  │ TRADER  │  │  RISK   │  │SENTIMENT│   │
│  │ Agent   │→ │ Agent   │→ │ Agent   │→ │ MANAGER │→ │ Agent   │   │
│  │LLM factor│  │Regime-  │  │HRP-µ/RL │  │Fail-closed│ │IndoBERT │   │
│  │discovery│  │conditioned│  │allocator│  │VaR/ES   │  │NLP      │   │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │              PIPELINE STATE MACHINE (self-healing)            │    │
│  │  pipeline_state: pending → ingested → screened → analyzed    │    │
│  │                  → signal_generated → portfolio → done       │    │
│  │                  ↘ FAILED (error_message + traceback + retry)│    │
│  │  recompute_watermark: incremental checkpoint per ticker      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ BACKTEST │  │ MONITOR  │  │ ALERTS   │  │ SCHEDULER│            │
│  │ WFA+DSR  │  │ IC/Drift │  │ Telegram │  │ Cron+    │            │
│  │ PBO/CSCV │  │ Retirement│  │ Risk     │  │ Catch-up │            │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │         CROSS-ASSET CAUSALITY ENGINE (NEW)                   │    │
│  │  Granger Causality + VAR + CCF Time-Lag → Impact Weight      │    │
│  │  global_market_interdependencies (master) + history (child)  │    │
│  │  Scheduler: 17:15 WIB (before daily pipeline)                │    │
│  │  Decision engine: causality-weighted signal aggregation      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  Hardware: 2x GTX 1050 Ti (cuda:1 compute, cuda:0 display)          │
│  Display: Epson HDMI-0 1920x1080 (primary)                           │
│  DB: PostgreSQL 16 (30 tables, 73 indexes, 1.29 GB)                 │
│  Frontend: Next.js 16 (cosmos + dashboard, WebSocket + SSE)          │
└──────────────────────────────────────────────────────────────────────┘
```

---

**Dokumen ini adalah hasil analisis mendalam sebagai Lead AI Software Architect untuk aplikasi `quant`. Semua data bersumber dari codebase aktual (110+ Python files, 25,000+ baris), database live (30 tabel, 3.58M OHLCV rows), dan riset internet arsitektur SOTA 2025-2026.**
