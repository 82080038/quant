"""Add FK constraints and industry columns.

Revision ID: 0004
Revises: 0003_pipeline_state_machine
Create Date: 2026-08-20

Changes:
- Add industry, sub_industry columns to instruments
- Add FK constraints from all child tables to instruments(ticker)
- ON UPDATE CASCADE, ON DELETE RESTRICT (preserve historical data)
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_fk_normalization"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # Add industry columns
    op.add_column("instruments", sa.Column("industry", sa.String(100)))
    op.add_column("instruments", sa.Column("sub_industry", sa.String(100)))
    op.execute("COMMENT ON COLUMN instruments.industry IS 'Yahoo Finance industry classification'")
    op.execute("COMMENT ON COLUMN instruments.sub_industry IS 'Yahoo Finance sub-industry'")

    # FK constraints: child → instruments(ticker)
    child_tables = [
        "stock_prices", "feature_values", "signal_attribution_log",
        "portfolio_weights", "pipeline_state", "news_sentiment",
        "foreign_flow", "fundamental_data", "corporate_actions",
        "prediction_evaluation", "paper_trading_orders", "orders",
        "trade_journal", "recompute_watermark", "corporate_calendar",
        "portfolio_state",
    ]
    for tbl in child_tables:
        op.create_foreign_key(
            f"fk_{tbl}_instruments",
            tbl, "instruments",
            ["ticker"], ["ticker"],
            onupdate="CASCADE", ondelete="RESTRICT",
        )


def downgrade():
    child_tables = [
        "stock_prices", "feature_values", "signal_attribution_log",
        "portfolio_weights", "pipeline_state", "news_sentiment",
        "foreign_flow", "fundamental_data", "corporate_actions",
        "prediction_evaluation", "paper_trading_orders", "orders",
        "trade_journal", "recompute_watermark", "corporate_calendar",
        "portfolio_state",
    ]
    for tbl in child_tables:
        op.drop_constraint(f"fk_{tbl}_instruments", tbl, type_="foreignkey")
    op.drop_column("instruments", "sub_industry")
    op.drop_column("instruments", "industry")
