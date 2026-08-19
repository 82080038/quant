# Engine/Module Audit Matrix — Full Quant Trading Pipeline

## Status: RENOVATION ACTIVE — Clean slate build from audit findings
## Date: 2026-08-19 (updated 2026-08-20 — causality engine added)

> **Note:** Dokumen ini adalah audit matriks yang dipindahkan dari aplikasi `market` (`/home/petrick/projects/market/`). Aplikasi `quant` dibangun berdasarkan temuan audit ini dengan perbaikan arsitektur 7-layer pipeline.


---

## Daftar Isi

### Part I: Pipeline Architecture
1. [Pipeline Architecture Overview](#1-pipeline-architecture-overview)
2. [Inventarisasi Engine & Modul](#2-inventarisasi-engine--modul)
3. [Riset: Modul Ideal untuk Quant Trading IDX](#3-riset-modul-ideal-untuk-quant-trading-idx)

### Part II: Layer-by-Layer Audit
4. [Layer 1: Data Fetch & Ingestion](#4-layer-1-data-fetch--ingestion)
5. [Layer 2: Recompute & Feature Engineering](#5-layer-2-recompute--feature-engineering)
6. [Layer 3: Signal Generation — 16 Engines](#6-layer-3-signal-generation--16-engines)
   - 6.1 [Technical Engine](#61-technical-engine)
   - 6.2 [Fundamental Engine](#62-fundamental-engine)
   - 6.3 [Macro Engine](#63-macro-engine)
   - 6.4 [Sentiment Engine](#64-sentiment-engine)
   - 6.5 [Relationship Engine](#65-relationship-engine)
   - 6.6 [Global Market Engine](#66-global-market-engine)
   - 6.7 [Alpha Mean Reversion](#67-alpha-mean-reversion)
   - 6.8 [Alpha Short-Term Reversal](#68-alpha-short-term-reversal)
   - 6.9 [Alpha EWMA Momentum](#69-alpha-ewma-momentum)
   - 6.10 [Alpha Regime Switch](#610-alpha-regime-switch)
   - 6.11 [Astronacci](#611-astronacci)
   - 6.12 [Volume Features](#612-volume-features)
   - 6.13 [Policy Event Scorer](#613-policy-event-scorer)
   - 6.14 [Holiday Effect](#614-holiday-effect)
   - 6.15 [Fama-French 5-Factor](#615-fama-french-5-factor)
   - 6.16 [HMM Regime Detector](#616-hmm-regime-detector)
7. [Layer 4: Portfolio Construction & Risk](#7-layer-4-portfolio-construction--risk)
   - 7.1 [HRP — Hierarchical Risk Parity](#71-hrp--hierarchical-risk-parity)
   - 7.2 [Deflated Sharpe Ratio (DSR)](#72-deflated-sharpe-ratio-dsr)
   - 7.3 [PBO — Probability of Backtest Overfitting](#73-pbo--probability-of-backtest-overfitting)
   - 7.4 [Kelly Criterion & Position Sizing](#74-kelly-criterion--position-sizing)
   - 7.5 [Monte Carlo VaR](#75-monte-carlo-var)
8. [Layer 5: Execution & Order Management](#8-layer-5-execution--order-management)
9. [Layer 6: Backtesting & Validation](#9-layer-6-backtesting--validation)
10. [Layer 7: Evaluation, Monitoring & Feedback Loop](#10-layer-7-evaluation-monitoring--feedback-loop)

### Part III: Synthesis & Action
11. [Data Inventory & Gaps](#11-data-inventory--gaps)
12. [Metodologi Pengujian](#12-metodologi-pengujian)
13. [Decision Matrix — Full Pipeline](#13-decision-matrix--full-pipeline)
14. [Renovation Plan](#14-renovation-plan)
15. [References](#15-references)

---

## 1. Pipeline Architecture Overview

### A. Arsitektur Current — Event-Driven 7-Phase Pipeline

Sistem saat ini menggunakan **event-driven architecture** dengan pub/sub broker (`src/market/core/wiring.py`). 7 phase berjalan secara berurutan setiap hari bursa:

```
PHASE 1: FETCH          → DataFetchPipeline (yfinance, IDX API, FRED)
    data.fetch.requested        → IDX equities OHLCV
    data.fetch_global.requested → 25 global indices
    data.fetch_commodity.requested → 6 commodity futures
    data.fetch_macro.requested  → macro rates → macro_data
    data.fetch_fx.requested     → 61 FX pairs
    data.fetch.intraday.requested → 15-min polling
    Emits: data.fetch.stored (NO auto-trigger recompute)

PHASE 2: RECOMPUTE      → RecomputePipeline (18 functions)
    data.recompute.requested   → run_all_recompute()
    9 core: technical_indicators, scores, relationship_matrix, cross_market,
            fear_greed, stock_personality, ml_labels, market_regimes, weights
    9 advanced: holiday_effects, instrument_profiles, cross_market_coefficients,
                dcc_garch, seasonal_patterns, macro_correlation,
                causal_relationships, satellite_correlation, astronacci_cycles
    RecomputeGraph: selective recompute based on data dependencies
    Emits: data.recompute.completed

PHASE 3: EXPORT         → ExportPipeline (DB → Parquet)
    data.export.requested      → sync_to_parquet
    Emits: data.export.completed

PHASE 4: HEALTH         → HealthPipeline
    data.export.completed      → health check
    Emits: health.check.completed

PHASE 5: ALERTS         → AlertPipeline
    data.recompute.completed   → alert evaluation (56 alert types)
    Emits: alert.check.completed

PHASE 6: SIGNALS        → SignalPipeline (subprocess → daily_signal_cron.py)
    signal.generate.requested  → 4-module signal generation:
        Module 1: Config loader (best_ticker_quant_config.json)
        Module 2: EOD data ingestion (300-day lookback)
        Module 3: Live signal processing (generate_ticker_signals)
        Module 4: App notification injection (app_notifications table)
    Emits: signal.generate.completed

PHASE 7: NOTIFICATIONS  → NotificationPipeline (terminal)
    alert.check.completed      → notification
    signal.generate.completed  → notification
```

**File kunci:**
- `src/market/core/wiring.py` — event wiring (55 lines, single place for module coupling)
- `src/market/core/events.py` — pub/sub broker
- `src/market/scheduler_tasks.py` — 1789 lines, all scheduled tasks
- `scripts/run_daily_scheduler.sh` — cron entry point (17:00 WIB Mon-Fri)

### B. Arsitektur Ideal — 7-Layer Quant Trading Pipeline (Industry Best Practice)

Berdasarkan riset terbaru (Algovantis 2024, Micro Alphas 2024, NautilusTrader, NexusFi 2024, Lycore 2024):

```
Layer 1: Data Ingestion
    → Point-in-time (bitemporal) storage — "what was known and when"
    → Validation, anomaly detection, deduplication
    → Circuit breaker pattern untuk fault tolerance
    → Backpressure management (ring buffer / bounded queue)

Layer 2: Feature Engineering (Factor Library)
    → Versioned, tested factor components — bukan ad-hoc computation
    → Point-in-time correctness: factor hanya menggunakan data available at t
    → Freshness monitoring (STALE/EXPIRED detection)
    → Dependency graph untuk selective recompute

Layer 3: Signal Generation
    → Continuous signals (expected returns), bukan binary BUY/SELL
    → Ensemble approach: multiple models → model averaging
    → Walk-forward validated sebelum deployment
    → Backtest-live parity: same logic, same data versions → same results

Layer 4: Portfolio Construction
    → Risk-constrained optimization (HRP, MinVar, atau hybrid)
    → Position sizing dengan Kelly/fractional Kelly + drawdown constraints
    → Rebalance threshold (drift-based, tidak setiap hari)
    → Transaction cost-aware optimization

Layer 5: Execution
    → Order Management System (OMS) sebagai source of truth untuk state
    → Smart Order Router (SOR) untuk best execution
    → Pre-trade risk checks (hard gate, fail-closed)
    → Market impact model untuk size-aware execution

Layer 6: Backtesting
    → Event-driven engine (bukan vectorised saja) untuk realistic execution
    → Next-bar-open execution (no look-ahead bias)
    → Transaction costs: commission 0.15%, sales tax 0.1%, slippage
    → Walk-forward optimization dengan embargo period
    → DSR/PBO multiple testing correction

Layer 7: Monitoring & Feedback
    → Drift detection (PSI pada predictions, features, metrics)
    → Prediction vs Reality comparison (forward return vs predicted direction)
    → Signal attribution log (which engine contributed to which decision)
    → Automated alerting ketika performance degrades
    → Model retirement criteria (MinTRL, DSR threshold)
```

### C. Gap Analysis: Current vs Ideal

| Layer | Current Status | Ideal | Gap |
|-------|---------------|-------|-----|
| 1. Data Ingestion | yfinance + IDX API + FRED, retry dengan backoff | Point-in-time bitemporal, anomaly detection, circuit breaker | **TIDAK ADA point-in-time storage, tidak ada tick validation, tidak ada circuit breaker** |
| 2. Feature Engineering | 18 recompute functions, RecomputeGraph, FeatureStore | Versioned factor library, point-in-time correctness, freshness monitoring | **FeatureStore ada tapi tidak terintegrasi penuh, factor tidak versioned, tidak ada point-in-time guarantee** |
| 3. Signal Generation | 16 engines, dry-run tested, backfill script | Continuous signals, ensemble, walk-forward validated, backtest-live parity | **Sinyal masih binary (UP/DOWN/FLAT), tidak ada ensemble weighting, tidak ada walk-forward validation per engine** |
| 4. Portfolio Construction | HRP dengan IV fix, Kelly quarter, VaR 10K MC | Risk-constrained Kelly, HRP Topdown, rebalance threshold, cost-aware | **HRP belum Topdown, Kelly belum risk-constrained, tidak ada cost-aware optimization** |
| 5. Execution | AutomationOrchestrator, MockBroker, OMS, SOR | Real broker adapter, fail-closed risk gate, market impact model | **MockBroker only, tidak ada real broker, risk gate tidak fail-closed, market impact model ada tapi tidak terintegrasi** |
| 6. Backtesting | Event-driven engine, walk-forward optimizer | DSR/PBO integration, vectorised + event-driven, cost modeling | **Tidak ada DSR/PBO, tidak ada vectorised engine, walk-forward tidak terintegrasi dengan engine selection** |
| 7. Monitoring | DriftDetector (PSI), attribution log, prediction accuracy | Real-time monitoring, automated retirement, signal decay detection | **Drift detection ada tapi tidak real-time, tidak ada automated retirement, tidak ada signal decay tracking** |

### D. Key Architectural Principles (Micro Alphas 2024)

1. **Point-in-time (bitemporal) data is the foundation** — "storing what was known and when is the single most important defence against lookahead bias"
2. **Versioned factor library** — "turns one-off research into reusable, tested building blocks and stops the same signal being re-implemented inconsistently"
3. **Backtest-live parity** — "the same logic and the same data versions must produce the same results"
4. **Monitoring closes the loop** — "live performance is compared against backtest expectations so decay is detected early rather than discovered in the P&L"
5. **Fail closed** — "when the system doesn't know its current state, it stops trading, not continues with potentially corrupt state" (NexusFi 2024)
6. **Separation of concerns** — "strategy engine shouldn't know how orders are routed; execution system shouldn't care what signal generated the order" (Brenndoerfer 2024)

---

## 2. Inventarisasi Engine & Modul

### A. Engine yang Menghasilkan Sinyal Direksional (16 di backfill)

| # | Engine | File | Sinyal | Status Dry-Run |
|---|--------|------|--------|----------------|
| 1 | technical | `technical.py` | Trend/RSI/MACD/BB/ATR → score 0-100 | ACTIVE (9 UP, 34 DOWN, 7 FLAT) |
| 2 | fundamental | `fundamental.py` | P/E, P/B, ROE, debt ratio → score | ACTIVE (50 UP — all bullish) |
| 3 | macro | `macro.py` | US10Y, gold, oil, USD/IDR → regime | ACTIVE (50 UP — all bullish) |
| 4 | sentiment | `sentiment.py` | News + foreign_flow → score | 96% FLAT (signal too weak) |
| 5 | relationship | `relationship.py` | Cross-market correlation → score | ACTIVE (50 UP) |
| 6 | global | `global_market.py` | Global index signals → score | ACTIVE (35 DOWN, 15 FLAT) |
| 7 | alpha_mean_reversion | `alpha_signals.py` | BB + RSI → [-1,+1] | 96% FLAT (conditions too strict) |
| 8 | alpha_reversal | `alpha_signals.py` | Z-score reversal + holding period | 74% FLAT (Z-threshold too high) |
| 9 | alpha_ewma_momentum | `alpha_signals.py` | EWMA 20/50 crossover | ACTIVE (22 UP, 27 DOWN) |
| 10 | alpha_regime_switch | `alpha_signals.py` | Vol regime → momentum/reversion | ACTIVE (47 UP, 3 DOWN) |
| 11 | astronacci | `astronacci.py` | Astrology cycles + Fibonacci | ACTIVE (39 UP, 11 DOWN) |
| 12 | volume | `volume_features.py` | OFI + VWAP deviation | ACTIVE (29 UP, 16 DOWN, 5 FLAT) |
| 13 | policy_event | `policy_event_scorer.py` | Policy/external events → signal | ACTIVE (50 DOWN — all bearish) |
| 14 | holiday_effect | backfill (direct query) | Pre/post-holiday effect | CONTEXTUAL (FLAT when no holiday) |
| 15 | fama_french_5f | `fama_french.py` | 5-factor exposure → signal | ACTIVE |
| 16 | hmm_regime | `hmm_regime.py` | HMM volatility regime → signal | ACTIVE (25 UP, 25 DOWN — fallback) |

### B. Engine Lain yang Tidak Masuk Backfill (43 modul)

| Category | Modules | Notes |
|----------|---------|-------|
| **ML/Deep Learning** | `lstm_predictor.py`, `ml_signal.py`, `prediction.py` | LSTM trained, but too expensive for batch |
| **Risk/Portfolio** | `multi_factor.py`, `meta_labeling.py`, `walk_forward.py`, `attribution.py` | Evaluation/risk tools |
| **Cross-Market** | `cross_market_coefficients.py`, `cross_market_timezone.py`, `spillover_lab.py`, `macro_correlation.py` | Correlation analysis |
| **Alternative Data** | `google_trends.py`, `social_sentiment.py`, `news_features.py`, `denoised_news.py` | Alternative signals |
| **Pattern/Strategy** | `pattern_detector.py`, `pairs_trading.py`, `sector_rotation.py`, `strategy_selector.py` | Strategy modules |
| **Infrastructure** | `recompute*.py`, `profiling.py`, `weight_registry.py`, `explainability.py` | Pipeline infrastructure |
| **Other** | `astronacci.py`, `holiday_effect.py`, `delisting_memory.py`, `execution_analyzer.py`, `vta_reasoning.py`, `causal_discovery.py`, `extras.py` | Various |

---

## 3. Riset: Modul Ideal untuk Quant Trading IDX

### Sumber Riset:
- FinRL-X (arxiv 2026) — modular trading architecture
- ML4T Diagnostic — DSR, PBO, walk-forward, HAC IC
- Framler Methodology — Bayesian factor framework, BOCPD regime
- systematic-alpha-lab — factor research pipeline
- wraquant — 38+ regime detection functions, 263 indicators
- oos-lab — PSR, DSR, PBO, haircut Sharpe
- IDX-specific: LQ45 ML prediction, behavioral-fundamental PCA, macro-JCI regression

### Modul Esensial untuk Quant Trading IDX (Swing Trading, EOD):

| Priority | Module Category | Specific Modules | Rationale |
|----------|----------------|------------------|-----------|
| **P0: Core** | Factor Models | Fama-French 5F/6F, Momentum, Value, Quality, Low-Vol | Academic consensus: factor-based investing works in emerging markets |
| **P0: Core** | Mean Reversion | Short-term reversal, RSI+BB | IDX exhibits strong mean-reversion (IC negatif untuk momentum) |
| **P0: Core** | Regime Detection | HMM or BOCPD volatility regime | Regime-aware factor weighting |
| **P0: Core** | Sentiment | News sentiment, foreign flow | IDX: foreign flow is key driver; sentiment-price correlation documented |
| **P1: Important** | Macro Overlay | BI rate, USD/IDR, VIX, commodities | Macro indicators stronger than technical for IDX (multiple studies 2024-2025) |
| **P1: Important** | Cross-Market | Global index correlation, commodity linkage | IDX correlated with global indices, especially Asia |
| **P1: Important** | Volume/Flow | OFI, VWAP, foreign flow | Foreign flow is key driver in IDX |
| **P1: Important** | Event Signals | Policy events, corporate calendar | Event-driven alpha in emerging markets |
| **P2: Optional** | Pairs Trading | Cointegration z-score | Works in IDX but limited universe |
| **P2: Optional** | Sector Rotation | Sector momentum | IDX has 12 sectors, rotation effect documented |
| **P2: Optional** | Holiday Effect | Pre/post-holiday | Pre-holiday effect documented in IDX (Sasikirono & Meidiawati 2017) |
| **P3: Experimental** | Astronacci | Astrology + Fibonacci | No academic backing; IC negative = inverted or noise |
| **P3: Experimental** | LSTM/ML | Deep learning prediction | R² near-zero for LQ45 (MDPI 2025), but may work as ensemble |

### Modul Evaluasi yang Wajib Ada:

| Module | Purpose | Reference |
|--------|---------|-----------|
| **Deflated Sharpe Ratio** | Correct for multiple testing | Bailey & López de Prado 2014 |
| **PBO (CSCV)** | Probability of Backtest Overfitting | Bailey et al. 2014 |
| **Walk-Forward Validation** | Out-of-sample testing | Pardo 1992/2008 |
| **IC Analysis (HAC-adjusted)** | Information Coefficient with robust SE | ML4T Diagnostic |
| **MinTRL** | Minimum Track Record Length | Bailey & López de Prado 2012 |
| **Haircut Sharpe** | Harvey-Liu multiple testing correction | Harvey & Liu 2015 |

---

## 4. Layer 1: Data Fetch & Ingestion

### A. Current Implementation

**File:** `src/market/pipelines/data_fetch.py` (30K lines), `src/market/data/fetch_registry.py`

DataFetchPipeline adalah **satu-satunya modul** yang berkomunikasi dengan external data sources. Pipeline ini fetch:
- IDX equities OHLCV (yfinance, ~1030 tickers)
- Global indices (25 tickers: ^GSPC, ^DJI, ^N225, dll)
- Commodity futures (6: gold, oil, CPO, dll)
- Macro rates (FRED: US10Y, BI rate, inflation)
- FX pairs (61 pairs, termasuk USD/IDR)
- Intraday 15-min polling (untuk day trading monitoring)

**Fitur existing:**
- Retry dengan exponential backoff untuk transient errors
- FetchRegistry: DB-as-source-of-truth untuk data fetching routing
- `idx_adapter.py`: IDX Official Adapter via cloudscraper (idx.co.id API)
- `timestamp_validation.py`: validasi timestamp data
- `refresh_stale.py`: deteksi dan refresh stale data

### B. Evaluasi Akademik & Praktis

#### Kritik & Kelemahan

1. **Tidak ada point-in-time (bitemporal) storage** — Ini adalah **kelemahan arsitektur paling fundamental**. Micro Alphas (2024): "storing what was known and when is the single most important defence against lookahead bias." Sistem saat ini hanya menyimpan latest value, tidak ada revision history. Fundamental data yang direvisi, macro data yang restated, dan price adjustments untuk corporate actions — semuanya tidak tracked secara bitemporal.

2. **Tidak ada tick-level anomaly detection** — White Oak Intelligence (2024): "Raw market data contains bad ticks: erroneous prints from exchange matching engine glitches, crossed markets, price spikes 3σ outside recent distribution." Sistem tidak ada rolling Z-score validation, tidak ada crossed-market detection.

3. **Tidak ada circuit breaker pattern** — NexusFi (2024): "A circuit breaker prevents a failing downstream system from dragging down the entire pipeline." Jika DB write gagal, tidak ada Open/Half-Open/Closed state machine untuk graceful degradation.

4. **Tidak ada backpressure management** — yfinance API rate limit ditangani dengan retry, tapi tidak ada bounded queue/ring buffer untuk handle burst data.

5. **yfinance reliability** — yfinance adalah unofficial API, sering break ketika Yahoo Finance mengubah endpoint. Tidak ada SLA guarantee.

6. **Corporate actions handling** — Stock splits dan dividends di-adjust oleh yfinance, tapi tidak ada audit trail untuk verify adjustment correctness.

#### Perbaikan & Best Practices

1. **Point-in-Time Database Schema** (Micro Alphas 2024):
   ```
   stock_prices_point_in_time:
       ticker, date, ohlcv, 
       as_of_date (kapan data ini diketahui),
       is_revised (bool), revised_from (FK)
   ```
   - Setiap query backtest menggunakan `WHERE as_of_date <= backtest_date`
   - Fundamental data: simpan both as-reported dan revised values

2. **Tick Validation Pipeline** (White Oak 2024):
   - Rolling Z-score: `z = (price - μ_20) / σ_20`, reject if |z| > 4.0
   - Crossed market detection: reject if bid >= ask
   - Volume anomaly: flag if volume > 10× 20-day median

3. **Circuit Breaker** (NexusFi 2024):
   - Open: short-circuit all downstream calls for cooldown (60s)
   - Half-Open: allow 1 test call, success → Closed, failure → Open
   - Closed: normal operation

4. **Multi-Source Redundancy**:
   - Primary: yfinance (free, unreliable)
   - Secondary: IDX Official API (`idx_adapter.py`, sudah ada)
   - Tertiary: Polygon.io atau Alpaca API (paid, reliable)
   - Cross-validate: jika 3 source berbeda > 1%, flag untuk review

5. **Data Quality Scoring**:
   - Completeness: % expected tickers fetched
   - Timeliness: lag antara market close dan data available
   - Accuracy: cross-check dengan IDX official closing prices
   - Consistency: OHLCV relationships (high >= max(open,close), dll)

### C. Status Implementasi

- **Existing:** Functional pipeline dengan retry, FetchRegistry, IDX adapter
- **Missing:** Point-in-time storage, anomaly detection, circuit breaker, multi-source redundancy
- **Keputusan:** **FIX (P1)** — Implement point-in-time schema untuk fundamental_data dan macro_data (paling critical untuk backtest validity). Tambah tick validation untuk real-time pipeline. Circuit breaker untuk fault tolerance.

---

## 5. Layer 2: Recompute & Feature Engineering

### A. Current Implementation

**Files:**
- `src/market/analysis/recompute.py` (1433 lines) — 9 core recompute functions
- `src/market/analysis/recompute_advanced.py` — 9 advanced recompute functions
- `src/market/analysis/recompute_graph.py` (557 lines) — dependency graph untuk selective recompute
- `src/market/analysis/recompute_estimator.py` — duration/row prediction
- `src/market/analysis/recompute_analyzer.py` (644 lines) — prediction accuracy evaluation
- `src/market/mlops/feature_store.py` (383 lines) — feature registration, caching, freshness monitoring
- `src/market/pipelines/recompute.py` (76 lines) — pipeline wrapper

**18 Recompute Functions:**

| # | Function | Output Table | Type | Incremental? |
|---|----------|-------------|------|-------------|
| 1 | recompute_technical_indicators | technical_indicators | Snapshot | No (full) |
| 2 | recompute_scores | scores | Snapshot | No (full) |
| 3 | recompute_relationship_matrix | relationship_matrix | Snapshot | No (full) |
| 4 | recompute_cross_market | cross_market_stats | Snapshot | No (full) |
| 5 | recompute_fear_greed | fear_greed | Time-series | Yes (append) |
| 6 | recompute_stock_personality | stock_personality | Snapshot | No (full) |
| 7 | recompute_ml_labels | ml_labels | Time-series | Yes (append) |
| 8 | recompute_market_regimes | market_regimes | Time-series | Yes (append) |
| 9 | recompute_weights | signal_weights | Snapshot | No (full) |
| 10 | recompute_holiday_effects | holiday_effects | Snapshot | No |
| 11 | recompute_instrument_profiles | instrument_behavior_profiles | Snapshot | No |
| 12 | recompute_cross_market_coefficients | cross_market_coefficients | Snapshot | No |
| 13 | recompute_dcc_garch | dcc_garch_params | Snapshot | No |
| 14 | recompute_seasonal_patterns | seasonal_patterns | Snapshot | No |
| 15 | recompute_macro_correlation | macro_correlation | Snapshot | No |
| 16 | recompute_causal_relationships | causal_relationships | Snapshot | No |
| 17 | recompute_satellite_correlation | satellite_correlation | Snapshot | No |
| 18 | recompute_astronacci_cycles | astronacci_cycles | Snapshot | No |

**RecomputeGraph features:**
- Dependency mapping: function_name → data_source (many-to-many)
- Selective recompute: only run functions affected by updated data source
- Smart skip: skip functions where data hasn't changed (via watermark)
- Duration prediction: `RecomputeEstimator` predicts duration and row count
- Feedback loop: `RecomputeAnalyzer` evaluates prediction accuracy

**FeatureStore features:**
- Feature definition and registration (RSI, SMA, BB, ATR, volume_ratio, forward_return)
- In-memory caching with freshness monitoring (FRESH/STALE/EXPIRED/MISSING/ERROR)
- Versioning support (feature@version)
- `evict_stale()` untuk automatic cache cleanup

### B. Evaluasi Akademik & Praktis

#### Kelebihan

1. **Selective recompute via dependency graph** — Ini adalah best practice. Micro Alphas (2024): "A versioned factor library turns one-off research into reusable, tested building blocks." RecomputeGraph mendekati ini dengan dependency tracking.
2. **Incremental support** — Time-series tables support append-only mode, menghindari full recompute setiap hari.
3. **Freshness monitoring** — FeatureStore memiliki FRESH/STALE/EXPIRED detection (Gap #36).
4. **Prediction feedback loop** — RecomputeAnalyzer evaluates prediction accuracy (duration, rows), closing the loop.

#### Kritik & Kelemahan

1. **FeatureStore tidak terintegrasi penuh** — FeatureStore ada tapi tidak digunakan oleh recompute pipeline. Recompute functions compute features ad-hoc, bukan melalui FeatureStore. Micro Alphas (2024): "stops the same signal being re-implemented inconsistently" — saat ini, same indicator bisa di-compute berbeda di different places.

2. **Factor tidak versioned** — Saat definition RSI berubah (e.g., dari SMA-based ke EMA-based), tidak ada version tracking. Old backtest results become irreproducible. Micro Alphas (2024): "when a factor's definition changes, prior results remain reproducible because the old version is preserved."

3. **Tidak ada point-in-time guarantee** — Recompute functions menggunakan latest available data, bukan data available at timestamp t. Ini bisa cause lookahead bias dalam backtest.

4. **18 functions = monolithic recompute** — `run_all_recompute()` runs all 9 core functions sequentially. Jika satu gagal, others masih jalan tapi error handling tidak ideal untuk production.

5. **GPU utilization tidak optimal** — `select_device()` dipanggil per function, tapi tidak ada parallel execution across functions.

6. **Technical indicators di DB sebagai snapshot** — `technical_indicators` table hanya simpan latest values per ticker. Historical technical indicator values tidak tersimpan — harus recompute setiap kali backtest.

#### Perbaikan & Best Practices

1. **Integrate FeatureStore dengan Recompute** (Micro Alphas 2024):
   - Setiap recompute function should register its features dengan FeatureStore
   - Feature definitions versioned: `rsi_14@1.0.0` vs `rsi_14@2.0.0`
   - Backtest dapat request specific version → reproducibility

2. **Point-in-Time Feature Computation**:
   - Untuk setiap date t, recompute hanya menggunakan data dengan `as_of_date <= t`
   - Store historical feature values: `feature_values(ticker, date, feature_name, value, as_of_date)`

3. **Store Historical Technical Indicators**:
   - Ubah `technical_indicators` dari snapshot ke time-series table
   - Simpan daily technical indicator values → tidak perlu recompute untuk backtest
   - Trade-off: storage vs compute time (~9K rows/day × 250 days = 2.25M rows/year)

4. **Parallel Recompute**:
   - Functions without dependencies dapat run in parallel
   - Gunakan `concurrent.futures.ProcessPoolExecutor` untuk CPU-bound functions
   - GPU functions (DCC-GARCH, astronacci) run on cuda:1

5. **Feature Registry sebagai Code** (Micro Alphas 2024):
   ```python
   @register_feature(name="rsi_14", version="1.0.0", dependencies=["close"])
   def compute_rsi(df: pd.DataFrame) -> pd.Series:
       ...
   ```
   - Unit test per feature
   - CI: verify feature stability (PSI < 0.1 between versions)

### C. Status Implementasi

- **Existing:** 18 recompute functions, RecomputeGraph, FeatureStore (partial), prediction feedback loop
- **Missing:** FeatureStore integration, factor versioning, point-in-time guarantee, historical indicator storage, parallel execution
- **Keputusan:** **FIX (P1)** — Integrate FeatureStore, add factor versioning, store historical technical indicators, implement point-in-time feature computation for backtest correctness

---

## 6. Layer 3: Signal Generation — 16 Engines

Setiap engine dianalisis berdasarkan: (a) persamaan matematis, (b) perbandingan model, (c) penerapan praktis, (d) kritik & kelemahan, (e) perbaikan dari akademik & industri, (f) status implementasi.

---

### 6.1 Technical Engine

**File:** `src/market/analysis/technical.py` | **Sumber:** Murphy (1999), Caporale & Plastun (2024, CESifo WP 10213)

#### Persamaan Matematis

- **RSI:** `RSI = 100 - 100/(1 + RS)`, `RS = AvgGain(n)/AvgLoss(n)`, n=14
- **MACD:** `MACD = EMA(12) - EMA(26)`, Signal = `EMA(9, MACD)`
- **Bollinger Bands:** `BB_upper = SMA(20) + 2σ`, `BB_lower = SMA(20) - 2σ`
- **ATR:** `ATR = EMA(14, TrueRange)`, `TrueRange = max(H-L, |H-C_prev|, |L-C_prev|)`

#### Perbandingan Model

| Model | Kelebihan | Kelemahan |
|-------|-----------|-----------|
| MA Crossover | Sederhana, robust | Lagging, false signals di sideways |
| RSI | Good for OB/OS | Divergensi tidak selalu reversal |
| MACD | Trend + momentum | Whipsaw di ranging market |
| BB | Volatility-adaptive | Sensitive to parameter choice |

#### Kritik & Kelemahan

1. **Data Snooping (Caporale & Plastun 2024):** Dari 6,406 technical trading rules di 41 pasar, mayoritas profit "illusory" setelah koreksi data snooping (Hsu et al. 2010, Stepwise SPA). Technical analysis dikategorikan "voodoo finance" dari academic perspective
2. **Profitabilitas menurun:** Emerging markets predictable hingga 2002-2008, hampir semua unpredictable post-2009 (Adaptive Market Hypothesis, Lo 2004)
3. **Subjektivitas:** Interpretasi pola chart tidak reproducible
4. **Transaksi costs:** Ribuan strategi profitable sebelum biaya, unprofitable setelahnya
5. **BRICS study (2025):** EMA, RSI, MACD gagal menghasilkan alpha positif vs buy-and-hold di BRICS post-COVID

#### Perbaikan & Improvements

1. **Stepwise SPA Test (Hsu et al. 2010):** Multiple hypothesis testing correction wajib saat menguji banyak technical rules
2. **Adaptive parameters:** Parameter dinamis berdasarkan regime (volatility-adjusted lookback)
3. **ML ensemble (Gu et al. 2020):** ML dapat mengekstrak sinyal non-linear dari technical features
4. **Mean-reversion mode:** Untuk IDX (5-day horizon), invert momentum signals → mean-reversion (IC negatif → kontrarian)

#### Status Implementasi
- **Dry-run:** 9 UP, 34 DOWN, 7 FLAT — sinyal aktif dan bervariasi
- **Keputusan:** KEEP dengan inverted signal, perlu DSR correction untuk 120+ indicators

---

### 6.2 Fundamental Engine

**File:** `src/market/analysis/fundamental.py` | **Sumber:** Fama & French (1993, 2015), Cao & You (2024), CEPR DP19320 (2024)

#### Persamaan Matematis

- **P/B-ROE Model:** `Expected Return = f(P/B, ROE)` — saham "cheap" dengan ROE tinggi = undervalued
- **Residual Income Model:** `V₀ = B₀ + Σ(RI_t / (1+r)^t)`, `RI_t = EPS_t - r × B_{t-1}`
- **Piotroski F-Score:** 9 binary signals (profitability, leverage, efficiency) → score 0-9

#### Perbandingan Model

| Model | Fokus | Kelebihan | Kelemahan |
|-------|-------|-----------|-----------|
| P/B-ROE | Value + Quality | Sederhana, intuitive | Intangible assets tidak tertangkap |
| F-Score | Financial health | Multi-dimensional | Binary, tidak nuanced |
| Intrinsic Value (IVM) | True value | Menangkap economic profits | Butuh discount rate estimation |
| ML Fundamental | Non-linear patterns | Outperform analysts' consensus | Black box, overfitting risk |

#### Kritik & Kelemahan

1. **Intangible Assets (Classical Stock Valuation 2024):** P/B-ROE efficacy menurun karena intangible capital (R&D, brand, software) tidak tertangkap accounting standards. Sektor high-II: cheaper companies justru lebih profitable sejak 1983
2. **Value Factor Decline (CEPR 2024):** Book-to-market ratio gagal memprediksi returns di 2 dekade terakhir. IVM ratio menggantikan B/M dengan menambahkan discounted future economic profits — 56 bps/month alpha untuk large stocks (1999-2023)
3. **Accounting Manipulation:** Laba operasional bisa dimanipulasi (accruals). Cash Profitability lebih robust
4. **Stale Data:** Fundamental data update quarterly; sinyal mungkin stale

#### Perbaikan & Improvements

1. **Intangible-Adjusted P/B-ROE (2024):** Capitalize intangible investments ke book value dan earnings → efficacy improves dramatically
2. **IVM Ratio:** `IVM = (B + PV(future economic profits)) / Market Cap` — 56 bps/month alpha vs B/M ≈ 0
3. **ML Fundamental (Cao & You 2024):** ML generate more accurate earnings forecasts; top quintile outperform bottom by 34-77 bps/month
4. **Cash Profitability:** Gunakan operating cash flow / assets sebagai pengganti accrual-based profitability

#### Status Implementasi
- **Dry-run:** 50 UP (all bullish) — perlu verify apakah genuine atau default bias
- **Keputusan:** FIX — wire ke `fundamental_data` table, tambahkan intangible adjustment, gunakan cash profitability

---

### 6.3 Macro Engine

**File:** `src/market/analysis/macro.py` | **Sumber:** Sia et al. (2024), Wardatunisa et al. (2024), IJEBMR (2025), PKP (2025)

#### Persamaan Matematis

- **Regime Score:** `Score = Σ(w_i × sign(Δx_i) × impact_i)` untuk setiap macro indicator i
- **USD/IDR Impact:** `ΔJCI ≈ -β × Δ(USD/IDR)` — depresiasi rupiah → JCI turun
- **BI Rate Impact:** `ΔJCI ≈ -β × Δ(BI_Rate)` — kenaikan suku bunga → JCI turun
- **Commodity Channel:** `ΔJCI ≈ γ₁ × Δ(Gold) + γ₂ × Δ(Oil) + γ₃ × Δ(CPO)`

#### Perbandingan Model

| Model | Variabel | Kelebihan | Kelemahan |
|-------|----------|-----------|-----------|
| Linear Regression | BI rate, USD/IDR, M2 | Simple, interpretable | Linear assumption |
| VAR | Multi-variate lagged | Captures dynamics | Sensitive to lag order |
| ML + Macro (PKP 2025) | Macro + technical | SHAP interpretable | Overfitting risk |
| GARCH-MIDAS | EPU + volatility | Mixed-frequency | Complex, data-hungry |

#### Kritik & Kelemahan

1. **Insignificant factors (Wardatunisa 2024):** Exchange rate efek negatif tapi **tidak signifikan** terhadap JCI. Interest rates tidak show significant effect di beberapa studi
2. **Structural breaks:** Hubungan macro-JCI berubah (pre-COVID vs post-COVID vs political transition 2025-2026)
3. **Multicollinearity:** BI rate, inflation, USD/IDR saling berkorelasi → koefisien tidak stabil
4. **Lag mismatch:** Macro data monthly/quarterly, stock prices daily
5. **Prabowo policies (2025-2026):** $80B outflow — political risk tidak tertangkap macro variables standar

#### Perbaikan & Improvements

1. **SHAP-based Selection (PKP 2025):** Macro indicators (global indices, bond yields) punya pengaruh lebih kuat dari technical untuk IDX. Hanya 3-month EMA yang konsisten predictive di technical
2. **Asymmetric NARDL (Sia et al. 2024):** JCI merespons negatif lebih kuat terhadap kenaikan BI rate daripada respons positif terhadap penurunan
3. **GARCH-MIDAS + Signal Quality (Salisu et al. 2023):** Quality of political signals mempengaruhi predictive power. High-quality EPU → predict high volatility; low-quality → relationship breaks down
4. **DJIA as external factor:** Dow Jones punya efek positif signifikan terhadap JCI

#### Status Implementasi
- **Dry-run:** 50 UP (all bullish) — perlu verify keragaman sinyal
- **Keputusan:** KEEP — tambahkan BI rate, inflation, DJIA; gunakan asymmetric model

---

### 6.4 Sentiment Engine

**File:** `src/market/analysis/sentiment.py` | **Sumber:** Kengmegni (2025), Glasserman & Lin (2024), Lopez-Lira & Tang (2025)

#### Persamaan Matematis

- **Composite Score:** `S = Σ(w_i × s_i)`, s_i = normalized score dari source i
  - Sources: news_nlp (0.30), foreign_flow (0.25), historical (0.20), broker (0.10), social (0.10), trends (0.05)
- **Foreign Flow:** `FF_score = 50 + 50 × tanh(Σ(foreign_net_5d) / scale)`
- **News Sentiment:** `News_score = 50 + 50 × avg(sentiment_score)`, sentiment ∈ [-1, +1]

#### Perbandingan Model

| Model | Input | Kelebihan | Kelemahan |
|-------|-------|-----------|-----------|
| Lexicon-based | Word matching | Fast, transparent | Context-blind, sarcasm |
| FinBERT / IndoBERT | Transformer | Context-aware | Domain fine-tuning needed |
| LLM (GPT) | Full text | Deep reasoning | Look-ahead bias |
| Multi-level (2025) | Stock + industry + economy | Hierarchical | Complex, data-hungry |

#### Kritik & Kelemahan

1. **LLM Look-Ahead Bias (Glasserman & Lin 2024):** LLMs trained on data including realized outcomes → "parametric look-ahead bias". LLM "tahu" bagaimana saham bergerak post-berita, menginflate predictive power
2. **Short-term Elusive (Kengmegni 2025):** Bahkan LLaMA 3 8B + FinBERT, next-day prediction tetap sulit. Economy-wide sentiment > industry > stock-specific
3. **Transaction Costs:** Sentiment strategies limited economic significance setelah costs
4. **Aggregation Problem:** Averaging sentiment menghapus nuance — satu sangat bullish + satu sangat bearish → neutral, padahal keduanya informatif

#### Perbaikan & Improvements

1. **FinCAD (2025):** Inference-time Context-Aware Decoding suppresses LLM's memory of historical outcomes tanpa retraining. Cuts in-sample returns by 67% on memorized dates
2. **Multi-level Hierarchy (2025):** Pisahkan ke economy-wide, industry, stock-specific. Economy-wide punya predictive power tertinggi
3. **Foreign Flow as Primary:** Untuk IDX, foreign flow (1.26M rows, daily) adalah sentiment proxy paling reliable
4. **Disagreement Signal:** Gunakan variance/dispersion sentiment (bukan mean) — high disagreement = bearish

#### Status Implementasi
- **Dry-run:** 96% FLAT — signal terlalu lemah (avg 0.008, threshold 0.05)
- **Keputusan:** FIX — lower threshold ke 0.02, amplify foreign flow weight, gunakan disagreement signal

---

### 6.5 Relationship Engine

**File:** `src/quant/signals/relationship.py` | **Sumber:** Diebold & Yilmaz (2012), Zhang et al. (2024), Muñoz Mendoza et al. (2024), Granger (1969)

#### Persamaan Matematis

- **Correlation:** `ρ_{i,j} = Cov(r_i, r_j) / (σ_i × σ_j)` — rolling 60-day
- **Granger Causality:** F-test apakah lagged returns dari asset j memprediksi returns asset i. F-statistic dinormalisasi ke [0,1] via sigmoid: `causality_score = 1/(1+exp(-F))`
- **CCF Time-Lag:** `lag* = argmax_k |corr(source_{t-k}, target_t)|` untuk k ∈ [-max_lag, +max_lag]. `time_lag_seconds = |lag*| × 86400`
- **VAR:** Vector Autoregression dengan AIC-optimal lag order untuk impact coefficient analysis
- **Impact Weight:** `impact_weight = |correlation_coefficient| × causality_score`
- **Signal:** `sig = sign(ρ) × |ρ| × sign(market_return)`

#### Kritik & Kelemahan

1. **Spurious Correlation:** Correlation tinggi bisa karena common factor (USD strength), bukan genuine relationship
2. **Non-stationarity:** Correlation IDX-global berubah over time — 2020 COVID vs 2024 normal vs 2026 political crisis
3. **ETF Arbitrage Channel (2024):** Country ETFs propagate global shocks to local markets, increasing return correlation dengan US, limiting diversification. Countries dengan stronger ETF price discovery punya higher comovement
4. **Lag Structure:** Spillover US→IDX terjadi dengan lag (timezone), tapi predictive power substantially weakens during COVID
5. **Cross-predictability concentrates on small stocks (2024):** Economic value gravitates towards small, difficult-to-arbitrage stocks. Untuk large-cap IDX, cross-prediction becomes detrimental

#### Perbaikan & Improvements (IMPLEMENTED)

1. **✅ Granger Causality Test:** F-test dengan statsmodels, normalisasi sigmoid ke [0,1]. Direction detection: source→target, target→source, bidirectional, none
2. **✅ CCF Time-Lag Analysis:** Cross-correlation function untuk optimal lag detection. Positive lag = source leads target
3. **✅ VAR Model:** AIC-optimal lag order selection via statsmodels VAR
4. **✅ DB-backed lookups:** `analyze_from_db()` method queries `global_market_interdependencies` table untuk sub-ms lookups
5. **✅ Regime-conditional:** `analyze_regime_conditional()` splits time series by regime labels
6. **⬜ LASSO-VAR (Muñoz 2024):** Remove common global factors via PCA, then LASSO-VAR untuk idiosyncratic spillover
7. **⬜ Asymmetric Spillover:** Pisahkan positive vs negative spillover
8. **⬜ Overnight Signal (Xu et al. 2025):** Cross-market overnight momentum

#### Status Implementasi
- **Refactored:** ✅ Full CausalityAnalyzer integration (Granger + VAR + CCF)
- **DB integration:** ✅ Reads from `global_market_interdependencies` table, falls back to live computation
- **Tests:** ✅ 18 tests passing (CCF, Granger, VAR, pairwise, matrix, regime-conditional, edge cases)
- **Keputusan:** KEEP — engine sekarang menggunakan formal econometric methods. TODO: tambah LASSO-VAR, asymmetric spillover, overnight signal

---

### 6.6 Global Market Engine

**File:** `src/quant/signals/global_market.py` | **Sumber:** Wen et al. (2023), Xu et al. (2025), ETF Arbitrage (2024), Granger (1969)

#### Persamaan Matematis

- **Global Signal (legacy):** `sig = Σ(w_i × r_i^{lagged})` untuk indices i ∈ {^GSPC, ^DJI, ^N225, ^HSI, ^FTSE, ^GDAXI}
- **Causality-Weighted Signal (NEW):** `sig = Σ(impact_weight_i × MA_score_i)` di mana `impact_weight` dibaca dari `global_market_interdependencies` table
- **Lagged Returns:** t-1 untuk US/Europe (close sebelum IDX open), t untuk Asia (concurrent)
- **VIX Adjustment:** `sig_adjusted = sig × (1 - VIX/50)`

#### Kritik & Kelemahan

1. **Diminishing Power (Wen et al. 2023):** Lagged US returns adalah superior predictor untuk international markets, tapi predictive power substantially weakens during COVID. Degree of predictability driven by evolutionary market conditions
2. **ETF Channel Contamination:** Country ETFs alter return correlations — stronger ETF price discovery → higher comovement dengan US, limiting diversification
3. **Timezone Complexity:** US close 04:00 WIB, Europe 01:00 WIB, Asia concurrent — lag structure tidak straightforward
4. **Regime Dependence:** Global signals work in normal periods tapi fail during crises

#### Perbaikan & Improvements (IMPLEMENTED)

1. **✅ Causality-Weighted Scoring:** Engine sekarang membaca `global_market_interdependencies` table dan weighted each global index's MA signal by its `impact_weight` dari causality analysis
2. **✅ DB-backed mode:** `analyze_with_causality()` method — sub-ms DB lookup, falls back to legacy MA50/MA200 scoring
3. **✅ Dominant source tracking:** `dominant_source` dan `avg_time_lag_periods` fields ditambahkan ke `GlobalMarketScore`
4. **⬜ Cross-Market Overnight Momentum (Xu et al. 2025):** Gunakan overnight returns (close-to-open) US/Europe sebagai predictor IDX
5. **⬜ VIX-Conditioned Signal:** Low VIX (<20) → follow global trend; high VIX (>30) → contrarian/defensive
6. **⬜ Asia-Specific Chain:** ^N225 → ^HSI → ^JKSE: cascading signal dari Asia chain

#### Status Implementasi
- **Refactored:** ✅ Causality-weighted scoring from DB interdependency matrix
- **Fallback:** ✅ Legacy MA50/MA200 scoring ketika DB data unavailable
- **Keputusan:** KEEP — engine sekarang menggunakan causality impact weights. TODO: tambah overnight momentum, VIX conditioning

---

### 6.7 Alpha Mean Reversion

**File:** `src/market/analysis/alpha_signals.py` | **Sumber:** Jegadeesh (1990), Lehmann (1990), Dai et al. (2024, JPM)

#### Persamaan Matematis

- **BB Mean Reversion:** `Signal = -1 if Price < BB_lower, +1 if Price > BB_upper, 0 otherwise`
- **RSI Mean Reversion:** `Signal = +1 if RSI < 30, -1 if RSI > 70`
- **Combined:** `Signal = 0.5 × BB_signal + 0.5 × RSI_signal` → [-1, +1]

#### Kritik & Kelemahan

1. **Conditions Too Strict:** RSI < 30 atau price < BB_lower jarang terjadi → 96% FLAT. Bukan bug — mean reversion sinyal memang hanya muncul di extreme conditions
2. **Reversal Weakening (Dai et al. 2024):** "Classic short-term reversal effect has steadily weakened over time to the point of vanishing in most regions"
3. **Bid-Ask Bounce (Jegadeesh & Titman 1995):** Short-horizon reversals partly artifact of bid-ask bounce
4. **Size Effect:** Reversal lebih kuat untuk small, illiquid stocks. Large-cap IDX mungkin tidak exhibit reversal

#### Perbaikan & Improvements

1. **Enhanced Reversal (JPM 2024):** Combine reversal dengan short-term momentum filter — "higher return with lower risk, more than 2× risk-adjusted performance"
2. **Continuous Signal:** `Signal = -z_score / max_z` di mana `z_score = (price - SMA) / σ` → smooth -1 to +1
3. **Liquidity-Conditioned:** Hanya aktifkan untuk low turnover stocks (more persistent reversals)
4. **Industry-Residual Reversal (Da, Liu & Schaumburg 2013):** Within-industry residual-based reversals punya far higher Sharpe ratio

#### Status Implementasi
- **Dry-run:** 96% FLAT — conditions too strict
- **Keputusan:** FIX — gunakan continuous z-score signal, lower thresholds, add momentum filter

---

### 6.8 Alpha Short-Term Reversal

**File:** `src/market/analysis/alpha_signals.py` | **Sumber:** Jegadeesh (1990), Columbia (2015), Dai et al. (2024, JPM)

#### Persamaan Matematis

- **Z-Score Reversal:** `Z = (return_t - μ_n) / σ_n`, n=20 day lookback
- **Signal:** `Signal = -Z / Z_threshold if |Z| > Z_threshold, else 0`
- **Holding Period:** 1-5 days (half-life ~2.5 days per Columbia study)

#### Kritik & Kelemahan

1. **Vanishing Effect (JPM 2024):** "Classic short-term reversal effect has steadily weakened over time to the point of now having vanished entirely in most regions"
2. **10% Temporary, 90% Permanent (Columbia 2015):** Hanya ~10% idiosyncratic price shocks temporary (revert dengan half-life ~2.5 hari). 90% permanent → reversal signal mostly noise
3. **Rate of Decay Variable:** Half-life relatif constant, tapi magnitude varies considerably. Tidak related to VIX (contrary to Nagel 2012)
4. **Transaction Costs:** Reversal strategy requires daily rebalancing → high costs menghapus profit
5. **Z-threshold Too High:** Current threshold 2.0 → hanya extreme moves qualify. 74% FLAT

#### Perbaikan & Improvements

1. **Momentum-Adjusted Reversal (JPM 2024):** "Enhanced short-term reversal strategies show higher return with lower risk, more than double the risk-adjusted performance"
2. **Exponential Decay (Columbia 2015):** `Expected return = λ × past_residual_return` di mana λ = decay rate. "Well captured by a model in which expected return is an exponentially weighted function of past residual returns"
3. **Lower Z-Threshold:** Ubah dari 2.0 ke 1.0-1.5
4. **Liquidity Provision Interpretation:** Reversal strategy = acting as liquidity provider

#### Status Implementasi
- **Dry-run:** 74% FLAT — threshold too high
- **Keputusan:** FIX — lower threshold ke 1.0, add momentum filter, use exponential decay

---

### 6.9 Alpha EWMA Momentum

**File:** `src/market/analysis/alpha_signals.py` | **Sumber:** Moskowitz, Ooi & Pedersen (2012), Daniel & Moskowitz (2016), Bianchi et al. (2024)

#### Persamaan Matematis

- **EWMA:** `EMA_t = α × Price_t + (1-α) × EMA_{t-1}`, `α = 2/(n+1)`
- **Crossover Signal:** `Signal = sign(EMA_fast - EMA_slow)` → +1 uptrend, -1 downtrend
- **TSMOM:** `Signal = sign(return_{t-12m to t-1m})` — persistensi returns 1-12 bulan

#### Kritik & Kelemahan

1. **Momentum Crashes (Daniel & Moskowitz 2016):** "Infrequent and persistent strings of negative returns". Crashes terjadi di panic states, following market declines, when volatility is high, contemporaneous dengan market rebounds. "Low ex ante expected returns in panic states"
2. **Power-Law Variance (Bianchi et al. 2024):** Realized momentum variances mengikuti power law dengan exponent α̂ < 2 → **theoretical mean is infinite**. "1% of sample observations represent more than 90% of potential overall compounded return"
3. **Negative Skewness:** Momentum returns exhibit predominantly negative, time-varying skewness yang deepens during crashes
4. **IDX-Specific:** IC negatif untuk momentum di IDX 5-day horizon → momentum inverted di short-term. Tapi TSMOM (12-month) mungkin still works

#### Perbaikan & Improvements

1. **Dynamic Momentum (Daniel & Moskowitz 2016):** "An implementable dynamic momentum strategy based on forecasts of momentum's mean and variance approximately doubles the alpha and Sharpe ratio"
2. **Skewness-Adjusted (Bianchi et al. 2024):** "A dynamic skewness-adjusted maximum Sharpe ratio strategy significantly improves upon popular volatility scaling approaches"
3. **Volatility Scaling:** `Scaled_signal = signal / σ_t` — reduce exposure ketika volatility tinggi
4. **Trend-Following vs Momentum:** Pisahkan EWMA crossover (short-term) dari 12-month TSMOM (medium-term)

#### Status Implementasi
- **Dry-run:** 22 UP, 27 DOWN — active dan bervariasi
- **Keputusan:** KEEP — tambahkan volatility scaling, test TSMOM separately

---

### 6.10 Alpha Regime Switch

**File:** `src/market/analysis/alpha_signals.py` | **Sumber:** Hamilton (1989), Daniel & Moskowitz (2016)

#### Persamaan Matematis

- **Volatility Regime:** `σ_t = stdev(returns, 20)`. High-vol jika `σ_t > 1.5 × σ_median`
- **Signal Logic:** High-vol → mean reversion; Low-vol → momentum
- **Signal:** `Signal = momentum_signal if low_vol else reversal_signal`

#### Kritik & Kelemahan

1. **Threshold Sensitivity:** 1.5× median arbitrary — terlalu rendah → sering switch, terlalu tinggi → rarely switches
2. **Lookback Bias:** 20-day rolling σ backward-looking; regime change mungkin sudah terjadi
3. **Binary Switch:** Hard boundary → smooth transition lebih robust
4. **No Causal Mechanism:** Tidak menjelaskan mengapa high-vol → mean reversion

#### Perbaikan & Improvements

1. **Smooth Transition:** `weight = 1/(1 + exp(-(σ_t/σ_median - threshold)))` → gradual shift
2. **Forward-Looking Volatility:** Gunakan VIX atau implied volatility sebagai regime indicator
3. **HMM Integration:** Gunakan HMM regime detector (section 3.16) sebagai pengganti simple vol threshold

#### Status Implementasi
- **Dry-run:** 47 UP, 3 DOWN — active tapi heavily biased UP
- **Keputusan:** KEEP — integrate dengan HMM regime, gunakan smooth transition

---

### 6.11 Astronacci

**File:** `src/market/analysis/astronacci.py` | **Sumber:** Lestari (2021, IJEBR), Caporale & Plastun (2024), Cambridge History of Finance

#### Persamaan Matematis

- **Fibonacci Retracement:** Levels 23.6%, 38.2%, 50%, 61.8%, 78.6% — "golden ratio" φ = 1.618
- **Astronacci Cycle:** Kombinasi astrological cycles + Fibonacci time ratios untuk predict reversal dates
- **Signal:** Buy/sell berdasarkan cycle convergence dates

#### Kritik & Kelemahan

1. **No Scientific Basis (Caporale & Plastun 2024):** Technical analysis berbasis Fibonacci/Gann/Elliott Wave = "voodoo finance". "Unjustified algorithms" — tidak ada alasan matematis mengapa rasio Fibonacci memprediksi market movements
2. **Financial Astrology (Cambridge Hist.):** W.D. Gann's methods = "idiosyncratic" dan "numerological analysis". Reputation "bolstered by interview" — lebih self-promotion. "Anybody who had the ability to make profits at this rate would soon become one of the world's wealthiest people and would presumably feel no need to sell courses"
3. **Self-Fulfilling Prophecy:** Jika cukup banyak trader menggunakan Fibonacci levels, price reactions bisa self-fulfilling — tapi bukan predictive power
4. **Data Snooping:** Dari huge number of cycles, some akan "work" by chance
5. **IC Negatif di IDX:** IC = -0.22 → inverted atau pure noise

#### Perbaikan & Improvements

1. **Behavioral Interpretation:** Fibonacci levels mungkin work karena self-fulfilling prophecy. Test sebagai behavioral signal
2. **Spectral Analysis:** Ganti astrological cycles dengan rigorous Fourier/wavelet analysis untuk detect genuine periodicities
3. **Inverted Signal:** Jika IC konsisten negatif, invert signal — tapi verify stability OOS

#### Status Implementasi
- **Dry-run:** 39 UP, 11 DOWN — active
- **Keputusan:** EXPERIMENTAL — keep dengan inverted signal, test rigorously dengan DSR/PBO. Jika tidak lolos multiple testing correction, DROP

---

### 6.12 Volume Features

**File:** `src/market/analysis/volume_features.py` | **Sumber:** Cont et al. (2024), Lu et al. (2024), Deep OFI (2023)

#### Persamaan Matematis

- **OFI (proxy):** `OFI ≈ (close - open) × volume` (true OFI needs tick-by-tick)
- **VWAP Deviation:** `VWAP_dev = (close - VWAP) / VWAP`, `VWAP = Σ(price × volume) / Σ(volume)`
- **OBV:** `OBV_t = OBV_{t-1} + sign(close_t - close_{t-1}) × volume_t`
- **Percentile Rank:** `OFI_rank = percentile_rank(OFI_t, OFI_{t-252:t-1})` → [0, 1]

#### Kritik & Kelemahan

1. **OFI Proxy Limitation:** True OFI requires tick-by-tick buy/sell classification (Lee-Ready). EOD data hanya proxy → noisy
2. **Algorithmic Trading Erosion (2024):** AT improves market efficiency → predictive power of OFI decreases over time
3. **Deep OFI (2023):** Standard OFI hanya captures top-of-book. "Decomposed OFI" dengan order book event types → significant improvement
4. **Multi-Horizon:** Effective horizon ≈ 2 average price changes — very short-term. Untuk swing trading, signal mungkin stale

#### Perbaikan & Improvements

1. **Conditional Order Imbalance (COI, Lu et al. 2024):** Classify trades by proximity → 5 types. COIs achieve conspicuous returns. Isolated trades: positive predictability; co-occurring: negative
2. **Foreign Flow as OFI Proxy:** Untuk IDX, `foreign_net` dari `foreign_flow` table adalah better proxy untuk true OFI
3. **Percentile Rank Normalization:** Rolling 252-day percentile rank untuk normalize across stocks
4. **Volume Price Trend (VPT):** `VPT_t = VPT_{t-1} + volume_t × (close_t - close_{t-1}) / close_{t-1}` — alternative ke OBV

#### Status Implementasi
- **Dry-run:** 29 UP, 16 DOWN, 5 FLAT — active dan bervariasi
- **Keputusan:** KEEP — tambahkan foreign flow as primary OFI proxy, gunakan COI classification

---

### 6.13 Policy Event Scorer

**File:** `src/market/analysis/policy_event_scorer.py` | **Sumber:** Salisu et al. (2023), Hassan et al. (2024), PUR Index (2025), Political Information Quality (2025)

#### Persamaan Matematis

- **Event Signal:** `Signal = Σ(event_i.impact × decay(t - event_i.date))` untuk events dalam window
- **Decay Function:** `decay(Δt) = exp(-Δt / half_life)`, half_life = 5 days
- **Impact Score:** `impact = base_impact × direction × ticker_specificity`
  - base_impact: Tinggi=1.0, Sedang=0.5, Rendah=0.25
  - direction: Positif=+1, Negatif=-1, Netral=0
  - ticker_specificity: 1.0 jika event relevant, 0.3 jika market-wide

#### Kritik & Kelemahan

1. **Signal Quality Matters (Salisu et al. 2023):** "High EPU predicts high volatility, particularly when signal quality is high. The positive relationship between EPU and volatility breaks down when signal quality is low." Quality of political signals adalah moderator variable
2. **Political Risk → Crash Risk (Hassan et al. 2024):** Firm-level political risk positively associated dengan stock price crash risk. Mediated via higher idiosyncratic volatility, lower price informativeness, higher distress risk. Strong corporate governance can moderate
3. **Information Quality (2025):** Low-quality political information significantly diminishes predictive power of investor sentiment while amplifying risk aversion. Quality of information is critical moderator
4. **Event Mapping:** Sulit memetakan event umum (BI rate hike) ke ticker spesifik. Market-wide events punya dampak berbeda per sector
5. **All DOWN in Dry-Run:** 50 DOWN signals menunjukkan possible bias

#### Perbaikan & Improvements

1. **Signal Quality Index (Qindex, 2025):** Incorporate proxy untuk political information quality. "Incorporating a proxy for political information quality into predictive regression models significantly enhances their explanatory power"
2. **Text-Based Uncertainty (PUR Index, 2025):** Measure frequency of risk/uncertainty synonyms adjacent to political mentions in news. "A unit increase in SD of frequency → 21.3 bps decrease in abnormal stock returns"
3. **Sector-Specific Impact:** BI rate hike → negative untuk property/infrastructure, neutral untuk banking. Tambahkan sector mapping
4. **Pre/Post Event Windows:** Pisahkan pre-event (anticipation) vs post-event (reaction) — sinyal berbeda

#### Status Implementasi
- **Dry-run:** 50 DOWN — perlu verify event distribution
- **Keputusan:** KEEP — tambahkan signal quality index, sector-specific impact mapping

---

### 6.14 Holiday Effect

**File:** Direct DB query in backfill | **Sumber:** 34-country study (2024), Sasikirono & Meidiawati (2017), Stefanescu & Dumitriu (2018)

#### Persamaan Matematis

- **Pre-Holiday Effect:** `AR_pre = avg(return_{t-1})` untuk t = holiday date
- **Post-Holiday Effect:** `AR_post = avg(return_{t+1})` untuk t = holiday date
- **Signal:** `Signal = +1 if AR_pre > 0, -1 if AR_post < 0`
- **Normal Day Benchmark:** `μ_normal = avg(return) untuk non-holiday-adjacent days`

#### Kritik & Kelemahan

1. **Anomaly Decay (Dimson & Marsh 1999):** "Publication of an anomaly could cause its disappearance or reversal." Holiday effect mungkin sudah arbitraged away
2. **Regional Variation (2024, 34-country):** Pre-holiday effect exists for Asian and North American markets (7× higher returns). Post-holiday effect in Europe and North America (3× higher). **No effect for South African and South American markets.** Indonesia = Asia → pre-holiday effect expected
3. **Crisis Sensitivity:** Holiday effect weakened after financial crisis — "may signal improvement in market efficiency"
4. **Time-Varying:** Results inconsistent across studies — Chinese markets show "no signs of decline over time" (Stefanescu & Dumitriu 2018)
5. **Independence:** Holiday effect independent dari end-of-year dan weekend effects

#### Perbaikan & Improvements

1. **Conditional on Market State:** Pre-holiday effect lebih kuat dalam normal/bull markets, disappears dalam bear markets
2. **Holiday Type Classification:** Religious (Eid, Christmas) vs political (Independence Day) vs regular weekends → different effects
3. **Liquidity Effect:** Pre-holiday effect stronger untuk less liquid stocks (investor inattention hypothesis)
4. **IDX-Specific (Sasikirono 2017):** Holiday effect documented di IDX — tapi perlu re-verify dengan data 2024-2026

#### Status Implementasi
- **Dry-run:** CONTEXTUAL (FLAT when no holiday in test window — correct behavior)
- **Keputusan:** KEEP — verify dengan data yang includes holiday dates, add holiday type classification

---

### 6.15 Fama-French 5-Factor

**File:** `src/market/analysis/fama_french.py` | **Sumber:** Fama & French (2015, 2017), Hou et al. (2015), INT factor (2024), q-factor model

#### Persamaan Matematis

- **5-Factor Model:** `r_i - r_f = α + β_MKT×MKT + β_SMB×SMB + β_HML×HML + β_RMW×RMW + β_CMA×CMA + ε`
  - MKT: Market excess return
  - SMB: Small Minus Big (size factor)
  - HML: High Minus Low (value factor)
  - RMW: Robust Minus Weak (profitability factor)
  - CMA: Conservative Minus Aggressive (investment factor)
- **Expected Return:** `E[r_i] = r_f + Σ β_k × λ_k`
- **Signal:** `Signal = sign(E[r_i] - r_f)` → long jika expected excess return positive

#### Perbandingan Model

| Model | Factors | Kelebihan | Kelemahan |
|-------|---------|-----------|-----------|
| FF5 | MKT, SMB, HML, RMW, CMA | Gold standard, widely tested | HML redundant dengan CMA |
| FF6 | FF5 + UMD (Momentum) | Menangkap momentum anomaly | 6 factors → more noise |
| q-Factor (HXZ) | MKT, ME, I/A, ROE | 4 factors, less data snooping | Based on q-theory, less intuitive |
| INT5 | MKT, SMB, RMW, INT, MOM | Intangibles factor, best fit | New, less validated |
| Cash Profitability | FF5 dengan cash-based RMW | HML tidak redundant | Butuh cash flow data |

#### Kritik & Kelemahan

1. **Data Snooping / Sharpe Ratio Puzzle (SSRN 2023, revised 2025):** "Estimates of maximum Sharpe ratios for popular multifactor asset pricing models seem too large to be consistent with risk-based explanations." Historical data influences factor selection → "optimistic bias." "Multifactor model Sharpe ratio improvements relative to CAPM fall dramatically" setelah koreksi
2. **HML Redundancy:** Value factor (HML) lacks incremental pricing power, subsumed by investment factor (CMA). "Factors' relationship arises because book-to-market and investment both capture information about expected returns and cash flows"
3. **Data-Snooping → q-Factor (Hou et al. 2015):** "It is not difficult to data mine factor models that explain a large cross-section of anomalies." q-factor model based on Tobin's q-theory, explains 29/36 anomalies. "HXZ largely subsumes FF5"
4. **Regional Adaptation Needed:** Model asli US-based. "Model ini sering kali gagal total saat diaplikasikan langsung di negara berkembang seperti Indonesia." SMB breakpoints perlu disesuaikan dengan kapitalisasi BEI
5. **Intangible Assets (INT factor, 2024):** "INT5 model (MKT + SMB + RMW + INT + MOM) delivers the strongest performance across all evaluation metrics, reducing significant alphas to 27, compared to 39 for FF5 and 42 for q-factor"
6. **Investing Perspective (2023):** "A model that is better for pricing is not necessarily better for investing." HXZ outperforms FF5 for pricing, tapi dengan margin requirements dan model uncertainty, outperformance becomes negligible

#### Perbaikan & Improvements

1. **Upgrade ke FF6 (Fama & French 2017):** Tambahkan faktor Momentum (UMD). "Faktor UMD menangkap kecenderungan saham yang berkinerja sangat baik dalam beberapa bulan terakhir untuk melanjutkan tren kenaikannya"
2. **Cash Profitability (2024):** Ganti Operating Profitability (accrual-based) dengan Cash Profitability (cash flow-based). "Ketika dihitung berbasis arus kas riil, faktor Value (HML) kembali menunjukkan taringnya dan tidak lagi terserap oleh faktor profitabilitas"
3. **Intangibles Factor (INT, 2024):** Tambahkan intangibles intensity factor. INT5 outperforms FF5 dan q-factor. "Intangible assets may be an important driver of firm performance and stock returns in an increasingly knowledge-based economy"
4. **Low-Volatility Factor:** Tambahkan faktor low-volatility untuk menangkap "Low-Volatility Anomaly" — saham beta rendah justru return jangka panjang lebih tinggi
5. **Regional Adaptation IDX:** Sesuaikan SMB breakpoints (median market cap BEI, bukan NYSE), tambahkan USD/IDR sebagai macro factor
6. **Resurrecting Value Factor (2024):** "A value factor built from stocks for which book-to-market is a good expected return indicator is not redundant" — filter stocks di mana B/M reflects expected returns

#### Status Implementasi
- **Dry-run:** ACTIVE
- **Keputusan:** KEEP — upgrade ke FF6 (tambah momentum), gunakan cash profitability, tambahkan intangibles factor, adaptasi SMB untuk IDX

---

### 6.16 HMM Regime Detector

**File:** `src/market/analysis/hmm_regime.py` | **Sumber:** Hamilton (1989), Adams & MacKay (2007), Casarin et al. (2024), BOCPD

#### Persamaan Matematis

- **HMM:** `P(state_t | state_{t-1}) = A[state_{t-1}, state_t]` (transition matrix)
- **Emission:** `P(returns_t | state_t) = N(μ_{state}, σ²_{state})`
- **Baum-Welch:** EM algorithm untuk estimate `(A, μ, σ²)` dari observed returns
- **Regime Classification:** Map states ke trending/ranging/crisis berdasarkan `μ` dan `σ`
- **Fallback (volatility percentile):** `regime = "crisis" if vol_pctile > 90, "trending" if vol_pctile < 30, else "ranging"`
- **Signal:** `trending → +0.3 × adjustment, ranging → -0.1, crisis → -0.5`

#### Kritik & Kelemahan

1. **Path Dependence (Gray 1996):** Estimated parameters depend on initialization → non-unique solutions. Different random seeds → different regimes
2. **Convergence Issues:** EM algorithm tidak guaranteed converge ke global optimum. Di praktik, banyak local optima
3. **Model Order Selection:** Memilih n_states=3 (trending/ranging/crisis) adalah arbitrary. Bisa 2, 4, atau 5 states
4. **Computational Cost:** Fitting HMM per ticker per day terlalu expensive untuk backfill (O(n² × T) per iteration)
5. **Regime Lag:** HMM detects regime change dengan lag — by the time confidence high, regime already shifted
6. **Non-Stationarity:** Transition matrix itself might change over time → fixed A assumption violated

#### Perbaikan & Improvements

1. **BOCPD (Bayesian Online Change Point Detection, Adams & MacKay 2007):** Detect regime changes in real-time tanpa re-fitting. "Exact inference of the posterior probability of the current run length" — computationally efficient, online
2. **Hierarchical HMM (Casarin et al. 2024):** Multi-level HMM yang menangkap regime changes at different time scales (daily, weekly, monthly)
3. **Sticky HMM (Fox et al. 2011):** Add self-transition prior → lebih persistent regimes, fewer spurious switches
4. **GPU-Accelerated Fitting:** Gunakan CUDA untuk parallel HMM fitting across tickers — viable dengan `cuda:1`
5. **Ensemble Regime:** Combine HMM dengan vol percentile fallback, BOCPD, dan GARCH volatility forecast → vote on regime
6. **Pre-Fitted Global Model:** Fit HMM pada IHSG index returns (sufficient data), then apply regime labels ke individual stocks — avoids per-ticker fitting

#### Status Implementasi
- **Dry-run:** 25 UP, 25 DOWN — fallback mechanism works (HMM fitting bypassed for performance)
- **Keputusan:** KEEP — implement BOCPD as alternative, pre-fit HMM on IHSG, use ensemble regime detection

---

## 7. Layer 4: Portfolio Construction & Risk

Audit tidak lengkap tanpa membahas modul-modul yang beroperasi di level portofolio, bukan individual stock. Modul-modul ini menentukan bagaimana sinyal dari 16 engine di atas dikombinasikan, dialokasikan modal, dan dievaluasi secara statistik.

---

### 7.1 HRP — Hierarchical Risk Parity

**File:** `src/market/analysis/portfolio_cluster_tuner.py` | **Sumber:** López de Prado (2016), Raffinot (2017, 2018), Copenhagen Business School Thesis (2023), Schur Complementary Allocation (2024)

#### Persamaan Matematis

- **Stage 1 — Tree Clustering:** `d_{i,j} = √(2(1 - ρ_{i,j}))` → hierarchical clustering via single-linkage
- **Stage 2 — Quasi-Diagonalization:** Reorder covariance matrix sesuai tree structure
- **Stage 3 — Recursive Bisection:** `w_i = w_{cluster} × (σ_{other} / (σ_i + σ_{other}))` → inverse-variance allocation within each cluster

#### Perbandingan Model

| Model | Kelebihan | Kelemahan |
|-------|-----------|-----------|
| Markowitz MVO | Optimal in-sample | Unstable, concentrated, requires invertible Σ |
| Equal Weight | Simple, robust | Ignores risk structure |
| Inverse Variance | Risk-aware | Ignores correlations |
| HRP | Stable, diversified, no Σ inversion needed | Arbitrary bisection, counterintuitive features |
| HRP Topdown (2023) | Rational alternatives to arbitrary choices | Higher transaction costs |
| Schur HRP (2024) | Unifies HRP + Min Variance | More complex |

#### Kritik & Kelemahan

1. **Counterintuitive Bisection (Copenhagen Thesis 2023):** "The hierarchical structure produced in stage 1 is not considered when the bisection is performed in stage 3, which induces some arbitrariness in the method." HRP Topdown fixes this → significantly increases returns, but higher transaction costs
2. **Less Robust to Covariance Misspecification:** "HRP shows less robustness towards misspecifications of the sample covariance matrix than other non-hierarchical allocations" — contrary to López de Prado's claims
3. **Underperforms Min Variance in Walk-Forward (2023):** "HRP outperforms the inverse-variance, equally weighted, and equal risk contribution portfolios on risk-based performance measures in the walk-forward analysis but underperforms relative to the minimum-variance portfolio"
4. **Kaczmarek & Perez (2022):** Pushes back on empirical superiority of HRP over optimization — challenges the consensus
5. **Distance Metric Sensitivity (Springer 2025):** Correlation-based metrics perform better than non-correlation metrics. "HRP methods outperform quadratic optimizers in two of three stock market scenarios (bull, sideways), but quadratic optimizer is best in bear market"

#### Perbaikan & Improvements

1. **HRP Topdown (2023):** Replaces arbitrary bisection dengan rational alternatives based on hierarchical structure. "Significantly increases returns and performs better from a risk-based perspective"
2. **Schur Complementary Allocation (2024):** "Reveals the hidden connection between HRP and minimum variance portfolios." HRP is a special case (γ=0) of a family that nests both HRP and MinVar
3. **Ledoit-Wolf Shrinkage (2020):** Apply shrinkage to covariance matrix before HRP → steers away from concentrated, long-short positions
4. **Correlation-Based Distance (Springer 2025):** Use correlation-based distance metrics, not Euclidean. Outperform in bull and sideways markets
5. **HRP + Constraints (Pfitzinger & Katzke 2019):** Add allocation constraints to HRP → more practical for real-world portfolios

#### Status Implementasi
- **Implemented:** `portfolio_cluster_tuner.py` dengan iterative cap+redistribute (fix from Aug 2026)
- **Weekly cron:** `0 3 * * 6` — HRP recompute every Saturday
- **Known issue:** 15/20 tickers still have negative Sharpe — perlu re-run dengan updated signals
- **Keputusan:** KEEP — upgrade ke HRP Topdown, add Ledoit-Wolf shrinkage, test correlation-based distance

---

### 7.2 Deflated Sharpe Ratio (DSR)

**Sumber:** Bailey & López de Prado (2014), Harvey & Liu (2015), Haircut Sharpe (2015)

#### Persamaan Matematis

- **Sharpe Ratio:** `SR = E[r] / σ_r`
- **Deflated Sharpe:** `DSR = Φ⁻¹(1 - P(SR* > SR_observed | SR_true = 0))`
  - `SR* = E[max(SR_1, ..., SR_N)]` — expected maximum SR from N independent trials
  - Adjusts for: (1) number of trials N, (2) length of track record T, (3) skewness and kurtosis of returns
- **Haircut Sharpe (Harvey-Liu):** `SR_haircut = SR_observed × (1 - haircut%)` di mana haircut% depends on number of tests

#### Kritik & Kelemahan

1. **Multiple Testing Burden:** Dengan 16 engines × 120+ technical indicators × multiple parameter sets → thousands of trials. DSR correction akan sangat aggressive → banyak sinyal "signifikan" menjadi tidak signifikan
2. **Non-Independence:** Engine signals tidak independent — technical dan alpha_mean_reversion berkorelasi. DSR assumes independence → overcorrects
3. **Selection Bias:** Pilih engine yang "works" dari backtest → bias. DSR helps tapi tidak fully eliminates
4. **Skewness/Kurtosis Sensitivity:** DSR formula sensitive ke estimate of higher moments → unstable untuk small samples

#### Perbaikan & Improvements

1. **Harvey-Liu Haircut (2015):** Lebih nuanced dari DSR — accounts for dependency between tests via bootstrap
2. **White's Reality Check / SPA (Hsu et al. 2010):** Stepwise SPA test untuk technical trading rules — controls for data snooping secara lebih rigorous
3. **Bonferroni-Holm:** Simple but conservative — multiply p-value by number of tests. Good baseline
4. **FDR Control (Benjamini-Hochberg):** Control False Discovery Rate instead of FWER → less conservative, more powerful

#### Status Implementasi
- **Status:** NOT YET IMPLEMENTED — perlu implement untuk evaluasi 16 engines
- **Keputusan:** IMPLEMENT — DSR + Haircut Sharpe untuk evaluasi. Gunakan FDR untuk less conservative alternative

---

### 7.3 PBO — Probability of Backtest Overfitting

**Sumber:** Bailey et al. (2014), López de Prado (2018), Combinatorial Symmetric Cross-Validation (CSCV)

#### Persamaan Matematis

- **CSCV Framework:** Split data into N sub-samples, form all C(N, N/2) combinations of train/test splits
- **PBO:** `PBO = P(ranking_IS ≠ ranking_OOS)` — probability that in-sample optimal strategy is NOT out-of-sample optimal
- **Logit:** `PBO = Σ 1[rank_IS ≠ rank_OOS] / C(N, N/2)`
- **Interpretation:** PBO > 0.5 → overfitting likely; PBO < 0.1 → robust

#### Kritik & Kelemahan

1. **Computational Cost:** C(16, 8) = 12,870 combinations per evaluation → expensive tapi feasible
2. **Assumes Stationarity:** CSCV assumes sub-samples from same distribution → violated jika structural breaks
3. **Strategy Space:** PBO hanya valid jika strategy space well-defined. Jika kita "cherry-pick" strategies post-hoc, PBO tidak capture
4. **Small Sample:** Dengan 250 trading days, splitting ke 16 sub-samples → ~15 days each → too noisy

#### Perbaikan & Improvements

1. **Combinatorially Symmetric Cross-Validation:** Use N=8 atau N=10 (not 16) untuk balance granularity vs noise
2. **Walk-Forward PBO:** Combine PBO dengan walk-forward validation → lebih realistic untuk time series
3. **PBO + DSR:** Gunakan keduanya — PBO untuk strategy selection, DSR untuk performance evaluation

#### Status Implementasi
- **Status:** NOT YET IMPLEMENTED
- **Keputusan:** IMPLEMENT — CSCV dengan N=8, combine dengan walk-forward

---

### 7.4 Kelly Criterion & Position Sizing

**File:** `src/market/risk/capital_aware_sizer.py` | **Sumber:** Kelly (1956), Thorp (1969), MacLean et al. (2010), Busseti et al. (2016), Downey (2024)

#### Persamaan Matematis

- **Kelly Criterion:** `f* = (p × b - q) / b` di mana p = win prob, q = 1-p, b = odds ratio
- **Continuous Version:** `f* = μ / σ²` (expected return / variance)
- **Fractional Kelly:** `f = α × f*`, α ∈ (0, 1) — typically α = 0.25 (quarter-Kelly)
- **Risk-Constrained Kelly (Busseti 2016):** `maximize E[log(b₁P + (1-b₁))]` subject to `P(wealth < α) < β`
- **Current Implementation:** Quarter-Kelly + liquidity constraints + risk caps

#### Kritik & Kelemahan

1. **Overbetting Risk (Thorp):** "Overbetting is worse than underbetting." Full Kelly can produce very large drawdowns. "Betting half-Kelly offers protection against negative growth rate at the cost of reducing growth rate by ≤25%"
2. **Parameter Uncertainty (Downey 2024):** "If overbetting is worse than underbetting, then increasing uncertainty reduces the optimal bet size." σ=20% → optimal drops from 0.40 to 0.36. "Uncertainty matters, but apparently not that much"
3. **Risk of Ruin (Downey 2024):** Even 1% risk of total loss dramatically reduces optimal bet. "1% risk of ruin → optimal bet drops from 0.80 to 0.463; 2% → 0.39"
4. **Drawdown Problem (Busseti 2016):** "The Kelly Criterion ensures maximum long-term return but in practice you would face many long-lasting big drawdowns." Basic Kelly → volatile equity curve
5. **Estimation Error:** μ dan σ² estimated from historical data → noisy. Small estimation error in μ → large error in f*
6. **Non-Stationarity:** μ dan σ² change over time → Kelly fraction based on stale estimates

#### Perbaikan & Improvements

1. **Risk-Constrained Kelly (Busseti et al. 2016):** "Incorporates maximizing long-term log-growth rate together with drawdown as a constraint." Smoother equity curve, less frequent and smaller drawdowns. "Range reduces from [0, 0.8] to [0, 0.25]"
2. **Fractional Kelly (Thorp):** Quarter-Kelly (α=0.25) — current implementation. "Asymmetry in your favor when reducing bet size from full to half"
3. **Dynamic Kelly (2024):** "fk(B) becomes a function of both k (games remaining) and B (current bankroll)" — adaptive to remaining opportunities
4. **Model Averaging:** Use Bayesian model averaging untuk μ estimation → accounts for parameter uncertainty
5. **Drawdown-Adjusted:** `f_adjusted = f* × (1 - current_drawdown / max_drawdown)` — reduce exposure during drawdowns

#### Status Implementasi
- **Implemented:** `CapitalAwarePositionSizer` dengan quarter-Kelly + liquidity + risk caps
- **Known issue:** 15/20 tickers have negative Sharpe → Kelly fraction akan near-zero atau negative
- **Keputusan:** KEEP — tambahkan risk-constrained Kelly (Busseti 2016), drawdown-adjusted sizing

---

### 7.5 Monte Carlo VaR

**File:** `src/market/risk/monte_carlo_var.py` | **Sumber:** Jorion (2007), Glasserman (2003)

#### Persamaan Matematis

- **Historical VaR:** `VaR_α = -percentile(returns, α)` — e.g., VaR_95 = -5th percentile
- **Monte Carlo VaR:** Simulate N paths dari fitted distribution → `VaR_α = -percentile(simulated_returns, α)`
- **Parametric:** Assume returns ~ N(μ, σ²) → `VaR_α = -(μ + z_α × σ)`
- **Current:** 10,000 simulations, CUDA:1, VaR95=-1.56%, VaR99=-2.16%

#### Kritik & Kelemahan

1. **Distribution Assumption:** MC VaR assumes returns follow fitted distribution (usually Gaussian or Student-t). Real returns have fat tails, skewness → VaR underestimated
2. **Correlation Stability:** Portfolio VaR assumes correlation matrix stable → violated during crises (correlation → 1)
3. **Backtesting Difficulty:** VaR exceptions are rare (5% or 1%) → hard to validate statistically
4. **Tail Risk:** VaR doesn't capture Expected Shortfall (ES) — magnitude of loss beyond VaR threshold

#### Perbaikan & Improvements

1. **Expected Shortfall (ES):** `ES_α = -E[returns | returns < -VaR_α]` — more informative than VaR, coherent risk measure
2. **Copula-Based Simulation:** Use copula (t-copula, Clayton) untuk model tail dependence → better portfolio VaR
3. **Filtered Historical Simulation:** Bootstrap from recent returns conditioned on current volatility → adaptive
4. **Stress Testing:** Combine VaR dengan scenario analysis (2008 crisis, 2020 COVID, 2026 political)

#### Status Implementasi
- **Implemented:** 10K simulations, CUDA:1, VaR95/99
- **Keputusan:** KEEP — tambahkan ES, copula-based simulation, stress testing scenarios

---

## 8. Layer 5: Execution & Order Management

### A. Current Implementation

**Files:**
- `src/market/execution/automation.py` (46K, 1303 lines) — PlanBuilder, AutoExecutor, AutomationOrchestrator
- `src/market/execution/brokers.py` (6K) — BrokerAdapter (Mock/Paper/Real)
- `src/market/execution/oms.py` (6.3K) — Order Management System
- `src/market/execution/smart_order_router.py` (13.5K) — SOR untuk best execution
- `src/market/execution/market_impact.py` (11K) — Market impact model
- `src/market/execution/validation.py` (4.8K) — Pre-trade validation
- `src/market/execution/event_store.py` (16K) — Event sourcing untuk audit trail
- `src/market/execution/portfolio.py` (6.9K) — Portfolio state tracking

**AutomationOrchestrator Flow:**
```
1. User mengatur config (centang pilihan) di FE
2. AutomationGate memeriksa config — jika pass, lanjut
3. PlanBuilder membuat ExecutionPlan dari sinyal:
   - Filter berdasarkan source, confidence, market scope
   - Validasi readiness gate per instrumen
   - Hitung position sizing via RiskEngine
   - Validasi IDX rules (lot size 100, tick size)
   - Buat ExecutionPlan dengan PlanOrders
4. AutoExecutor menjalankan plan via broker:
   - Holds persistent OMS instance
   - Submit order via BrokerAdapter
5. Hasil dilaporkan ke user
```

### B. Evaluasi Akademik & Praktis

#### Kelebihan

1. **Event-driven architecture** — AutomationOrchestrator menggunakan event broker, sesuai best practice (NautilusTrader, NexusFi 2024)
2. **OMS sebagai persistent state** — AutoExecutor holds persistent OMS instance, preserving order history across calls
3. **Smart Order Router** — SOR (13.5K lines) mengimplementasikan best execution logic
4. **Market impact model** — `market_impact.py` (11K) menghitung price impact dari order size
5. **IDX-specific validation** — Lot size (100 shares), tick size validation
6. **Event sourcing** — `event_store.py` (16K) untuk audit trail dan replay

#### Kritik & Kelemahan

1. **MockBroker only** — Tidak ada real broker adapter yang berfungsi. Untuk IDX, broker yang umum: RHB Sekuritas, BCA Sekuritas, Mirae Asset. Tidak ada FIX protocol adapter.

2. **Risk gate tidak fail-closed** — NexusFi (2024): "When the system doesn't know its current state — after a disconnect, during reconciliation — it stops trading, not continues with potentially corrupt state." Sistem saat ini tidak memiliki fail-closed mechanism.

3. **Tidak ada reconciliation loop** — Setelah broker disconnect, sistem tidak otomatis reconcile positions. NexusFi (2024): "A broker disconnect reconciles automatically within seconds."

4. **Market impact model tidak terintegrasi penuh** — `market_impact.py` ada tapi tidak clear apakah digunakan dalam PlanBuilder's position sizing.

5. **Tidak ada execution algorithm** — Tidak ada TWAP, VWAP, atau implementation shortfall (IS) algorithm. Hanya simple market/limit orders.

6. **Slippage model terlalu sederhana** — `SLIPPAGE_RATE` adalah fixed percentage, bukan dynamic berdasarkan volume/volatility.

7. **Tidak ada partial fill handling** — OMS tidak explicitly handle partial fills dan order modifications.

#### Perbaikan & Best Practices

1. **Real Broker Adapter** (IDX-specific):
   - RHB Sekuritas API (jika available) atau universal FIX 4.4 adapter
   - At minimum: email/API notification untuk manual execution dengan auto-tracking
   - Paper trading mode dengan real market data sebagai intermediate step

2. **Fail-Closed Risk Gate** (NexusFi 2024):
   ```python
   if not self._state_confident:
       # Deny all new orders, cancel pending orders
       self._cancel_all_pending()
       return OrderDenied(reason="state_uncertain")
   ```

3. **Reconciliation Loop** (NexusFi 2024):
   - Periodic (every 30s): compare OMS positions dengan broker positions
   - On reconnect: full reconciliation, mark state as confident only when matched
   - Log discrepancies untuk audit

4. **Execution Algorithms**:
   - VWAP: split order secara proportional ke historical volume curve
   - TWAP: split order evenly across time window
   - IS (Implementation Shortfall): minimize difference between decision price dan execution price
   - Adaptive: switch algorithm berdasarkan volume/volatility regime

5. **Dynamic Slippage Model** (Almgren-Chriss):
   - `slippage = η × σ × √(participation_rate)`
   - η = market impact parameter, σ = daily volatility
   - More realistic daripada fixed percentage

6. **Pre-Trade Risk Checks** (hard gate):
   - Position limit: tidak boleh exceed max_position_pct
   - Notional limit: tidak boleh exceed max_notional_per_order
   - Order rate: max N orders per minute
   - Drawdown limit: stop trading jika drawdown > threshold
   - All checks must pass before order reaches OMS

### C. Status Implementasi

- **Existing:** AutomationOrchestrator, OMS, SOR, market impact model, event store, IDX validation
- **Missing:** Real broker adapter, fail-closed risk gate, reconciliation, execution algorithms, dynamic slippage
- **Keputusan:** **FIX (P2)** — Prioritas: (1) paper trading dengan real market data, (2) fail-closed risk gate, (3) reconciliation loop, (4) VWAP/TWAP execution, (5) real broker adapter

---

## 9. Layer 6: Backtesting & Validation

### A. Current Implementation

**Files:**
- `src/market/backtest/engine.py` — Event-driven BacktestEngine
- `src/market/analysis/walk_forward.py` (191 lines) — WalkForwardOptimizer
- `src/market/analysis/strategy_selector.py` (438 lines) — Strategy selection dengan in-sample evaluation
- `src/market/analysis/attribution.py` — Signal attribution analysis
- `scripts/engine_ablation/run_ablation.py` — Ablation testing framework

**BacktestEngine features:**
- Event-driven simulation dengan realistic execution
- Transaction costs: commission 0.15%, sales tax 0.1%, slippage
- Initial capital: 100M IDR (configurable)
- Max position: 100% per trade (configurable)
- Equity curve, trade log, performance metrics

**WalkForwardOptimizer features:**
- Rolling train/test folds (default: 252 train, 63 test, 5 embargo)
- Parameter grid search per fold
- OOS Sharpe, total return, max drawdown
- Parameter stability metric (fraction of folds with same params)
- Stitches OOS returns untuk honest equity curve

### B. Evaluasi Akademik & Praktis

#### Kelebihan

1. **Event-driven engine** — Micro Alphas (2024): "event-driven backtests process one event at a time and model execution, latency, and order handling far more faithfully." BacktestEngine mengimplementasikan ini.
2. **Walk-forward dengan embargo** — Embargo period (5 days) mencegah leakage antara train dan test. Ini adalah best practice (López de Prado 2018).
3. **Parameter stability tracking** — WalkForwardOptimizer mengukur fraction of folds dengan same params, indikator overfitting.
4. **Transaction costs modeled** — Commission, sales tax, slippage semua di-account for.
5. **Strategy selector** — Combines personality-based recommendation dengan in-sample backtesting.

#### Kritik & Kelemahan

1. **Tidak ada DSR/PBO integration** — Walk-forward results tidak dikoreksi untuk multiple testing. Dengan 16 engines × multiple parameter combinations, probability of finding false positive sangat tinggi. Bailey & López de Prado (2014): DSR wajib untuk any system yang tests multiple strategies.

2. **Tidak ada vectorised backtest engine** — Micro Alphas (2024): "Mature teams use both — the vectorised engine to screen, the event-driven engine to validate finalists." Sistem hanya punya event-driven, yang lebih realistic tapi slower untuk screening.

3. **Walk-forward tidak terintegrasi dengan engine selection** — WalkForwardOptimizer ada tapi tidak dipanggil oleh SignalPipeline atau StrategySelector secara automatic. Harus manual run.

4. **Tidak ada combinatorially symmetric cross-validation (CSCV)** — PBO tidak dapat di-compute tanpa CSCV framework.

5. **Tidak ada transaction cost sensitivity analysis** — Tidak ada test untuk verify apakah strategy survive dengan 2× atau 3× current transaction costs.

6. **Tidak ada regime-conditional backtesting** — Backtest tidak split results by market regime (trending/ranging/crisis). Performance bisa sangat berbeda antar regime.

7. **Look-ahead bias risk** — BacktestEngine menggunakan close prices untuk signal generation dan execution. Harusnya: signal dari close_t, execution di open_{t+1} (next bar open).

#### Perbaikan & Best Practices

1. **DSR + PBO Framework** (Bailey & López de Prado 2014):
   - Setelah walk-forward, compute DSR untuk each engine
   - DSR adjusts for: N trials (16 engines × param combinations), T (track record length), skewness, kurtosis
   - PBO via CSCV: N=8 sub-samples, C(8,4)=70 train/test combinations
   - Only engines dengan DSR > 0.95 dan PBO < 0.1 pass ke production

2. **Vectorised Backtest Engine** (Micro Alphas 2024):
   - Fast screening: `returns = signal.shift(1) * price.pct_change()`
   - Use untuk rank 100s of parameter combinations
   - Top 5 finalists → event-driven validation

3. **Next-Bar-Open Execution**:
   - Signal generated dari close_t → execution at open_{t+1}
   - Menghilangkan look-ahead bias
   - Lebih realistic: tidak bisa trade at close price

4. **Regime-Conditional Backtesting**:
   - Split backtest period by HMM regime (trending/ranging/crisis)
   - Report Sharpe per regime
   - Strategy yang hanya profit di 1 regime → less robust

5. **Transaction Cost Stress Test**:
   - Run backtest dengan 1×, 2×, 3× transaction costs
   - Strategy yang profitable hanya di 1× → fragile
   - IDX costs: commission 0.15% + sales tax 0.1% = 0.25% round trip

6. **Monte Carlo Permutation Test** (Harvey & Liu 2015):
   - Shuffle signal timestamps, recompute Sharpe
   - P-value = fraction of shuffled Sharpes > observed Sharpe
   - Controls for data snooping tanpa parametric assumptions

### C. Status Implementasi

- **Existing:** Event-driven BacktestEngine, WalkForwardOptimizer, StrategySelector, ablation framework
- **Missing:** DSR/PBO, vectorised engine, CSCV, regime-conditional backtest, cost stress test, permutation test
- **Keputusan:** **FIX (P0)** — DSR/PBO adalah critical untuk validasi 16 engines. Implement next-bar-open execution. Tambah vectorised engine untuk fast screening.

---

## 10. Layer 7: Evaluation, Monitoring & Feedback Loop

### A. Current Implementation

**Files:**
- `src/market/mlops/drift.py` (261 lines) — DriftDetector dengan PSI
- `src/market/analysis/attribution.py` — Signal attribution analysis
- `src/market/analysis/recompute_analyzer.py` (644 lines) — Prediction accuracy evaluation
- `src/market/scheduler_tasks.py:308-408` — `_task_drift_detection()` scheduled task
- `src/market/analysis/execution_analyzer.py` — Post-execution analysis
- `scripts/track_kpi.py` — KPI tracking
- `scripts/run_30day_paper_trading.py` — 30-day paper trading evaluation

**DriftDetector features:**
- Prediction drift: PSI pada predicted return distribution
- Feature drift: PSI per feature column
- Performance drift: metric degradation (mean confidence, std, return)
- PSI thresholds: < 0.1 (OK), 0.1-0.25 (monitor), > 0.25 (investigate)
- `assess()` method untuk full drift report

**Scheduled drift detection:**
- Runs periodically via scheduler
- Compares last 30 days predictions vs 30-90 days ago baseline
- Requires minimum 20 predictions in each window
- Persists warning to `app_notifications` jika drift detected

**RecomputeAnalyzer feedback loop:**
- `evaluate_prediction_accuracy()`: compares predicted duration/rows vs actual
- Tracks `duration_error_pct` and `rows_error_pct`
- Marks predictions as `was_used` when actual run stats available

### B. Evaluasi Akademik & Praktis

#### Kelebihan

1. **PSI-based drift detection** — PSI adalah industry standard untuk monitoring model drift. Thresholds (0.1/0.25) sesuai best practice.
2. **Multi-dimensional drift** — Checks predictions, features, dan metrics separately — comprehensive.
3. **Scheduled automated detection** — Tidak perlu manual, runs via scheduler.
4. **Prediction accuracy feedback** — RecomputeAnalyzer closes the loop untuk recompute duration/row predictions.
5. **Signal attribution** — `attribution.py` tracks which engine contributed to which decision.

#### Kritik & Kelemahan

1. **Tidak ada signal decay tracking** — Micro Alphas (2024): "live performance is compared against backtest expectations so decay is detected early rather than discovered in the P&L." Sistem tidak track per-engine IC over time. Tidak ada chart: IC_t vs IC_{t-30d} untuk detect decay.

2. **Tidak ada automated model retirement** — Bailey & López de Prado (2012): MinTRL (Minimum Track Record Length) — berapa lama track record diperlukan untuk have confidence. Tidak ada automated retirement ketika DSR < threshold atau IC < 0 untuk N consecutive periods.

3. **Drift detection tidak real-time** — Runs via scheduler (daily/weekly), bukan per-prediction. Untuk swing trading, daily mungkin cukup, tapi untuk day trading, perlu lebih frequent.

4. **Tidak ada prediction vs reality comparison** — Sistem tidak systematically compare predicted direction (UP/DOWN) vs actual forward returns. `stock_prediction` table ada tapi tidak ada automated comparison pipeline.

5. **Tidak ada live-vs-backtest parity check** — Micro Alphas (2024): "the same logic and the same data versions must produce the same results." Tidak ada verification bahwa live signals match backtest signals untuk same input data.

6. **Tidak ada alert escalation** — Drift warning hanya persist ke `app_notifications`. Tidak ada escalation (email, Telegram, auto-disable strategy).

7. **Attribution log tidak lengkap** — `attribution.py` ada tapi tidak clear apakah setiap trading decision logged dengan full attribution (which engines contributed, what weight, what signal value).

#### Perbaikan & Best Practices

1. **Per-Engine IC Tracking** (Micro Alphas 2024):
   - Compute rolling 30-day IC per engine: `IC_t = corr(signal_t, forward_return_t)`
   - Alert jika IC drops below 0 for 5 consecutive days
   - Chart: IC over time per engine → visual decay detection
   - Store di `signal_attribution_log` table

2. **Automated Model Retirement** (Bailey & López de Prado 2012):
   ```python
   def check_retirement(engine_name, track_record_days, sharpe, dsr):
       if track_record_days < MinTRL(sharpe, skew, kurt):
           return "insufficient_track_record"
       if dsr < 0.95:
           return "dsr_below_threshold"
       if rolling_ic < 0 for 20 consecutive days:
           return "ic_negative_persistent"
       return "healthy"
   ```

3. **Prediction vs Reality Pipeline**:
   - Setiap signal: store predicted_direction, predicted_magnitude, confidence
   - T+5: compute actual forward return
   - Compare: directional accuracy, IC, calibration
   - Store di `prediction_evaluation` table
   - Automated report: "Engine X accuracy last 30 days: 54% (expected >52%)"

4. **Live-Backtest Parity Check**:
   - Run backtest untuk last 5 days dengan same data
   - Compare signals: live signal vs backtest signal
   - If mismatch > threshold → alert (possible code bug atau data issue)

5. **Alert Escalation**:
   - Level 1: app notification (current)
   - Level 2: Telegram/email untuk repeated drift
   - Level 3: Auto-disable strategy (stop generating signals dari engine tersebut)
   - Level 4: Human review required untuk re-enable

6. **Signal Attribution Log Schema**:
   ```
   signal_attribution_log:
       date, ticker, engine_name, signal_value, signal_direction,
       confidence, weight_in_portfolio, contribution_to_decision,
       actual_forward_return_5d, ic_contribution
   ```

### C. Status Implementasi

- **Existing:** DriftDetector (PSI), RecomputeAnalyzer feedback, attribution module, scheduled drift detection
- **Missing:** Per-engine IC tracking, automated retirement, prediction vs reality pipeline, live-backtest parity, alert escalation, full attribution log
- **Keputusan:** **FIX (P1)** — Implement per-engine IC tracking, prediction vs reality pipeline, automated retirement criteria. Alert escalation untuk production safety.

---

## 11. Data Inventory & Gaps

### Data yang Ada (cukup untuk pengujian):
- `stock_prices`: 3.6M rows, 1030 IDX tickers, 1927-2026
- `fundamental_data`: 7769 rows, 1007 tickers, 2024-2026
- `macro_data`: 72786 rows, 46 series, 1962-2026
- `news_sentiment`: 3689 rows, 165 tickers, 2024-2026
- `foreign_flow`: 1.26M rows, 983 tickers, 2019-2026
- `policy_events`: 179 rows
- `external_events`: 44 rows
- `exchange_holidays`: 5883 rows
- `market_influence_kb`: 34760 rows
- `ml_labels`: 9.8M rows
- `broker_daily_summary`: 440 rows (5 dates × 88 brokers)
- `corporate_calendar`: 251 rows (RUPS, buyback, dividend)
- Global indices: ^GSPC, ^DJI, ^N225, ^HSI, ^FTSE, ^GDAXI, ^VIX, ^TNX, 000001.SS, DX-Y.NYB

### Data yang Belum Ada / Perlu Dilengkapi:
1. **Fear & Greed Index** — tidak ada di macro_data (perlu fetch dari CNN Fear & Greed API)
2. **Risk-free rate** — BI rate ada di macro_data, tapi perlu sebagai daily series untuk Sharpe calculation
3. **Sector classification mapping** — perlu verify mapping ticker → sector untuk sector-neutral factors dan sector rotation
4. **Intangible capital data** — R&D expense, brand value, software assets untuk intangible-adjusted fundamental
5. **Cash flow statement data** — untuk cash profitability factor (Fama-French improvement)
6. **Options/implied volatility** — untuk forward-looking regime detection dan VIX-conditioned signals
7. **Tick-level data** — untuk true OFI computation (currently proxy dengan EOD data)

---

## 12. Metodologi Pengujian

### Phase 1: Dry-Run / Sample Duration Testing ✅ COMPLETED
- Test dengan 5 tickers (BBCA, BBRI, TLKM, ASII, UNVR), 10 trading days
- Verify semua engine menghasilkan sinyal non-FLAT
- Measure computation time per ticker-day
- Result: 14/16 engines active, 2 still need parameter tuning (sentiment, alpha_mean_reversion)

### Phase 2: Full Backfill
- 20-50 tickers (fokus liquid IDX), 250 trading days
- Compute all engine signals
- Fill forward returns (1d, 3d, 5d, 10d)

### Phase 3: Evaluation with Proper Methodology
For each engine:
1. **IC (Information Coefficient)** — Spearman rank correlation between signal and fwd return, HAC-adjusted SE
2. **Directional Accuracy** — % of days where signal direction matches fwd return direction
3. **Forward Return Spread** — avg fwd return when UP vs DOWN signal
4. **Walk-Forward Sharpe** — rolling 60-day OOS Sharpe ratio
5. **Deflated Sharpe Ratio** — correct for 16 engines × multiple parameter sets tested
6. **PBO (CSCV)** — probability that signal selection is overfit, N=8 sub-samples
7. **MinTRL** — minimum track record length for statistical significance
8. **Haircut Sharpe** — Harvey-Liu multiple testing correction

### Phase 4: Decision Matrix
| Criteria | Threshold | Action |
|----------|-----------|--------|
| IC > 0.05 AND DSR > 0.95 | Strong | KEEP |
| IC > 0.02 AND DirAcc > 52% | Moderate | KEEP with monitoring |
| IC ~ 0 OR DirAcc ~ 50% | Weak | FIX or DROP |
| IC < 0 (inverted) | Inverted | INVERT or DROP |
| Always FLAT | No signal | DROP |
| PBO > 0.5 | Overfit | DROP |

---

## 13. Decision Matrix — Full Pipeline

### Summary of Decisions

| # | Engine | Decision | Priority | Key Action |
|---|--------|----------|----------|------------|
| 1 | technical | KEEP | P0 | Inverted signal, DSR correction |
| 2 | fundamental | FIX | P1 | Wire ke DB, intangible adjustment, cash profitability |
| 3 | macro | KEEP | P1 | Tambah BI rate, inflation, DJIA; asymmetric model |
| 4 | sentiment | FIX | P0 | Lower threshold, amplify foreign flow, disagreement signal |
| 5 | relationship | KEEP | P1 | Asymmetric spillover, overnight signal |
| 6 | global | KEEP | P1 | Overnight momentum, VIX conditioning |
| 7 | alpha_mean_reversion | FIX | P0 | Continuous z-score, lower thresholds, momentum filter |
| 8 | alpha_reversal | FIX | P0 | Lower Z-threshold, momentum filter, exponential decay |
| 9 | alpha_ewma_momentum | KEEP | P1 | Volatility scaling, test TSMOM separately |
| 10 | alpha_regime_switch | KEEP | P1 | Integrate dengan HMM, smooth transition |
| 11 | astronacci | EXPERIMENTAL | P3 | Inverted signal, DSR/PBO test. DROP if not significant |
| 12 | volume | KEEP | P1 | Foreign flow as primary OFI, COI classification |
| 13 | policy_event | KEEP | P1 | Signal quality index, sector-specific impact |
| 14 | holiday_effect | KEEP | P2 | Verify with holiday dates, type classification |
| 15 | fama_french_5f | KEEP | P0 | Upgrade ke FF6, cash profitability, intangibles, IDX adaptation |
| 16 | hmm_regime | KEEP | P0 | BOCPD alternative, pre-fit on IHSG, ensemble regime |
| — | **HRP** | KEEP | P0 | Upgrade ke Topdown, Ledoit-Wolf shrinkage |
| — | **DSR** | IMPLEMENT | P0 | DSR + Haircut Sharpe untuk evaluasi |
| — | **PBO** | IMPLEMENT | P0 | CSCV N=8, combine dengan walk-forward |
| — | **Kelly** | KEEP | P1 | Risk-constrained Kelly, drawdown-adjusted |
| — | **VaR** | KEEP | P1 | Tambah ES, copula, stress testing |

### Priority Implementation Order:
1. **P0 (Critical):** Fix sentiment, alpha_mean_reversion, alpha_reversal → backfill → evaluate dengan DSR/PBO
2. **P0 (Critical):** Implement DSR + PBO evaluation framework
3. **P0 (Critical):** Upgrade Fama-French ke FF6, HMM dengan BOCPD/pre-fit
4. **P0 (Critical):** Next-bar-open execution di BacktestEngine (look-ahead bias fix)
5. **P1 (Important):** Fundamental DB wiring, macro asymmetric model, volume foreign flow
6. **P1 (Important):** HRP Topdown, risk-constrained Kelly
7. **P1 (Important):** Point-in-time storage untuk fundamental_data dan macro_data
8. **P1 (Important):** FeatureStore integration, factor versioning
9. **P1 (Important):** Per-engine IC tracking, prediction vs reality pipeline
10. **P2 (Optional):** Holiday effect verification, relationship/global improvements
11. **P2 (Optional):** Paper trading dengan real market data, fail-closed risk gate
12. **P2 (Optional):** Vectorised backtest engine untuk fast screening
13. **P3 (Experimental):** Astronacci rigorous testing — keep or drop
14. **P3 (Experimental):** Real broker adapter (IDX), execution algorithms (VWAP/TWAP)

### Pipeline-Level Decisions

| Layer | Decision | Priority | Key Action |
|-------|----------|----------|------------|
| 1. Data Fetch | FIX | P1 | Point-in-time schema, tick validation, circuit breaker |
| 2. Recompute | FIX | P1 | FeatureStore integration, factor versioning, historical indicator storage |
| 3. Signal Gen | MIXED | P0-P3 | Per-engine decisions (see above) |
| 4. Portfolio | KEEP+FIX | P1 | HRP Topdown, risk-constrained Kelly, cost-aware optimization |
| 5. Execution | FIX | P2 | Paper trading, fail-closed risk, reconciliation, VWAP/TWAP |
| 6. Backtesting | FIX | P0 | DSR/PBO, next-bar-open, vectorised engine, regime-conditional |
| 7. Monitoring | FIX | P1 | Per-engine IC tracking, automated retirement, prediction vs reality |

---

## 14. Renovation Plan

### A. Pendekatan: Incremental Renovation (Bukan Rewrite dari Nol)

Berdasarkan audit lengkap 7-layer pipeline, rekomendasi adalah **incremental renovation** dari codebase existing, bukan membuat aplikasi baru dari nol. Alasan:

1. **Database schema sudah mature** — 99 tables, 39 migrations, 6.6 GB data, Alembic head 0039. Membuat ulang database = massive data migration risk.
2. **Event-driven architecture sudah correct** — `core/wiring.py` dengan pub/sub broker adalah best practice (NautilusTrader, NexusFi 2024). Tidak perlu rewrite architecture.
3. **18 recompute functions sudah functional** — RecomputeGraph dengan selective recompute adalah advanced feature. Tidak perlu rebuild.
4. **Signal engines sudah ada 16** — Sebagian besar KEEP atau FIX, bukan DROP. Rewriting dari nol = 6+ bulan kerja ulang.
5. **BacktestEngine dan WalkForwardOptimizer sudah ada** — Perlu enhancement (DSR/PBO), bukan rewrite.

### B. Renovation Phases

#### Phase 1: Foundation Fixes (P0, 2-4 minggu)
**Goal:** Fix critical validity issues yang membuat backtest tidak trustworthy.

1. **Implement next-bar-open execution** di BacktestEngine
   - Signal dari `close_t` → execution di `open_{t+1}`
   - Eliminasi look-ahead bias

2. **Implement DSR + PBO framework**
   - `src/market/evaluation/dsr.py` — Deflated Sharpe Ratio
   - `src/market/evaluation/pbo.py` — PBO via CSCV (N=8)
   - Integrate dengan WalkForwardOptimizer

3. **Fix 3 FLAT engines** (sentiment, alpha_mean_reversion, alpha_reversal)
   - Lower thresholds, continuous signals, wire ke DB data
   - Backfill → verify non-FLAT signals

4. **Add vectorised backtest engine**
   - `src/market/backtest/vectorised.py`
   - Fast screening untuk parameter grid search

#### Phase 2: Data & Feature Integrity (P1, 4-8 minggu)
**Goal:** Ensure data correctness untuk backtest dan live parity.

1. **Point-in-time storage untuk fundamental_data**
   - Add `as_of_date` column
   - Migration: backfill as_of_date dari fetch timestamps
   - Query helper: `get_fundamental(ticker, date, as_of=date)`

2. **FeatureStore integration**
   - Register all 18 recompute functions sebagai feature definitions
   - Versioning: `feature_name@version`
   - Backtest dapat request specific version

3. **Store historical technical indicators**
   - Ubah `technical_indicators` dari snapshot ke time-series
   - Migration: add `date` column, backfill dari OHLCV recompute
   - ~2.25M rows/year, acceptable untuk PostgreSQL

4. **Per-engine IC tracking**
   - New table: `signal_attribution_log`
   - Scheduled task: compute rolling 30-day IC per engine
   - Alert jika IC < 0 for 5 consecutive days

#### Phase 3: Portfolio & Risk Enhancement (P1, 4-6 minggu)
**Goal:** Improve portfolio construction dan risk management.

1. **HRP Topdown** — Upgrade dari standard HRP
2. **Risk-constrained Kelly** (Busseti 2016)
3. **Drawdown-adjusted position sizing**
4. **Transaction cost-aware rebalancing**
5. **Regime-conditional backtesting** — Split results by HMM regime

#### Phase 4: Execution Safety (P2, 4-8 minggu)
**Goal:** Safe execution untuk paper trading dan eventual live trading.

1. **Paper trading mode** dengan real market data
2. **Fail-closed risk gate** — Stop trading when state uncertain
3. **Reconciliation loop** — Compare OMS vs broker positions
4. **VWAP/TWAP execution algorithms**
5. **Dynamic slippage model** (Almgren-Chriss)

#### Phase 5: Monitoring & Feedback (P1-P2, 3-5 minggu)
**Goal:** Close the loop between prediction dan reality.

1. **Prediction vs reality pipeline**
   - Store predicted direction + magnitude + confidence
   - T+5: compare dengan actual forward return
   - Automated accuracy report per engine

2. **Automated model retirement**
   - MinTRL check, DSR threshold, IC persistence check
   - Auto-disable engines yang fail criteria

3. **Alert escalation**
   - Level 1: app notification → Level 2: Telegram → Level 3: auto-disable → Level 4: human review

4. **Live-backtest parity check**
   - Run backtest untuk last 5 days, compare dengan live signals
   - Alert jika mismatch

#### Phase 6: Advanced Features (P3, ongoing)
**Goal:** Research dan experimental features.

1. **FF6 upgrade** — Tambah momentum factor ke Fama-French
2. **BOCPD regime detection** — Bayesian alternative untuk HMM
3. **Copula-based VaR** — Better tail dependence modeling
4. **Astronacci rigorous testing** — DSR/PBO test, keep or drop
5. **Real broker adapter** — FIX 4.4 atau IDX-specific API

### C. File Structure Proposal (Renovation)

```
src/market/
├── core/                    # Event bus, wiring (KEEP)
├── data/                    # Data fetching (FIX: add point-in-time)
│   ├── fetch_registry.py    # KEEP
│   ├── idx_adapter.py       # KEEP
│   ├── timestamp_validation.py  # KEEP
│   └── point_in_time.py     # NEW: bitemporal query helpers
├── mlops/                   # ML ops (FIX: integrate FeatureStore)
│   ├── feature_store.py     # FIX: integrate dengan recompute
│   ├── drift.py             # KEEP
│   └── cross_validation.py  # KEEP
├── analysis/                # Signal engines (MIXED: per-engine decisions)
│   ├── technical.py         # KEEP
│   ├── fundamental.py       # FIX
│   ├── ... (16 engines)     # See decision matrix
│   ├── recompute.py         # FIX: use FeatureStore
│   └── recompute_graph.py   # KEEP
├── evaluation/              # NEW: evaluation framework
│   ├── dsr.py               # NEW: Deflated Sharpe Ratio
│   ├── pbo.py               # NEW: PBO via CSCV
│   ├── ic_tracking.py       # NEW: per-engine IC tracking
│   └── prediction_reality.py # NEW: prediction vs reality
├── risk/                    # Risk management (FIX)
│   ├── capital_aware_sizer.py  # FIX: risk-constrained Kelly
│   ├── monte_carlo_var.py   # KEEP
│   └── portfolio.py         # FIX: HRP Topdown
├── backtest/                # Backtesting (FIX)
│   ├── engine.py            # FIX: next-bar-open
│   ├── vectorised.py        # NEW: vectorised backtest
│   └── regime_conditional.py # NEW: regime-conditional backtest
├── execution/               # Execution (FIX)
│   ├── automation.py        # FIX: fail-closed risk gate
│   ├── oms.py               # FIX: reconciliation
│   ├── brokers.py           # FIX: paper trading mode
│   ├── smart_order_router.py # KEEP
│   ├── market_impact.py     # FIX: integrate dengan PlanBuilder
│   └── algorithms.py        # NEW: VWAP/TWAP/IS
├── pipelines/               # Event-driven pipelines (KEEP)
└── api/                     # REST API (KEEP)
```

### D. New Tables Required

| Table | Purpose | Migration |
|-------|---------|-----------|
| `stock_prices_pit` | Point-in-time OHLCV dengan as_of_date | 0040 |
| `fundamental_data_pit` | Point-in-time fundamental dengan as_of_date | 0041 |
| `technical_indicators_historical` | Time-series technical indicators (bukan snapshot) | 0042 |
| `signal_attribution_log` | Per-engine IC tracking dan attribution | 0043 |
| `prediction_evaluation` | Prediction vs reality comparison | 0044 |
| `model_retirement_log` | Engine retirement decisions dan reasons | 0045 |
| `global_market_interdependencies` | Cross-asset causality matrix (master) | 0009 |
| `global_market_interdependency_history` | Daily causality snapshots (child) | 0009 |

### E. Testing Methodology untuk Renovation

Setiap phase harus melalui:

1. **Unit test** — Setiap new module memiliki unit test
2. **Integration test** — Verify module integrates dengan existing pipeline
3. **Backtest parity test** — Before/after renovation, run same backtest, verify results match atau improve
4. **Dry-run** — Run pada 5 tickers, 10 days, verify no errors
5. **Duration test** — Run pada 20 tickers, 250 days, verify performance
6. **Full backfill** — Run pada all tickers, verify completeness
7. **DSR/PBO evaluation** — Only engines yang pass masuk production

---

## 15. References

### Technical Analysis
- Caporale, G.M. & Plastun, A. (2024). "Pitfalls of Technical Analysis." CESifo Working Paper no. 10213.
- Hsu, P.H., Hsu, Y.C., & Kuan, C.M. (2010). "Testing the predictive ability of technical analysis using the new SPA test." Journal of Financial Econometrics.
- Lo, A. (2004). "The Adaptive Markets Hypothesis." Journal of Portfolio Management.

### Fundamental Analysis
- Cao, K. & You, H. (2024). "Fundamental Analysis via Machine Learning." Financial Analysts Journal, 80(2), 74-98.
- CEPR DP19320 (2024). "Intrinsic Value: A Solution to the Declining Performance of Value Strategies."
- "Classical Stock Valuation in the Modern Era of Intangibles" (2024). Journal of Investing.

### Macro
- Sia, P.C. et al. (2024). "Does inflation or interest rate matter to Indonesian stock prices? An asymmetric approach." Journal of Economics and Development.
- Wardatunisa et al. (2024). "Pengaruh inflasi, nilai tukar, suku bunga BI dan Dow Jones Index terhadap IHSG."
- IJEBMR (2025). "Macroeconomic Determinants of Stock Market Performance: Evidence From Indonesia."
- PKP (2025). "Bridging finance and technology: ML-based portfolio construction in the Indonesian market."
- Salisu, A.A. et al. (2023). "Policy uncertainty and stock market volatility revisited: The predictive role of signal quality." Journal of Forecasting.

### Sentiment
- Kengmegni, F.N. (2025). "Multi-level Stock Movement Prediction Using LLMs." arXiv.
- Glasserman, S. & Lin, Y. (2024). "Look-ahead bias in LLM-based stock predictions."
- Lopez-Lira, A. & Tang, Y. (2025). "Can ChatGPT forecast stock price movements?"

### Cross-Market & Global
- Diebold, F.X. & Yilmaz, K. (2012). "Better to Give than to Receive: Predictive Directional Measurement of Volatility Spillovers."
- Zhang, Y. et al. (2024). "Industry volatility spillover and aggregate stock returns." European Journal of Finance, 30(10), 1097-1126.
- Muñoz Mendoza et al. (2024). "Stock, foreign exchange and commodity markets linkages." Global Finance Journal, 63.
- Wen, Y.C. et al. (2023). "Spillover effects of the US stock market and the predictability of returns." Applied Economics, 55(45), 5251-5266.
- Xu, D. et al. (2025). "Cross-market overnight time-series momentum." J. Int. Financial Markets, Institutions & Money, 105.

### Mean Reversion & Reversal
- Jegadeesh, N. (1990). "Evidence of Predictable Behavior of Security Returns." Journal of Finance.
- Lehmann, B. (1990). "Fads, Martingales, and Market Efficiency." Quarterly Journal of Economics.
- Dai, R. et al. (2024). "Enhanced Short-Term Reversal." Journal of Portfolio Management.
- Columbia (2015). "The Rate of Decay of Idiosyncratic Price Shocks."

### Momentum
- Moskowitz, T.J., Ooi, Y.H., & Pedersen, L.H. (2012). "Time Series Momentum." Journal of Financial Economics.
- Daniel, K. & Moskowitz, T.J. (2016). "Momentum Crashes." Journal of Financial Economics.
- Bianchi, F. et al. (2024). "Momentum variances and power laws."

### Fama-French & Factor Models
- Fama, E.F. & French, K.R. (2015). "A five-factor asset pricing model." Journal of Financial Economics.
- Fama, E.F. & French, K.R. (2017). "International tests of a five-factor asset pricing model." Journal of Financial Economics.
- Hou, K., Xue, C., & Zhang, L. (2015). "Digesting Anomalies: An Investment Approach." Review of Financial Studies.
- INT factor (2024). "Intangible assets and the cross-section of stock returns."

### HMM & Regime Detection
- Hamilton, J.D. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series." Econometrica.
- Adams, R.P. & MacKay, D.J.C. (2007). "Bayesian Online Changepoint Detection." arXiv.
- Casarin, R. et al. (2024). "Hierarchical Markov Switching Models for Regime Detection."

### Portfolio Optimization
- López de Prado, M. (2016). "Building Diversified Portfolios that Outperform Out of Sample." Journal of Portfolio Management, 42(4), 59-69.
- Raffinot, T. (2017). "Hierarchical Clustering-Based Asset Allocation." Journal of Portfolio Management.
- Copenhagen Business School (2023). "Hierarchical Risk Parity: Performance and Modifications." Master Thesis.
- Schur Complementary Allocation (2024). arXiv:2411.05807.
- Springer (2025). "An Empirical Evaluation of Distance Metrics in HRP Methods."

### Multiple Testing & Evaluation
- Bailey, D. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." Journal of Portfolio Management.
- Bailey, D. et al. (2014). "The Probability of Backtest Overfitting." Journal of Computational Finance.
- Harvey, C.R. & Liu, Y. (2015). "Backtesting 101: Haircut Sharpe Ratios."

### Kelly Criterion
- Kelly, J.L. (1956). "A New Interpretation of Information Rate." Bell System Technical Journal.
- Thorp, E.O. (1969). "Optimal Gambling Systems for Favorable Games." Review of the International Statistical Institute.
- Busseti, E., Sun, L., & Boyd, S. (2016). "Risk-Constrained Kelly Gambling." Journal of Investing.
- Downey, M. (2024). "Why fractional Kelly? Simulations of bet size with uncertainty."
- MacLean, L.C., Thorp, E.O., & Ziemba, W.T. (2010). "Long-term capital growth: good and bad properties of Kelly."

### Holiday Effect
- 34-country study (2024). "Holiday effect in stock markets: A global perspective."
- Sasikirono, N. & Meidiawati, H. (2017). "Holiday effect di Bursa Efek Indonesia."
- Stefanescu, D. & Dumitriu, R. (2018). "Holiday effects in the Chinese stock market."

### Astronacci
- Lestari, P. (2021). "Financial analysis method based on astrology, Fibonacci, and Astronacci." IJEBR, 22(2/3), 290-310.
- Cambridge History of Finance. "Financial Astrology." Chapter 8.

### Policy & Political Risk
- Hassan, T.A. et al. (2024). "The Global Impact of Brexit Uncertainty." Journal of Finance, 79(1), 413-458.
- PUR Index (2025). "U.S. Presidential news coverage: Risk, uncertainty and stocks." Review of Economics.
- Political Information Quality (2025). "Quality of political information and return predictability." J. Banking & Finance, 177.

### Pipeline Architecture & System Design
- Algovantis (2024). "Building a Robust Algo Trading Signal-to-Execution Pipeline Architecture."
- Micro Alphas (2024). "Building Robust Signal Processing Systems." https://microalphas.com/signal-processing-architecture/
- White Oak Intelligence (2024). "Algorithmic Trading Pipelines." https://whiteoakintel.com/blog/algorithmic-trading-pipelines/
- NexusFi Academy (2024). "Automated Futures Trading Architecture: Production System Design for 7 Decoupled Layers."
- NautilusTrader (2024). "Architecture." https://nautilustrader.io/docs/latest/concepts/architecture/
- Brenndoerfer, M. (2024). "Quant Trading Systems: Architecture & Infrastructure."
- Lycore (2024). "Data Science Trading Systems: Architecture and Portfolio Lessons."
- Git Push and Run (2024). "Designing a High-Throughput Algorithmic Trading Platform on AWS."

### Volume & Order Flow
- Cont, R. et al. (2024). "Order flow imbalance and price impact." Journal of Financial Econometrics.
- Lu, X. et al. (2024). "Deep Order Flow Imbalance." arXiv.
- Deep OFI (2023). "Deep Learning for Order Flow Imbalance Prediction."
