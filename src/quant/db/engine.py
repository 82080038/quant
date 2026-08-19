"""Database engine — re-exports from core.db for compatibility.

Thin compatibility shim so legacy modules that import from ``quant.db.engine``
resolve to the same engine/session infrastructure as ``quant.core.db``.
"""

from quant.core.db import SessionLocal, engine as _engine, get_db


def get_engine():
    """Return the shared SQLAlchemy engine."""
    return _engine


def get_sessionmaker():
    """Return the shared sessionmaker (``SessionLocal``)."""
    return SessionLocal


__all__ = ["get_engine", "get_sessionmaker", "get_db"]
