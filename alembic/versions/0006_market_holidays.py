"""Create market_holidays table for global holiday calendar engine.

Revision ID: 0006
Revises: 0005_delisted_flags
Create Date: 2026-08-20

Changes:
- Create market_holidays table with FK to exchanges
- Add composite indexes for fast lookups
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_market_holidays"
down_revision = "0005_delisted_flags"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "market_holidays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exchange_id", sa.Integer(), sa.ForeignKey("exchanges.id", ondelete="CASCADE")),
        sa.Column("market_code", sa.String(10), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("holiday_name", sa.String(200)),
        sa.Column("is_historical", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("exchange_id", "holiday_date", "holiday_name"),
    )

    op.create_index("idx_market_holidays_date", "market_holidays", ["holiday_date"])
    op.create_index("idx_market_holidays_market_date", "market_holidays", ["market_code", "holiday_date"])
    op.create_index("idx_market_holidays_exchange_date", "market_holidays", ["exchange_id", "holiday_date"])


def downgrade():
    op.drop_index("idx_market_holidays_exchange_date", "market_holidays")
    op.drop_index("idx_market_holidays_market_date", "market_holidays")
    op.drop_index("idx_market_holidays_date", "market_holidays")
    op.drop_table("market_holidays")
