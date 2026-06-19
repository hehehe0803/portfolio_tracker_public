"""
Add foundational portfolio state tables.

Revision ID: backend_foundation_tables
Revises: auth_sessions
Create Date: 2026-04-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "backend_foundation_tables"
down_revision: str | None = "auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("last_price_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_assets_symbol"),
    )

    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 10), nullable=False),
        sa.Column("avg_buy_price_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("total_cost_usd", sa.Numeric(20, 6), nullable=False),
        sa.Column("current_price_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("current_value_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("unrealized_pnl_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("unrealized_pnl_pct", sa.Numeric(20, 10), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id",
            "captured_at",
            name="uq_position_snapshots_asset_id_captured_at",
        ),
    )
    op.create_index(
        "ix_position_snapshots_captured_at",
        "position_snapshots",
        ["captured_at"],
    )

    op.create_table(
        "pending_orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("institution", sa.String(length=50), nullable=False),
        sa.Column("external_order_id", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("order_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 10), nullable=False),
        sa.Column("limit_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("stop_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution",
            "external_order_id",
            name="uq_pending_orders_institution_external_order_id",
        ),
    )

    op.create_table(
        "benchmark_quotes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_usd", sa.Numeric(20, 6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "captured_at",
            name="uq_benchmark_quotes_symbol_captured_at",
        ),
    )
    op.create_index(
        "ix_benchmark_quotes_captured_at",
        "benchmark_quotes",
        ["captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_benchmark_quotes_captured_at", table_name="benchmark_quotes")
    op.drop_table("benchmark_quotes")
    op.drop_table("pending_orders")
    op.drop_index("ix_position_snapshots_captured_at", table_name="position_snapshots")
    op.drop_table("position_snapshots")
    op.drop_table("assets")
