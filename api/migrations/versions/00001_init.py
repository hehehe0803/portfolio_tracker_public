"""
Initial schema: users, institutions, transactions, import_artifacts,
alert_rules, alert_events.

Revision ID: init
Revises:
Create Date: 2026-03-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("totp_secret", sa.String(64), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("telegram_chat_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "institutions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("api_secret", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "import_artifacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("institution", sa.String(50), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("parsed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("committed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("parse_preview", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("institution", sa.String(50), nullable=False),
        sa.Column("tx_type", sa.String(50), nullable=False),
        sa.Column("asset_symbol", sa.String(20), nullable=False),
        sa.Column(
            "asset_type", sa.String(20), nullable=False, server_default="unknown"
        ),
        sa.Column("quantity", sa.Numeric(30, 10), nullable=False),
        sa.Column("price_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("total_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("fee", sa.Numeric(20, 10), nullable=False, server_default="0"),
        sa.Column("fee_currency", sa.String(20), nullable=False, server_default="USD"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("import_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["import_artifacts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint", name="uq_transactions_fingerprint"),
    )
    op.create_index("ix_transactions_asset_symbol", "transactions", ["asset_symbol"])
    op.create_index("ix_transactions_timestamp", "transactions", ["timestamp"])
    op.create_index("ix_transactions_institution", "transactions", ["institution"])

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_symbol", sa.String(20), nullable=False),
        sa.Column("condition", sa.String(30), nullable=False),
        sa.Column("threshold", sa.Numeric(10, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "telegram_delivered", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_events_triggered_at", "alert_events", ["triggered_at"])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
    op.drop_table("transactions")
    op.drop_table("import_artifacts")
    op.drop_table("institutions")
    op.drop_table("users")
