"""Database connection layer for quant application.

Connection pool: pool_size=10, max_overflow=20, pool_timeout=30, pool_recycle=3600.
All sessions created via get_db() MUST be closed by the caller (use try/finally).
Use get_session() context manager for automatic lifecycle management.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator

from quant.core.config import config

engine = create_engine(
    config.database_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with auto-commit/rollback."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Session:
    """Get a raw SQLAlchemy session (caller manages lifecycle).

    ⚠️  Caller MUST close the session in a finally block:
        session = get_db()
        try:
            ...
        finally:
            session.close()
    """
    return SessionLocal()


def test_connection() -> bool:
    """Test database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"DB connection failed: {e}")
        return False


def pool_stats() -> dict:
    """Return connection pool statistics for observability."""
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "checked_in": pool.checkedin(),
    }


def table_row_count(table_name: str) -> int:
    """Get row count for a table."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        return result.scalar()
