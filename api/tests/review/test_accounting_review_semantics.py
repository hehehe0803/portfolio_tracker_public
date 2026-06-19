# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.db.models import (
    AccountingCostBasisDecision,
    AccountingEvidenceClaim,
    AccountingExternalCashflowClassification,
    AccountingImportApproval,
    AccountingReconciliationTask,
    AccountingTransferLink,
    ActivityLog,
    User,
)
from app.services.accounting_review import (
    AccountingReviewDecisionConflict,
    AccountingReviewDecisionRequest,
    AccountingReviewError,
    InternalTransferDecision,
    ManualCostBasisDecision,
    approve_accounting_review_decision,
    list_open_accounting_review_tasks,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.tests.db.test_schema_alignment import _run_alembic, temporary_database_url

NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


@pytest.fixture()
def migrated_database_url() -> str:
    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url)
        yield database_url


@pytest.fixture()
async def session_factory(migrated_database_url: str):
    engine = create_async_engine(migrated_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            User(
                id=1,
                username="accounting-review-tester",
                password_hash="test",  # noqa: S106 - inert test fixture hash
            )
        )
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


def _task(
    *,
    task_id: str = "task_unknown_outgoing_transfer_abc",
    task_key: str = "task:unknown_outgoing_transfer:binance-usdt-withdrawal",
    task_type: str = "unknown_outgoing_transfer",
    source: str = "binance",
    asset_symbol: str = "USDT",
    quantity: Decimal | None = Decimal("100"),
    amount_usd: Decimal | None = Decimal("100"),
    evidence_key: str = "binance-usdt-withdrawal",
    candidate_actions: list[dict] | None = None,
) -> AccountingReconciliationTask:
    return AccountingReconciliationTask(
        task_id=task_id,
        task_key=task_key,
        task_type=task_type,
        status="open",
        severity="review_required",
        source=source,
        asset_symbol=asset_symbol,
        quantity=quantity,
        amount_usd=amount_usd,
        occurred_at=NOW,
        evidence={
            "source_evidence_key": evidence_key,
            "candidate_evidence_keys": ["hyperliquid-usdt-deposit"],
            "reasons": ["unknown_outgoing_crypto"],
        },
        candidate_actions=candidate_actions
        or [
            {"action": "internal_transfer", "effect": "capital_effect_usd=0"},
            {"action": "personal_withdrawal", "effect": "capital_effect_usd<0"},
        ],
        affected_metric_scopes=[
            "gross_withdrawals",
            "net_capital",
            "lifetime_pnl",
        ],
        created_by="system",
    )


async def test_lists_open_accounting_tasks_without_investment_review_language(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(_task())

        queue = await list_open_accounting_review_tasks(session)

    assert queue.review_type == "accounting"
    assert queue.allowed_actions == [
        "internal_transfer",
        "personal_withdrawal",
        "import_approval",
        "manual_cost_basis",
        "unknown_cost_basis",
        "unknown",
    ]
    assert len(queue.tasks) == 1
    assert queue.tasks[0].task_id == "task_unknown_outgoing_transfer_abc"
    assert queue.tasks[0].candidate_actions[0]["action"] == "internal_transfer"


async def test_internal_transfer_approval_writes_link_then_audit_then_resolves_task(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(_task())
            result = await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_unknown_outgoing_transfer_abc",
                    action="internal_transfer",
                    idempotency_key="approve-transfer-1",
                    rationale="Hyperliquid deposit is the destination.",
                    internal_transfer=InternalTransferDecision(
                        to_source="hyperliquid",
                        to_evidence_key="hyperliquid-usdt-deposit",
                        to_quantity=Decimal("99.5"),
                        fee_quantity=Decimal("0.5"),
                        fee_asset_symbol="USDT",
                    ),
                ),
                user_id=1,
                username="local_user",
            )

        transfer = await session.get(AccountingTransferLink, result.decision_id)
        task = await session.scalar(
            select(AccountingReconciliationTask).where(
                AccountingReconciliationTask.task_id
                == "task_unknown_outgoing_transfer_abc"
            )
        )
        audit_log = await session.scalar(
            select(ActivityLog).where(ActivityLog.source == "accounting_review")
        )

    assert result.decision_type == "accounting_transfer_link"
    assert transfer is not None
    assert transfer.review_task_id == "task_unknown_outgoing_transfer_abc"
    assert transfer.decision_reason == "manual_internal_transfer"
    assert transfer.decision_source == "manual"
    claims = (
        (
            await session.execute(
                select(AccountingEvidenceClaim).order_by(
                    AccountingEvidenceClaim.claim_role
                )
            )
        )
        .scalars()
        .all()
    )
    assert task is not None
    assert task.status == "resolved"
    assert task.resolved_by_decision_type == "accounting_transfer_link"
    assert task.resolved_by_decision_id == transfer.id
    assert [(claim.evidence_key, claim.claim_role) for claim in claims] == [
        ("binance-usdt-withdrawal", "transfer_from"),
        ("hyperliquid-usdt-deposit", "transfer_to"),
    ]
    assert audit_log is not None
    assert audit_log.event_metadata["decision_type"] == "accounting_transfer_link"
    assert audit_log.event_metadata["decision_id"] == transfer.id
    assert audit_log.event_metadata["request_fingerprint"]


async def test_personal_withdrawal_approval_writes_cashflow_and_is_replay_safe(
    session_factory,
) -> None:
    request = AccountingReviewDecisionRequest(
        task_id="task_unknown_outgoing_transfer_abc",
        action="personal_withdrawal",
        idempotency_key="withdrawal-approval-1",
        rationale="Confirmed personal wallet withdrawal.",
    )

    async with session_factory() as session:
        async with session.begin():
            session.add(_task())
            first = await approve_accounting_review_decision(
                session,
                request,
                user_id=1,
                username="local_user",
            )
            replay = await approve_accounting_review_decision(
                session,
                request,
                user_id=1,
                username="local_user",
            )

        cashflows = (
            (await session.execute(select(AccountingExternalCashflowClassification)))
            .scalars()
            .all()
        )
        audit_logs = (
            (await session.execute(select(ActivityLog).order_by(ActivityLog.id)))
            .scalars()
            .all()
        )

    assert first.decision_id == replay.decision_id
    assert replay.replayed is True
    assert len(cashflows) == 1
    assert cashflows[0].cashflow_type == "external_withdrawal"
    assert cashflows[0].capital_effect_usd == Decimal("-100.000000")
    assert len(audit_logs) == 1


async def test_replay_with_same_key_and_different_payload_is_rejected(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(_task())
            await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_unknown_outgoing_transfer_abc",
                    action="personal_withdrawal",
                    idempotency_key="same-payload-key",
                    rationale="Confirmed personal wallet withdrawal.",
                ),
                user_id=1,
                username="local_user",
            )

            with pytest.raises(AccountingReviewDecisionConflict):
                await approve_accounting_review_decision(
                    session,
                    AccountingReviewDecisionRequest(
                        task_id="task_unknown_outgoing_transfer_abc",
                        action="personal_withdrawal",
                        idempotency_key="same-payload-key",
                        rationale="Different rationale changes the payload.",
                    ),
                    user_id=1,
                    username="local_user",
                )


async def test_unknown_outgoing_can_be_deferred_without_capital_effect(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(_task())
            result = await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_unknown_outgoing_transfer_abc",
                    action="unknown",
                    idempotency_key="defer-unknown-outgoing",
                    rationale="Need brokerage support before classifying.",
                ),
                user_id=1,
                username="local_user",
            )

        cashflow = await session.get(
            AccountingExternalCashflowClassification,
            result.decision_id,
        )

    assert result.decision_type == "accounting_external_cashflow_classification"
    assert cashflow is not None
    assert cashflow.cashflow_type == "not_external_cashflow"
    assert cashflow.movement_type == "internal_movement"
    assert cashflow.capital_effect_usd == Decimal("0.000000")
    assert cashflow.confidence_state == "blocked"


async def test_import_approval_persists_canonical_import_state(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            task = _task(
                task_id="task_import_gap",
                task_key="task:import_approval:binance-2026-05",
                task_type="import_approval",
                evidence_key="binance-import-2026-05",
                candidate_actions=[
                    {"action": "import_approval", "effect": "trust_import_scope"}
                ],
            )
            task.evidence.update(
                {
                    "source_fingerprints": ["binance-export-2026-05"],
                    "approved_scope": ["transactions"],
                    "import_scope_id": "binance-2026-05",
                    "coverage_start": "2026-05-01T00:00:00+00:00",
                    "coverage_end": "2026-05-31T23:59:59+00:00",
                }
            )
            session.add(task)
            result = await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_import_gap",
                    action="import_approval",
                    idempotency_key="import-approval-1",
                    rationale="May Binance export reconciles to control totals.",
                ),
                user_id=1,
                username="local_user",
            )

        approval = await session.get(AccountingImportApproval, result.decision_id)

    assert result.decision_type == "accounting_import_approval"
    assert approval is not None
    assert approval.review_task_id == "task_import_gap"
    assert approval.source_fingerprints == ["binance-export-2026-05"]
    assert approval.approved_scope == ["transactions"]
    assert approval.import_scope_id == "binance-2026-05"
    assert approval.coverage_start == datetime(2026, 5, 1, tzinfo=UTC)
    assert approval.coverage_end == datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)
    assert approval.confidence_state == "trusted"


async def test_import_approval_rejects_weak_task_evidence(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                _task(
                    task_id="task_import_gap",
                    task_key="task:import_approval:binance-2026-05",
                    task_type="import_approval",
                    evidence_key="binance-import-2026-05",
                    candidate_actions=[
                        {"action": "import_approval", "effect": "trust_import_scope"}
                    ],
                )
            )

            with pytest.raises(AccountingReviewError):
                await approve_accounting_review_decision(
                    session,
                    AccountingReviewDecisionRequest(
                        task_id="task_import_gap",
                        action="import_approval",
                        idempotency_key="weak-import-approval",
                    ),
                    user_id=1,
                    username="local_user",
                )


async def test_manual_and_unknown_cost_basis_decisions_resolve_missing_basis_tasks(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    _task(
                        task_id="task_sol_basis",
                        task_key="task:missing_cost_basis:sol",
                        task_type="missing_cost_basis",
                        asset_symbol="SOL",
                        quantity=Decimal("5"),
                        amount_usd=None,
                        evidence_key="sol-lot",
                        candidate_actions=[
                            {"action": "manual_cost_basis", "effect": "trust_basis"}
                        ],
                    ),
                    _task(
                        task_id="task_arb_basis_unknown",
                        task_key="task:missing_cost_basis:arb",
                        task_type="missing_cost_basis",
                        asset_symbol="ARB",
                        quantity=Decimal("100"),
                        amount_usd=None,
                        evidence_key="arb-lot",
                        candidate_actions=[
                            {
                                "action": "unknown_cost_basis",
                                "effect": "keep_basis_blocked",
                            }
                        ],
                    ),
                ]
            )
            manual = await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_sol_basis",
                    action="manual_cost_basis",
                    idempotency_key="manual-basis-1",
                    cost_basis=ManualCostBasisDecision(
                        quantity=Decimal("5"),
                        cost_basis_usd=Decimal("750"),
                        basis_method="manual_average_cost",
                    ),
                ),
                user_id=1,
                username="local_user",
            )
            unknown = await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_arb_basis_unknown",
                    action="unknown_cost_basis",
                    idempotency_key="unknown-basis-1",
                    rationale="Source data is unavailable.",
                ),
                user_id=1,
                username="local_user",
            )

        manual_decision = await session.get(
            AccountingCostBasisDecision,
            manual.decision_id,
        )
        unknown_decision = await session.get(
            AccountingCostBasisDecision,
            unknown.decision_id,
        )

    assert manual_decision is not None
    assert manual_decision.decision_type == "manual_cost_basis"
    assert manual_decision.confidence_state == "trusted"
    assert manual_decision.cost_basis_usd == Decimal("750.000000")
    assert unknown_decision is not None
    assert unknown_decision.decision_type == "unknown_cost_basis"
    assert unknown_decision.confidence_state == "blocked"
    assert unknown_decision.cost_basis_usd is None
    assert unknown_decision.unit_cost_usd is None


async def test_manual_cost_basis_requires_a_basis_value(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                _task(
                    task_id="task_sol_basis",
                    task_key="task:missing_cost_basis:sol",
                    task_type="missing_cost_basis",
                    asset_symbol="SOL",
                    quantity=Decimal("5"),
                    amount_usd=None,
                    evidence_key="sol-lot",
                )
            )

            with pytest.raises(AccountingReviewError):
                await approve_accounting_review_decision(
                    session,
                    AccountingReviewDecisionRequest(
                        task_id="task_sol_basis",
                        action="manual_cost_basis",
                        idempotency_key="manual-basis-missing-value",
                        cost_basis=ManualCostBasisDecision(quantity=Decimal("5")),
                    ),
                    user_id=1,
                    username="local_user",
                )


@pytest.mark.parametrize(
    "cost_basis",
    [
        ManualCostBasisDecision(
            quantity=Decimal("5"),
            cost_basis_usd=Decimal("-1"),
        ),
        ManualCostBasisDecision(
            quantity=Decimal("5"),
            unit_cost_usd=Decimal("-1"),
        ),
        ManualCostBasisDecision(
            quantity=Decimal("5"),
            cost_basis_usd=Decimal("100"),
            unit_cost_usd=Decimal("10"),
        ),
    ],
)
async def test_manual_cost_basis_rejects_invalid_values(
    session_factory,
    cost_basis: ManualCostBasisDecision,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                _task(
                    task_id="task_sol_basis",
                    task_key="task:missing_cost_basis:sol",
                    task_type="missing_cost_basis",
                    asset_symbol="SOL",
                    quantity=Decimal("5"),
                    amount_usd=None,
                    evidence_key="sol-lot",
                )
            )

            with pytest.raises(AccountingReviewError):
                await approve_accounting_review_decision(
                    session,
                    AccountingReviewDecisionRequest(
                        task_id="task_sol_basis",
                        action="manual_cost_basis",
                        idempotency_key="manual-basis-invalid-value",
                        cost_basis=cost_basis,
                    ),
                    user_id=1,
                    username="local_user",
                )


async def test_replay_with_different_action_is_rejected(
    session_factory,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(_task())
            await approve_accounting_review_decision(
                session,
                AccountingReviewDecisionRequest(
                    task_id="task_unknown_outgoing_transfer_abc",
                    action="personal_withdrawal",
                    idempotency_key="same-key",
                ),
                user_id=1,
                username="local_user",
            )

            with pytest.raises(AccountingReviewDecisionConflict):
                await approve_accounting_review_decision(
                    session,
                    AccountingReviewDecisionRequest(
                        task_id="task_unknown_outgoing_transfer_abc",
                        action="internal_transfer",
                        idempotency_key="same-key",
                        internal_transfer=InternalTransferDecision(
                            to_source="hyperliquid",
                            to_evidence_key="hyperliquid-usdt-deposit",
                            to_quantity=Decimal("100"),
                        ),
                    ),
                    user_id=1,
                    username="local_user",
                )
