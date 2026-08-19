"""Add state-driven incremental pipeline infrastructure.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-19

Implements state-driven incremental processing pipeline:
- pipeline_state table: per-ticker, per-step status tracking with failover
- recompute_watermark table: incremental processing checkpoints (ticker + table_name)
- Enriches scheduler_state with is_stale, data_dependencies, data_ready, last_result, last_duration_seconds
- Enriches instruments with fetch_status, data_layer, fetch_frequency, last_fetch_at, next_fetch_at
- Enriches recompute_dependencies with depends_on, step_level, status_column

References:
- https://thoughtbot.com/blog/modeling-state-transitions-in-postgres
- https://cursa.app/en/page/maintaining-projections-with-incremental-and-replayable-processing
- https://www.citusdata.com/blog/2018/06/14/scalable-incremental-data-aggregation/
- Old market project: recompute_watermark, scheduler_state, fetch_registry patterns
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. pipeline_state: per-ticker per-step status tracking ──────────
    op.create_table(
        "pipeline_state",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(30), nullable=False, index=True),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("step", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("step_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_traceback", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("ticker", "date", "step", name="uq_pipeline_state_pk"),
    )
    op.create_index(
        "idx_pipeline_state_status_step",
        "pipeline_state",
        ["status", "step_level"],
    )
    op.create_index(
        "idx_pipeline_state_ticker_status",
        "pipeline_state",
        ["ticker", "status"],
    )
    op.create_index(
        "idx_pipeline_state_date_status",
        "pipeline_state",
        [sa.text("date DESC"), "status"],
    )

    # ── 2. recompute_watermark: incremental processing checkpoint ────────
    op.create_table(
        "recompute_watermark",
        sa.Column("ticker", sa.String(20), primary_key=True),
        sa.Column("table_name", sa.String(50), primary_key=True),
        sa.Column("last_processed_date", sa.Date, nullable=True),
        sa.Column("last_ohlcv_date", sa.Date, nullable=True),
        sa.Column("rows_processed", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_recompute_watermark_table",
        "recompute_watermark",
        ["table_name"],
    )

    # ── 3. Enrich scheduler_state ────────────────────────────────────────
    op.add_column("scheduler_state", sa.Column("is_stale", sa.Boolean, server_default="false"))
    op.add_column("scheduler_state", sa.Column("data_dependencies", sa.JSON, nullable=True))
    op.add_column("scheduler_state", sa.Column("data_ready", sa.Boolean, server_default="false"))
    op.add_column("scheduler_state", sa.Column("last_result", sa.JSON, nullable=True))
    op.add_column("scheduler_state", sa.Column("is_catchup", sa.Boolean, server_default="false"))
    op.add_column("scheduler_state", sa.Column("last_duration_seconds", sa.Float, nullable=True))
    op.add_column("scheduler_state", sa.Column("run_count", sa.Integer, server_default="0"))

    # ── 4. Enrich instruments with fetch metadata ───────────────────────
    op.add_column("instruments", sa.Column("data_layer", sa.String(30), nullable=True))
    op.add_column("instruments", sa.Column("fetch_frequency", sa.String(20), server_default="EOD"))
    op.add_column("instruments", sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("instruments", sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("instruments", sa.Column("fetch_status", sa.String(20), server_default="NEVER_FETCHED"))
    op.add_column("instruments", sa.Column("data_source_type", sa.String(50), nullable=True))
    op.add_column("instruments", sa.Column("data_source_url", sa.String(255), nullable=True))
    op.add_column("instruments", sa.Column("data_source_fallback", sa.String(255), nullable=True))
    op.add_column("instruments", sa.Column("fetch_adapter", sa.String(50), nullable=True))
    op.add_column("instruments", sa.Column("data_source_metadata", sa.JSON, nullable=True))
    op.add_column("instruments", sa.Column("exchange_mic", sa.String(20), nullable=True))
    op.add_column("instruments", sa.Column("delisting_date", sa.Date, nullable=True))
    op.add_column("instruments", sa.Column("underlying_ticker", sa.String(30), nullable=True))

    op.create_index("idx_instruments_fetch_status", "instruments", ["fetch_status"])
    op.create_index("idx_instruments_data_layer", "instruments", ["data_layer"])
    op.create_index("idx_instruments_next_fetch", "instruments", ["next_fetch_at"])

    # ── 5. Enrich recompute_dependencies ────────────────────────────────
    op.add_column("recompute_dependencies", sa.Column("depends_on", sa.String(50), nullable=True))
    op.add_column("recompute_dependencies", sa.Column("step_level", sa.Integer, server_default="0"))
    op.add_column("recompute_dependencies", sa.Column("status_column", sa.String(50), nullable=True))
    op.add_column("recompute_dependencies", sa.Column("target_table", sa.String(50), nullable=True))
    op.add_column("recompute_dependencies", sa.Column("is_active", sa.Boolean, server_default="true"))

    # ── 6. Add composite index on stock_prices for pipeline queries ──────
    op.create_index(
        "idx_stock_prices_ticker_date_source",
        "stock_prices",
        ["ticker", sa.text("date DESC"), "source"],
    )

    # ── 7. Add status index on data_watermark ────────────────────────────
    # data_watermark already has a unique index on source; skip duplicate


def downgrade() -> None:
    op.drop_index("idx_stock_prices_ticker_date_source", table_name="stock_prices")
    op.drop_index("idx_instruments_next_fetch", table_name="instruments")
    op.drop_index("idx_instruments_data_layer", table_name="instruments")
    op.drop_index("idx_instruments_fetch_status", table_name="instruments")
    op.drop_column("instruments", "underlying_ticker")
    op.drop_column("instruments", "delisting_date")
    op.drop_column("instruments", "exchange_mic")
    op.drop_column("instruments", "data_source_metadata")
    op.drop_column("instruments", "fetch_adapter")
    op.drop_column("instruments", "data_source_fallback")
    op.drop_column("instruments", "data_source_url")
    op.drop_column("instruments", "data_source_type")
    op.drop_column("instruments", "fetch_status")
    op.drop_column("instruments", "next_fetch_at")
    op.drop_column("instruments", "last_fetch_at")
    op.drop_column("instruments", "fetch_frequency")
    op.drop_column("instruments", "data_layer")
    op.drop_column("recompute_dependencies", "is_active")
    op.drop_column("recompute_dependencies", "target_table")
    op.drop_column("recompute_dependencies", "status_column")
    op.drop_column("recompute_dependencies", "step_level")
    op.drop_column("recompute_dependencies", "depends_on")
    op.drop_column("scheduler_state", "run_count")
    op.drop_column("scheduler_state", "last_duration_seconds")
    op.drop_column("scheduler_state", "is_catchup")
    op.drop_column("scheduler_state", "last_result")
    op.drop_column("scheduler_state", "data_ready")
    op.drop_column("scheduler_state", "data_dependencies")
    op.drop_column("scheduler_state", "is_stale")
    op.drop_index("idx_recompute_watermark_table", table_name="recompute_watermark")
    op.drop_table("recompute_watermark")
    op.drop_index("idx_pipeline_state_date_status", table_name="pipeline_state")
    op.drop_index("idx_pipeline_state_ticker_status", table_name="pipeline_state")
    op.drop_index("idx_pipeline_state_status_step", table_name="pipeline_state")
    op.drop_table("pipeline_state")
