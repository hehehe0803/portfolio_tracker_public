"""Durable accounting state schema constraints."""

# ruff: noqa: S101
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from api.tests.db.test_schema_alignment import _run_alembic, temporary_database_url

NOW = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)


@pytest.fixture()
def migrated_database_url() -> str:
    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url)
        yield database_url


async def _execute(database_url: str, sql: str, params: Mapping[str, object]) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql), params)
    finally:
        await engine.dispose()


def _run(database_url: str, sql: str, params: Mapping[str, object]) -> None:
    asyncio.run(_execute(database_url, sql, params))


def _json(value: object) -> str:
    return json.dumps(value)


def _insert_transfer_link(
    database_url: str,
    *,
    link_group_key: str,
    from_evidence_key: str,
    to_evidence_key: str,
    status: str = "active",
    confidence_state: str = "trusted",
    decision_source: str = "manual",
    voided_at: datetime | None = None,
    voided_by: str | None = None,
    to_evidence: object | None = None,
    from_quantity: Decimal = Decimal("100"),
    to_quantity: Decimal = Decimal("100"),
    quantity_delta: Decimal = Decimal("0"),
    fee_quantity: Decimal | None = None,
    amount_usd: Decimal | None = None,
) -> None:
    _run(
        database_url,
        """
        INSERT INTO accounting_transfer_links (
            link_group_key,
            from_evidence,
            to_evidence,
            from_evidence_key,
            to_evidence_key,
            asset_symbol,
            from_quantity,
            to_quantity,
            quantity_delta,
            fee_quantity,
            amount_usd,
            from_source,
            to_source,
            occurred_at,
            confidence_state,
            created_at,
            created_by,
            decision_source,
            status,
            supersedes_id,
            voided_at,
            voided_by,
            decision_reason
        )
        VALUES (
            :link_group_key,
            CAST(:from_evidence AS JSON),
            CAST(:to_evidence AS JSON),
            :from_evidence_key,
            :to_evidence_key,
            'USDT',
            :from_quantity,
            :to_quantity,
            :quantity_delta,
            :fee_quantity,
            :amount_usd,
            'binance',
            'hyperliquid',
            :occurred_at,
            :confidence_state,
            :created_at,
            'local_user',
            :decision_source,
            :status,
            NULL,
            :voided_at,
            :voided_by,
            'manual_match'
        )
        """,
        {
            "link_group_key": link_group_key,
            "from_evidence": _json({"fingerprint": from_evidence_key}),
            "to_evidence": _json(
                to_evidence
                if to_evidence is not None
                else {"fingerprint": to_evidence_key}
            ),
            "from_evidence_key": from_evidence_key,
            "to_evidence_key": to_evidence_key,
            "from_quantity": from_quantity,
            "to_quantity": to_quantity,
            "quantity_delta": quantity_delta,
            "fee_quantity": fee_quantity,
            "amount_usd": amount_usd,
            "occurred_at": NOW,
            "confidence_state": confidence_state,
            "decision_source": decision_source,
            "created_at": NOW,
            "status": status,
            "voided_at": voided_at,
            "voided_by": voided_by,
        },
    )


def _insert_cashflow_classification(
    database_url: str,
    *,
    classification_key: str,
    evidence_key: str,
    cashflow_type: str = "external_deposit",
    movement_type: str = "external_cashflow",
    capital_effect_usd: Decimal | None = Decimal("100"),
    confidence_state: str = "trusted",
    status: str = "active",
) -> None:
    _run(
        database_url,
        """
        INSERT INTO accounting_external_cashflow_classifications (
            classification_key,
            evidence,
            evidence_key,
            cashflow_type,
            movement_type,
            source,
            asset_symbol,
            quantity,
            amount_usd,
            occurred_at,
            capital_effect_usd,
            confidence_state,
            created_at,
            created_by,
            decision_source,
            status,
            decision_reason
        )
        VALUES (
            :classification_key,
            CAST(:evidence AS JSON),
            :evidence_key,
            :cashflow_type,
            :movement_type,
            'xtb',
            'USD',
            :quantity,
            :amount_usd,
            :occurred_at,
            :capital_effect_usd,
            :confidence_state,
            :created_at,
            'local_user',
            'manual',
            :status,
            'manual_personal_withdrawal'
        )
        """,
        {
            "classification_key": classification_key,
            "evidence": _json({"fingerprint": evidence_key}),
            "evidence_key": evidence_key,
            "cashflow_type": cashflow_type,
            "movement_type": movement_type,
            "quantity": Decimal("100"),
            "amount_usd": Decimal("100"),
            "occurred_at": NOW,
            "capital_effect_usd": capital_effect_usd,
            "confidence_state": confidence_state,
            "status": status,
            "created_at": NOW,
        },
    )


def _insert_import_approval(
    database_url: str,
    *,
    approval_key: str,
    confidence_state: str = "trusted",
    coverage_start: datetime | None = NOW,
    coverage_end: datetime | None = NOW,
) -> None:
    _run(
        database_url,
        """
        INSERT INTO accounting_import_approvals (
            approval_key,
            source,
            import_scope_id,
            source_fingerprints,
            coverage_start,
            coverage_end,
            approved_scope,
            confidence_state,
            created_at,
            created_by,
            decision_source,
            status,
            decision_reason
        )
        VALUES (
            :approval_key,
            'xtb',
            'statement-2026-06',
            CAST(:source_fingerprints AS JSON),
            :coverage_start,
            :coverage_end,
            CAST(:approved_scope AS JSON),
            :confidence_state,
            :created_at,
            'local_user',
            'manual',
            'active',
            'manual_scope_approval'
        )
        """,
        {
            "approval_key": approval_key,
            "source_fingerprints": _json(["fp-1"]),
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "approved_scope": _json(["current_value"]),
            "confidence_state": confidence_state,
            "created_at": NOW,
        },
    )


def _insert_cost_basis_decision(
    database_url: str,
    *,
    basis_key: str,
    decision_type: str = "manual_cost_basis",
    basis_scope: str = "asset_global",
    confidence_state: str = "trusted",
    cost_basis_usd: Decimal | None = Decimal("1000"),
    quantity: Decimal | None = None,
    unit_cost_usd: Decimal | None = None,
) -> None:
    _run(
        database_url,
        """
        INSERT INTO accounting_cost_basis_decisions (
            basis_key,
            decision_type,
            asset_symbol,
            basis_scope,
            quantity,
            cost_basis_usd,
            unit_cost_usd,
            effective_at,
            confidence_state,
            affected_metric_scopes,
            created_at,
            created_by,
            decision_source,
            status,
            decision_reason
        )
        VALUES (
            :basis_key,
            :decision_type,
            'SOL',
            :basis_scope,
            :quantity,
            :cost_basis_usd,
            :unit_cost_usd,
            :effective_at,
            :confidence_state,
            CAST(:affected_metric_scopes AS JSON),
            :created_at,
            'local_user',
            'manual',
            'active',
            'manual_average_cost'
        )
        """,
        {
            "basis_key": basis_key,
            "decision_type": decision_type,
            "basis_scope": basis_scope,
            "quantity": quantity,
            "cost_basis_usd": cost_basis_usd,
            "unit_cost_usd": unit_cost_usd,
            "effective_at": NOW,
            "confidence_state": confidence_state,
            "affected_metric_scopes": _json(["asset_lifetime_pnl"]),
            "created_at": NOW,
        },
    )


def test_active_transfer_link_keys_are_unique(migrated_database_url: str) -> None:
    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:1",
        from_evidence_key="from:1",
        to_evidence_key="to:1",
    )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:1",
            from_evidence_key="from:2",
            to_evidence_key="to:2",
        )


def test_active_transfer_evidence_keys_are_unique(
    migrated_database_url: str,
) -> None:
    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:evidence:1",
        from_evidence_key="from:evidence:1",
        to_evidence_key="to:evidence:1",
    )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:evidence:2",
            from_evidence_key="from:evidence:1",
            to_evidence_key="to:evidence:2",
        )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:evidence:3",
            from_evidence_key="from:evidence:3",
            to_evidence_key="to:evidence:1",
        )


def test_active_evidence_claims_are_unique_across_transfer_sides_and_cashflows(
    migrated_database_url: str,
) -> None:
    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:claim:1",
        from_evidence_key="evidence:shared",
        to_evidence_key="evidence:destination",
    )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:claim:2",
            from_evidence_key="evidence:other",
            to_evidence_key="evidence:shared",
        )

    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key="cashflow:claim:1",
            evidence_key="evidence:shared",
        )

    _insert_cashflow_classification(
        migrated_database_url,
        classification_key="cashflow:claim:superseded",
        evidence_key="evidence:shared",
        status="superseded",
    )


def test_superseded_transfer_link_can_reuse_group_key(
    migrated_database_url: str,
) -> None:
    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:2",
        from_evidence_key="from:3",
        to_evidence_key="to:3",
    )
    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:2",
        from_evidence_key="from:4",
        to_evidence_key="to:4",
        status="superseded",
    )


def test_active_evidence_keys_are_unique(migrated_database_url: str) -> None:
    _insert_cashflow_classification(
        migrated_database_url,
        classification_key="cashflow:1",
        evidence_key="cashflow-evidence:1",
    )

    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key="cashflow:2",
            evidence_key="cashflow-evidence:1",
        )

    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key="cashflow:1",
            evidence_key="cashflow-evidence:2",
        )


def test_active_import_and_cost_basis_keys_are_unique(
    migrated_database_url: str,
) -> None:
    _insert_import_approval(migrated_database_url, approval_key="import:1")
    with pytest.raises(IntegrityError):
        _insert_import_approval(migrated_database_url, approval_key="import:1")

    _insert_cost_basis_decision(migrated_database_url, basis_key="basis:1")
    with pytest.raises(IntegrityError):
        _insert_cost_basis_decision(migrated_database_url, basis_key="basis:1")


def test_bounded_vocabularies_are_constrained(migrated_database_url: str) -> None:
    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:bad-status",
            from_evidence_key="from:bad-status",
            to_evidence_key="to:bad-status",
            status="Active",
        )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:bad-source",
            from_evidence_key="from:bad-source",
            to_evidence_key="to:bad-source",
            decision_source="maybe",
        )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:bad-confidence",
            from_evidence_key="from:bad-confidence",
            to_evidence_key="to:bad-confidence",
            confidence_state="certain",
        )

    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key="cashflow:bad-type",
            evidence_key="evidence:bad-type",
            cashflow_type="deposit_guess",
        )

    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key="cashflow:bad-movement",
            evidence_key="evidence:bad-movement",
            movement_type="sign_inferred",
        )

    with pytest.raises(IntegrityError):
        _insert_cost_basis_decision(
            migrated_database_url,
            basis_key="basis:bad-scope",
            basis_scope="wallet_guess",
        )


@pytest.mark.parametrize(
    ("cashflow_type", "capital_effect_usd"),
    [
        ("not_external_cashflow", Decimal("1")),
        ("external_deposit", Decimal("-1")),
        ("external_withdrawal", Decimal("1")),
    ],
)
def test_cashflow_capital_effect_sign_is_constrained(
    migrated_database_url: str,
    cashflow_type: str,
    capital_effect_usd: Decimal,
) -> None:
    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key=f"cashflow:{cashflow_type}:{capital_effect_usd}",
            evidence_key=f"evidence:{cashflow_type}:{capital_effect_usd}",
            cashflow_type=cashflow_type,
            capital_effect_usd=capital_effect_usd,
        )


@pytest.mark.parametrize(
    ("cashflow_type", "movement_type"),
    [
        ("external_deposit", "internal_movement"),
        ("external_withdrawal", "trade_allocation"),
        ("not_external_cashflow", "external_cashflow"),
    ],
)
def test_cashflow_type_and_movement_type_must_agree(
    migrated_database_url: str,
    cashflow_type: str,
    movement_type: str,
) -> None:
    with pytest.raises(IntegrityError):
        _insert_cashflow_classification(
            migrated_database_url,
            classification_key=f"cashflow:bad-pair:{cashflow_type}:{movement_type}",
            evidence_key=f"evidence:bad-pair:{cashflow_type}:{movement_type}",
            cashflow_type=cashflow_type,
            movement_type=movement_type,
            capital_effect_usd=(
                Decimal("-100")
                if cashflow_type == "external_withdrawal"
                else Decimal("0")
            ),
        )


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"from_quantity": Decimal("-1")},
        {"to_quantity": Decimal("0")},
        {"quantity_delta": Decimal("-1")},
        {"fee_quantity": Decimal("-1")},
        {"amount_usd": Decimal("-1")},
        {"from_evidence_key": "same-evidence", "to_evidence_key": "same-evidence"},
    ],
)
def test_transfer_numeric_sanity_is_constrained(
    migrated_database_url: str,
    kwargs: dict[str, object],
) -> None:
    params = {
        "link_group_key": f"transfer:sanity:{len(str(kwargs))}",
        "from_evidence_key": f"from:sanity:{len(str(kwargs))}",
        "to_evidence_key": f"to:sanity:{len(str(kwargs))}",
    }
    params.update(kwargs)

    with pytest.raises(IntegrityError):
        _insert_transfer_link(migrated_database_url, **params)


def test_void_lifecycle_requires_voided_status(migrated_database_url: str) -> None:
    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:voided-at",
            from_evidence_key="from:voided-at",
            to_evidence_key="to:voided-at",
            voided_at=NOW,
            voided_by="local_user",
        )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:voided-missing-fields",
            from_evidence_key="from:voided-missing-fields",
            to_evidence_key="to:voided-missing-fields",
            status="voided",
        )

    with pytest.raises(IntegrityError):
        _insert_transfer_link(
            migrated_database_url,
            link_group_key="transfer:voided-missing-by",
            from_evidence_key="from:voided-missing-by",
            to_evidence_key="to:voided-missing-by",
            status="voided",
            voided_at=NOW,
        )


def test_import_approval_coverage_order_is_constrained(
    migrated_database_url: str,
) -> None:
    with pytest.raises(IntegrityError):
        _insert_import_approval(
            migrated_database_url,
            approval_key="import:bad-coverage",
            coverage_start=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
            coverage_end=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        )


def test_cost_basis_decision_value_rules(migrated_database_url: str) -> None:
    with pytest.raises(IntegrityError):
        _insert_cost_basis_decision(
            migrated_database_url,
            basis_key="basis:missing-value",
            cost_basis_usd=None,
            quantity=None,
            unit_cost_usd=None,
        )

    _insert_cost_basis_decision(
        migrated_database_url,
        basis_key="basis:unknown",
        decision_type="unknown_cost_basis",
        confidence_state="blocked",
        cost_basis_usd=None,
    )

    with pytest.raises(IntegrityError):
        _insert_cost_basis_decision(
            migrated_database_url,
            basis_key="basis:unknown-trusted",
            decision_type="unknown_cost_basis",
            confidence_state="trusted",
            cost_basis_usd=None,
        )


@pytest.mark.parametrize(
    ("basis_key", "kwargs"),
    [
        ("basis:negative-total", {"cost_basis_usd": Decimal("-1")}),
        (
            "basis:negative-quantity",
            {
                "cost_basis_usd": None,
                "quantity": Decimal("-1"),
                "unit_cost_usd": Decimal("10"),
            },
        ),
        (
            "basis:negative-unit",
            {
                "cost_basis_usd": None,
                "quantity": Decimal("10"),
                "unit_cost_usd": Decimal("-1"),
            },
        ),
        (
            "basis:inconsistent-values",
            {
                "cost_basis_usd": Decimal("100"),
                "quantity": Decimal("3"),
                "unit_cost_usd": Decimal("10"),
            },
        ),
    ],
)
def test_cost_basis_decision_money_sanity_is_constrained(
    migrated_database_url: str,
    basis_key: str,
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError):
        _insert_cost_basis_decision(
            migrated_database_url,
            basis_key=basis_key,
            **kwargs,
        )


def test_live_schema_contract_includes_columns_constraints_and_partial_indexes(
    migrated_database_url: str,
) -> None:
    async def collect_schema() -> dict[str, object]:
        engine = create_async_engine(migrated_database_url)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text(
                        """
                        SELECT table_name, column_name, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                          AND table_name LIKE 'accounting_%'
                        ORDER BY table_name, ordinal_position
                        """
                    )
                )
                columns = {}
                for row in result:
                    columns.setdefault(row.table_name, {})[row.column_name] = (
                        row.is_nullable
                    )

                checks = await connection.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE connamespace = 'public'::regnamespace
                          AND contype = 'c'
                          AND conrelid::regclass::text LIKE 'accounting_%'
                        """
                    )
                )
                indexes = await connection.execute(
                    text(
                        """
                        SELECT indexname, indexdef
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename LIKE 'accounting_%'
                        """
                    )
                )
                return {
                    "columns": columns,
                    "checks": {row.conname for row in checks},
                    "indexes": {row.indexname: row.indexdef for row in indexes},
                }
        finally:
            await engine.dispose()

    schema = asyncio.run(collect_schema())

    assert {
        "accounting_transfer_links",
        "accounting_external_cashflow_classifications",
        "accounting_import_approvals",
        "accounting_cost_basis_decisions",
    } <= set(schema["columns"])
    assert {
        "id",
        "created_at",
        "created_by",
        "decision_source",
        "status",
        "decision_reason",
    } <= set(schema["columns"]["accounting_transfer_links"])
    assert schema["columns"]["accounting_transfer_links"]["created_at"] == "NO"
    assert schema["columns"]["accounting_transfer_links"]["voided_at"] == "YES"
    assert "ck_accounting_cost_basis_decisions_unknown_not_trusted" in schema["checks"]
    assert "ck_acct_cashflow_capital_effect" in schema["checks"]
    transfer_predicate = schema["indexes"]["uq_accounting_transfer_links_active_group"]
    cashflow_predicate = schema["indexes"]["uq_acct_cashflow_active_evidence"]
    assert "WHERE" in transfer_predicate
    assert "status" in transfer_predicate
    assert "'active'" in transfer_predicate
    assert "WHERE" in cashflow_predicate
    assert "status" in cashflow_predicate
    assert "'active'" in cashflow_predicate


def test_many_leg_transfer_overlap_is_not_claimed_as_prevented(
    migrated_database_url: str,
) -> None:
    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:many-leg:1",
        from_evidence_key="from:many-leg:1",
        to_evidence_key="to-group:a-b",
        to_evidence=[{"fingerprint": "a"}, {"fingerprint": "b"}],
    )

    _insert_transfer_link(
        migrated_database_url,
        link_group_key="transfer:many-leg:2",
        from_evidence_key="from:many-leg:2",
        to_evidence_key="to-group:b-c",
        to_evidence=[{"fingerprint": "b"}, {"fingerprint": "c"}],
    )
