"""Add is_delisted, delisted_reason columns and composite index.

Revision ID: 0005
Revises: 0004_fk_normalization
Create Date: 2026-08-20

Changes:
- Add is_delisted (BOOLEAN, default FALSE) to instruments
- Add delisted_reason (TEXT) to instruments
- Sync is_delisted from is_active and delisted_date
- Consolidate delisting_date → delisted_date, drop redundant column
- Add composite index on (is_delisted, delisted_date)
- Add partial index on is_active WHERE is_active = TRUE
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_delisted_flags"
down_revision = "0004_fk_normalization"
branch_labels = None
depends_on = None


def upgrade():
    # Add columns
    op.add_column("instruments", sa.Column("is_delisted", sa.Boolean(), server_default=sa.text("FALSE")))
    op.add_column("instruments", sa.Column("delisted_reason", sa.Text()))
    op.execute("COMMENT ON COLUMN instruments.is_delisted IS 'TRUE if ticker has been delisted from exchange'")
    op.execute("COMMENT ON COLUMN instruments.delisted_reason IS 'Official reason for delisting'")

    # Sync from existing data
    op.execute("UPDATE instruments SET is_delisted = TRUE WHERE is_active = FALSE")
    op.execute("UPDATE instruments SET is_delisted = TRUE WHERE delisted_date IS NOT NULL")
    op.execute("UPDATE instruments SET is_delisted = TRUE WHERE delisting_date IS NOT NULL")
    op.execute("UPDATE instruments SET delisted_date = delisting_date WHERE delisted_date IS NULL AND delisting_date IS NOT NULL")

    # Drop redundant column
    op.drop_column("instruments", "delisting_date")

    # Composite index for fast delisted filtering
    op.create_index("idx_instruments_delisted_date", "instruments", ["is_delisted", "delisted_date"])

    # Partial index for active-only queries
    op.execute("CREATE INDEX idx_instruments_is_active ON instruments (is_active) WHERE is_active = TRUE")


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_instruments_is_active")
    op.drop_index("idx_instruments_delisted_date", "instruments")
    op.add_column("instruments", sa.Column("delisting_date", sa.Date()))
    op.execute("UPDATE instruments SET delisting_date = delisted_date WHERE delisting_date IS NULL AND delisted_date IS NOT NULL")
    op.drop_column("instruments", "delisted_reason")
    op.drop_column("instruments", "is_delisted")
