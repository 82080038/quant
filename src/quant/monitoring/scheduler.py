"""Scheduler — cron-like task scheduling for the quant pipeline.

Manages periodic tasks:
  - Data fetching (daily, 17:00 WIB after market close)
  - Factor computation (daily, after data fetch)
  - Signal generation (daily, after factors)
  - Backtest validation (weekly)
  - Model retirement check (weekly)
  - Daily reconciliation & alerts

Uses APScheduler if available, otherwise falls back to simple loop.
All task state is persisted to scheduler_state DB table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, UTC
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A scheduled task definition."""
    name: str
    func: Callable
    schedule: str  # "daily", "weekly", "hourly", cron expression
    time: time = time(17, 0)  # Default 17:00 WIB
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_error: Optional[str] = None
    n_runs: int = 0
    n_errors: int = 0


class TaskScheduler:
    """Cron-like task scheduler for the quant pipeline.

    Usage:
        scheduler = TaskScheduler()
        scheduler.add_task("fetch_data", fetch_data_fn, schedule="daily", time=time(17, 0))
        scheduler.add_task("compute_factors", compute_factors_fn, schedule="daily", time=time(17, 30))
        scheduler.run_pending()
    """

    def __init__(self, session=None):
        self._session = session
        self._tasks: dict[str, ScheduledTask] = {}

    def add_task(
        self,
        name: str,
        func: Callable,
        schedule: str = "daily",
        time: time = time(17, 0),
        enabled: bool = True,
    ) -> None:
        """Add a scheduled task."""
        task = ScheduledTask(
            name=name,
            func=func,
            schedule=schedule,
            time=time,
            enabled=enabled,
        )
        task.next_run = self._compute_next_run(task)
        self._tasks[name] = task
        self._persist_state(task)
        logger.info("Scheduled task: %s (%s at %s)", name, schedule, time)

    def remove_task(self, name: str) -> None:
        """Remove a scheduled task."""
        if name in self._tasks:
            del self._tasks[name]

    def run_pending(self, now: Optional[datetime] = None) -> list[str]:
        """Run all pending tasks.

        Args:
            now: Current datetime (defaults to actual now)

        Returns:
            List of task names that were executed
        """
        now = now or datetime.now(UTC)
        executed = []

        for task in self._tasks.values():
            if not task.enabled:
                continue

            if task.next_run and now >= task.next_run:
                try:
                    logger.info("Running task: %s", task.name)
                    task.func()
                    task.last_run = now
                    task.n_runs += 1
                    task.last_error = None
                    executed.append(task.name)
                except Exception as e:
                    task.n_errors += 1
                    task.last_error = str(e)
                    logger.error("Task %s failed: %s", task.name, e)

                task.next_run = self._compute_next_run(task, now)
                self._persist_state(task)

        return executed

    def run_task(self, name: str) -> bool:
        """Manually run a specific task by name.

        Returns:
            True if task ran successfully
        """
        task = self._tasks.get(name)
        if task is None:
            logger.warning("Task not found: %s", name)
            return False

        try:
            task.func()
            task.last_run = datetime.now(UTC)
            task.n_runs += 1
            task.last_error = None
            self._persist_state(task)
            return True
        except Exception as e:
            task.n_errors += 1
            task.last_error = str(e)
            logger.error("Task %s failed: %s", name, e)
            self._persist_state(task)
            return False

    def _compute_next_run(
        self,
        task: ScheduledTask,
        now: Optional[datetime] = None,
    ) -> datetime:
        """Compute next run time for a task."""
        now = now or datetime.now(UTC)

        if task.schedule == "daily":
            next_dt = datetime.combine(now.date(), task.time, tzinfo=UTC)
            if next_dt <= now:
                next_dt += timedelta(days=1)
            return next_dt

        elif task.schedule == "hourly":
            return now.replace(minute=0, second=0) + timedelta(hours=1)

        elif task.schedule == "weekly":
            days_ahead = (0 - now.weekday()) % 7  # Next Monday
            next_dt = datetime.combine(
                now.date() + timedelta(days=days_ahead), task.time, tzinfo=UTC
            )
            if next_dt <= now:
                next_dt += timedelta(weeks=1)
            return next_dt

        else:
            return now + timedelta(hours=1)

    def _persist_state(self, task: ScheduledTask) -> None:
        """Persist task state to scheduler_state table."""
        if self._session is None:
            return

        try:
            from sqlalchemy import text

            self._session.execute(text("""
                INSERT INTO scheduler_state (task_name, last_run_at, next_run_at, status, last_error)
                VALUES (:name, :last_run, :next_run, :status, :error)
                ON CONFLICT (task_name) DO UPDATE
                SET last_run_at = EXCLUDED.last_run_at,
                    next_run_at = EXCLUDED.next_run_at,
                    status = EXCLUDED.status,
                    last_error = EXCLUDED.last_error
            """), {
                "name": task.name,
                "last_run": task.last_run,
                "next_run": task.next_run,
                "status": "error" if task.last_error else "idle",
                "error": task.last_error,
            })
            self._session.commit()
        except Exception as e:
            logger.warning("Failed to persist scheduler state: %s", e)
            if self._session:
                self._session.rollback()

    def get_status(self) -> list[dict]:
        """Get status of all tasks."""
        return [
            {
                "name": t.name,
                "schedule": t.schedule,
                "time": t.time.isoformat(),
                "enabled": t.enabled,
                "last_run": t.last_run.isoformat() if t.last_run else None,
                "next_run": t.next_run.isoformat() if t.next_run else None,
                "n_runs": t.n_runs,
                "n_errors": t.n_errors,
                "last_error": t.last_error,
            }
            for t in self._tasks.values()
        ]

    def setup_default_tasks(
        self,
        fetch_data_fn: Optional[Callable] = None,
        compute_factors_fn: Optional[Callable] = None,
        generate_signals_fn: Optional[Callable] = None,
        run_backtest_fn: Optional[Callable] = None,
        reconcile_fn: Optional[Callable] = None,
        retirement_check_fn: Optional[Callable] = None,
    ) -> None:
        """Setup default scheduled tasks for the quant pipeline.

        All functions are optional — only tasks with provided functions are scheduled.
        """
        if fetch_data_fn:
            self.add_task("fetch_data", fetch_data_fn, schedule="daily", time=time(17, 0))

        if compute_factors_fn:
            self.add_task("compute_factors", compute_factors_fn, schedule="daily", time=time(17, 15))

        if generate_signals_fn:
            self.add_task("generate_signals", generate_signals_fn, schedule="daily", time=time(17, 30))

        if reconcile_fn:
            self.add_task("daily_reconciliation", reconcile_fn, schedule="daily", time=time(17, 45))

        if run_backtest_fn:
            self.add_task("weekly_backtest", run_backtest_fn, schedule="weekly", time=time(18, 0))

        if retirement_check_fn:
            self.add_task("retirement_check", retirement_check_fn, schedule="weekly", time=time(18, 30))
