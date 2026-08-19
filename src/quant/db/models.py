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
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import declarative_base

from quant.core.db import engine

Base = declarative_base()
Base.metadata.bind = engine


class Instrument(Base):
    """Instrument master row (``instruments`` table)."""

    __tablename__ = "instruments"

    ticker = Column(String, primary_key=True)
    company_name = Column(String)
    is_active = Column(Boolean, default=True)
    asset_class = Column(String, default="equity")
    sector_id = Column(Integer)
    market_mic = Column(String)


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


__all__ = [
    "Base",
    "Instrument",
    "Exchange",
    "InstrumentMaster",
    "StrategyAssignment",
]
