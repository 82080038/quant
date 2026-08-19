"""Create asset_classes master table and add FK from instruments.asset_class.

This migration normalizes the asset_class column in instruments from a
free-text string into a proper foreign key to a master table. This enables
strict referential integrity for multi-asset multi-exchange trading.

Asset classes seeded:
  - equity      (stocks/ETFs)
  - forex       (currency pairs)
  - commodity   (gold, oil, CPO, etc.)
  - crypto      (BTC, ETH, etc.)
  - index       (market indices: ^GSPC, ^JKSE, etc.)
  - bond        (government/corporate bonds)
  - macro_rate  (interest rates, policy rates)

Revision ID: 0010
Revises: 0009_global_interdependency
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_asset_classes"
down_revision = "0009_global_interdependency"
branch_labels = None
depends_on = None


def upgrade():
    # ── Master table: asset_classes ──────────────────────────────────────
    op.create_table(
        "asset_classes",
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("market_hours_24h", sa.Boolean, nullable=False, default=False),
        sa.Column("holiday_calendar_source", sa.String(50), default="exchange"),
        sa.Column("default_currency", sa.String(3), default="USD"),
        sa.Column("default_data_source", sa.String(50), default="yahoo_finance"),
        sa.Column("default_fetch_frequency", sa.String(20), default="EOD"),
        sa.Column("is_tradeable", sa.Boolean, default=True),
        sa.Column("sort_order", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Seed standard asset classes ─────────────────────────────────────
    op.execute(
        """
        INSERT INTO asset_classes (code, name, description, market_hours_24h, holiday_calendar_source, default_currency, default_data_source, default_fetch_frequency, is_tradeable, sort_order) VALUES
        ('equity',     'Equity / Stock',       'Individual stocks and ETFs',                     FALSE, 'exchange',       'IDR', 'yahoo_finance', 'EOD',          TRUE, 1),
        ('index',      'Market Index',         'Benchmark indices (non-tradeable directly)',     FALSE, 'exchange',       'USD', 'yahoo_finance', 'EOD',          FALSE, 2),
        ('forex',      'Foreign Exchange',     'Currency pairs (e.g. EUR/USD, USD/IDR)',          TRUE,  'central_bank',   'USD', 'yahoo_finance', 'EOD',          TRUE, 3),
        ('commodity',  'Commodity',            'Gold, oil, CPO, agricultural products',           TRUE,  'exchange',       'USD', 'yahoo_finance', 'EOD',          TRUE, 4),
        ('crypto',     'Cryptocurrency',       'Digital assets (BTC, ETH, etc.)',                 TRUE,  'none',           'USD', 'binance',       'INTRADAY_15M', TRUE, 5),
        ('bond',       'Bond / Fixed Income',  'Government and corporate bonds',                  FALSE, 'central_bank',   'USD', 'yahoo_finance', 'EOD',          TRUE, 6),
        ('macro_rate', 'Macro Economic Rate',  'Policy rates, interbank rates (non-tradeable)',   TRUE,  'central_bank',   'USD', 'fred',          'WEEKLY',       FALSE, 7)
        """
    )

    # ── Add base_currency and quote_currency columns for forex ─────────
    op.add_column("instruments", sa.Column("base_currency", sa.String(3)))
    op.add_column("instruments", sa.Column("quote_currency", sa.String(3)))

    # ── Migrate existing instruments.asset_class values ──────────────────
    # Current values: EQUITY_INDIVIDUAL, EQUITY, INDEX_COMPOSITE, FX,
    # COMMODITY_FUTURES, ETF, fund, VOLATILITY_RATE, index
    # Map each to the correct asset_classes.code.
    op.execute(
        """
        UPDATE instruments SET asset_class = 'equity'
        WHERE asset_class IN ('EQUITY_INDIVIDUAL', 'EQUITY', 'ETF', 'fund')
           OR asset_class ILIKE 'EQUITY%%'
        """
    )
    op.execute(
        """
        UPDATE instruments SET asset_class = 'index'
        WHERE asset_class IN ('INDEX_COMPOSITE', 'INDEX')
        """
    )
    op.execute(
        """
        UPDATE instruments SET asset_class = 'forex'
        WHERE asset_class IN ('FX', 'FOREX')
        """
    )
    op.execute(
        """
        UPDATE instruments SET asset_class = 'commodity'
        WHERE asset_class IN ('COMMODITY_FUTURES', 'COMMODITY')
        """
    )
    op.execute(
        """
        UPDATE instruments SET asset_class = 'macro_rate'
        WHERE asset_class IN ('VOLATILITY_RATE', 'MACRO_RATE')
        """
    )
    # Any remaining unknown values → 'equity' as safe default
    op.execute(
        """
        UPDATE instruments
        SET asset_class = 'equity'
        WHERE asset_class NOT IN (SELECT code FROM asset_classes)
        """
    )
    # Set default for asset_class column
    op.alter_column("instruments", "asset_class", server_default=sa.text("'equity'"))

    # ── Add FK constraint ────────────────────────────────────────────────
    op.create_foreign_key(
        "fk_instruments_asset_class",
        "instruments",
        "asset_classes",
        ["asset_class"],
        ["code"],
        ondelete="SET DEFAULT",
        onupdate="CASCADE",
    )

    # ── Add index for asset_class queries ────────────────────────────────
    op.create_index(
        "idx_instruments_asset_class",
        "instruments",
        ["asset_class"],
    )


def downgrade():
    op.drop_index("idx_instruments_asset_class", table_name="instruments")
    op.drop_constraint("fk_instruments_asset_class", "instruments", type_="foreignkey")
    op.drop_column("instruments", "quote_currency")
    op.drop_column("instruments", "base_currency")
    op.drop_table("asset_classes")
