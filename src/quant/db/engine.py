"""Database engine — re-exports from core.db for compatibility."""

from quant.core.db import engine as _engine, get_db

def get_engine():
    return _engine
