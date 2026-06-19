# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.accounting_reconciliation import (
    MovementEvidence,
    ReconciliationResult,
    reconcile_movements,
)

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
