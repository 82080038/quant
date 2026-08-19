"""Baseline schema — point-in-time native

Revision ID: 0001
Revises: 
Create Date: 2026-08-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema already created via docs/SCHEMA.sql
    # This migration is a stamp — no DDL to execute
    # Future migrations will add/modify tables from this baseline
    pass


def downgrade() -> None:
    # Cannot downgrade baseline
    pass
