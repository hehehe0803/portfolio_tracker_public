from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

TRACKED_CRYPTO_SOURCES = {"binance", "aster", "hyperliquid", "tracked_wallet"}
TRANSFER_DESTINATIONS = {"aster", "hyperliquid", "tracked_wallet", "binance"}
TRANSFER_WINDOW = timedelta(days=2)


@dataclass(frozen=True)
class MovementEvidence:
    source: str
    tx_type: str
    asset_symbol: str
    quantity: Decimal
    occurred_at: datetime
    evidence_key: str
    source_event_id: str | None = None
    destination_event_id: str | None = None
    authoritative_control_total_key: str | None = None
    amount_usd: Decimal | None = None


@dataclass(frozen=True)
class TransferLinkRecord:
    link_group_key: str
    from_evidence: dict
    to_evidence: dict
    from_evidence_key: str
    to_evidence_key: str
    asset_symbol: str
    from_quantity: Decimal
    to_quantity: Decimal
    quantity_delta: Decimal
    fee_quantity: Decimal | None
    fee_asset_symbol: str | None
    amount_usd: Decimal | None
    from_source: str
    to_source: str
    occurred_at: datetime
    confidence_state: str
    review_task_id: str | None
    created_by: str
    decision_source: str
    status: str
    decision_reason: str
    capital_effect_usd: Decimal


@dataclass(frozen=True)
class ExternalCashflowClassificationRecord:
    classification_key: str
    evidence: dict
    evidence_key: str
    cashflow_type: str
    movement_type: str
    source: str
    asset_symbol: str
    quantity: Decimal
    amount_usd: Decimal | None
    occurred_at: datetime
    capital_effect_usd: Decimal | None
    confidence_state: str
    materiality_usd: Decimal | None
    review_task_id: str | None
    created_by: str
    decision_source: str
    status: str
    decision_reason: str


@dataclass(frozen=True)
class ReconciliationTaskRecord:
    task_id: str
    task_key: str
    task_type: str
    status: str
    severity: str
    source: str
    asset_symbol: str
    quantity: Decimal | None
    amount_usd: Decimal | None
    occurred_at: datetime
    evidence: dict
    candidate_actions: list[dict[str, str]]
    affected_metric_scopes: list[str]
    created_by: str


@dataclass(frozen=True)
class ReconciliationResult:
    transfer_links: list[TransferLinkRecord]
    reconciliation_tasks: list[ReconciliationTaskRecord]
    external_cashflow_classifications: list[ExternalCashflowClassificationRecord]


def reconcile_movements(movements: list[MovementEvidence]) -> ReconciliationResult:
    unique_movements = _dedupe_movements(movements)
    deposits = [movement for movement in unique_movements if _is_deposit(movement)]
    transfer_links: dict[str, TransferLinkRecord] = {}
    tasks: dict[str, ReconciliationTaskRecord] = {}
    cashflows: dict[str, ExternalCashflowClassificationRecord] = {}

    for movement in unique_movements:
        if not _is_outgoing(movement):
            continue

        source = _source(movement)
        if source == "xtb":
            cashflow = _external_withdrawal(movement)
            cashflows.setdefault(cashflow.classification_key, cashflow)
            continue

        if source not in TRACKED_CRYPTO_SOURCES:
            continue

        candidates = _transfer_candidates(movement, deposits)
        deterministic = _deterministic_candidate(movement, candidates)
        if deterministic is not None:
            link = _transfer_link(movement, deterministic)
            transfer_links.setdefault(link.link_group_key, link)
            continue

        task = _unknown_outgoing_task(movement, candidates)
        tasks.setdefault(task.task_key, task)

    return ReconciliationResult(
        transfer_links=list(transfer_links.values()),
        reconciliation_tasks=list(tasks.values()),
        external_cashflow_classifications=list(cashflows.values()),
    )


def _dedupe_movements(movements: list[MovementEvidence]) -> list[MovementEvidence]:
    deduped: dict[str, MovementEvidence] = {}
    for movement in movements:
        deduped.setdefault(movement.evidence_key, movement)
    return list(deduped.values())


def _source(movement: MovementEvidence) -> str:
    return movement.source.strip().lower()


def _asset(movement: MovementEvidence) -> str:
    return movement.asset_symbol.strip().upper()


def _occurred_at(movement: MovementEvidence) -> datetime:
    if movement.occurred_at.tzinfo is None:
        return movement.occurred_at.replace(tzinfo=UTC)
    return movement.occurred_at.astimezone(UTC)


def _is_outgoing(movement: MovementEvidence) -> bool:
    return movement.quantity < Decimal("0") and (
        "withdraw" in movement.tx_type.lower() or "outgoing" in movement.tx_type.lower()
    )


def _is_deposit(movement: MovementEvidence) -> bool:
    return movement.quantity > Decimal("0") and (
        "deposit" in movement.tx_type.lower()
        or "incoming" in movement.tx_type.lower()
        or "transfer_candidate" in movement.tx_type.lower()
    )


def _transfer_candidates(
    withdrawal: MovementEvidence,
    deposits: list[MovementEvidence],
) -> list[MovementEvidence]:
    withdrawal_time = _occurred_at(withdrawal)
    return [
        deposit
        for deposit in deposits
        if deposit.evidence_key != withdrawal.evidence_key
        and _source(deposit) in TRANSFER_DESTINATIONS
        and _asset(deposit) == _asset(withdrawal)
        and abs(_occurred_at(deposit) - withdrawal_time) <= TRANSFER_WINDOW
        and _is_candidate_quantity(withdrawal, deposit)
    ]


def _is_candidate_quantity(
    withdrawal: MovementEvidence,
    deposit: MovementEvidence,
) -> bool:
    withdrawn = abs(withdrawal.quantity)
    if withdrawn == Decimal("0"):
        return deposit.quantity == Decimal("0")
    delta = abs(deposit.quantity - withdrawn)
    if delta == Decimal("0"):
        return True
    return delta <= withdrawn * Decimal("0.01")


def _deterministic_candidate(
    withdrawal: MovementEvidence,
    candidates: list[MovementEvidence],
) -> MovementEvidence | None:
    exact_quantity_candidates = [
        candidate
        for candidate in candidates
        if candidate.quantity == abs(withdrawal.quantity)
    ]
    deterministic = [
        candidate
        for candidate in exact_quantity_candidates
        if _has_exact_identifier_link(withdrawal, candidate)
        or _has_authoritative_control_total(withdrawal, candidate)
    ]
    if len(deterministic) != 1:
        return None
    return deterministic[0]


def _has_exact_identifier_link(
    withdrawal: MovementEvidence,
    deposit: MovementEvidence,
) -> bool:
    return bool(
        withdrawal.destination_event_id
        and deposit.source_event_id
        and withdrawal.destination_event_id == deposit.source_event_id
    )


def _has_authoritative_control_total(
    withdrawal: MovementEvidence,
    deposit: MovementEvidence,
) -> bool:
    return bool(
        withdrawal.authoritative_control_total_key
        and deposit.authoritative_control_total_key
        and withdrawal.authoritative_control_total_key
        == deposit.authoritative_control_total_key
    )


def _transfer_link(
    withdrawal: MovementEvidence,
    deposit: MovementEvidence,
) -> TransferLinkRecord:
    quantity_delta = abs(abs(withdrawal.quantity) - deposit.quantity)
    decision_reason = (
        "authoritative_control_total"
        if _has_authoritative_control_total(withdrawal, deposit)
        else "exact_source_destination_identifier"
    )
    return TransferLinkRecord(
        link_group_key=_stable_key(
            "transfer",
            withdrawal.evidence_key,
            deposit.evidence_key,
        ),
        from_evidence=_evidence(withdrawal),
        to_evidence=_evidence(deposit),
        from_evidence_key=withdrawal.evidence_key,
        to_evidence_key=deposit.evidence_key,
        asset_symbol=_asset(withdrawal),
        from_quantity=abs(withdrawal.quantity),
        to_quantity=deposit.quantity,
        quantity_delta=quantity_delta,
        fee_quantity=None,
        fee_asset_symbol=None,
        amount_usd=_positive_amount(withdrawal.amount_usd),
        from_source=_source(withdrawal),
        to_source=_source(deposit),
        occurred_at=_occurred_at(withdrawal),
        confidence_state="trusted",
        review_task_id=None,
        created_by="system",
        decision_source="deterministic",
        status="active",
        decision_reason=decision_reason,
        capital_effect_usd=Decimal("0"),
    )


def _unknown_outgoing_task(
    withdrawal: MovementEvidence,
    candidates: list[MovementEvidence],
) -> ReconciliationTaskRecord:
    task_key = _stable_key("task", "unknown_outgoing_transfer", withdrawal.evidence_key)
    candidate_count = len(candidates)
    reasons = ["unknown_outgoing_crypto"]
    if candidate_count == 1:
        candidate = candidates[0]
        if candidate.quantity != abs(withdrawal.quantity):
            reasons.append("fee_or_slippage_candidate")
        else:
            reasons.append("amount_date_only_candidate")
    elif candidate_count > 1:
        reasons.append("multiple_transfer_candidates")

    return ReconciliationTaskRecord(
        task_id=f"task_unknown_outgoing_transfer_{_digest(task_key)}",
        task_key=task_key,
        task_type="unknown_outgoing_transfer",
        status="open",
        severity="review_required",
        source=_source(withdrawal),
        asset_symbol=_asset(withdrawal),
        quantity=abs(withdrawal.quantity),
        amount_usd=_positive_amount(withdrawal.amount_usd),
        occurred_at=_occurred_at(withdrawal),
        evidence={
            "source_evidence_key": withdrawal.evidence_key,
            "source_event_id": withdrawal.source_event_id,
            "destination_event_id": withdrawal.destination_event_id,
            "candidate_count": candidate_count,
            "candidate_evidence_keys": [
                candidate.evidence_key for candidate in candidates
            ],
            "reasons": reasons,
        },
        candidate_actions=[
            {"action": "internal_transfer", "effect": "capital_effect_usd=0"},
            {"action": "personal_withdrawal", "effect": "capital_effect_usd<0"},
            {"action": "unknown", "effect": "keep metrics provisional_or_blocked"},
        ],
        affected_metric_scopes=[
            "gross_withdrawals",
            "net_capital",
            "lifetime_pnl",
            "period_performance",
        ],
        created_by="system",
    )


def _external_withdrawal(
    movement: MovementEvidence,
) -> ExternalCashflowClassificationRecord:
    amount = _positive_amount(movement.amount_usd)
    capital_effect = -amount if amount is not None else None
    return ExternalCashflowClassificationRecord(
        classification_key=_stable_key(
            "cashflow", "external_withdrawal", movement.evidence_key
        ),
        evidence=_evidence(movement),
        evidence_key=movement.evidence_key,
        cashflow_type="external_withdrawal",
        movement_type="external_cashflow",
        source=_source(movement),
        asset_symbol=_asset(movement),
        quantity=abs(movement.quantity),
        amount_usd=amount,
        occurred_at=_occurred_at(movement),
        capital_effect_usd=capital_effect,
        confidence_state="trusted",
        materiality_usd=amount,
        review_task_id=None,
        created_by="system",
        decision_source="system",
        status="active",
        decision_reason="source_policy_xtb_external_withdrawal",
    )


def _evidence(movement: MovementEvidence) -> dict[str, str | None]:
    return {
        "source": _source(movement),
        "evidence_key": movement.evidence_key,
        "source_event_id": movement.source_event_id,
        "destination_event_id": movement.destination_event_id,
        "authoritative_control_total_key": movement.authoritative_control_total_key,
    }


def _positive_amount(amount: Decimal | None) -> Decimal | None:
    if amount is None:
        return None
    return abs(amount)


def _stable_key(*parts: str) -> str:
    return ":".join(parts)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
