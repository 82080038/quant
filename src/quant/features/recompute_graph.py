"""Recompute Dependency Graph — selective recompute based on data updates.

When a data source is updated (e.g. ``stock_prices`` from fetch_eod),
only the recompute functions that depend on that source are triggered.
This avoids unnecessary full recompute of all modules.

Schema::

    recompute_dependencies:
        function_name → data_source (many-to-many)

    recompute_triggers:
        log of each selective recompute execution

Usage::

    from quant.analysis.recompute_graph import RecomputeGraph

    # After fetch_eod updates stock_prices:
    affected = RecomputeGraph.get_affected_functions("stock_prices")
    # → ["recompute_technical_indicators", "recompute_scores",
    #    "recompute_relationship_matrix", ...]

    # Run selective recompute:
    result = RecomputeGraph.trigger_recompute(
        data_source="stock_prices",
        triggered_by="fetch_eod",
        session=session,
    )

    # View dependency graph:
    graph = RecomputeGraph.get_full_graph()
    # → {"recompute_scores": ["stock_prices", "fundamental_data", ...], ...}

    # Add new dependency:
    RecomputeGraph.add_dependency(
        function_name="recompute_new_module",
        data_source="stock_prices",
        is_required=True,
    )
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from quant.db.engine import get_sessionmaker
from quant.db.models import RecomputeDependency, RecomputeTrigger

logger = logging.getLogger(__name__)

# In-memory cache of dependency graph
_graph_cache: dict[str, list[str]] | None = None
_graph_cache_ts: datetime | None = None
_CACHE_TTL_SECONDS = 600  # 10 minutes


class RecomputeGraph:
    """Dependency graph for selective recompute."""

    # ── Query ──────────────────────────────────────────────────────

    @staticmethod
    def get_affected_functions(
        data_source: str,
        session: Session | None = None,
    ) -> list[str]:
        """Get list of recompute functions that depend on a data source.

        Args:
            data_source: Table or data source name (e.g. 'stock_prices').
            session: Optional SQLAlchemy session.

        Returns:
            List of function names that depend on this data source.
        """
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        try:
            rows = session.execute(
                select(RecomputeDependency.function_name)
                .where(RecomputeDependency.data_source == data_source)
                .distinct()
            ).scalars().all()
            return sorted(rows)
        finally:
            if own_session:
                session.close()

    @staticmethod
    def get_function_dependencies(
        function_name: str,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        """Get all data sources a function depends on.

        Returns list of dicts: {data_source, source_type, is_required, description}
        """
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        try:
            rows = session.execute(
                select(RecomputeDependency)
                .where(RecomputeDependency.function_name == function_name)
            ).scalars().all()
            return [
                {
                    "data_source": r.data_source,
                    "source_type": r.source_type,
                    "is_required": r.is_required,
                    "description": r.description,
                }
                for r in rows
            ]
        finally:
            if own_session:
                session.close()

    @staticmethod
    def get_full_graph(
        session: Session | None = None,
    ) -> dict[str, list[str]]:
        """Get the complete dependency graph: {function_name: [data_sources]}.

        Uses in-memory cache (10 min TTL).
        """
        global _graph_cache, _graph_cache_ts

        now = datetime.now(UTC)
        if _graph_cache is not None and _graph_cache_ts is not None:
            age = (now - _graph_cache_ts).total_seconds()
            if age < _CACHE_TTL_SECONDS:
                return _graph_cache.copy()

        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        graph: dict[str, list[str]] = {}
        try:
            rows = session.execute(
                select(RecomputeDependency)
            ).scalars().all()

            for row in rows:
                if row.function_name not in graph:
                    graph[row.function_name] = []
                graph[row.function_name].append(row.data_source)

            _graph_cache = graph.copy()
            _graph_cache_ts = now
        finally:
            if own_session:
                session.close()

        return graph

    @staticmethod
    def get_all_data_sources(
        session: Session | None = None,
    ) -> list[str]:
        """Get all unique data sources in the dependency graph."""
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        try:
            rows = session.execute(
                select(RecomputeDependency.data_source).distinct()
            ).scalars().all()
            return sorted(rows)
        except Exception:
            return []
        finally:
            if own_session:
                session.close()

    # ── Trigger selective recompute ────────────────────────────────

    @staticmethod
    def trigger_recompute(
        data_source: str,
        triggered_by: str,
        session: Session | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Trigger selective recompute for functions depending on data_source.

        Only functions that depend on the updated data source are run.
        Results are logged to recompute_triggers table.

        Args:
            data_source: Which data source was updated (e.g. 'stock_prices').
            triggered_by: What triggered this (e.g. 'fetch_eod', 'manual').
            session: Optional SQLAlchemy session.
            dry_run: If True, only return what would be triggered without running.

        Returns:
            Dict with: functions_triggered, functions_skipped, status, duration.
        """
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        affected = RecomputeGraph.get_affected_functions(data_source, session=session)

        # Get all known recompute functions to compute skipped
        full_graph = RecomputeGraph.get_full_graph(session=session)
        all_functions = set(full_graph.keys())
        skipped = sorted(all_functions - set(affected))

        # Estimate before running
        from quant.analysis.recompute_estimator import RecomputeEstimator

        estimate = RecomputeEstimator.estimate_trigger(data_source, session=session)

        # Smart skip: remove functions where data hasn't changed
        skip_functions = estimate.get("can_skip", [])
        functions_to_run = [f for f in affected if f not in skip_functions]

        if dry_run:
            return {
                "data_source": data_source,
                "triggered_by": triggered_by,
                "functions_triggered": affected,
                "functions_to_run": functions_to_run,
                "functions_skipped": skipped,
                "functions_skip_fresh": skip_functions,
                "estimate": estimate,
                "status": "dry_run",
            }

        # Log trigger
        trigger_row = RecomputeTrigger(
            triggered_by=triggered_by,
            data_source_updated=data_source,
            functions_triggered=json.dumps(affected),
            functions_skipped=json.dumps(skipped),
            status="running",
            started_at=datetime.now(UTC),
        )
        session.add(trigger_row)
        session.commit()
        session.refresh(trigger_row)
        trigger_id = trigger_row.id

        # Execute affected recompute functions
        from quant.analysis.recompute import (
            recompute_fear_greed,
            recompute_market_regimes,
            recompute_ml_labels,
            recompute_relationship_matrix,
            recompute_scores,
            recompute_stock_personality,
            recompute_technical_indicators,
            recompute_weights,
        )
        from quant.multi_asset.cross_market import recompute_cross_market
        from quant.analysis.recompute_advanced import (
            recompute_holiday_effects,
            recompute_instrument_profiles,
            recompute_cross_market_coefficients,
            recompute_dcc_garch,
            recompute_seasonal_patterns,
            recompute_macro_correlation,
            recompute_causal_relationships,
            recompute_satellite_correlation,
            recompute_astronacci_cycles,
        )

        # Map function names to callables (9 core + 9 advanced = 18)
        FUNCTION_MAP = {
            # Core (from recompute.py + cross_market.py)
            "recompute_technical_indicators": recompute_technical_indicators,
            "recompute_scores": recompute_scores,
            "recompute_relationship_matrix": recompute_relationship_matrix,
            "recompute_cross_market": recompute_cross_market,
            "recompute_fear_greed": recompute_fear_greed,
            "recompute_stock_personality": recompute_stock_personality,
            "recompute_ml_labels": recompute_ml_labels,
            "recompute_market_regimes": recompute_market_regimes,
            "recompute_weights": recompute_weights,
            # Advanced (from recompute_advanced.py)
            "recompute_holiday_effects": recompute_holiday_effects,
            "recompute_instrument_profiles": recompute_instrument_profiles,
            "recompute_cross_market_coefficients": recompute_cross_market_coefficients,
            "recompute_dcc_garch": recompute_dcc_garch,
            "recompute_seasonal_patterns": recompute_seasonal_patterns,
            "recompute_macro_correlation": recompute_macro_correlation,
            "recompute_causal_relationships": recompute_causal_relationships,
            "recompute_satellite_correlation": recompute_satellite_correlation,
            "recompute_astronacci_cycles": recompute_astronacci_cycles,
        }

        results: dict[str, int] = {}
        errors: list[str] = []
        total_rows = 0

        for fn_name in affected:
            # Smart skip: skip if data is fresh
            if fn_name in skip_functions:
                logger.info("Selective recompute: SKIP %s (data fresh, source=%s)", fn_name, data_source)
                results[fn_name] = 0
                RecomputeEstimator.record_run(
                    function_name=fn_name,
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    duration_seconds=0.0,
                    rows_affected=0,
                    status="skipped",
                    trigger_id=trigger_id,
                    session=session,
                )
                continue

            fn = FUNCTION_MAP.get(fn_name)
            if fn is None:
                logger.warning("Unknown recompute function: %s", fn_name)
                results[fn_name] = -1
                continue

            fn_start = datetime.now(UTC)
            # Mark the prediction as used (for feedback loop accuracy tracking)
            try:
                from quant.analysis.recompute_analyzer import RecomputeAnalyzer
                RecomputeAnalyzer.mark_prediction_used(fn_name, incremental=False, session=session)
            except Exception:
                pass

            try:
                logger.info("Selective recompute: %s (source=%s)", fn_name, data_source)
                count = fn(session, dry_run=False)
                fn_end = datetime.now(UTC)
                fn_dur = (fn_end - fn_start).total_seconds()
                results[fn_name] = count
                total_rows += max(count, 0)

                # Record run stats
                RecomputeEstimator.record_run(
                    function_name=fn_name,
                    started_at=fn_start,
                    completed_at=fn_end,
                    duration_seconds=fn_dur,
                    rows_affected=max(count, 0),
                    status="completed",
                    trigger_id=trigger_id,
                    session=session,
                )
            except Exception as e:
                fn_end = datetime.now(UTC)
                fn_dur = (fn_end - fn_start).total_seconds()
                logger.error("  %s FAILED: %s", fn_name, e)
                results[fn_name] = -1
                errors.append(f"{fn_name}: {e}")
                session.rollback()

                # Record failed run
                RecomputeEstimator.record_run(
                    function_name=fn_name,
                    started_at=fn_start,
                    completed_at=fn_end,
                    duration_seconds=fn_dur,
                    status="failed",
                    error_message=str(e),
                    trigger_id=trigger_id,
                    session=session,
                )

        # Update trigger log
        now = datetime.now(UTC)
        trigger_row = session.get(RecomputeTrigger, trigger_id)
        if trigger_row:
            start = trigger_row.started_at or now
            trigger_row.status = "completed" if not errors else "partial"
            trigger_row.completed_at = now
            trigger_row.duration_seconds = (now - start).total_seconds()
            trigger_row.rows_affected = total_rows
            trigger_row.error_message = "; ".join(errors) if errors else None
            session.commit()

        if own_session:
            session.close()

        RecomputeGraph._invalidate_cache()

        return {
            "trigger_id": trigger_id,
            "data_source": data_source,
            "triggered_by": triggered_by,
            "functions_triggered": affected,
            "functions_to_run": functions_to_run,
            "functions_skipped": skipped,
            "functions_skip_fresh": skip_functions,
            "results": results,
            "total_rows": total_rows,
            "errors": errors,
            "status": "completed" if not errors else "partial",
            "estimate": estimate,
            "actual_duration_s": (datetime.now(UTC) - trigger_row.started_at).total_seconds() if trigger_row.started_at else None,
        }

    # ── Manage dependencies ────────────────────────────────────────

    @staticmethod
    def add_dependency(
        function_name: str,
        data_source: str,
        source_type: str = "table",
        is_required: bool = True,
        description: str | None = None,
        session: Session | None = None,
    ) -> bool:
        """Add a new dependency mapping."""
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        try:
            existing = session.execute(
                select(RecomputeDependency)
                .where(
                    RecomputeDependency.function_name == function_name,
                    RecomputeDependency.data_source == data_source,
                )
            ).scalar_one_or_none()

            if existing:
                existing.source_type = source_type
                existing.is_required = is_required
                if description:
                    existing.description = description
            else:
                session.add(RecomputeDependency(
                    function_name=function_name,
                    data_source=data_source,
                    source_type=source_type,
                    is_required=is_required,
                    description=description,
                ))

            session.commit()
            RecomputeGraph._invalidate_cache()
            return True
        except Exception as e:
            logger.error("RecomputeGraph: add_dependency failed: %s", e)
            session.rollback()
            return False
        finally:
            if own_session:
                session.close()

    @staticmethod
    def remove_dependency(
        function_name: str,
        data_source: str,
        session: Session | None = None,
    ) -> bool:
        """Remove a dependency mapping."""
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        try:
            row = session.execute(
                select(RecomputeDependency)
                .where(
                    RecomputeDependency.function_name == function_name,
                    RecomputeDependency.data_source == data_source,
                )
            ).scalar_one_or_none()

            if row:
                session.delete(row)
                session.commit()
                RecomputeGraph._invalidate_cache()
                return True
            return False
        except Exception as e:
            logger.error("RecomputeGraph: remove_dependency failed: %s", e)
            session.rollback()
            return False
        finally:
            if own_session:
                session.close()

    # ── Trigger history ────────────────────────────────────────────

    @staticmethod
    def get_trigger_history(
        limit: int = 20,
        session: Session | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent recompute trigger history."""
        own_session = False
        if session is None:
            session = get_sessionmaker()()
            own_session = True

        try:
            rows = session.execute(
                select(RecomputeTrigger)
                .order_by(RecomputeTrigger.created_at.desc())
                .limit(limit)
            ).scalars().all()

            return [
                {
                    "id": r.id,
                    "triggered_by": r.triggered_by,
                    "data_source_updated": r.data_source_updated,
                    "functions_triggered": json.loads(r.functions_triggered) if r.functions_triggered else [],
                    "functions_skipped": json.loads(r.functions_skipped) if r.functions_skipped else [],
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "duration_seconds": float(r.duration_seconds) if r.duration_seconds else None,
                    "rows_affected": r.rows_affected,
                    "error_message": r.error_message,
                }
                for r in rows
            ]
        except Exception as e:
            logger.debug("RecomputeGraph: get_trigger_history failed: %s", e)
            return []
        finally:
            if own_session:
                session.close()

    # ── Cache ──────────────────────────────────────────────────────

    @staticmethod
    def _invalidate_cache() -> None:
        global _graph_cache, _graph_cache_ts
        _graph_cache = None
        _graph_cache_ts = None

    @staticmethod
    def clear_cache() -> None:
        RecomputeGraph._invalidate_cache()
