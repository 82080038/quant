"""Database models — compatibility layer for legacy modules ported from the
market app.

These are minimal SQLAlchemy declarative models mirroring the table shapes
expected by importers (``fetch_registry``, ``ticker_util``,
``strategy_selector``). They share the same engine as ``quant.core.db`` so
queries hit the live database. If a table/column does not yet exist in the
deployed schema, callers are expected to handle the resulting SQLAlchemy
error (most do, via try/except fallbacks).
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

from quant.core.db import engine

Base = declarative_base()
Base.metadata.bind = engine


class AssetClass(Base):
    """Master table for asset classes (migration 0010).

    Normalizes the ``instruments.asset_class`` column into a proper FK.
    Each asset class has its own market hours, holiday calendar source,
    and default data source configuration.
    """

    __tablename__ = "asset_classes"

    code = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    market_hours_24h = Column(Boolean, nullable=False, default=False)
    holiday_calendar_source = Column(String(50), default="exchange")
    default_currency = Column(String(3), default="USD")
    default_data_source = Column(String(50), default="yahoo_finance")
    default_fetch_frequency = Column(String(20), default="EOD")
    is_tradeable = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default="now()")
    updated_at = Column(DateTime(timezone=True), default="now()")


class Instrument(Base):
    """Instrument master row (``instruments`` table).

    Includes fetch metadata columns (migration 0003) for state-driven
    pipeline: fetch_status, data_layer, fetch_frequency, etc.
    The ``asset_class`` column is a FK to ``asset_classes.code`` (migration 0010).
    """

    __tablename__ = "instruments"

    ticker = Column(String, primary_key=True)
    company_name = Column(String)
    is_active = Column(Boolean, default=True)
    asset_class = Column(String(20), ForeignKey("asset_classes.code", ondelete="SET DEFAULT"), default="equity")
    sector_id = Column(Integer)
    market_mic = Column(String)
    currency = Column(String, default="IDR")
    # Fetch metadata (migration 0003)
    exchange_mic = Column(String(20))
    data_layer = Column(String(30))
    fetch_frequency = Column(String(20), default="EOD")
    last_fetch_at = Column(DateTime(timezone=True))
    next_fetch_at = Column(DateTime(timezone=True))
    fetch_status = Column(String(20), default="NEVER_FETCHED")
    data_source_type = Column(String(50))
    data_source_url = Column(String(255))
    data_source_fallback = Column(String(255))
    fetch_adapter = Column(String(50))
    data_source_metadata = Column(JSON)
    delisting_date = Column(Date)
    underlying_ticker = Column(String(30))
    base_currency = Column(String(3))
    quote_currency = Column(String(3))


class Exchange(Base):
    """Exchange master row (``exchanges`` table).

    DB schema: id (serial PK), mic, name, country, timezone, currency,
    is_active, created_at. The ``mic`` column is the ISO 10383 Market
    Identifier Code (e.g. XIDX, XNYS, XNAS).
    """

    __tablename__ = "exchanges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mic = Column(String, unique=True, nullable=False)
    name = Column(String)
    country = Column(String)
    timezone = Column(String)
    currency = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default="now()")


class InstrumentMaster(Base):
    """Historical instrument master (``instrument_master`` table).

    Tracks ticker renames so lookups by former ticker resolve to the current
    one. Columns are nullable because the table may not be deployed yet.
    """

    __tablename__ = "instrument_master"

    ticker = Column(String, primary_key=True)
    former_ticker = Column(String, nullable=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)


class StrategyAssignment(Base):
    """Per-instrument strategy assignment (``strategy_assignment`` table)."""

    __tablename__ = "strategy_assignment"

    ticker = Column(String, primary_key=True)
    strategy = Column(String)
    assigned_at = Column(DateTime)
    confidence = Column(Numeric)
    rationale = Column(String)


class PipelineState(Base):
    """Per-ticker per-step pipeline status tracking (migration 0003).

    Tracks each ticker's position in the modular pipeline:
    INGESTED → SCREENED → ANALYZED → SIGNAL_GENERATED → DONE
        ↘ FAILED (with error tracking for self-healing)
    """

    __tablename__ = "pipeline_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(30), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    step = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    step_level = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
    error_traceback = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0)
    processed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default="now()")
    updated_at = Column(DateTime(timezone=True), default="now()")


class RecomputeWatermark(Base):
    """Incremental processing checkpoint (migration 0003).

    Tracks last-processed date per ticker per table for incremental recompute.
    """

    __tablename__ = "recompute_watermark"

    ticker = Column(String(20), primary_key=True)
    table_name = Column(String(50), primary_key=True)
    last_processed_date = Column(Date)
    last_ohlcv_date = Column(Date)
    rows_processed = Column(Integer)
    updated_at = Column(DateTime(timezone=True), default="now()")


class SchedulerState(Base):
    """Persistent scheduler state for catch-up of missed tasks.

    Enriched in migration 0003 with is_stale, data_dependencies,
    data_ready, last_result, last_duration_seconds.
    """

    __tablename__ = "scheduler_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_name = Column(String, unique=True)
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="idle")
    last_error = Column(Text)
    # Enriched columns (migration 0003)
    is_stale = Column(Boolean, default=False)
    data_dependencies = Column(JSON)
    data_ready = Column(Boolean, default=False)
    last_result = Column(JSON)
    is_catchup = Column(Boolean, default=False)
    last_duration_seconds = Column(Float)
    run_count = Column(Integer, default=0)


class GlobalMarketInterdependency(Base):
    """Master table: latest cross-asset interdependency matrix (migration 0009).

    Stores the most recent causality, correlation, and time-lag metrics
    for each source→target instrument pair. The decision engine queries
    this table before generating trading signals to incorporate global
    cross-asset causal relationships.
    """

    __tablename__ = "global_market_interdependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_instrument_id = Column(String(50), nullable=False)
    target_instrument_id = Column(String(50), nullable=False)
    source_asset_class = Column(String(20))
    target_asset_class = Column(String(20))
    correlation_coefficient = Column(Numeric(8, 6), nullable=False)
    causality_score = Column(Numeric(8, 6), nullable=False)
    causality_p_value = Column(Numeric(10, 8))
    causality_direction = Column(String(10), default="none")
    time_lag_seconds = Column(Integer, nullable=False, default=0)
    time_lag_periods = Column(Integer, default=0)
    impact_weight = Column(Numeric(8, 6), default=0)
    regime = Column(String(20), default="unknown")
    var_order = Column(Integer)
    sample_size = Column(Integer)
    as_of_date = Column(Date, nullable=False)
    updated_at = Column(DateTime(timezone=True), default="now()")
    created_at = Column(DateTime(timezone=True), default="now()")


class GlobalMarketInterdependencyHistory(Base):
    """Child table: daily historical snapshots of the interdependency matrix.

    Maintains a time-series record of how cross-asset causal relationships
    evolve over time, enabling backtesting of regime-conditional strategies
    and analysis of structural breaks in market connectedness.
    """

    __tablename__ = "global_market_interdependency_history"

    id = Column(Integer, primary_key=True, autoincrement=True)  # BIGSERIAL in DB
    source_instrument_id = Column(String(50), nullable=False)
    target_instrument_id = Column(String(50), nullable=False)
    correlation_coefficient = Column(Numeric(8, 6), nullable=False)
    causality_score = Column(Numeric(8, 6), nullable=False)
    causality_p_value = Column(Numeric(10, 8))
    causality_direction = Column(String(10), default="none")
    time_lag_seconds = Column(Integer, nullable=False, default=0)
    time_lag_periods = Column(Integer, default=0)
    impact_weight = Column(Numeric(8, 6), default=0)
    regime = Column(String(20), default="unknown")
    var_order = Column(Integer)
    sample_size = Column(Integer)
    snapshot_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), default="now()")


__all__ = [
    "Base",
    "AssetClass",
    "Instrument",
    "Exchange",
    "InstrumentMaster",
    "StrategyAssignment",
    "PipelineState",
    "RecomputeWatermark",
    "SchedulerState",
    "GlobalMarketInterdependency",
    "GlobalMarketInterdependencyHistory",
]
