"""
Portfolio intelligence and watchlist tables.

Revision ID: intel_watchlist_001
Revises: sec001_institution_creds
Create Date: 2026-04-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "intel_watchlist_001"
down_revision: str | None = "sec001_institution_creds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("sector", sa.String(length=80), nullable=True))
    op.add_column("assets", sa.Column("thesis_status", sa.String(length=30), nullable=False, server_default="none"))
    op.alter_column("assets", "thesis_status", server_default=None)

    op.add_column("notes", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notes", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("activity_logs", sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.alter_column("activity_logs", "metadata", server_default=None)

    op.create_table(
        "themes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "asset_tags",
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id", "tag_id"),
    )
    op.create_table(
        "asset_themes",
        sa.Column("asset_id", sa.BigInteger(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["theme_id"], ["themes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id", "theme_id"),
    )
    op.create_table(
        "note_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "version", name="uq_note_versions_note_id_version"),
    )
    op.create_index("ix_note_versions_note_id", "note_versions", ["note_id"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("market", sa.String(length=30), nullable=True),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_entry_min", sa.Numeric(20, 6), nullable=True),
        sa.Column("target_entry_max", sa.Numeric(20, 6), nullable=True),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("catalyst", sa.Text(), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("owned_asset_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owned_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_watchlist_items_symbol"),
    )
    op.create_index("ix_watchlist_items_status_priority", "watchlist_items", ["status", "priority"])
    op.create_table(
        "watchlist_target_alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("watchlist_item_id", sa.BigInteger(), nullable=False),
        sa.Column("trigger_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("target_entry_max", sa.Numeric(20, 6), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("telegram_delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["watchlist_item_id"], ["watchlist_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_watchlist_target_alerts_triggered_at", "watchlist_target_alerts", ["triggered_at"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_target_alerts_triggered_at", table_name="watchlist_target_alerts")
    op.drop_table("watchlist_target_alerts")
    op.drop_index("ix_watchlist_items_status_priority", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_index("ix_note_versions_note_id", table_name="note_versions")
    op.drop_table("note_versions")
    op.drop_table("asset_themes")
    op.drop_table("asset_tags")
    op.drop_table("themes")
    op.drop_column("activity_logs", "metadata")
    op.drop_column("notes", "deleted_at")
    op.drop_column("notes", "updated_at")
    op.drop_column("assets", "thesis_status")
    op.drop_column("assets", "sector")
