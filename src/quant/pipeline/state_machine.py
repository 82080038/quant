"""State-driven pipeline state machine for incremental processing.

Implements a state machine that tracks each ticker's position in the
modular pipeline:
  INGESTED → SCREENED → ANALYZED → SIGNAL_GENERATED → PORTFOLIO_OPTIMIZED → DONE
      ↘ FAILED (at any step, with error tracking for self-healing)

Each transition is recorded in the `pipeline_state` table with:
  - ticker, date, step, status, step_level
  - error_message + error_traceback (for Agentic AI debugging)
  - retry_count, processed_at, updated_at

Design references:
- https://thoughtbot.com/blog/modeling-state-transitions-in-postgres
  "Model each status change as its own row — full history and current state"
- https://cursa.app/en/page/maintaining-projections-with-incremental-and-replayable-processing
  "Checkpoint table keyed by projection name, stores last processed position"
- Old market project: scheduler_state, recompute_watermark patterns
"""

from __future__ import annotations

import logging
import traceback
from datetime import UTC, date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import text

from quant.core.db import get_db

logger = logging.getLogger(__name__)


class PipelineStatus(str, Enum):
    """Status values for pipeline_state rows."""

    PENDING = "pending"
    INGESTED = "ingested"
    SCREENED = "screened"
    ANALYZED = "analyzed"
    SIGNAL_GENERATED = "signal_generated"
    PORTFOLIO_OPTIMIZED = "portfolio_optimized"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# Step ordering — each step has a level for ordering
STEP_LEVELS: dict[str, int] = {
    "ingest": 0,
    "screen": 1,
    "analyze": 2,
    "signal": 3,
    "portfolio": 4,
    "execute": 5,
}

# Valid transitions
TRANSITIONS: dict[str, set[str]] = {
    PipelineStatus.PENDING.value: {PipelineStatus.INGESTED.value, PipelineStatus.SKIPPED.value},
    PipelineStatus.INGESTED.value: {PipelineStatus.SCREENED.value, PipelineStatus.FAILED.value},
    PipelineStatus.SCREENED.value: {PipelineStatus.ANALYZED.value, PipelineStatus.FAILED.value, PipelineStatus.SKIPPED.value},
    PipelineStatus.ANALYZED.value: {PipelineStatus.SIGNAL_GENERATED.value, PipelineStatus.FAILED.value},
    PipelineStatus.SIGNAL_GENERATED.value: {PipelineStatus.PORTFOLIO_OPTIMIZED.value, PipelineStatus.FAILED.value},
    PipelineStatus.PORTFOLIO_OPTIMIZED.value: {PipelineStatus.DONE.value, PipelineStatus.FAILED.value},
    PipelineStatus.DONE.value: set(),
    PipelineStatus.FAILED.value: {PipelineStatus.PENDING.value},  # retry
    PipelineStatus.SKIPPED.value: set(),
}


class PipelineTracker:
    """Tracks per-ticker pipeline state for incremental processing.

    Usage:
        tracker = PipelineTracker(session)

        # Check if ticker needs processing at a step
        if tracker.needs_processing("BBCA.JK", today, "analyze"):
            # ... do analysis ...
            tracker.mark_status("BBCA.JK", today, "analyze", PipelineStatus.ANALYZED)

        # On failure
        tracker.mark_failed("BBCA.JK", today, "analyze", error, traceback_str)
    """

    def __init__(self, session=None):
        self._session = session
        self._owns_session = session is None

    @property
    def session(self):
        if self._session is None:
            self._session = get_db()
        return self._session

    def close(self):
        if self._owns_session and self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def get_state(
        self,
        ticker: str,
        date: date,
        step: str,
    ) -> Optional[str]:
        """Get current status for a ticker+date+step.

        Uses composite index idx_pipeline_state_ticker_status for O(1) lookup.
        """
        result = self.session.execute(
            text("""
                SELECT status FROM pipeline_state
                WHERE ticker = :ticker AND date = :date AND step = :step
            """),
            {"ticker": ticker, "date": date, "step": step},
        ).scalar_one_or_none()
        return result

    def get_latest_state(
        self,
        ticker: str,
        date: date,
    ) -> Optional[str]:
        """Get the highest step_level status for a ticker+date."""
        result = self.session.execute(
            text("""
                SELECT ps.status FROM pipeline_state ps
                WHERE ps.ticker = :ticker AND ps.date = :date
                ORDER BY ps.step_level DESC
                LIMIT 1
            """),
            {"ticker": ticker, "date": date},
        ).scalar_one_or_none()
        return result

    def needs_processing(
        self,
        ticker: str,
        date: date,
        step: str,
    ) -> bool:
        """Check if a ticker+date+step needs processing.

        Returns True if:
        - No record exists (never processed)
        - Status is 'pending' or 'failed' (retryable)
        """
        status = self.get_state(ticker, date, step)
        if status is None:
            return True
        return status in (PipelineStatus.PENDING.value, PipelineStatus.FAILED.value)

    def mark_status(
        self,
        ticker: str,
        date: date,
        step: str,
        status: PipelineStatus,
    ) -> None:
        """Upsert pipeline state for a ticker+date+step.

        Uses ON CONFLICT for atomic upsert — no race conditions.
        """
        step_level = STEP_LEVELS.get(step, 0)
        self.session.execute(
            text("""
                INSERT INTO pipeline_state (ticker, date, step, status, step_level, processed_at, updated_at)
                VALUES (:ticker, :date, :step, :status, :step_level, now(), now())
                ON CONFLICT (ticker, date, step) DO UPDATE
                SET status = EXCLUDED.status,
                    step_level = EXCLUDED.step_level,
                    processed_at = EXCLUDED.processed_at,
                    updated_at = EXCLUDED.updated_at,
                    error_message = NULL,
                    error_traceback = NULL
            """),
            {
                "ticker": ticker,
                "date": date,
                "step": step,
                "status": status.value,
                "step_level": step_level,
            },
        )
        self.session.commit()

    def mark_failed(
        self,
        ticker: str,
        date: date,
        step: str,
        error: str,
        tb: str = "",
    ) -> None:
        """Mark a step as failed with error details for self-healing.

        Increments retry_count for tracking repeated failures.
        """
        step_level = STEP_LEVELS.get(step, 0)
        self.session.execute(
            text("""
                INSERT INTO pipeline_state (ticker, date, step, status, step_level, error_message, error_traceback, retry_count, updated_at)
                VALUES (:ticker, :date, :step, 'failed', :step_level, :error, :tb, 1, now())
                ON CONFLICT (ticker, date, step) DO UPDATE
                SET status = 'failed',
                    error_message = EXCLUDED.error_message,
                    error_traceback = EXCLUDED.error_traceback,
                    retry_count = pipeline_state.retry_count + 1,
                    updated_at = now()
            """),
            {
                "ticker": ticker,
                "date": date,
                "step": step,
                "step_level": step_level,
                "error": error[:2000],
                "tb": tb[:4000],
            },
        )
        self.session.commit()

    def get_pending(
        self,
        step: str,
        target_date: Optional[date] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get tickers pending processing at a given step.

        Uses idx_pipeline_state_status_step for fast lookup.
        Returns tickers that either:
        - Have no record at this step (never processed)
        - Have status 'pending' or 'failed' (retryable)
        """
        step_level = STEP_LEVELS.get(step, 0)
        if target_date:
            result = self.session.execute(
                text("""
                    SELECT DISTINCT sp.ticker, sp.date
                    FROM stock_prices sp
                    LEFT JOIN pipeline_state ps
                      ON sp.ticker = ps.ticker AND sp.date = ps.date AND ps.step = :step
                    WHERE sp.date = :target_date
                      AND (ps.status IS NULL OR ps.status IN ('pending', 'failed'))
                    ORDER BY sp.ticker
                    LIMIT :limit
                """),
                {"step": step, "target_date": target_date, "limit": limit},
            ).fetchall()
        else:
            result = self.session.execute(
                text("""
                    SELECT DISTINCT sp.ticker, sp.date
                    FROM stock_prices sp
                    LEFT JOIN pipeline_state ps
                      ON sp.ticker = ps.ticker AND sp.date = ps.date AND ps.step = :step
                    WHERE sp.date = (SELECT MAX(date) FROM stock_prices)
                      AND (ps.status IS NULL OR ps.status IN ('pending', 'failed'))
                    ORDER BY sp.ticker
                    LIMIT :limit
                """),
                {"step": step, "limit": limit},
            ).fetchall()

        return [{"ticker": r[0], "date": r[1]} for r in result]

    def get_failed_steps(
        self,
        step: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get all failed steps for Agentic AI self-healing.

        Returns error_message and traceback for debugging.
        """
        if step:
            result = self.session.execute(
                text("""
                    SELECT ticker, date, step, error_message, error_traceback, retry_count, updated_at
                    FROM pipeline_state
                    WHERE status = 'failed' AND step = :step
                    ORDER BY updated_at DESC
                    LIMIT :limit
                """),
                {"step": step, "limit": limit},
            ).fetchall()
        else:
            result = self.session.execute(
                text("""
                    SELECT ticker, date, step, error_message, error_traceback, retry_count, updated_at
                    FROM pipeline_state
                    WHERE status = 'failed'
                    ORDER BY updated_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            ).fetchall()

        return [
            {
                "ticker": r[0],
                "date": r[1],
                "step": r[2],
                "error": r[3],
                "traceback": r[4],
                "retry_count": r[5],
                "updated_at": r[6],
            }
            for r in result
        ]

    def get_pipeline_summary(self) -> dict[str, int]:
        """Get count of each status across all pipeline_state rows."""
        result = self.session.execute(
            text("""
                SELECT status, count(*) as cnt
                FROM pipeline_state
                GROUP BY status
            """)
        ).fetchall()
        return {r[0]: r[1] for r in result}

    def reset_failed(self, ticker: str, date: date, step: str) -> None:
        """Reset a failed step to pending for retry."""
        self.session.execute(
            text("""
                UPDATE pipeline_state
                SET status = 'pending', updated_at = now()
                WHERE ticker = :ticker AND date = :date AND step = :step
            """),
            {"ticker": ticker, "date": date, "step": step},
        )
        self.session.commit()
