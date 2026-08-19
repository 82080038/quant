-- Quant Trading Application — Initial Schema
-- Point-in-time native design from day 1
-- Database: quant (PostgreSQL 16)

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================
-- Reference Tables
-- ============================================================

CREATE TABLE exchanges (
    id SERIAL PRIMARY KEY,
    mic VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    country VARCHAR(50),
    timezone VARCHAR(50),
    currency VARCHAR(3),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE sector_master (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    code VARCHAR(10)
);

CREATE TABLE instruments (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL UNIQUE,
    exchange_id INTEGER REFERENCES exchanges(id),
    sector_id INTEGER REFERENCES sector_master(id),
    asset_class VARCHAR(20) DEFAULT 'equity',
    currency VARCHAR(3) DEFAULT 'IDR',
    lot_size INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    listed_date DATE,
    delisted_date DATE,
    company_name VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Raw Market Data (Point-in-Time Native)
-- ============================================================

-- OHLCV with as_of_date for bitemporal storage
CREATE TABLE stock_prices (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(20,4),
    high NUMERIC(20,4),
    low NUMERIC(20,4),
    close NUMERIC(20,4),
    volume BIGINT,
    adj_open NUMERIC(20,4),
    adj_high NUMERIC(20,4),
    adj_low NUMERIC(20,4),
    adj_close NUMERIC(20,4),
    as_of_date DATE DEFAULT CURRENT_DATE,  -- when data was known
    source VARCHAR(20) DEFAULT 'yfinance',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, date, as_of_date)
);
CREATE INDEX idx_stock_prices_ticker_date ON stock_prices(ticker, date DESC);
CREATE INDEX idx_stock_prices_date ON stock_prices(date DESC);

-- Foreign flow (IDX-specific: foreign buy/sell per ticker per day)
CREATE TABLE foreign_flow (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    foreign_buy BIGINT,
    foreign_sell BIGINT,
    foreign_net BIGINT,
    domestic_buy BIGINT,
    domestic_sell BIGINT,
    domestic_net BIGINT,
    as_of_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, date)
);
CREATE INDEX idx_foreign_flow_ticker_date ON foreign_flow(ticker, date DESC);

-- Macro data with as_of_date
CREATE TABLE macro_data (
    id BIGSERIAL PRIMARY KEY,
    series_name VARCHAR(50) NOT NULL,
    date DATE NOT NULL,
    value NUMERIC(20,6),
    unit VARCHAR(20),
    source VARCHAR(30),
    as_of_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(series_name, date, as_of_date)
);
CREATE INDEX idx_macro_data_series_date ON macro_data(series_name, date DESC);

-- Fundamental data with as_of_date (point-in-time critical)
CREATE TABLE fundamental_data (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    period VARCHAR(10),
    revenue NUMERIC(20,2),
    net_income NUMERIC(20,2),
    total_assets NUMERIC(20,2),
    total_equity NUMERIC(20,2),
    total_debt NUMERIC(20,2),
    cash NUMERIC(20,2),
    eps NUMERIC(20,4),
    book_value_per_share NUMERIC(20,4),
    roe NUMERIC(10,4),
    roa NUMERIC(10,4),
    debt_ratio NUMERIC(10,4),
    current_ratio NUMERIC(10,4),
    pe_ratio NUMERIC(10,4),
    pb_ratio NUMERIC(10,4),
    dividend_yield NUMERIC(10,4),
    market_cap NUMERIC(20,2),
    operating_cash_flow NUMERIC(20,2),
    as_of_date DATE DEFAULT CURRENT_DATE,
    source VARCHAR(30),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(ticker, date, period, as_of_date)
);
CREATE INDEX idx_fundamental_ticker_date ON fundamental_data(ticker, date DESC);

-- News sentiment
CREATE TABLE news_sentiment (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20),
    date DATE NOT NULL,
    headline TEXT,
    sentiment_score NUMERIC(6,4),
    sentiment_label VARCHAR(10),
    source VARCHAR(50),
    url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_news_sentiment_ticker_date ON news_sentiment(ticker, date DESC);

-- ============================================================
-- Event Data
-- ============================================================

CREATE TABLE exchange_holidays (
    id SERIAL PRIMARY KEY,
    exchange_id INTEGER REFERENCES exchanges(id),
    holiday_date DATE NOT NULL,
    name VARCHAR(100),
    type VARCHAR(30),
    UNIQUE(exchange_id, holiday_date)
);

CREATE TABLE policy_events (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(50),
    impact VARCHAR(20),
    direction VARCHAR(10),
    description TEXT,
    source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE external_events (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    title TEXT NOT NULL,
    category VARCHAR(50),
    impact_market VARCHAR(20),
    description TEXT,
    source VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE corporate_calendar (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20),
    event_date DATE NOT NULL,
    event_type VARCHAR(30),
    title TEXT,
    description TEXT,
    location TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE corporate_actions (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    ex_date DATE NOT NULL,
    action_type VARCHAR(30),
    ratio NUMERIC(10,4),
    amount NUMERIC(20,4),
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Feature Store (Versioned Factor Library)
-- ============================================================

CREATE TABLE feature_definitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    version VARCHAR(20) NOT NULL,
    description TEXT,
    dependencies TEXT[],
    computation_module VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, version)
);

CREATE TABLE feature_values (
    id BIGSERIAL PRIMARY KEY,
    feature_def_id INTEGER REFERENCES feature_definitions(id),
    ticker VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    value NUMERIC(20,8),
    as_of_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(feature_def_id, ticker, date, as_of_date)
);
CREATE INDEX idx_feature_values_lookup ON feature_values(feature_def_id, ticker, date DESC);

-- ============================================================
-- Signal Generation
-- ============================================================

CREATE TABLE signal_attribution_log (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    engine_name VARCHAR(50) NOT NULL,
    signal_value NUMERIC(8,4),
    signal_direction VARCHAR(10),
    confidence NUMERIC(6,4),
    weight_in_portfolio NUMERIC(6,4),
    contribution_to_decision NUMERIC(8,4),
    rationale TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_signal_attr_date_ticker ON signal_attribution_log(date DESC, ticker);
CREATE INDEX idx_signal_attr_engine ON signal_attribution_log(engine_name, date DESC);

-- ============================================================
-- Evaluation & Monitoring
-- ============================================================

CREATE TABLE prediction_evaluation (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    engine_name VARCHAR(50) NOT NULL,
    predicted_direction VARCHAR(10),
    predicted_magnitude NUMERIC(10,4),
    confidence NUMERIC(6,4),
    actual_forward_return_5d NUMERIC(10,4),
    actual_direction VARCHAR(10),
    directional_correct BOOLEAN,
    ic_contribution NUMERIC(10,4),
    evaluated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, ticker, engine_name)
);

CREATE TABLE model_retirement_log (
    id SERIAL PRIMARY KEY,
    engine_name VARCHAR(50) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    reason TEXT,
    dsr_value NUMERIC(6,4),
    pbo_value NUMERIC(6,4),
    rolling_ic NUMERIC(8,4),
    track_record_days INTEGER,
    decided_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Portfolio & Risk
-- ============================================================

CREATE TABLE portfolio_state (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    shares BIGINT,
    avg_cost NUMERIC(20,4),
    current_price NUMERIC(20,4),
    market_value NUMERIC(20,4),
    weight_pct NUMERIC(8,4),
    unrealized_pnl NUMERIC(20,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, ticker)
);

CREATE TABLE portfolio_weights (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    weight NUMERIC(8,4),
    method VARCHAR(30),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(date, ticker, method)
);

-- ============================================================
-- Execution
-- ============================================================

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    date TIMESTAMPTZ NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    quantity BIGINT,
    price NUMERIC(20,4),
    order_type VARCHAR(20),
    status VARCHAR(20) DEFAULT 'pending',
    broker VARCHAR(50),
    fill_price NUMERIC(20,4),
    fill_quantity BIGINT,
    fill_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE trade_journal (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    entry_date TIMESTAMPTZ,
    exit_date TIMESTAMPTZ,
    entry_price NUMERIC(20,4),
    exit_price NUMERIC(20,4),
    quantity BIGINT,
    pnl NUMERIC(20,4),
    pnl_pct NUMERIC(10,4),
    strategy VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Pipeline Infrastructure
-- ============================================================

CREATE TABLE recompute_dependencies (
    id SERIAL PRIMARY KEY,
    function_name VARCHAR(100) NOT NULL,
    data_source VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(function_name, data_source)
);

CREATE TABLE data_watermark (
    id SERIAL PRIMARY KEY,
    source VARCHAR(100) NOT NULL UNIQUE,
    last_updated TIMESTAMPTZ,
    rows_affected BIGINT DEFAULT 0
);

CREATE TABLE scheduler_state (
    id SERIAL PRIMARY KEY,
    task_name VARCHAR(100) NOT NULL UNIQUE,
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'idle',
    last_error TEXT
);

-- ============================================================
-- Compatibility Views
-- ============================================================

CREATE VIEW v_active_instruments AS
    SELECT i.ticker, i.company_name, s.name as sector, e.mic as exchange
    FROM instruments i
    LEFT JOIN sector_master s ON i.sector_id = s.id
    LEFT JOIN exchanges e ON i.exchange_id = e.id
    WHERE i.is_active = TRUE;
