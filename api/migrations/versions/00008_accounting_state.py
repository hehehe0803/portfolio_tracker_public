"""
Durable accounting state tables.

Revision ID: accounting_state_001
Revises: intel_watchlist_001
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "accounting_state_001"
down_revision: str | None = "intel_watchlist_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


STATUS_CHECK = "status IN ('active', 'superseded', 'voided')"
DECISION_SOURCE_CHECK = (
    "decision_source IN ('manual', 'system', 'import', 'deterministic')"
)
CONFIDENCE_CHECK = (
    "confidence_state IN "
    "('trusted', 'warning', 'provisional', 'review_required', 'blocked')"
)
VOID_LIFECYCLE_CHECK = (
    "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
    "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))"
)


def _lifecycle_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("decision_source", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("supersedes_id", sa.BigInteger(), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by", sa.String(length=80), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.String(length=80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    ]


def _lifecycle_constraints(table_name: str) -> list[sa.CheckConstraint]:
    constraint_prefix = (
        "acct_cashflow"
        if table_name == "accounting_external_cashflow_classifications"
        else table_name
    )
    return [
        sa.CheckConstraint(STATUS_CHECK, name=f"ck_{constraint_prefix}_status"),
        sa.CheckConstraint(
            DECISION_SOURCE_CHECK,
            name=f"ck_{constraint_prefix}_decision_source",
        ),
        sa.CheckConstraint(
            CONFIDENCE_CHECK,
            name=f"ck_{constraint_prefix}_confidence_state",
        ),
        sa.CheckConstraint(
            VOID_LIFECYCLE_CHECK,
            name=f"ck_{constraint_prefix}_void_lifecycle",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "accounting_evidence_claims",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("evidence_key", sa.String(length=128), nullable=False),
        sa.Column("source_table", sa.String(length=80), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("claim_role", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_key", name="uq_accounting_evidence_claims_key"),
        sa.CheckConstraint(
            "source_table IN ('accounting_transfer_links', "
            "'accounting_external_cashflow_classifications')",
            name="ck_accounting_evidence_claims_source_table",
        ),
        sa.CheckConstraint(
            "claim_role IN ('transfer_from', 'transfer_to', 'cashflow')",
            name="ck_accounting_evidence_claims_role",
        ),
    )
    op.create_index(
        "ix_accounting_evidence_claims_source",
        "accounting_evidence_claims",
        ["source_table", "source_id"],
    )

    op.create_table(
        "accounting_transfer_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("link_group_key", sa.String(length=128), nullable=False),
        sa.Column("from_evidence", sa.JSON(), nullable=False),
        sa.Column("to_evidence", sa.JSON(), nullable=False),
        sa.Column("from_evidence_key", sa.String(length=128), nullable=False),
        sa.Column("to_evidence_key", sa.String(length=128), nullable=False),
        sa.Column("asset_symbol", sa.String(length=20), nullable=False),
        sa.Column("from_quantity", sa.Numeric(30, 10), nullable=False),
        sa.Column("to_quantity", sa.Numeric(30, 10), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(30, 10), nullable=False),
        sa.Column("fee_quantity", sa.Numeric(30, 10), nullable=True),
        sa.Column("fee_asset_symbol", sa.String(length=20), nullable=True),
        sa.Column("amount_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("from_source", sa.String(length=50), nullable=False),
        sa.Column("to_source", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence_state", sa.String(length=30), nullable=False),
        sa.Column("review_task_id", sa.String(length=100), nullable=True),
        *_lifecycle_columns(),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["accounting_transfer_links.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        *_lifecycle_constraints("accounting_transfer_links"),
        sa.CheckConstraint(
            "from_quantity > 0 AND to_quantity > 0 AND quantity_delta >= 0",
            name="ck_accounting_transfer_links_quantity_sanity",
        ),
        sa.CheckConstraint(
            "fee_quantity IS NULL OR fee_quantity >= 0",
            name="ck_accounting_transfer_links_fee_sanity",
        ),
        sa.CheckConstraint(
            "amount_usd IS NULL OR amount_usd >= 0",
            name="ck_accounting_transfer_links_amount_sanity",
        ),
        sa.CheckConstraint(
            "from_evidence_key <> to_evidence_key",
            name="ck_accounting_transfer_links_distinct_evidence",
        ),
    )
    op.create_index(
        "ix_accounting_transfer_links_occurred_at",
        "accounting_transfer_links",
        ["occurred_at"],
    )
    op.create_index(
        "ix_accounting_transfer_links_sources",
        "accounting_transfer_links",
        ["from_source", "to_source"],
    )
    op.create_index(
        "uq_accounting_transfer_links_active_group",
        "accounting_transfer_links",
        ["link_group_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_accounting_transfer_links_active_from_evidence",
        "accounting_transfer_links",
        ["from_evidence_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_accounting_transfer_links_active_to_evidence",
        "accounting_transfer_links",
        ["to_evidence_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "accounting_external_cashflow_classifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("classification_key", sa.String(length=128), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_key", sa.String(length=128), nullable=False),
        sa.Column("cashflow_type", sa.String(length=40), nullable=False),
        sa.Column("movement_type", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("asset_symbol", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 10), nullable=False),
        sa.Column("amount_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capital_effect_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("confidence_state", sa.String(length=30), nullable=False),
        sa.Column("materiality_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("review_task_id", sa.String(length=100), nullable=True),
        *_lifecycle_columns(),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["accounting_external_cashflow_classifications.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        *_lifecycle_constraints("accounting_external_cashflow_classifications"),
        sa.CheckConstraint(
            "cashflow_type IN "
            "('external_deposit', 'external_withdrawal', 'not_external_cashflow')",
            name="ck_acct_cashflow_cashflow_type",
        ),
        sa.CheckConstraint(
            "movement_type IN "
            "('external_cashflow', 'internal_movement', 'trade_allocation')",
            name="ck_acct_cashflow_movement_type",
        ),
        sa.CheckConstraint(
            "((cashflow_type = 'external_deposit' AND "
            "(capital_effect_usd IS NULL OR capital_effect_usd >= 0)) OR "
            "(cashflow_type = 'external_withdrawal' AND "
            "(capital_effect_usd IS NULL OR capital_effect_usd <= 0)) OR "
            "(cashflow_type = 'not_external_cashflow' AND "
            "(capital_effect_usd IS NULL OR capital_effect_usd = 0)))",
            name="ck_acct_cashflow_capital_effect",
        ),
        sa.CheckConstraint(
            "((cashflow_type IN ('external_deposit', 'external_withdrawal') "
            "AND movement_type = 'external_cashflow') OR "
            "(cashflow_type = 'not_external_cashflow' "
            "AND movement_type <> 'external_cashflow'))",
            name="ck_acct_cashflow_type_movement_pair",
        ),
    )
    op.create_index(
        "ix_acct_cashflow_occurred_at",
        "accounting_external_cashflow_classifications",
        ["occurred_at"],
    )
    op.create_index(
        "ix_acct_cashflow_source",
        "accounting_external_cashflow_classifications",
        ["source"],
    )
    op.create_index(
        "uq_acct_cashflow_active_key",
        "accounting_external_cashflow_classifications",
        ["classification_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_acct_cashflow_active_evidence",
        "accounting_external_cashflow_classifications",
        ["evidence_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION refresh_accounting_evidence_claims()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                DELETE FROM accounting_evidence_claims
                WHERE source_table = TG_TABLE_NAME AND source_id = OLD.id;
                RETURN OLD;
            END IF;

            DELETE FROM accounting_evidence_claims
            WHERE source_table = TG_TABLE_NAME AND source_id = NEW.id;

            IF NEW.status = 'active' THEN
                IF TG_TABLE_NAME = 'accounting_transfer_links' THEN
                    INSERT INTO accounting_evidence_claims (
                        evidence_key,
                        source_table,
                        source_id,
                        claim_role,
                        created_at
                    )
                    VALUES
                        (
                            NEW.from_evidence_key,
                            TG_TABLE_NAME,
                            NEW.id,
                            'transfer_from',
                            now()
                        ),
                        (
                            NEW.to_evidence_key,
                            TG_TABLE_NAME,
                            NEW.id,
                            'transfer_to',
                            now()
                        );
                ELSIF TG_TABLE_NAME =
                    'accounting_external_cashflow_classifications'
                THEN
                    INSERT INTO accounting_evidence_claims (
                        evidence_key,
                        source_table,
                        source_id,
                        claim_role,
                        created_at
                    )
                    VALUES (
                        NEW.evidence_key,
                        TG_TABLE_NAME,
                        NEW.id,
                        'cashflow',
                        now()
                    );
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_accounting_transfer_links_evidence_claims
        AFTER INSERT OR UPDATE OR DELETE ON accounting_transfer_links
        FOR EACH ROW EXECUTE FUNCTION refresh_accounting_evidence_claims()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_acct_cashflow_evidence_claims
        AFTER INSERT OR UPDATE OR DELETE
        ON accounting_external_cashflow_classifications
        FOR EACH ROW EXECUTE FUNCTION refresh_accounting_evidence_claims()
        """
    )

    op.create_table(
        "accounting_import_approvals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("approval_key", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_account_id", sa.String(length=120), nullable=True),
        sa.Column("import_scope_id", sa.String(length=160), nullable=False),
        sa.Column("source_fingerprints", sa.JSON(), nullable=False),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_scope", sa.JSON(), nullable=False),
        sa.Column("control_totals", sa.JSON(), nullable=True),
        sa.Column("confidence_state", sa.String(length=30), nullable=False),
        sa.Column("review_task_id", sa.String(length=100), nullable=True),
        *_lifecycle_columns(),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["accounting_import_approvals.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        *_lifecycle_constraints("accounting_import_approvals"),
        sa.CheckConstraint(
            "coverage_start IS NULL OR coverage_end IS NULL OR "
            "coverage_start <= coverage_end",
            name="ck_accounting_import_approvals_coverage_order",
        ),
    )
    op.create_index(
        "ix_accounting_import_approvals_source_scope",
        "accounting_import_approvals",
        ["source", "import_scope_id"],
    )
    op.create_index(
        "ix_accounting_import_approvals_coverage",
        "accounting_import_approvals",
        ["coverage_start", "coverage_end"],
    )
    op.create_index(
        "uq_accounting_import_approvals_active_key",
        "accounting_import_approvals",
        ["approval_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "accounting_cost_basis_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("basis_key", sa.String(length=160), nullable=False),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("asset_symbol", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("source_account_id", sa.String(length=120), nullable=True),
        sa.Column("basis_scope", sa.String(length=40), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("quantity", sa.Numeric(30, 10), nullable=True),
        sa.Column("cost_basis_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("unit_cost_usd", sa.Numeric(20, 6), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("basis_method", sa.String(length=40), nullable=True),
        sa.Column("confidence_state", sa.String(length=30), nullable=False),
        sa.Column("affected_metric_scopes", sa.JSON(), nullable=False),
        sa.Column("review_task_id", sa.String(length=100), nullable=True),
        *_lifecycle_columns(),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["accounting_cost_basis_decisions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        *_lifecycle_constraints("accounting_cost_basis_decisions"),
        sa.CheckConstraint(
            "decision_type IN ('manual_cost_basis', 'unknown_cost_basis')",
            name="ck_accounting_cost_basis_decisions_decision_type",
        ),
        sa.CheckConstraint(
            "basis_scope IN ('lot', 'position', 'asset_source', 'asset_global')",
            name="ck_accounting_cost_basis_decisions_basis_scope",
        ),
        sa.CheckConstraint(
            "decision_type <> 'manual_cost_basis' OR "
            "cost_basis_usd IS NOT NULL OR "
            "(quantity IS NOT NULL AND unit_cost_usd IS NOT NULL)",
            name="ck_accounting_cost_basis_decisions_manual_value",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_accounting_cost_basis_decisions_quantity_positive",
        ),
        sa.CheckConstraint(
            "cost_basis_usd IS NULL OR cost_basis_usd >= 0",
            name="ck_accounting_cost_basis_decisions_total_nonnegative",
        ),
        sa.CheckConstraint(
            "unit_cost_usd IS NULL OR unit_cost_usd >= 0",
            name="ck_accounting_cost_basis_decisions_unit_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_basis_usd IS NULL OR quantity IS NULL OR unit_cost_usd IS NULL OR "
            "cost_basis_usd = round(quantity * unit_cost_usd, 6)",
            name="ck_accounting_cost_basis_decisions_value_consistent",
        ),
        sa.CheckConstraint(
            "decision_type <> 'unknown_cost_basis' OR confidence_state <> 'trusted'",
            name="ck_accounting_cost_basis_decisions_unknown_not_trusted",
        ),
    )
    op.create_index(
        "ix_accounting_cost_basis_decisions_asset_effective_at",
        "accounting_cost_basis_decisions",
        ["asset_symbol", "effective_at"],
    )
    op.create_index(
        "uq_accounting_cost_basis_decisions_active_key",
        "accounting_cost_basis_decisions",
        ["basis_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_acct_cashflow_evidence_claims "
        "ON accounting_external_cashflow_classifications"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_accounting_transfer_links_evidence_claims "
        "ON accounting_transfer_links"
    )
    op.execute("DROP FUNCTION IF EXISTS refresh_accounting_evidence_claims()")

    op.drop_index(
        "uq_accounting_cost_basis_decisions_active_key",
        table_name="accounting_cost_basis_decisions",
    )
    op.drop_index(
        "ix_accounting_cost_basis_decisions_asset_effective_at",
        table_name="accounting_cost_basis_decisions",
    )
    op.drop_table("accounting_cost_basis_decisions")

    op.drop_index(
        "uq_accounting_import_approvals_active_key",
        table_name="accounting_import_approvals",
    )
    op.drop_index(
        "ix_accounting_import_approvals_coverage",
        table_name="accounting_import_approvals",
    )
    op.drop_index(
        "ix_accounting_import_approvals_source_scope",
        table_name="accounting_import_approvals",
    )
    op.drop_table("accounting_import_approvals")

    op.drop_index(
        "uq_acct_cashflow_active_evidence",
        table_name="accounting_external_cashflow_classifications",
    )
    op.drop_index(
        "uq_acct_cashflow_active_key",
        table_name="accounting_external_cashflow_classifications",
    )
    op.drop_index(
        "ix_acct_cashflow_source",
        table_name="accounting_external_cashflow_classifications",
    )
    op.drop_index(
        "ix_acct_cashflow_occurred_at",
        table_name="accounting_external_cashflow_classifications",
    )
    op.drop_table("accounting_external_cashflow_classifications")

    op.drop_index(
        "uq_accounting_transfer_links_active_to_evidence",
        table_name="accounting_transfer_links",
    )
    op.drop_index(
        "uq_accounting_transfer_links_active_from_evidence",
        table_name="accounting_transfer_links",
    )
    op.drop_index(
        "uq_accounting_transfer_links_active_group",
        table_name="accounting_transfer_links",
    )
    op.drop_index(
        "ix_accounting_transfer_links_sources",
        table_name="accounting_transfer_links",
    )
    op.drop_index(
        "ix_accounting_transfer_links_occurred_at",
        table_name="accounting_transfer_links",
    )
    op.drop_table("accounting_transfer_links")

    op.drop_index(
        "ix_accounting_evidence_claims_source",
        table_name="accounting_evidence_claims",
    )
    op.drop_table("accounting_evidence_claims")
