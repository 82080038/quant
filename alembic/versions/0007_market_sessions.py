"""Create market_sessions table for global timezone orchestration.

Revision ID: 0007
Revises: 0006_market_holidays
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_market_sessions"
down_revision = "0006_market_holidays"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "market_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exchange_id", sa.Integer(), sa.ForeignKey("exchanges.id", ondelete="CASCADE")),
        sa.Column("market_code", sa.String(10), nullable=False, unique=True),
        sa.Column("market_name", sa.String(200)),
        sa.Column("timezone_iana", sa.String(50), nullable=False),
        sa.Column("open_time_utc", sa.Time(), nullable=False),
        sa.Column("close_time_utc", sa.Time(), nullable=False),
        sa.Column("open_time_wib", sa.Time(), nullable=False),
        sa.Column("close_time_wib", sa.Time(), nullable=False),
        sa.Column("timezone_offset_hours", sa.Numeric(4, 1), nullable=False),
        sa.Column("has_dst", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("pre_market_open_utc", sa.Time()),
        sa.Column("post_market_close_utc", sa.Time()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("idx_market_sessions_code", "market_sessions", ["market_code"])


def downgrade():
    op.drop_index("idx_market_sessions_code", "market_sessions")
    op.drop_table("market_sessions")
