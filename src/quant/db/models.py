"""Database models — minimal stubs for quant app.

Will be expanded as modules are ported from market app.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from quant.core.config import config

Base = declarative_base()
_engine = create_engine(config.database_url, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine)


def get_engine():
    return _engine


class Instrument:
    """Minimal Instrument stub — use raw SQL queries instead."""
    pass


class Exchange:
    """Minimal Exchange stub."""
    pass


class InstrumentMaster:
    """Compatibility stub — use instruments table directly."""
    pass


class StrategyAssignment:
    """Minimal stub for strategy assignment."""
    pass
