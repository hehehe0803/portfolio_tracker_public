"""
Durable accounting reconciliation tasks.

Revision ID: accounting_tasks_001
Revises: accounting_state_001
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "accounting_tasks_001"
down_revision: str | None = "accounting_state_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounting_reconciliation_tasks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("task_key", sa.String(length=180), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("asset_symbol", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 10), nullable=True),
        sa.Column("amount_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("candidate_actions", sa.JSON(), nullable=False),
        sa.Column("affected_metric_scopes", sa.JSON(), nullable=False),
        sa.Column("resolved_by_decision_type", sa.String(length=80), nullable=True),
        sa.Column("resolved_by_decision_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=80), nullable=True),
        sa.Column("supersedes_id", sa.BigInteger(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by", sa.String(length=80), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["accounting_reconciliation_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'superseded', 'voided')",
            name="ck_accounting_reconciliation_tasks_status",
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'provisional', 'review_required', 'blocked')",
            name="ck_accounting_reconciliation_tasks_severity",
        ),
        sa.CheckConstraint(
            "task_type IN ('unknown_outgoing_transfer', 'missing_cost_basis', "
            "'import_approval', 'source_coverage_gap')",
            name="ck_accounting_reconciliation_tasks_task_type",
        ),
        sa.CheckConstraint(
            "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
            "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))",
            name="ck_accounting_reconciliation_tasks_void_lifecycle",
        ),
        sa.CheckConstraint(
            "((status = 'resolved' AND resolved_at IS NOT NULL "
            "AND resolved_by IS NOT NULL "
            "AND resolved_by_decision_type IS NOT NULL "
            "AND resolved_by_decision_id IS NOT NULL) OR "
            "(status <> 'resolved' AND resolved_at IS NULL "
            "AND resolved_by IS NULL "
            "AND resolved_by_decision_type IS NULL "
            "AND resolved_by_decision_id IS NULL))",
            name="ck_accounting_reconciliation_tasks_resolution_lifecycle",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_accounting_reconciliation_tasks_quantity_sanity",
        ),
        sa.CheckConstraint(
            "amount_usd IS NULL OR amount_usd >= 0",
            name="ck_accounting_reconciliation_tasks_amount_sanity",
        ),
        sa.CheckConstraint(
            "resolved_by_decision_type IS NULL OR "
            "resolved_by_decision_type IN ("
            "'accounting_transfer_link', "
            "'accounting_external_cashflow_classification', "
            "'accounting_import_approval', "
            "'accounting_cost_basis_decision')",
            name="ck_accounting_reconciliation_tasks_decision_reference",
        ),
    )
    op.create_index(
        "ix_accounting_reconciliation_tasks_source_occurred_at",
        "accounting_reconciliation_tasks",
        ["source", "occurred_at"],
    )
    op.create_index(
        "ix_accounting_reconciliation_tasks_status_severity",
        "accounting_reconciliation_tasks",
        ["status", "severity"],
    )
    op.create_index(
        "uq_accounting_reconciliation_tasks_task_id",
        "accounting_reconciliation_tasks",
        ["task_id"],
        unique=True,
    )
    op.create_index(
        "uq_accounting_reconciliation_tasks_active_key",
        "accounting_reconciliation_tasks",
        ["task_key"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_accounting_reconciliation_tasks_active_key",
        table_name="accounting_reconciliation_tasks",
    )
    op.drop_index(
        "uq_accounting_reconciliation_tasks_task_id",
        table_name="accounting_reconciliation_tasks",
    )
    op.drop_index(
        "ix_accounting_reconciliation_tasks_status_severity",
        table_name="accounting_reconciliation_tasks",
    )
    op.drop_index(
        "ix_accounting_reconciliation_tasks_source_occurred_at",
        table_name="accounting_reconciliation_tasks",
    )
    op.drop_table("accounting_reconciliation_tasks")
