"""Create global_market_interdependencies master table and
global_market_interdependency_history child table for cross-asset
causality and time-lag analysis.

Revision ID: 0009
Revises: 0008_market_indices
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_global_interdependency"
down_revision = "0008_market_indices"
branch_labels = None
depends_on = None


def upgrade():
    # ── Master table: latest interdependency matrix ──────────────────────
    op.create_table(
        "global_market_interdependencies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_instrument_id", sa.String(50), nullable=False),
        sa.Column("target_instrument_id", sa.String(50), nullable=False),
        sa.Column("source_asset_class", sa.String(20)),
        sa.Column("target_asset_class", sa.String(20)),
        sa.Column("correlation_coefficient", sa.Numeric(8, 6), nullable=False),
        sa.Column("causality_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("causality_p_value", sa.Numeric(10, 8)),
        sa.Column("causality_direction", sa.String(10), server_default="none"),
        sa.Column("time_lag_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_lag_periods", sa.Integer(), server_default="0"),
        sa.Column("impact_weight", sa.Numeric(8, 6), server_default="0"),
        sa.Column("regime", sa.String(20), server_default="unknown"),
        sa.Column("var_order", sa.Integer()),
        sa.Column("sample_size", sa.Integer()),
        sa.Column("as_of_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "source_instrument_id",
            "target_instrument_id",
            "as_of_date",
            name="uq_gmi_source_target_date",
        ),
    )

    # Composite covering index for sub-millisecond lookups:
    #   "given target ticker, find all sources that influence it"
    op.create_index(
        "idx_gmi_target_date",
        "global_market_interdependencies",
        ["target_instrument_id", "as_of_date", "impact_weight"],
    )

    # Reverse lookup: "given source, find all targets it influences"
    op.create_index(
        "idx_gmi_source_date",
        "global_market_interdependencies",
        ["source_instrument_id", "as_of_date"],
    )

    # Regime-filtered query: "get all relationships under crisis regime"
    op.create_index(
        "idx_gmi_regime_date",
        "global_market_interdependencies",
        ["regime", "as_of_date"],
    )

    # ── Child table: daily historical snapshots ──────────────────────────
    op.create_table(
        "global_market_interdependency_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source_instrument_id", sa.String(50), nullable=False),
        sa.Column("target_instrument_id", sa.String(50), nullable=False),
        sa.Column("correlation_coefficient", sa.Numeric(8, 6), nullable=False),
        sa.Column("causality_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("causality_p_value", sa.Numeric(10, 8)),
        sa.Column("causality_direction", sa.String(10), server_default="none"),
        sa.Column("time_lag_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("time_lag_periods", sa.Integer(), server_default="0"),
        sa.Column("impact_weight", sa.Numeric(8, 6), server_default="0"),
        sa.Column("regime", sa.String(20), server_default="unknown"),
        sa.Column("var_order", sa.Integer()),
        sa.Column("sample_size", sa.Integer()),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "source_instrument_id",
            "target_instrument_id",
            "snapshot_date",
            name="uq_gmih_source_target_snapshot",
        ),
    )

    op.create_index(
        "idx_gmih_target_snapshot",
        "global_market_interdependency_history",
        ["target_instrument_id", "snapshot_date"],
    )

    op.create_index(
        "idx_gmih_source_snapshot",
        "global_market_interdependency_history",
        ["source_instrument_id", "snapshot_date"],
    )

    op.create_index(
        "idx_gmih_snapshot_date",
        "global_market_interdependency_history",
        ["snapshot_date"],
    )


def downgrade():
    op.drop_index("idx_gmih_snapshot_date", "global_market_interdependency_history")
    op.drop_index("idx_gmih_source_snapshot", "global_market_interdependency_history")
    op.drop_index("idx_gmih_target_snapshot", "global_market_interdependency_history")
    op.drop_table("global_market_interdependency_history")

    op.drop_index("idx_gmi_regime_date", "global_market_interdependencies")
    op.drop_index("idx_gmi_source_date", "global_market_interdependencies")
    op.drop_index("idx_gmi_target_date", "global_market_interdependencies")
    op.drop_table("global_market_interdependencies")
