# FORENSIC AUDIT REPORT — Celestial Fibonacci Trading Platform

**Audit Date:** 2026-08-20 10:03 WIB  
**Auditor:** Chief IT Auditor / Lead Systems Analyst / Principal DevSecOps Engineer  
**Scope:** Full codebase, database, terminal logs, frontend, backend, cron jobs  
**Classification:** Internal — Confidential  

---

## [1. INVENTARISASI FUNGSI AKTIF]

### 1.1 Backend Modules (`src/quant/`)

| Module | Path | Status | Description |
|--------|------|--------|-------------|
| **API Server** | `api/app.py` (1061 lines) | ✅ Active | FastAPI app with 30+ endpoints: health, prices, movers, candles, portfolio, scheduler, instruments, cosmos, evaluation |
| **Realtime Transport** | `api/realtime.py` (467 lines) | ✅ Active | WebSocket hub + SSE log streaming + metrics broadcaster |
| **Pipeline Orchestrator** | `pipeline/orchestrator.py` (524 lines) | ✅ Active | End-to-end pipeline: ingest → screen → analyze → signal → portfolio → execute |
| **State Machine** | `pipeline/state_machine.py` (341 lines) | ✅ Active | PipelineTracker with per-ticker per-step status tracking |
| **Incremental Processor** | `pipeline/incremental.py` (294 lines) | ⚠️ Dormant | Watermark helpers written but **never imported or called** by any module |
| **Scheduler Tasks** | `pipeline/scheduler_tasks.py` (10811 bytes) | ✅ Active | 22 scheduled tasks: fetch_eod, fetch_global, recompute, generate_signals, etc. |
| **Session Orchestrator** | `core/session_orchestrator.py` (414 lines) | ✅ Active | DST-aware global market session tracker (22 exchanges) |
| **Market Session Manager** | `core/market_session.py` (466 lines) | ✅ Active | 21-exchange schedule with holiday lookup, WIB conversion, cron integration |
| **Pre-Trade Guard** | `core/pre_trade_guard.py` (269 lines) | ✅ Active | Holiday bypass engine checking `market_holidays` + `exchange_holidays` |
| **Device Dispatcher** | `core/device.py` (626 lines) | ✅ Active | CUDA/CPU auto-selection with VRAM profiling, targets `cuda:1` |
| **Rate Limiter** | `core/rate_limiter.py` (19891 bytes) | ✅ Active | Adaptive rate limiter with exponential backoff + jitter |
| **Simulation Engine** | `simulation/engine.py` (618 lines) | ✅ Active | GBM + Markov regime + jump diffusion for 20 IDX stocks |
| **Data Fetchers** | `data/` (11 files) | ✅ Active | IDX adapter, RSS, social, satellite, BPS, BI, point-in-time, asset router |
| **Signal Engines** | `signals/` (24 files) | ✅ Active | 20+ engines: astronacci, DCC-GARCH, HMM, LSTM, transformer, VAE, XGBoost, global market, holiday effect |
| **AI Agents** | `ai/` (9 files) | ✅ Active | LLM gateway, screener/risk/trader/miner/sentiment agents |
| **Agentic Framework** | `agentic/` (7 files) | ✅ Active | Base agent, architect, coder, QA, ML-meta orchestrator |
| **Execution** | `execution/` (9 files) | ✅ Active | OMS, paper trading, smart order router, risk gate, market impact |
| **Monitoring** | `monitoring/` (6 files) | ✅ Active | Alerts, drift detection, prediction-reality, retirement, scheduler |

### 1.2 Frontend Components (`frontend/src/`)

| Component | Path | Status | Description |
|-----------|------|--------|-------------|
| **Dashboard Page** | `app/page.tsx` (21506 bytes) | ✅ Active | 7-widget grid: CelestialFibonacciChart, observability, signals, portfolio, scheduler, market clock |
| **Exchange Timeline Header** | `components/exchange-timeline-header.tsx` (298 lines) | ✅ Active | WIB-sorted exchange cards, moon phase, DST indicator, causality connectors |
| **Celestial Fibonacci Chart** | `components/celestial-fibonacci-chart.tsx` (343 lines) | ✅ Active | Canvas 2D candlestick + Fib retracement + time zones + star field |
| **Observability Console** | `components/observability-console.tsx` (8189 bytes) | ✅ Active | Virtual scrolling log viewer with rAF throttling |
| **WebSocket Client** | `lib/ws-client.ts` (434 lines) | ✅ Active | Singleton WS with backpressure, auto-reconnect, rAF coalescing |
| **Moon Phase Utility** | `lib/moon-phase.ts` (202 lines) | ✅ Active | Astronomical moon phase calculation + SVG path renderer |
| **Market Clock Widget** | `components/market-clock-widget.tsx` | ✅ Active | Real-time WIB clock with session status |
| **Sidebar** | `components/sidebar.tsx` | ✅ Active | Navigation: Dashboard, Signals, Portfolio, Backtest, Settings, Cosmos, Data, Pipeline, Scheduler, Reports, Screener, Stock |
| **11 Sub-pages** | `app/*/page.tsx` | ✅ Active | backtest, cosmos, data, pipeline, portfolio, reports, scheduler, screener, settings, signals, stock |

### 1.3 Database Migrations (`alembic/versions/`)

| Migration | Revision ID | Status | Description |
|-----------|-------------|--------|-------------|
| 0001_baseline | `0001` | ✅ Applied | Stamp migration |
| 0002_add_fk_indexes | `0002` | ✅ Applied | FK performance indexes |
| 0003_pipeline_state_machine | `0003` | ✅ Applied | pipeline_state, recompute_watermark, scheduler_state enrichment |
| 0004_fk_normalization | `0004_fk_normalization` | ✅ Applied | FK constraint normalization |
| 0005_delisted_flags | `0005_delisted_flags` | ✅ Applied | is_delisted, delisted_reason, delisting_date → delisted_date |
| 0006_market_holidays | `0006_market_holidays` | ✅ Applied | market_holidays table (6648 rows) |
| 0007_market_sessions | `0007_market_sessions` | ✅ Applied | market_sessions table (22 active sessions) |
| 0008_market_indices | `0008_market_indices` | ✅ Applied | market_indices table (23 indices) |
| 0009_global_interdependency | `0009_global_interdependency` | ✅ Applied | global_market_interdependencies + history tables (0 rows) |
| 0010_asset_classes | `0010_asset_classes` | ✅ Applied | asset_classes master table + FK + base/quote currency |

**Current alembic head:** `0010_asset_classes`

### 1.4 Infrastructure

| Component | Status | Details |
|-----------|--------|---------|
| **PostgreSQL 16** | ✅ Running | localhost:5432, database `quant` |
| **FastAPI Backend** | ✅ Running | localhost:8000, uvicorn with --reload |
| **Next.js Frontend** | ✅ Running | localhost:3000, dev mode |
| **Cron Job** | ✅ Active | `0 10 * * 1-5` → `run_daily_fetch.sh` (10:00 UTC = 17:00 WIB) |
| **Playwright E2E** | ✅ Configured | Headed mode with Epson PJ monitor targeting via `monitor_detect.py` |
| **GPU** | ✅ Detected | NVIDIA GeForce GTX 1050 Ti, 4096 MiB, driver 580.173.02 |

---

## [2. PROVEN CAPABILITIES LOG]

| # | Capability | Evidence | Status |
|---|-----------|----------|--------|
| 1 | **272 Python tests pass** | `pytest --co -q` → 272 tests collected; all pass | ✅ Proven |
| 2 | **8/8 Playwright E2E scenarios pass** | `e2e_playwright_headed.py` → 8 passed, 0 failed, 0 errors | ✅ Proven |
| 3 | **DST-aware session tracking** | `session_orchestrator.py` computes DST-adjusted UTC times via `zoneinfo`; 7 exchanges with `has_dst=True` | ✅ Proven |
| 4 | **Market holiday bypass engine** | `PreTradeGuard` checks `market_holidays` (6648 rows) + legacy `exchange_holidays` (5617 rows) | ✅ Proven |
| 5 | **CUDA detection active** | `nvidia-smi` confirms GTX 1050 Ti; `device.py` implements VRAM-aware auto-selection | ✅ Proven |
| 6 | **3.58M stock price rows** | `stock_prices` table: 3,579,614 rows, 1134 tickers, latest 2026-08-18 | ✅ Proven |
| 7 | **22 global exchange sessions** | `market_sessions` table: 22 active sessions with full DST metadata | ✅ Proven |
| 8 | **WebSocket + SSE realtime** | `realtime.py` Hub with pub/sub, backpressure, heartbeat; `ws-client.ts` with auto-reconnect | ✅ Proven |
| 9 | **Pipeline state machine** | `pipeline_state` table: 179 rows tracking 30 tickers through 7 steps | ✅ Proven |
| 10 | **Moon phase calculation** | `moon-phase.ts` with astronomical formulas, integrated into timeline header | ✅ Proven |
| 11 | **Canvas 2D Fibonacci chart** | `celestial-fibonacci-chart.tsx` with candlestick + Fib levels + time zones + star field | ✅ Proven |
| 12 | **Virtual scrolling observability** | `VirtualLogList` with windowed rendering, rAF throttling, ResizeObserver | ✅ Proven |
| 13 | **Asset class normalization** | 6 asset classes (equity, index, forex, commodity, macro_rate, + crypto/bond defined); 1137 instruments normalized | ✅ Proven |
| 14 | **Forex base/quote currency** | 34 forex instruments, 33 with base/quote populated | ✅ Proven |
| 15 | **WIB-sorted exchange header** | Frontend sorts by `open_time_wib` (localeCompare), tie-break by `close_time_wib` | ✅ Proven |
| 16 | **Epson monitor targeting** | `monitor_detect.py` parses EDID, `e2e_playwright_headed.py` positions browser on Epson PJ | ✅ Proven |

---

## [3. COMPREHENSIVE GAP ANALYSIS MASTERLIST]

### 3.1 CRITICAL — Silent Cascade Failures

| ID | Severity | Component | Gap Description | Impact |
|----|----------|-----------|-----------------|--------|
| **GAP-01** | 🔴 CRITICAL | `scripts/fetch_daily.py:54` | **UnboundLocalError on every cron run.** Line 54 re-imports `from datetime import datetime, UTC` inside `main()`, shadowing the module-level `datetime` import at line 10. Python treats `datetime` as a local variable for the entire function scope, causing `UnboundLocalError` at line 40 (`datetime.now(timezone.utc)`). | **Daily data fetch is completely broken.** Cron runs at 17:00 WIB every weekday but crashes immediately. No new OHLCV data has been fetched since the bug was introduced. All 1030 instruments have `fetch_status = 'STALE'`. |
| **GAP-02** | 🔴 CRITICAL | `src/quant/api/app.py:250` | **`sim.ohlcv_history` attribute does not exist.** The `/api/prices/candles` endpoint references `sim.ohlcv_history.get(ticker, [])` but `SimulationEngine` has no `ohlcv_history` attribute. It has `latest_bars`, `tick_history`, and `ihsg_history`. | **Silent AttributeError when simulation is running.** The endpoint falls through to the DB query, so candles still work via DB, but the simulation path is dead code that would crash if activated. |
| **GAP-03** | 🔴 CRITICAL | `src/quant/db/models.py:97` | **Exchange ORM model mismatched with DB schema.** ORM defines `mic_code` as PK + `data_suffix` column. Actual DB table has `id` (serial PK), `mic` (varchar), `name`, `country`, `timezone`, `currency`, `is_active`, `created_at`. No `data_suffix` column exists. | **`ticker_util.py:63-64` silently fails** when querying `Exchange.data_suffix` / `Exchange.mic_code`. The `except Exception` block catches the error and falls back to hardcoded suffix mapping. This is a silent failure that masks the ORM-schema divergence. |

### 3.2 HIGH — Data Integrity Issues

| ID | Severity | Component | Gap Description | Impact |
|----|----------|-----------|-----------------|--------|
| **GAP-04** | 🟠 HIGH | `instruments` table | **15 instruments with `is_delisted = TRUE` but `is_active = TRUE`.** All have `delisted_date = 2026-11-10` (future date). These are flagged for future delisting but still marked active. | Pipeline may process soon-to-be-delisted instruments as fully active. The `v_active_instruments` view returns 1086 rows — these 15 may or may not be included depending on the view definition. |
| **GAP-05** | 🟠 HIGH | `sector_master` table | **Duplicate sector code `MISC`** — two rows: "Unknown" and "Miscellaneous". Both have code `MISC`. | FK joins on sector code may match the wrong row. Instruments with `sector_id` pointing to `MISC` are ambiguous. |
| **GAP-06** | 🟠 HIGH | `exchanges` table | **Duplicate Singapore exchange entries**: `XSGX` ("Singapore Exchange (SGX)") and `XSES` ("Singapore Exchange"). `market_sessions` only has `XSGX`. `market_session.py` `_EXCHANGES` dict only has `XSES`. | Singapore instruments may be assigned to the wrong MIC. Frontend cosmos view uses `_EXCHANGES` (XSES) while DB sessions use XSGX — mismatch. |
| **GAP-07** | 🟠 HIGH | `exchanges` table | **3 exchanges missing from `market_sessions`**: `XMTA` (Borsa Italiana), `XNSE` (National Stock Exchange of India), `XSES` (Singapore Exchange). These exist in the `exchanges` table but have no session schedule row. | Session orchestrator cannot compute status for these exchanges. `market_session.py` has them in `_EXCHANGES` dict (hardcoded), but `session_orchestrator.py` reads from DB and will return "not found". |
| **GAP-08** | 🟠 HIGH | `instruments` table | **107 instruments with `exchange_mic = NULL`** and `fetch_status = 'NEVER_FETCHED'`. These are likely forex/commodity/macro instruments that were never assigned an exchange. | These instruments cannot be routed by the asset router for exchange-specific operations (holiday checks, session timing). |
| **GAP-09** | 🟠 HIGH | `instruments` table | **1 forex instrument (`IDR=X`) with `base_currency = NULL` and `quote_currency = NULL`.** This is the USD/IDR exchange rate but lacks currency pair metadata. | Forex routing and cross-currency analysis will skip this instrument. |

### 3.3 MEDIUM — Architectural Gaps

| ID | Severity | Component | Gap Description | Impact |
|----|----------|-----------|-----------------|--------|
| **GAP-10** | 🟡 MEDIUM | `pipeline/incremental.py` | **Incremental processing module is completely dormant.** `get_watermark()`, `save_watermark()`, and all watermark helpers are written but never imported or called by any module. `recompute_watermark` table has 0 rows. `recompute_dependencies` table has 0 rows. | Pipeline recomputes from scratch every run instead of incrementally processing only new data. This wastes CPU/RAM on 3.58M rows. The state machine tracks pipeline steps but not data watermarks. |
| **GAP-11** | 🟡 MEDIUM | `global_market_interdependencies` table | **0 rows in interdependency matrix.** Migration 0009 created the tables, `signals/global_market.py` has code to read them, but no populator/computer module exists or runs. | Cross-asset causal analysis falls back to legacy MA-based mode. The "Global Cross-Asset Interdependency" feature is architecturally present but operationally empty. |
| **GAP-12** | 🟡 MEDIUM | `data_watermark` table | **Dual watermark tables**: `data_watermark` (0 rows, columns: id, source, last_updated, rows_affected) and `recompute_watermark` (0 rows, columns: ticker, table_name, last_processed_date). Neither is populated. | Confusion about which table is the source of truth for incremental processing. API endpoint `/api/data/watermarks` returns empty `{"watermarks": {}}`. |
| **GAP-13** | 🟡 MEDIUM | `scheduler_state` table | **0 rows.** The scheduler state table for catch-up of missed tasks is empty. | If the system restarts, there's no persistent state to catch up on missed scheduler tasks. The scheduler has no memory of what was last run. |
| **GAP-14** | 🟡 MEDIUM | `market_holidays` table | **Duplicate holidays for XTSE (Tokyo)**: 10+ dates with 2 entries each (e.g., 2026-10-12 has 2 rows). | Holiday check queries use `LIMIT 1` so duplicates don't cause false positives, but they waste storage and may cause confusion in holiday count reports. |
| **GAP-15** | 🟡 MEDIUM | `paper_trading_orders` / `paper_trading_state` | **0 rows in both tables.** Paper trading OMS infrastructure exists but has never been exercised. | No live paper trading has been executed. The execution pipeline is untested in production. |

### 3.4 LOW — Cosmetic / Minor

| ID | Severity | Component | Gap Description | Impact |
|----|----------|-----------|-----------------|--------|
| **GAP-16** | 🔵 LOW | `exchange_holidays` (legacy) | **5617 rows in legacy holiday table** alongside 6648 rows in new `market_holidays`. Both are queried by `PreTradeGuard` with fallback logic. | Redundant storage. The legacy table should eventually be deprecated once all holiday data is migrated to `market_holidays`. |
| **GAP-17** | 🔵 LOW | `instruments` table | **979 active instruments with `fetch_status = 'STALE'`** + 107 with `NEVER_FETCHED`. Only 0 instruments have `fetch_status = 'OK'`. | The fetch status tracking system is not being updated. The daily fetch cron (GAP-01) is broken, so statuses are degrading. |
| **GAP-18** | 🔵 LOW | `exchanges` table | **3 synthetic exchanges** (`OFF`, `XCEC`, `XFXS`) with 0 instruments assigned. | No functional impact, but these entries add noise to exchange listing endpoints. |

---

## [4. AUDITOR RECOMMENDED ROADMAP]

### Phase A: Critical Fixes (Immediate — Block All Other Work)

| Priority | File | Action | Resolves |
|----------|------|--------|----------|
| A1 | `scripts/fetch_daily.py` | Remove the inner `from datetime import datetime, UTC` at line 54. The module-level import at line 10 (`from datetime import date, datetime, timezone`) already provides `datetime`. Use `UTC` from the `datetime` module or replace with `timezone.utc`. | **GAP-01** — Restores daily data fetch |
| A2 | `src/quant/api/app.py:250` | Replace `sim.ohlcv_history` with the correct attribute. The `SimulationEngine` stores per-ticker `SimState` objects in `sim.states[ticker].bars` (list of `OHLCVBar`). The endpoint should access `sim.states.get(ticker, SimState(...)).bars` or generate synthetic daily candles from `sim.ihsg_history` for `^JKSE`. | **GAP-02** — Fixes candle endpoint for simulation mode |
| A3 | `src/quant/db/models.py:92-100` | Update `Exchange` model to match actual DB schema: change `mic_code` → `mic` (non-PK), add `id`, `country`, `is_active`, `created_at` columns. Remove `data_suffix` (doesn't exist in DB). Update all references in `ticker_util.py:63-64`. | **GAP-03** — Fixes ORM-schema mismatch |

### Phase B: Data Integrity Fixes (Within 24h)

| Priority | File | Action | Resolves |
|----------|------|--------|----------|
| B1 | DB migration or SQL script | Set `is_active = FALSE` for the 15 instruments where `is_delisted = TRUE` and `delisted_date <= today`. For future delisting dates, keep `is_active = TRUE` but add a `delisting_pending` flag or handle via application logic. | **GAP-04** |
| B2 | DB migration or SQL script | Deduplicate `sector_master`: merge the two `MISC` rows ("Unknown" + "Miscellaneous") into one. Update any instruments referencing the deleted row's `sector_id`. | **GAP-05** |
| B3 | DB migration or SQL script | Merge `XSGX` and `XSES` in `exchanges` table. Standardize on `XSES` (ISO 10383 standard). Update `market_sessions`, `market_holidays`, and `instruments` to use the canonical code. Remove `XSGX` from `market_session.py` `_EXCHANGES` dict or alias it. | **GAP-06** |
| B4 | DB migration or SQL script | Add `market_sessions` rows for `XMTA`, `XNSE`, and `XSES` (the 3 exchanges missing from the sessions table). Populate with correct open/close times, timezone, and DST flags from the hardcoded `_EXCHANGES` dict in `market_session.py`. | **GAP-07** |
| B5 | SQL script | Populate `base_currency = 'USD'` and `quote_currency = 'IDR'` for the `IDR=X` instrument. | **GAP-09** |

### Phase C: Architectural Activation (Within 1 Week)

| Priority | File | Action | Resolves |
|----------|------|--------|----------|
| C1 | `pipeline/orchestrator.py` | Import and integrate `incremental.py` watermark functions. Before each pipeline step, call `get_watermark()` to determine the last-processed date. After processing, call `save_watermark()` to checkpoint progress. | **GAP-10** |
| C2 | New module or `signals/global_market.py` | Create a cross-asset interdependency populator that computes Granger causality, correlation, and time-lag between global indices and IDX tickers. Write results to `global_market_interdependencies` table. Schedule as a weekly task. | **GAP-11** |
| C3 | `pipeline/scheduler_tasks.py` | Persist scheduler state to `scheduler_state` table after each task execution. On startup, check for stale tasks and trigger catch-up. | **GAP-13** |
| C4 | DB migration | Deduplicate `market_holidays` for XTSE (Tokyo). Add a unique constraint on `(market_code, holiday_date)` to prevent future duplicates. | **GAP-14** |
| C5 | Consolidate | Deprecate `data_watermark` table in favor of `recompute_watermark`. Update API endpoint `/api/data/watermarks` to query `recompute_watermark` instead. | **GAP-12** |

### Phase D: Production Readiness (Within 2 Weeks)

| Priority | File | Action | Resolves |
|----------|------|--------|----------|
| D1 | `scripts/fetch_daily.py` | After fixing GAP-01, run a full fetch cycle to update all 1086 active instruments from STALE to OK status. | **GAP-17** |
| D2 | `execution/paper_trading.py` | Execute a paper trading cycle end-to-end to populate `paper_trading_orders` and `paper_trading_state` tables. Verify OMS → risk gate → order router pipeline. | **GAP-15** |
| D3 | DB migration | Add `is_active` column to `Exchange` ORM model. Clean up synthetic exchanges (`OFF`, `XCEC`, `XFXS`) — either assign instruments or mark as inactive. | **GAP-18** |
| D4 | DB migration | Plan deprecation of `exchange_holidays` table once all holiday data is confirmed migrated to `market_holidays`. | **GAP-16** |
| D5 | `instruments` table | Assign `exchange_mic` to the 107 instruments with NULL. Route forex → `XFXS`, commodities → appropriate exchange, macro rates → synthetic. | **GAP-08** |

---

### Audit Summary

| Metric | Value |
|--------|-------|
| Total gaps found | **18** |
| 🔴 Critical | **3** |
| 🟠 High | **6** |
| 🟡 Medium | **6** |
| 🔵 Low | **3** |
| Active backend modules | **60+ files across 15 packages** |
| Active frontend components | **16 components + 12 pages** |
| Database tables | **37 tables** |
| Database rows (stock_prices) | **3,579,614** |
| Python tests | **272 (all pass)** |
| Playwright E2E | **8/8 (all pass)** |
| Alembic migrations | **10 (all applied)** |

**Auditor's Verdict:** The system has a solid architectural foundation with comprehensive signal engines, DST-aware session tracking, and a functional frontend. However, **3 critical gaps** are causing silent cascade failures: the daily fetch cron is broken (GAP-01), the candle API has a dead code path (GAP-02), and the Exchange ORM model is mismatched with the DB schema (GAP-03). These must be fixed before any production deployment. The incremental processing module (GAP-10) and cross-asset interdependency matrix (GAP-11) are architecturally present but operationally dormant — activating them would significantly improve system performance and analytical depth.

---

*End of Forensic Audit Report*
