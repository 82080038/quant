"""Create market_indices table for major exchange index mapping.

Revision ID: 0008
Revises: 0007_market_sessions
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_market_indices"
down_revision = "0007_market_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "market_indices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("exchange_id", sa.Integer(), sa.ForeignKey("exchanges.id", ondelete="CASCADE")),
        sa.Column("market_code", sa.String(10), nullable=False),
        sa.Column("index_symbol", sa.String(20), nullable=False),
        sa.Column("index_name", sa.String(200), nullable=False),
        sa.Column("yahoo_ticker", sa.String(50)),
        sa.Column("display_priority", sa.Integer(), server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("market_code", "index_symbol", name="uq_market_indices_code_symbol"),
    )

    op.create_index(
        "idx_market_indices_market",
        "market_indices",
        ["market_code", "is_active"],
    )


def downgrade():
    op.drop_index("idx_market_indices_market", "market_indices")
    op.drop_table("market_indices")
