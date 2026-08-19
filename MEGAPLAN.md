# MEGAPLAN — Quant Trading Application
# "Gigantic AI" untuk Pasar Modal Indonesia & Global

## Status: ACTIVE — Autonomous Execution
## Date: 2026-08-19
## Location: /home/petrick/projects/quant/

---

## 0. Eksekutif Summary

Aplikasi `quant` adalah sistem trading kuantitatif berbasis **Gigantic AI** — sebuah multi-agent LLM system yang mengintegrasikan:

1. **Multi-Agent LLM Pipeline** (inspired by AlphaCrafter + FinRL-X + QuantAgents)
   - **Miner Agent**: LLM-guided continuous factor discovery
   - **Screener Agent**: Regime-conditioned factor ensemble construction
   - **Trader Agent**: Risk-constrained portfolio execution
   - **Risk Manager Agent**: Fail-closed risk gate, VaR/ES monitoring
   - **Sentiment Analyst Agent**: IndoBERT-based Indonesian financial NLP

2. **Deep Learning Ensemble** (VAE + Transformer + LSTM + XGBoost/LightGBM)
   - VAE: Dimensionality reduction & feature extraction
   - Transformer: Long-range pattern recognition (attention mechanism)
   - LSTM: Sequential temporal dynamics
   - XGBoost/LightGBM: Tabular feature ensemble with SHAP
   - Triple Barrier Labeling for IDX-specific volatility

3. **Weight-Centric Architecture** (FinRL-X pattern)
   - Selection → Allocation → Timing → Risk Overlay
   - Uniform weight vector interface between all components
   - Backtest-live parity guaranteed

4. **Academic-Grade Validation** (DSR + PBO/CSCV + Walk-Forward)
   - Deflated Sharpe Ratio for selection bias correction
   - Probability of Backtest Overfitting via CSCV
   - Combinatorial Purged K-Fold cross-validation
   - Regime-conditional evaluation

---

## 1. Arsitektur Gigantic AI

### 1.1 Multi-Agent System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    GIGANTIC AI CORE                          │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  MINER   │  │ SCREENER │  │  TRADER  │  │   RISK   │   │
│  │  Agent   │→ │  Agent   │→ │  Agent   │→ │ MANAGER  │   │
│  │          │  │          │  │          │  │  Agent   │   │
│  │ LLM-guided│  │ Regime-  │  │ Portfolio │  │ Fail-closed│  │
│  │ factor    │  │ conditioned│  │construction│  │ VaR/ES    │  │
│  │ discovery │  │ ensemble  │  │ + RL alloc │  │ drawdown   │  │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘   │
│        │             │             │             │          │
│        └─────────────┴─────────────┴─────────────┘          │
│                              │                               │
│                    ┌─────────┴─────────┐                     │
│                    │  SENTIMENT ANALYST │                     │
│                    │  Agent (IndoBERT)  │                     │
│                    │  News + Social     │                     │
│                    └───────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
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

### 1.2 Weight-Centric Pipeline (FinRL-X pattern)

```
w_t = R_t(T_t(A_t(S_t(X_≤t))))
```

Where:
- **S_t** = Stock Selection (ML scoring, liquidity filter, universe definition)
- **A_t** = Portfolio Allocation (HRP-µ, RL allocator, Kelly)
- **T_t** = Timing Adjustment (KAMA trend overlay, regime gate)
- **R_t** = Risk Overlay (VaR limit, drawdown control, concentration cap)

Each transformation preserves the weight vector contract — swap any module without touching the rest.

### 1.3 Deep Learning Ensemble Stack

```
┌─────────────────────────────────────────────┐
│            DL ENSEMBLE (per ticker)          │
│                                              │
│  ┌──────┐  ┌───────────┐  ┌──────┐         │
│  │ VAE  │  │ Transformer│  │ LSTM │         │
│  │ feat │→ │  attention  │→ │ seq  │         │
│  │ extr │  │  long-range │  │ dyn  │         │
│  └──┬───┘  └─────┬─────┘  └──┬───┘         │
│     └────────────┼────────────┘              │
│                  ▼                            │
│          ┌──────────────┐                    │
│          │  Concatenate  │                    │
│          │  + Technical  │                    │
│          │  + Sentiment  │                    │
│          └──────┬───────┘                    │
│                 ▼                             │
│          ┌──────────────┐                    │
│          │ XGBoost+LGBM │                    │
│          │  SHAP top-60  │                    │
│          │  ensemble     │                    │
│          └──────┬───────┘                    │
│                 ▼                             │
│          ┌──────────────┐                    │
│          │ Triple Barrier│                    │
│          │ Labeling (TBL)│                    │
│          │ +3%/-3%/5day  │                    │
│          └──────────────┘                    │
└─────────────────────────────────────────────┘
```

### 1.4 IDX-Specific Adaptations

Berdasarkan riset pasar Indonesia:

- **Retail dominance >70%**: Sentimen berita lokal critical (IndoBERT 94.2% accuracy)
- **Triple Barrier Labeling**: 3%/5-day optimal untuk IHSG volatility (Paperium finding)
- **Sentiment-price correlation**: 0.26 individual → 0.43 co-occurrence clusters
- **60% teknikal / 40% sentimen** optimal weight (clawRxiv finding)
- **Sector-specific**: Banking & Mining paling sensitif terhadap sentimen
- **Broker flow analysis**: Bandarmology untuk deteksi akumulasi institusi/asing
- **Foreign flow**: Net foreign buy/sell sebagai signal kuat di IDX
- **Trading hours**: 09:00-15:50 WIB, UTC+7, DST-aware untuk global markets

---

## 2. Data Layer (Point-in-Time Native)

### 2.1 Database Schema (Sudah Ada)

- `stock_prices` dengan `as_of_date` (bitemporal)
- `foreign_flow` — IDX-specific foreign/domestic flow
- `macro_data` dengan `as_of_date`
- `fundamental_data` dengan `as_of_date`
- `news_sentiment` — IndoBERT-scored
- `policy_events` + `external_events`
- `feature_definitions` + `feature_values` — versioned factor library
- `signal_attribution_log` — per-engine attribution
- `prediction_evaluation` — IC tracking per engine

### 2.2 Data Sources

| Source | Data | Frequency | Status |
|--------|------|-----------|--------|
| yfinance | OHLCV (IDX + global) | EOD + 15min intraday | ✅ Active (cron) |
| idx.co.id | Broker summary, corporate calendar, holidays | Daily | ✅ Adapter copied |
| RSS feeds | CNBC Indonesia, Detik, Kontan, Bisnis | Daily | ⬜ To build |
| BPS/World Bank | Macro indicators | Monthly | ⬜ To build |
| Bank Indonesia | BI Rate, forex | Weekly | ⬜ To build |
| NOAA | Weather/Satellite (CPO, mining) | Daily | ⬜ To build |
| Social media | Stockbit, X (Twitter) | Real-time | ⬜ Phase 3 |

### 2.3 Point-in-Time Query Layer (NEW)

```python
# src/quant/data/point_in_time.py
class PointInTimeQuery:
    """Bitemporal query helper — prevents look-ahead bias."""
    
    def get_prices(self, ticker, as_of_date, lookback=252):
        """Returns only data known as of as_of_date."""
        
    def get_fundamentals(self, ticker, as_of_date):
        """Returns only fundamental data available as of as_of_date."""
        
    def get_macro(self, series, as_of_date):
        """Returns only macro data available as of as_of_date."""
```

---

## 3. Feature Engineering (Versioned Factor Library)

### 3.1 Factor Library Structure

```python
# src/quant/features/factor_library.py
class FactorLibrary:
    """Versioned factor library with LLM-guided expansion."""
    
    factors: dict[str, FactorDefinition]
    
    def register(self, name, version, func, dependencies, description):
        """Register a new factor with metadata."""
        
    def compute(self, factor_name, ticker, date, as_of_date):
        """Compute factor value with PIT protection."""
        
    def validate(self, factor_name, universe, date_range):
        """Validate factor: IC, ICIR, turnover, decay profile."""
        
    def prune(self, threshold_ic=0.02):
        """Remove factors with decayed IC."""
```

### 3.2 Factor Categories

| Category | Factors | Source |
|----------|---------|--------|
| **Technical** | RSI, MACD, BB, ADX, OBV, MFI, ATR, KAMA | Copied from market |
| **Volume** | OFI proxy, VWAP dev, OBV divergence, foreign flow momentum | Copied |
| **Fundamental** | P/E, P/B, ROE, ROA, debt ratio, dividend yield, EPS growth | Copied |
| **Macro** | BI Rate, USD/IDR, CPO price, gold, S&P 500, VIX | Copied |
| **Sentiment** | News sentiment (IndoBERT), sentiment momentum, news volume | NEW (IndoBERT) |
| **Global** | Cross-market correlation, overnight IDX, DCC-GARCH | Copied |
| **Alpha** | Mean reversion, reversal, EWMA momentum, regime switch | Copied |
| **LLM-discovered** | LLM-guided factor mining via Miner Agent | NEW (Phase 2) |

### 3.3 Feature Store Integration

```python
# src/quant/features/feature_store.py (copied, needs adaptation)
class FeatureStore:
    """DB-backed feature store with versioning and freshness monitoring."""
    
    def compute_and_store(self, factor_name, ticker, date):
        """Compute factor → store in feature_values table."""
        
    def get_features(self, ticker, date, factor_names, as_of_date):
        """PIT-safe feature retrieval."""
        
    def freshness_report(self):
        """Report stale features for monitoring."""
```

---

## 4. Signal Generation (Ensemble of Ensembles)

### 4.1 Signal Engine Registry

| Engine | Type | Signal Range | Status |
|--------|------|-------------|--------|
| Technical | Rule-based | [-1, 1] | ✅ Copied |
| Fundamental | Factor-based | [-1, 1] | ✅ Copied |
| Macro | Factor-based | [-1, 1] | ✅ Copied |
| Sentiment (IndoBERT) | NLP + ML | [-1, 1] | ⬜ NEW |
| Global Market | Cross-market | [-1, 1] | ✅ Copied |
| Alpha Signals (4 engines) | ML | [-1, 1] | ✅ Copied |
| HMM Regime | Regime detection | [0, 1] confidence | ✅ Copied |
| Volume Features | Microstructure | [-1, 1] | ✅ Copied |
| Policy Event Scorer | Event-based | [-1, 1] | ✅ Copied |
| Astronacci | Time cycle | [-1, 1] | ✅ Copied |
| Fama-French 5F | Factor model | [-1, 1] | ✅ Copied |
| Holiday Effect | Calendar | [-1, 1] | ✅ Copied |
| DL Ensemble (VAE+Trans+LSTM) | Deep learning | [0, 1] probability | ⬜ NEW (Phase 2) |
| LLM Factor Signals | LLM-discovered | [-1, 1] | ⬜ NEW (Phase 3) |
| RL Allocator | Reinforcement learning | weight vector | ⬜ NEW (Phase 3) |

### 4.2 Continuous Signal Architecture

**Critical change from market app**: Signals are continuous [-1, +1], NOT binary UP/DOWN/FLAT.

```python
# Signal aggregation via weight-centric pipeline
composite_signal = sum(engine.signal * engine.weight for engine in active_engines)
# composite_signal ∈ [-1, +1]
# Position size = f(composite_signal, confidence, risk_budget)
```

### 4.3 Signal Attribution Log

Setiap signal dicatat dengan attribution lengkap di `signal_attribution_log`:
- engine_name, signal_value, signal_direction, confidence
- weight_in_portfolio, contribution_to_decision
- rationale (human-readable)

---

## 5. Portfolio Construction

### 5.1 HRP-µ (Signal-Aware Hierarchical Risk Parity)

Berdasarkan riset terbaru (Beyond De Prado 2025):

```python
# src/quant/portfolio/hrp_mu.py
class HRPMu:
    """HRP with signal integration — not signal-blind like standard HRP."""
    
    def allocate(self, signals: dict[str, float], covariance: pd.DataFrame,
                 gamma: float = 0.5) -> dict[str, float]:
        """
        signals: ticker → signal value [-1, 1]
        covariance: ticker × ticker covariance matrix
        gamma: interpolation between diagonal (0) and full Markowitz (1)
        Returns: ticker → weight [0, 1]
        """
```

### 5.2 Risk-Constrained Kelly

```python
# src/quant/portfolio/kelly.py
class RiskConstrainedKelly:
    """Quarter-Kelly with liquidity and risk caps."""
    
    def size(self, signal, win_rate, odds, max_weight=0.15, 
             liquidity_constraint=None, var_limit=None):
        """Position size with multiple safety constraints."""
```

### 5.3 RL Portfolio Allocator (Phase 3)

```python
# src/quant/portfolio/rl_allocator.py
class RLAllocator:
    """PPO/SAC-based portfolio weight generation."""
    
    def __init__(self, algorithm="PPO"):
        self.algo = algorithm  # PPO for bull, CPPO for bear (FinRL-DeepSeek)
        
    def allocate(self, state) -> np.ndarray:
        """Generate weight vector from market state."""
```

---

## 6. Backtesting & Validation

### 6.1 Walk-Forward Analysis

```python
# src/quant/backtest/walk_forward.py (copied, needs enhancement)
class WalkForwardOptimizer:
    """Rolling train/test folds with OOS metrics."""
    
    def run(self, strategy, data, train_window=252, test_window=63):
        """Returns: OOS Sharpe, return, drawdown, param stability."""
```

### 6.2 DSR + PBO Validation

```python
# src/quant/evaluation/dsr.py
class DeflatedSharpeRatio:
    """Corrects for selection bias and non-normality."""
    
    def compute(self, observed_sr, n_trials, t, skew, kurt):
        """Returns DSR ∈ [0, 1]. >0.95 = real edge."""

# src/quant/evaluation/pbo.py
class ProbabilityOfBacktestOverfit:
    """CSCV-based overfitting detection."""
    
    def compute(self, returns_matrix, n_partitions=16):
        """Returns PBO ∈ [0, 1]. <0.5 = not overfit."""
```

### 6.3 Regime-Conditional Evaluation

```python
# src/quant/evaluation/regime_conditional.py
class RegimeConditionalEvaluator:
    """Evaluate strategy performance per market regime."""
    
    regimes = ["bull", "bear", "sideways", "crisis"]
    
    def evaluate(self, strategy_returns, regime_labels):
        """Returns per-regime: Sharpe, max DD, win rate, IC."""
```

### 6.4 Backtest Engine

```python
# src/quant/backtest/engine.py (copied, needs adaptation)
class BacktestEngine:
    """Event-driven backtest with realistic costs."""
    
    costs = {
        "commission": 0.0015,  # 0.15% broker commission
        "sales_tax": 0.001,    # 0.1% final income tax
        "slippage": 0.001,     # 0.1% slippage
        "bid_ask": 0.0005,     # 0.05% bid-ask spread
    }
```

---

## 7. Execution Layer

### 7.1 Paper Trading OMS

```python
# src/quant/execution/oms.py (copied, needs adaptation)
class OrderManagementSystem:
    """Paper trading with realistic execution simulation."""
    
    def submit_order(self, order):
        """Submit → validate → risk check → fill simulation."""
        
    def reconcile(self):
        """Daily reconciliation: expected vs actual positions."""
```

### 7.2 Fail-Closed Risk Gate

```python
# src/quant/execution/risk_gate.py
class RiskGate:
    """Hard risk limits — blocks orders that violate constraints."""
    
    limits = {
        "max_position_pct": 0.15,      # max 15% per ticker
        "max_sector_pct": 0.40,        # max 40% per sector
        "max_portfolio_var": 0.03,     # max 3% daily VaR
        "max_drawdown": 0.15,          # max 15% drawdown → halt
        "min_cash_reserve": 0.05,      # min 5% cash
    }
    
    def check(self, order, portfolio_state) -> bool:
        """Returns True if order passes all risk checks."""
```

### 7.3 Smart Order Router (Phase 2)

```python
# src/quant/execution/smart_order_router.py (copied)
# VWAP/TWAP execution algorithms for realistic fill simulation
```

---

## 8. Monitoring & Feedback Loop

### 8.1 Per-Engine IC Tracking

```python
# src/quant/monitoring/ic_tracking.py
class ICTracker:
    """Information Coefficient tracking per engine per day."""
    
    def update(self, engine_name, date, predictions, actual_returns):
        """Compute and store IC, Rank IC, ICIR."""
        
    def rolling_ic(self, engine_name, window=60):
        """Rolling IC with decay detection."""
```

### 8.2 Drift Detection

```python
# src/quant/monitoring/drift.py (copied, needs adaptation)
class DriftDetector:
    """PSI-based feature and model drift detection."""
    
    def check_feature_drift(self, feature_name, window=30):
        """PSI > 0.25 = significant drift."""
        
    def check_model_drift(self, engine_name, window=30):
        """IC decay > 50% = model retirement candidate."""
```

### 8.3 Automated Model Retirement

```python
# src/quant/monitoring/retirement.py
class ModelRetirementManager:
    """Automated engine retirement based on performance criteria."""
    
    criteria = {
        "min_track_record_days": 126,    # 6 months minimum
        "min_dsr": 0.50,                 # DSR must be > 50%
        "max_pbo": 0.50,                 # PBO must be < 50%
        "min_rolling_ic": 0.02,          # IC must be > 0.02
        "max_ic_decay_pct": 0.50,        # IC decay < 50%
    }
    
    def evaluate(self, engine_name) -> str:
        """Returns: KEEP / WATCH / RETIRE."""
```

### 8.4 Prediction vs Reality Tracker

```python
# src/quant/monitoring/prediction_reality.py
class PredictionRealityTracker:
    """Track prediction accuracy: predicted vs actual forward returns."""
    
    def evaluate(self, date, horizon=5):
        """Compare predictions to actual N-day forward returns."""
```

---

## 9. Frontend (Next.js)

### 9.1 Pages (Enhanced from market app)

| Page | Function | Status |
|------|----------|--------|
| Dashboard | NAV, IHSG, movers + IC chart, DSR summary | ⬜ Adapt |
| Signals | Continuous signal display, attribution breakdown | ⬜ Adapt |
| Screener | Factor-based screening | ⬜ Adapt |
| Stock Detail | Signal attribution per engine, weight, confidence | ⬜ Adapt |
| Backtest | Walk-forward results, DSR/PBO, regime-conditional | ⬜ Adapt |
| Portfolio | HRP-µ allocation tree, VaR/ES, drawdown | ⬜ Adapt |
| **Evaluation** | DSR/PBO matrix per engine, IC heatmap, MinTRL | ⬜ NEW |
| **Monitoring** | Drift status, IC decay, prediction vs reality | ⬜ NEW |
| Automation | Fail-closed status, reconciliation | ⬜ Adapt |
| Data | Data source status + PIT info | ⬜ Adapt |

### 9.2 New Components

- `charts/ICHeatmap.tsx` — IC per engine per day heatmap
- `charts/EquityCurve.tsx` — Backtest equity with drawdown overlay
- `charts/DSRMatrix.tsx` — DSR/PBO quadrant per engine
- `tables/SignalAttribution.tsx` — Per-engine contribution table
- `tables/FactorLibrary.tsx` — Factor registry with IC/turnover

---

## 10. Implementation Phases

### Phase 1: Foundation (Week 1-2) — P0

**Goal**: Working data pipeline + basic signal generation + PIT queries

| Task | Module | Priority |
|------|--------|----------|
| Point-in-time query layer | `data/point_in_time.py` | P0 |
| Fix import paths (market→quant) | All copied modules | P0 |
| Database connection layer | `core/db.py` | P0 |
| Config system | `core/config.py` | P0 |
| Daily fetch pipeline (enhanced) | `data/fetcher.py` | P0 |
| IndoBERT sentiment integration | `signals/sentiment.py` | P0 |
| Signal aggregation (continuous) | `signals/aggregator.py` | P0 |
| FastAPI skeleton | `api/app.py` | P0 |
| Frontend adaptation (sidebar, dashboard) | `frontend/` | P0 |

### Phase 2: Core AI (Week 3-4) — P1

**Goal**: Deep learning ensemble + evaluation suite + backtest

| Task | Module | Priority |
|------|--------|----------|
| VAE feature extractor | `signals/vae.py` | P1 |
| Transformer attention model | `signals/transformer.py` | P1 |
| LSTM predictor (enhanced) | `signals/lstm.py` | P1 |
| XGBoost+LightGBM ensemble | `signals/xgb_lgbm.py` | P1 |
| Triple Barrier Labeling | `signals/tbl.py` | P1 |
| DSR implementation | `evaluation/dsr.py` | P1 |
| PBO/CSCV implementation | `evaluation/pbo.py` | P1 |
| Walk-forward enhancement | `backtest/walk_forward.py` | P1 |
| Regime-conditional evaluation | `evaluation/regime_conditional.py` | P1 |
| IC tracking | `monitoring/ic_tracking.py` | P1 |
| Frontend: Evaluation + Monitoring pages | `frontend/` | P1 |

### Phase 3: Gigantic AI (Week 5-8) — P2

**Goal**: Multi-agent LLM system + RL allocator + automated factor mining

| Task | Module | Priority |
|------|--------|----------|
| Miner Agent (LLM factor discovery) | `ai/miner_agent.py` | P2 |
| Screener Agent (regime ensemble) | `ai/screener_agent.py` | P2 |
| Trader Agent (risk-constrained) | `ai/trader_agent.py` | P2 |
| Risk Manager Agent | `ai/risk_agent.py` | P2 |
| Sentiment Analyst Agent (IndoBERT) | `ai/sentiment_agent.py` | P2 |
| HRP-µ (signal-aware allocation) | `portfolio/hrp_mu.py` | P2 |
| RL Portfolio Allocator (PPO/SAC) | `portfolio/rl_allocator.py` | P2 |
| Model retirement manager | `monitoring/retirement.py` | P2 |
| Prediction vs reality tracker | `monitoring/prediction_reality.py` | P2 |
| Drift detection (enhanced) | `monitoring/drift.py` | P2 |
| LLM integration (local Ollama or API) | `ai/llm_gateway.py` | P2 |

### Phase 4: Production Hardening (Week 9-10) — P3

**Goal**: Paper trading, monitoring, alerting, documentation

| Task | Module | Priority |
|------|--------|----------|
| Paper trading OMS (enhanced) | `execution/oms.py` | P3 |
| Fail-closed risk gate | `execution/risk_gate.py` | P3 |
| Smart order router (VWAP/TWAP) | `execution/smart_order_router.py` | P3 |
| Alert system (Telegram) | `monitoring/alerts.py` | P3 |
| Scheduler/cron integration | `core/scheduler.py` | P3 |
| Parquet sync | `data/sync_parquet.py` | P3 |
| Full test suite | `tests/` | P3 |
| Documentation | `docs/` | P3 |

### Phase 5: Advanced Features (Week 11-12) — P4

**Goal**: Social media sentiment, satellite data, cross-market

| Task | Module | Priority |
|------|--------|----------|
| Stockbit/X sentiment | `data/social_fetcher.py` | P4 |
| Satellite data (CPO, mining) | `data/satellite_fetcher.py` | P4 |
| DCC-GARCH (cross-market) | `signals/dcc_garch.py` | P4 |
| Pairs trading | `signals/pairs_trading.py` | P4 |
| Sector rotation | `signals/sector_rotation.py` | P4 |
| Meta-labeling | `signals/meta_labeling.py` | P4 |

---

## 11. Technology Stack

### Backend
- **Python 3.12+** (main language)
- **PostgreSQL 16** (database, point-in-time native)
- **SQLAlchemy 2.0** (ORM)
- **Alembic** (migrations)
- **FastAPI** (REST API)
- **PyTorch** (deep learning, CUDA:1)
- **XGBoost + LightGBM** (gradient boosting)
- **scikit-learn** (classical ML)
- **statsmodels** (econometrics)
- **Transformers (HuggingFace)** (IndoBERT)
- **yfinance** (data fetching)
- **cloudscraper** (IDX API)

### AI/LLM
- **Ollama** (local LLM: DeepSeek-R1-Distill or Llama 3.1)
- **IndoBERT-Large** (Indonesian sentiment, 94.2% accuracy)
- **FinBERT** (English financial sentiment, for global markets)
- **PyTorch** (VAE, Transformer, LSTM)
- **Stable-Baselines3** (RL: PPO, SAC)

### Frontend
- **Next.js 16** (React 18)
- **TailwindCSS 3.4**
- **Recharts 2.12** (charts)
- **Lucide React** (icons)
- **@tanstack/react-table** (data tables)
- **Zustand** (state management)

### Infrastructure
- **PostgreSQL 16** (quant database)
- **Redis** (optional: caching, pub/sub)
- **Cron** (scheduled tasks)
- **Telegram Bot API** (alerts)

---

## 12. Key Design Principles

1. **Point-in-time correctness**: Every query respects `as_of_date` — no look-ahead bias
2. **Weight-centric interface**: All modules communicate via weight vectors
3. **Continuous signals**: [-1, +1] not binary — enables nuanced position sizing
4. **Fail-closed risk**: Risk gate blocks, not warns — capital protection first
5. **Backtest-live parity**: Same code path for backtest and live trading
6. **Per-engine attribution**: Every signal traced to its source engine
7. **Automated validation**: DSR + PBO run automatically, engines retired without manual intervention
8. **Regime awareness**: All strategies evaluated per-regime, not aggregate only
9. **GPU-first**: Heavy computation (LSTM, Transformer, VAE, Monte Carlo) uses CUDA:1
10. **Bahasa Indonesia UI**: Technical terms in English, narrative in Indonesian

---

## 13. References

### Academic Papers
- FinRL-X: AI-Native Modular Infrastructure (arXiv:2603.21330)
- AlphaCrafter: Multi-Agent Framework for Cross-Sectional Quant (arXiv:2605.05580)
- QuantAgents: Multi-agent Financial System via Simulated Trading (EMNLP 2025)
- FinRL-DeepSeek: LLM-Infused Risk-Sensitive RL (arXiv:2502.07393)
- ATLAS: Adaptive Trading with LLM Agents (arXiv:2510.15949)
- FinPos: Position-Aware Trading Agent (arXiv:2510.27251)
- R&D-Agent-Quant: Multi-Agent Factor-Model Co-optimization (arXiv:2505.15155)
- Bailey & López de Prado: Deflated Sharpe Ratio (JPM 2014)
- Bailey et al.: Probability of Backtest Overfitting (JCF 2014)
- López de Prado: Hierarchical Risk Parity (2016)
- Beyond De Prado and Cotton: HRP-µ and CRISP (arXiv:2604.23833)
- Fine-tuned IndoBERT for stock market sentiment (IJECS 2025)
- Quant Engineering untuk Pasar Keuangan Indonesia (clawRxiv 2026)
- LSTM-Transformer Hybrid for Stock Prediction (IEEE 2025)
- VAE+Transformer+LSTM Ensemble (arXiv:2503.22192)
- AATS for Emerging Market Portfolios (Financial Innovation 2025)

### Open Source Projects
- FinRL-X: https://github.com/AI4Finance-Foundation/FinRL-Trading
- Microsoft Qlib: https://github.com/microsoft/qlib
- Microsoft RD-Agent: https://github.com/microsoft/RD-Agent
- oos-lab: https://github.com/OutOfSampleLab/oos-lab
- Paperium (IDX LSTM): https://github.com/snowfluke/paperium
- IndoBERT CNBC Sentiment: https://github.com/triagungj/CNBCI-Sentiment-Analysis
- Dellmology (IDX Brokermology): https://github.com/FadelSearr/Dellmology
- IDX MLOps: https://github.com/rafifshaf-fun/indonesian-stock-mlops

### Existing Audit
- ENGINE_AUDIT_MATRIX.md (7-layer pipeline audit, 1893 lines)
-docs/SCHEMA.sql (point-in-time native schema)
