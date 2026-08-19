"""Add missing FK indexes for performance.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19

Adds indexes on foreign key columns that were missing:
- instruments.exchange_id
- instruments.sector_id
- exchange_holidays.exchange_id
- feature_values.feature_def_id

These indexes prevent full table scans during cascading operations
and improve JOIN performance. See:
- https://www.cybertec-postgresql.com/en/postgresql-indexes-and-foreign-keys/
- https://wiki.postgresql.org/wiki/Unindexed_foreign_keys
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_instruments_exchange_id", "instruments", ["exchange_id"])
    op.create_index("idx_instruments_sector_id", "instruments", ["sector_id"])
    op.create_index("idx_exchange_holidays_exchange_id", "exchange_holidays", ["exchange_id"])
    op.create_index("idx_feature_values_feature_def_id", "feature_values", ["feature_def_id"])


def downgrade() -> None:
    op.drop_index("idx_feature_values_feature_def_id", table_name="feature_values")
    op.drop_index("idx_exchange_holidays_exchange_id", table_name="exchange_holidays")
    op.drop_index("idx_instruments_sector_id", table_name="instruments")
    op.drop_index("idx_instruments_exchange_id", table_name="instruments")
