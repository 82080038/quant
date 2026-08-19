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
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

from quant.core.db import engine

Base = declarative_base()
Base.metadata.bind = engine


class Instrument(Base):
    """Instrument master row (``instruments`` table).

    Includes fetch metadata columns (migration 0003) for state-driven
    pipeline: fetch_status, data_layer, fetch_frequency, etc.
    """

    __tablename__ = "instruments"

    ticker = Column(String, primary_key=True)
    company_name = Column(String)
    is_active = Column(Boolean, default=True)
    asset_class = Column(String, default="equity")
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


class Exchange(Base):
    """Exchange master row (``exchanges`` table)."""

    __tablename__ = "exchanges"

    mic_code = Column(String, primary_key=True)
    name = Column(String)
    data_suffix = Column(String)
    timezone = Column(String)
    currency = Column(String)


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


__all__ = [
    "Base",
    "Instrument",
    "Exchange",
    "InstrumentMaster",
    "StrategyAssignment",
    "PipelineState",
    "RecomputeWatermark",
    "SchedulerState",
]
