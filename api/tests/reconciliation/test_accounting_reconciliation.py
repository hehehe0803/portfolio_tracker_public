# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.db.models import (
    AccountingCostBasisDecision,
    AccountingExternalCashflowClassification,
    AccountingReconciliationTask,
    AccountingTransferLink,
)
from app.services.accounting_reconciliation import (
    AccountingResolutionError,
    MovementEvidence,
    ReconciliationResult,
    reconcile_and_persist_movements,
    reconcile_movements,
    resolve_reconciliation_task,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.tests.db.test_schema_alignment import _run_alembic, temporary_database_url

NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


def _movement(
    *,
    source: str = "binance",
    tx_type: str = "withdrawal",
    asset_symbol: str = "USDT",
    quantity: Decimal = Decimal("-100"),
    occurred_at: datetime = NOW,
    evidence_key: str = "binance-withdrawal-1",
    source_event_id: str | None = "withdrawal-1",
    destination_event_id: str | None = None,
    authoritative_control_total_key: str | None = None,
    amount_usd: Decimal | None = Decimal("100"),
) -> MovementEvidence:
    return MovementEvidence(
        source=source,
        tx_type=tx_type,
        asset_symbol=asset_symbol,
        quantity=quantity,
        occurred_at=occurred_at,
        evidence_key=evidence_key,
        source_event_id=source_event_id,
        destination_event_id=destination_event_id,
        authoritative_control_total_key=authoritative_control_total_key,
        amount_usd=amount_usd,
    )


def _result_for(*movements: MovementEvidence) -> ReconciliationResult:
    return reconcile_movements(list(movements))


@pytest.fixture()
def migrated_database_url() -> str:
    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url)
        yield database_url


@pytest.fixture()
async def session_factory(migrated_database_url: str):
    engine = create_async_engine(migrated_database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def test_exact_binance_to_aster_identifier_match_writes_active_transfer_link() -> None:
    withdrawal = _movement(destination_event_id="aster-deposit-1")
    deposit = _movement(
        source="aster",
        tx_type="deposit",
        quantity=Decimal("100"),
        evidence_key="aster-deposit-1",
        source_event_id="aster-deposit-1",
        occurred_at=NOW + timedelta(hours=2),
    )

    result = _result_for(withdrawal, deposit)

    assert result.reconciliation_tasks == []
    assert len(result.transfer_links) == 1
    link = result.transfer_links[0]
    assert link.status == "active"
    assert link.from_evidence_key == "binance-withdrawal-1"
    assert link.to_evidence_key == "aster-deposit-1"
    assert link.from_source == "binance"
    assert link.to_source == "aster"
    assert link.capital_effect_usd == Decimal("0")


def test_parser_style_transfer_out_without_match_creates_open_task() -> None:
    result = _result_for(
        _movement(
            tx_type="transfer_out",
            asset_symbol="BTC",
            quantity=Decimal("0.25"),
            evidence_key="binance-transfer-out-btc",
            amount_usd=Decimal("15000"),
        )
    )

    assert result.transfer_links == []
    assert result.external_cashflow_classifications == []
    assert len(result.reconciliation_tasks) == 1
    task = result.reconciliation_tasks[0]
    assert task.task_type == "unknown_outgoing_transfer"
    assert task.quantity == Decimal("0.25")


def test_parser_style_transfer_out_and_transfer_in_identifier_match() -> None:
    withdrawal = _movement(
        tx_type="transfer_out",
        quantity=Decimal("25"),
        destination_event_id="aster-transfer-in-1",
        evidence_key="binance-transfer-out-usdt",
    )
    deposit = _movement(
        source="aster",
        tx_type="transfer_in",
        quantity=Decimal("25"),
        evidence_key="aster-transfer-in-usdt",
        source_event_id="aster-transfer-in-1",
        occurred_at=NOW + timedelta(hours=2),
    )

    result = _result_for(withdrawal, deposit)

    assert result.reconciliation_tasks == []
    assert len(result.transfer_links) == 1
    link = result.transfer_links[0]
    assert link.from_quantity == Decimal("25")
    assert link.to_quantity == Decimal("25")


def test_exact_binance_to_hyperliquid_identifier_writes_active_link() -> None:
    withdrawal = _movement(
        quantity=Decimal("-50"),
        destination_event_id="hl-deposit-1",
        amount_usd=Decimal("50"),
    )
    deposit = _movement(
        source="hyperliquid",
        tx_type="deposit",
        quantity=Decimal("50"),
        evidence_key="hl-deposit-1",
        source_event_id="hl-deposit-1",
        occurred_at=NOW + timedelta(minutes=30),
        amount_usd=Decimal("50"),
    )

    result = _result_for(withdrawal, deposit)

    assert len(result.transfer_links) == 1
    assert result.transfer_links[0].to_source == "hyperliquid"
    assert result.external_cashflow_classifications == []


def test_authoritative_control_total_match_writes_active_transfer_link() -> None:
    withdrawal = _movement(
        evidence_key="binance-withdrawal-control",
        source_event_id=None,
        authoritative_control_total_key="control:batch-1",
    )
    deposit = _movement(
        source="aster",
        tx_type="deposit",
        quantity=Decimal("100"),
        evidence_key="aster-deposit-control",
        source_event_id=None,
        authoritative_control_total_key="control:batch-1",
    )

    result = _result_for(withdrawal, deposit)

    assert len(result.transfer_links) == 1
    assert result.transfer_links[0].decision_reason == "authoritative_control_total"


def test_amount_and_date_only_match_creates_review_task_not_active_link() -> None:
    withdrawal = _movement(source_event_id=None, destination_event_id=None)
    deposit = _movement(
        source="aster",
        tx_type="deposit",
        quantity=Decimal("100"),
        evidence_key="aster-date-amount",
        source_event_id=None,
        occurred_at=NOW + timedelta(hours=1),
    )

    result = _result_for(withdrawal, deposit)

    assert result.transfer_links == []
    assert len(result.reconciliation_tasks) == 1
    assert result.reconciliation_tasks[0].task_type == "unknown_outgoing_transfer"
    assert result.reconciliation_tasks[0].status == "open"
    assert result.reconciliation_tasks[0].severity == "review_required"
    assert result.reconciliation_tasks[0].candidate_actions[0]["action"] == (
        "internal_transfer"
    )


def test_multi_candidate_match_creates_review_task_not_active_link() -> None:
    withdrawal = _movement(destination_event_id=None)
    deposit_a = _movement(
        source="aster",
        tx_type="deposit",
        quantity=Decimal("100"),
        evidence_key="aster-candidate",
        source_event_id=None,
    )
    deposit_b = _movement(
        source="hyperliquid",
        tx_type="deposit",
        quantity=Decimal("100"),
        evidence_key="hl-candidate",
        source_event_id=None,
        occurred_at=NOW + timedelta(minutes=5),
    )

    result = _result_for(withdrawal, deposit_a, deposit_b)

    assert result.transfer_links == []
    assert len(result.reconciliation_tasks) == 1
    assert result.reconciliation_tasks[0].evidence["candidate_count"] == 2


def test_fee_or_slippage_candidate_creates_review_task_not_active_link() -> None:
    withdrawal = _movement(quantity=Decimal("-100"), destination_event_id=None)
    deposit = _movement(
        source="hyperliquid",
        tx_type="deposit",
        quantity=Decimal("99.8"),
        evidence_key="hl-slippage",
        source_event_id=None,
    )

    result = _result_for(withdrawal, deposit)

    assert result.transfer_links == []
    assert len(result.reconciliation_tasks) == 1
    assert result.reconciliation_tasks[0].severity == "review_required"
    assert (
        "fee_or_slippage_candidate"
        in result.reconciliation_tasks[0].evidence["reasons"]
    )


def test_unknown_outgoing_crypto_creates_open_task_not_personal_withdrawal() -> None:
    result = _result_for(
        _movement(
            asset_symbol="BTC",
            quantity=Decimal("-0.25"),
            evidence_key="binance-btc-withdrawal",
            amount_usd=Decimal("15000"),
        )
    )

    assert result.transfer_links == []
    assert result.external_cashflow_classifications == []
    assert len(result.reconciliation_tasks) == 1
    task = result.reconciliation_tasks[0]
    assert task.task_id.startswith("task_unknown_outgoing_transfer_")
    assert task.amount_usd == Decimal("15000")
    assert task.candidate_actions == [
        {"action": "internal_transfer", "effect": "capital_effect_usd=0"},
        {"action": "personal_withdrawal", "effect": "capital_effect_usd<0"},
        {"action": "unknown", "effect": "keep metrics provisional_or_blocked"},
    ]


def test_xtb_withdrawal_defaults_to_external_withdrawal() -> None:
    result = _result_for(
        _movement(
            source="xtb",
            tx_type="withdrawal",
            asset_symbol="USD",
            quantity=Decimal("-250"),
            evidence_key="xtb-withdrawal",
            amount_usd=Decimal("250"),
        )
    )

    assert result.reconciliation_tasks == []
    assert len(result.external_cashflow_classifications) == 1
    cashflow = result.external_cashflow_classifications[0]
    assert cashflow.cashflow_type == "external_withdrawal"
    assert cashflow.capital_effect_usd == Decimal("-250")


def test_reconcile_movements_is_idempotent_by_task_and_link_key() -> None:
    movement = _movement(
        asset_symbol="ETH",
        quantity=Decimal("-1.5"),
        evidence_key="binance-eth-withdrawal",
        amount_usd=Decimal("5250"),
    )

    first = _result_for(movement, movement)
    second = _result_for(movement)

    assert len({task.task_key for task in first.reconciliation_tasks}) == 1
    assert (
        first.reconciliation_tasks[0].task_key
        == second.reconciliation_tasks[0].task_key
    )


async def test_reconcile_and_persist_movements_writes_canonical_state_idempotently(
    session_factory,
) -> None:
    deterministic_withdrawal = _movement(destination_event_id="aster-deposit-1")
    deterministic_deposit = _movement(
        source="aster",
        tx_type="deposit",
        quantity=Decimal("100"),
        evidence_key="aster-deposit-1",
        source_event_id="aster-deposit-1",
    )
    unknown_crypto = _movement(
        asset_symbol="BTC",
        quantity=Decimal("-0.25"),
        evidence_key="binance-btc-withdrawal",
        amount_usd=Decimal("15000"),
    )
    xtb_withdrawal = _movement(
        source="xtb",
        tx_type="withdrawal",
        asset_symbol="USD",
        quantity=Decimal("-250"),
        evidence_key="xtb-withdrawal",
        amount_usd=Decimal("250"),
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(
                session,
                [
                    deterministic_withdrawal,
                    deterministic_deposit,
                    unknown_crypto,
                    xtb_withdrawal,
                ],
            )
            await reconcile_and_persist_movements(
                session,
                [
                    deterministic_withdrawal,
                    deterministic_deposit,
                    unknown_crypto,
                    xtb_withdrawal,
                ],
            )

        transfer_links = (
            (await session.execute(select(AccountingTransferLink))).scalars().all()
        )
        tasks = (
            (await session.execute(select(AccountingReconciliationTask)))
            .scalars()
            .all()
        )
        cashflows = (
            (await session.execute(select(AccountingExternalCashflowClassification)))
            .scalars()
            .all()
        )

    assert len(transfer_links) == 1
    assert transfer_links[0].status == "active"
    assert len(tasks) == 1
    assert tasks[0].status == "open"
    assert tasks[0].task_type == "unknown_outgoing_transfer"
    assert len(cashflows) == 1
    assert cashflows[0].cashflow_type == "external_withdrawal"
    assert cashflows[0].capital_effect_usd == Decimal("-250.000000")


async def test_resolve_reconciliation_task_validates_decision_back_reference(
    session_factory,
) -> None:
    movement = _movement(
        asset_symbol="SOL",
        quantity=Decimal("-10"),
        evidence_key="binance-sol-withdrawal",
        amount_usd=Decimal("1000"),
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(session, [movement])
            task = await session.scalar(
                select(AccountingReconciliationTask).where(
                    AccountingReconciliationTask.task_key
                    == "task:unknown_outgoing_transfer:binance-sol-withdrawal"
                )
            )
            assert task is not None
            decision = AccountingExternalCashflowClassification(
                classification_key="cashflow:sol:manual-withdrawal",
                evidence={"source_evidence_key": "binance-sol-withdrawal"},
                evidence_key="binance-sol-withdrawal",
                cashflow_type="external_withdrawal",
                movement_type="external_cashflow",
                source="binance",
                asset_symbol="SOL",
                quantity=Decimal("10"),
                amount_usd=Decimal("1000"),
                occurred_at=NOW,
                capital_effect_usd=Decimal("-1000"),
                confidence_state="trusted",
                materiality_usd=Decimal("1000"),
                review_task_id=task.task_id,
                created_by="local_user",
                decision_source="manual",
                status="active",
                decision_reason="manual_personal_withdrawal",
            )
            session.add(decision)
            await session.flush()
            resolved = await resolve_reconciliation_task(
                session,
                task_id=task.task_id,
                decision_type="accounting_external_cashflow_classification",
                decision_id=decision.id,
                resolved_by="local_user",
                resolved_at=NOW,
            )

        assert resolved.status == "resolved"
        assert (
            resolved.resolved_by_decision_type
            == "accounting_external_cashflow_classification"
        )
        assert resolved.resolved_by_decision_id == decision.id


async def test_resolved_task_is_not_recreated_on_same_evidence(
    session_factory,
) -> None:
    movement = _movement(
        asset_symbol="SOL",
        quantity=Decimal("-10"),
        evidence_key="binance-sol-resolved-rerun",
        amount_usd=Decimal("1000"),
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(session, [movement])
            task = await session.scalar(
                select(AccountingReconciliationTask).where(
                    AccountingReconciliationTask.task_key
                    == "task:unknown_outgoing_transfer:binance-sol-resolved-rerun"
                )
            )
            assert task is not None
            decision = AccountingExternalCashflowClassification(
                classification_key="cashflow:sol:resolved-rerun",
                evidence={"source_evidence_key": "binance-sol-resolved-rerun"},
                evidence_key="binance-sol-resolved-rerun",
                cashflow_type="external_withdrawal",
                movement_type="external_cashflow",
                source="binance",
                asset_symbol="SOL",
                quantity=Decimal("10"),
                amount_usd=Decimal("1000"),
                occurred_at=NOW,
                capital_effect_usd=Decimal("-1000"),
                confidence_state="trusted",
                materiality_usd=Decimal("1000"),
                review_task_id=task.task_id,
                created_by="local_user",
                decision_source="manual",
                status="active",
                decision_reason="manual_personal_withdrawal",
            )
            session.add(decision)
            await session.flush()
            await resolve_reconciliation_task(
                session,
                task_id=task.task_id,
                decision_type="accounting_external_cashflow_classification",
                decision_id=decision.id,
                resolved_by="local_user",
                resolved_at=NOW,
            )
            await reconcile_and_persist_movements(session, [movement])

        tasks = (
            (await session.execute(select(AccountingReconciliationTask)))
            .scalars()
            .all()
        )

    assert len(tasks) == 1
    assert tasks[0].status == "resolved"


async def test_resolve_reconciliation_task_rejects_missing_decision(
    session_factory,
) -> None:
    movement = _movement(
        asset_symbol="SOL",
        quantity=Decimal("-10"),
        evidence_key="binance-sol-missing-decision",
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(session, [movement])
            task = await session.scalar(
                select(AccountingReconciliationTask).where(
                    AccountingReconciliationTask.task_key
                    == "task:unknown_outgoing_transfer:binance-sol-missing-decision"
                )
            )
            assert task is not None
            with pytest.raises(AccountingResolutionError, match="does not exist"):
                await resolve_reconciliation_task(
                    session,
                    task_id=task.task_id,
                    decision_type="accounting_cost_basis_decision",
                    decision_id=999999,
                    resolved_by="local_user",
                    resolved_at=NOW,
                )


async def test_resolve_reconciliation_task_rejects_incompatible_decision_type(
    session_factory,
) -> None:
    movement = _movement(
        asset_symbol="SOL",
        quantity=Decimal("-10"),
        evidence_key="binance-sol-incompatible-decision",
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(session, [movement])
            task = await session.scalar(
                select(AccountingReconciliationTask).where(
                    AccountingReconciliationTask.task_key
                    == (
                        "task:unknown_outgoing_transfer:"
                        "binance-sol-incompatible-decision"
                    )
                )
            )
            assert task is not None
            decision = AccountingCostBasisDecision(
                basis_key="basis:sol:incompatible",
                decision_type="manual_cost_basis",
                asset_symbol="SOL",
                basis_scope="asset_global",
                cost_basis_usd=Decimal("1000"),
                effective_at=NOW,
                confidence_state="trusted",
                affected_metric_scopes=["asset_lifetime_pnl"],
                review_task_id=task.task_id,
                created_by="local_user",
                decision_source="manual",
                status="active",
                decision_reason="manual_average_cost",
            )
            session.add(decision)
            await session.flush()

            with pytest.raises(AccountingResolutionError, match="cannot resolve"):
                await resolve_reconciliation_task(
                    session,
                    task_id=task.task_id,
                    decision_type="accounting_cost_basis_decision",
                    decision_id=decision.id,
                    resolved_by="local_user",
                    resolved_at=NOW,
                )


async def test_resolve_reconciliation_task_rejects_mismatched_review_task_id(
    session_factory,
) -> None:
    movement = _movement(
        asset_symbol="SOL",
        quantity=Decimal("-10"),
        evidence_key="binance-sol-mismatched-decision",
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(session, [movement])
            task = await session.scalar(
                select(AccountingReconciliationTask).where(
                    AccountingReconciliationTask.task_key
                    == "task:unknown_outgoing_transfer:binance-sol-mismatched-decision"
                )
            )
            assert task is not None
            decision = AccountingExternalCashflowClassification(
                classification_key="cashflow:sol:mismatch",
                evidence={"source_evidence_key": "binance-sol-mismatched-decision"},
                evidence_key="binance-sol-mismatched-decision",
                cashflow_type="external_withdrawal",
                movement_type="external_cashflow",
                source="binance",
                asset_symbol="SOL",
                quantity=Decimal("10"),
                amount_usd=Decimal("1000"),
                occurred_at=NOW,
                capital_effect_usd=Decimal("-1000"),
                confidence_state="trusted",
                materiality_usd=Decimal("1000"),
                review_task_id="other_task",
                created_by="local_user",
                decision_source="manual",
                status="active",
                decision_reason="manual_personal_withdrawal",
            )
            session.add(decision)
            await session.flush()

            with pytest.raises(AccountingResolutionError, match="review_task_id"):
                await resolve_reconciliation_task(
                    session,
                    task_id=task.task_id,
                    decision_type="accounting_external_cashflow_classification",
                    decision_id=decision.id,
                    resolved_by="local_user",
                    resolved_at=NOW,
                )


async def test_resolve_reconciliation_task_rejects_inactive_decision(
    session_factory,
) -> None:
    movement = _movement(
        asset_symbol="SOL",
        quantity=Decimal("-10"),
        evidence_key="binance-sol-inactive-decision",
    )

    async with session_factory() as session:
        async with session.begin():
            await reconcile_and_persist_movements(session, [movement])
            task = await session.scalar(
                select(AccountingReconciliationTask).where(
                    AccountingReconciliationTask.task_key
                    == "task:unknown_outgoing_transfer:binance-sol-inactive-decision"
                )
            )
            assert task is not None
            decision = AccountingExternalCashflowClassification(
                classification_key="cashflow:sol:inactive",
                evidence={"source_evidence_key": "binance-sol-inactive-decision"},
                evidence_key="binance-sol-inactive-decision",
                cashflow_type="external_withdrawal",
                movement_type="external_cashflow",
                source="binance",
                asset_symbol="SOL",
                quantity=Decimal("10"),
                amount_usd=Decimal("1000"),
                occurred_at=NOW,
                capital_effect_usd=Decimal("-1000"),
                confidence_state="trusted",
                materiality_usd=Decimal("1000"),
                review_task_id=task.task_id,
                created_by="local_user",
                decision_source="manual",
                status="superseded",
                decision_reason="manual_personal_withdrawal",
            )
            session.add(decision)
            await session.flush()

            with pytest.raises(AccountingResolutionError, match="not active"):
                await resolve_reconciliation_task(
                    session,
                    task_id=task.task_id,
                    decision_type="accounting_external_cashflow_classification",
                    decision_id=decision.id,
                    resolved_by="local_user",
                    resolved_at=NOW,
                )
