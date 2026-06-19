from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AccountingCostBasisDecision,
    AccountingEvidenceClaim,
    AccountingExternalCashflowClassification,
    AccountingImportApproval,
    AccountingReconciliationTask,
    AccountingTransferLink,
    ActivityLog,
)
from app.services.accounting_reconciliation import (
    DECISION_TYPES_BY_TASK_TYPE,
    AccountingResolutionError,
    resolve_reconciliation_task,
)
from shared.python.contracts import (
    AccountingReviewDecisionRequest,
    AccountingReviewDecisionResponse,
    AccountingReviewQueue,
    AccountingReviewTask,
    InternalTransferDecision,
    ManualCostBasisDecision,
)

ALLOWED_ACCOUNTING_REVIEW_ACTIONS = [
    "internal_transfer",
    "personal_withdrawal",
    "import_approval",
    "manual_cost_basis",
    "unknown_cost_basis",
    "unknown",
]

DECISION_TYPE_BY_ACTION = {
    "internal_transfer": "accounting_transfer_link",
    "personal_withdrawal": "accounting_external_cashflow_classification",
    "import_approval": "accounting_import_approval",
    "manual_cost_basis": "accounting_cost_basis_decision",
    "unknown_cost_basis": "accounting_cost_basis_decision",
    "unknown": "accounting_external_cashflow_classification",
}

DECISION_MODEL_BY_TYPE = {
    "accounting_transfer_link": AccountingTransferLink,
    "accounting_external_cashflow_classification": (
        AccountingExternalCashflowClassification
    ),
    "accounting_import_approval": AccountingImportApproval,
    "accounting_cost_basis_decision": AccountingCostBasisDecision,
}


class AccountingReviewError(ValueError):
    pass


class AccountingReviewNotFound(AccountingReviewError):
    pass


class AccountingReviewDecisionConflict(AccountingReviewError):
    pass


async def list_open_accounting_review_tasks(
    session: AsyncSession,
) -> AccountingReviewQueue:
    tasks = (
        (
            await session.execute(
                select(AccountingReconciliationTask)
                .where(AccountingReconciliationTask.status == "open")
                .order_by(
                    AccountingReconciliationTask.occurred_at.asc(),
                    AccountingReconciliationTask.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return AccountingReviewQueue(
        allowed_actions=ALLOWED_ACCOUNTING_REVIEW_ACTIONS,
        tasks=[_task_contract(task) for task in tasks],
    )


async def approve_accounting_review_decision(
    session: AsyncSession,
    request: AccountingReviewDecisionRequest,
    *,
    user_id: int | None,
    username: str,
) -> AccountingReviewDecisionResponse:
    task = await _load_task(session, request.task_id, for_update=True)
    replayed = await _idempotent_replay(session, task, request)
    if replayed is not None:
        return replayed

    if task.status != "open":
        raise AccountingReviewDecisionConflict(
            f"accounting task {request.task_id!r} is not open"
        )

    decision_type = DECISION_TYPE_BY_ACTION[request.action]
    _validate_task_action_compatible(task, decision_type)
    decision = _build_decision(task, request, username=username)
    session.add(decision)
    await session.flush()

    await _claim_decision_evidence(session, decision)
    await session.flush()

    try:
        resolved = await resolve_reconciliation_task(
            session,
            task_id=task.task_id,
            decision_type=decision_type,
            decision_id=decision.id,
            resolved_by=username,
        )
    except AccountingResolutionError as exc:
        raise AccountingReviewDecisionConflict(str(exc)) from exc

    _add_audit_log(
        session,
        task=task,
        request=request,
        decision_type=decision_type,
        decision_id=decision.id,
        user_id=user_id,
    )
    await session.flush()

    return AccountingReviewDecisionResponse(
        task_id=resolved.task_id,
        task_status="resolved",
        decision_type=decision_type,
        decision_id=decision.id,
        replayed=False,
    )


async def _idempotent_replay(
    session: AsyncSession,
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
) -> AccountingReviewDecisionResponse | None:
    if task.status != "resolved":
        return None
    decision_type = DECISION_TYPE_BY_ACTION[request.action]
    if task.resolved_by_decision_type != decision_type:
        raise AccountingReviewDecisionConflict(
            "idempotency key already used for a different accounting action"
        )
    decision_id = task.resolved_by_decision_id
    if decision_id is None:
        raise AccountingReviewDecisionConflict(
            "resolved accounting task is missing a durable decision reference"
        )
    decision_model = DECISION_MODEL_BY_TYPE[decision_type]
    decision = await session.get(decision_model, decision_id)
    if decision is None:
        raise AccountingReviewDecisionConflict(
            "resolved accounting task decision no longer exists"
        )
    if _decision_key_value(decision) != _decision_key_for_type(
        _decision_key_prefix(decision_type, request.action),
        task,
        request,
    ):
        raise AccountingReviewDecisionConflict(
            "idempotency key already used for a different accounting payload"
        )
    return AccountingReviewDecisionResponse(
        task_id=task.task_id,
        task_status="resolved",
        decision_type=decision_type,
        decision_id=decision_id,
        replayed=True,
    )


async def _load_task(
    session: AsyncSession,
    task_id: str,
    *,
    for_update: bool = False,
) -> AccountingReconciliationTask:
    statement = select(AccountingReconciliationTask).where(
        AccountingReconciliationTask.task_id == task_id
    )
    if for_update:
        statement = statement.with_for_update()
    task = await session.scalar(statement)
    if task is None:
        raise AccountingReviewNotFound(f"accounting task {task_id!r} does not exist")
    return task


def _build_decision(
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    *,
    username: str,
):
    if request.action == "internal_transfer":
        if request.internal_transfer is None:
            raise AccountingReviewError("internal_transfer details are required")
        return _internal_transfer_decision(
            task,
            request,
            request.internal_transfer,
            username,
        )
    if request.action == "personal_withdrawal":
        return _personal_withdrawal_decision(task, request, username)
    if request.action == "unknown":
        return _unknown_outgoing_decision(task, request, username)
    if request.action == "import_approval":
        return _import_approval_decision(task, request, username)
    if request.action in {"manual_cost_basis", "unknown_cost_basis"}:
        return _cost_basis_decision(task, request, request.cost_basis, username)
    raise AccountingReviewError(f"unsupported accounting action {request.action!r}")


def _internal_transfer_decision(
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    details: InternalTransferDecision,
    username: str,
) -> AccountingTransferLink:
    from_quantity = _task_quantity(task)
    to_quantity = abs(details.to_quantity)
    return AccountingTransferLink(
        link_group_key=_decision_key("transfer", task, request),
        from_evidence=_task_evidence(task),
        to_evidence={
            "source": details.to_source.strip().lower(),
            "evidence_key": details.to_evidence_key,
            "review_task_id": task.task_id,
        },
        from_evidence_key=_source_evidence_key(task),
        to_evidence_key=details.to_evidence_key,
        asset_symbol=task.asset_symbol.upper(),
        from_quantity=from_quantity,
        to_quantity=to_quantity,
        quantity_delta=abs(from_quantity - to_quantity),
        fee_quantity=details.fee_quantity,
        fee_asset_symbol=details.fee_asset_symbol,
        amount_usd=_positive(task.amount_usd),
        from_source=task.source.lower(),
        to_source=details.to_source.strip().lower(),
        occurred_at=_utc(task.occurred_at),
        confidence_state="trusted",
        review_task_id=task.task_id,
        created_by=username,
        decision_source="manual",
        status="active",
        decision_reason="manual_internal_transfer",
        notes=request.rationale,
    )


def _personal_withdrawal_decision(
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    username: str,
) -> AccountingExternalCashflowClassification:
    amount = _positive(task.amount_usd)
    return AccountingExternalCashflowClassification(
        classification_key=_decision_key("cashflow", task, request),
        evidence=_task_evidence(task),
        evidence_key=_source_evidence_key(task),
        cashflow_type="external_withdrawal",
        movement_type="external_cashflow",
        source=task.source.lower(),
        asset_symbol=task.asset_symbol.upper(),
        quantity=_task_quantity(task),
        amount_usd=amount,
        occurred_at=_utc(task.occurred_at),
        capital_effect_usd=-amount if amount is not None else None,
        confidence_state="trusted",
        materiality_usd=amount,
        review_task_id=task.task_id,
        created_by=username,
        decision_source="manual",
        status="active",
        decision_reason="manual_personal_withdrawal",
        notes=request.rationale,
    )


def _unknown_outgoing_decision(
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    username: str,
) -> AccountingExternalCashflowClassification:
    return AccountingExternalCashflowClassification(
        classification_key=_decision_key("cashflow", task, request),
        evidence=_task_evidence(task),
        evidence_key=_source_evidence_key(task),
        cashflow_type="not_external_cashflow",
        movement_type="internal_movement",
        source=task.source.lower(),
        asset_symbol=task.asset_symbol.upper(),
        quantity=_task_quantity(task),
        amount_usd=_positive(task.amount_usd),
        occurred_at=_utc(task.occurred_at),
        capital_effect_usd=Decimal("0"),
        confidence_state="blocked",
        materiality_usd=_positive(task.amount_usd),
        review_task_id=task.task_id,
        created_by=username,
        decision_source="manual",
        status="active",
        decision_reason="manual_unknown_outgoing",
        notes=request.rationale,
    )


def _import_approval_decision(
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    username: str,
) -> AccountingImportApproval:
    evidence = task.evidence or {}
    source_fingerprints = _required_string_list(
        evidence,
        "source_fingerprints",
    )
    approved_scope = _required_string_list(evidence, "approved_scope")
    import_scope_id = _required_string(evidence, "import_scope_id")
    coverage_start = _required_datetime(evidence, "coverage_start")
    coverage_end = _required_datetime(evidence, "coverage_end")
    if coverage_start > coverage_end:
        raise AccountingReviewError(
            "import approval coverage_start exceeds coverage_end"
        )
    return AccountingImportApproval(
        approval_key=_decision_key("import", task, request),
        source=task.source.lower(),
        source_account_id=_optional_string(evidence.get("source_account_id")),
        import_scope_id=import_scope_id,
        source_fingerprints=[str(value) for value in source_fingerprints],
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        approved_scope=[str(value) for value in approved_scope],
        control_totals=(
            evidence.get("control_totals")
            if isinstance(evidence.get("control_totals"), dict)
            else None
        ),
        confidence_state="trusted",
        review_task_id=task.task_id,
        created_by=username,
        decision_source="manual",
        status="active",
        decision_reason="manual_import_approval",
        notes=request.rationale,
    )


def _cost_basis_decision(
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    details: ManualCostBasisDecision | None,
    username: str,
) -> AccountingCostBasisDecision:
    evidence = task.evidence or {}
    decision_type = (
        "manual_cost_basis"
        if request.action == "manual_cost_basis"
        else "unknown_cost_basis"
    )
    if decision_type == "manual_cost_basis" and details is None:
        raise AccountingReviewError("cost_basis details are required")
    if decision_type == "manual_cost_basis" and not _has_manual_basis_value(details):
        raise AccountingReviewError(
            "manual_cost_basis requires cost_basis_usd or quantity and unit_cost_usd"
        )
    confidence_state = "trusted" if decision_type == "manual_cost_basis" else "blocked"
    stored_details = details if decision_type == "manual_cost_basis" else None
    return AccountingCostBasisDecision(
        basis_key=_decision_key("basis", task, request),
        decision_type=decision_type,
        asset_symbol=task.asset_symbol.upper(),
        source=task.source.lower(),
        source_account_id=_optional_string(evidence.get("source_account_id")),
        basis_scope=str(evidence.get("basis_scope") or "asset_global"),
        evidence=_task_evidence(task),
        quantity=stored_details.quantity if stored_details else task.quantity,
        cost_basis_usd=stored_details.cost_basis_usd if stored_details else None,
        unit_cost_usd=stored_details.unit_cost_usd if stored_details else None,
        effective_at=_utc(task.occurred_at),
        basis_method=stored_details.basis_method if stored_details else None,
        confidence_state=confidence_state,
        affected_metric_scopes=task.affected_metric_scopes,
        review_task_id=task.task_id,
        created_by=username,
        decision_source="manual",
        status="active",
        decision_reason=decision_type,
        notes=request.rationale,
    )


def _add_audit_log(
    session: AsyncSession,
    *,
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
    decision_type: str,
    decision_id: int,
    user_id: int | None,
) -> None:
    session.add(
        ActivityLog(
            source="accounting_review",
            status=request.action,
            message=f"Accounting review {request.action} resolved {task.task_id}",
            user_id=user_id,
            event_metadata={
                "review_type": "accounting",
                "task_id": task.task_id,
                "task_type": task.task_type,
                "action": request.action,
                "idempotency_key": request.idempotency_key,
                "decision_type": decision_type,
                "decision_id": decision_id,
                "canonical_state_written": True,
                "request_fingerprint": _request_fingerprint(request),
            },
        )
    )


async def _claim_decision_evidence(
    session: AsyncSession,
    decision: object,
) -> None:
    claims = _evidence_claims_for_decision(decision)
    if not claims:
        return
    existing_by_key = {
        claim.evidence_key: claim
        for claim in (
            (
                await session.execute(
                    select(AccountingEvidenceClaim).where(
                        AccountingEvidenceClaim.evidence_key.in_(
                            [claim.evidence_key for claim in claims]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    }
    missing_claims = []
    for claim in claims:
        existing = existing_by_key.get(claim.evidence_key)
        if existing is None:
            missing_claims.append(claim)
            continue
        if (
            existing.source_table != claim.source_table
            or existing.source_id != claim.source_id
            or existing.claim_role != claim.claim_role
        ):
            raise AccountingReviewDecisionConflict(
                f"accounting evidence already claimed: {claim.evidence_key}"
            )
    session.add_all(missing_claims)


def _validate_task_action_compatible(
    task: AccountingReconciliationTask,
    decision_type: str,
) -> None:
    if decision_type not in DECISION_TYPES_BY_TASK_TYPE.get(task.task_type, set()):
        raise AccountingReviewDecisionConflict(
            f"decision type {decision_type!r} cannot resolve task type "
            f"{task.task_type!r}"
        )


def _evidence_claims_for_decision(decision: object) -> list[AccountingEvidenceClaim]:
    if isinstance(decision, AccountingTransferLink):
        return [
            AccountingEvidenceClaim(
                evidence_key=decision.from_evidence_key,
                source_table="accounting_transfer_links",
                source_id=decision.id,
                claim_role="transfer_from",
            ),
            AccountingEvidenceClaim(
                evidence_key=decision.to_evidence_key,
                source_table="accounting_transfer_links",
                source_id=decision.id,
                claim_role="transfer_to",
            ),
        ]
    if isinstance(decision, AccountingExternalCashflowClassification):
        return [
            AccountingEvidenceClaim(
                evidence_key=decision.evidence_key,
                source_table="accounting_external_cashflow_classifications",
                source_id=decision.id,
                claim_role="cashflow",
            )
        ]
    return []


def _task_contract(task: AccountingReconciliationTask) -> AccountingReviewTask:
    return AccountingReviewTask(
        task_id=task.task_id,
        task_type=task.task_type,
        status=task.status,
        severity=task.severity,
        source=task.source,
        asset_symbol=task.asset_symbol,
        quantity=task.quantity,
        amount_usd=task.amount_usd,
        occurred_at=_utc(task.occurred_at),
        evidence=task.evidence,
        candidate_actions=task.candidate_actions,
        affected_metric_scopes=task.affected_metric_scopes,
        created_at=_utc(task.created_at) if task.created_at else None,
    )


def _task_evidence(task: AccountingReconciliationTask) -> dict:
    evidence = dict(task.evidence or {})
    evidence.setdefault("source", task.source)
    evidence.setdefault("review_task_id", task.task_id)
    return evidence


def _source_evidence_key(task: AccountingReconciliationTask) -> str:
    evidence = task.evidence or {}
    return str(evidence.get("source_evidence_key") or task.task_key)


def _task_quantity(task: AccountingReconciliationTask) -> Decimal:
    return abs(task.quantity or Decimal("0"))


def _positive(value: Decimal | None) -> Decimal | None:
    return abs(value) if value is not None else None


def _decision_key(
    prefix: str,
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
) -> str:
    digest = hashlib.sha256(
        (
            f"{task.task_id}:{request.action}:{request.idempotency_key}:"
            f"{_request_fingerprint(request)}"
        ).encode()
    ).hexdigest()[:20]
    return f"{prefix}:{task.task_id}:{digest}"


def _decision_key_for_type(
    prefix: str,
    task: AccountingReconciliationTask,
    request: AccountingReviewDecisionRequest,
) -> str:
    return _decision_key(prefix, task, request)


def _decision_key_prefix(decision_type: str, action: str) -> str:
    if decision_type == "accounting_transfer_link":
        return "transfer"
    if decision_type == "accounting_external_cashflow_classification":
        return "cashflow"
    if decision_type == "accounting_import_approval":
        return "import"
    if decision_type == "accounting_cost_basis_decision":
        return "basis"
    raise AccountingReviewError(f"unsupported accounting action {action!r}")


def _decision_key_value(decision: object) -> str | None:
    if isinstance(decision, AccountingTransferLink):
        return decision.link_group_key
    if isinstance(decision, AccountingExternalCashflowClassification):
        return decision.classification_key
    if isinstance(decision, AccountingImportApproval):
        return decision.approval_key
    if isinstance(decision, AccountingCostBasisDecision):
        return decision.basis_key
    return None


def _request_fingerprint(request: AccountingReviewDecisionRequest) -> str:
    payload = request.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _required_string(evidence: dict, key: str) -> str:
    value = evidence.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AccountingReviewError(f"import approval evidence missing {key}")
    return value


def _required_string_list(evidence: dict, key: str) -> list[str]:
    values = evidence.get(key)
    if not isinstance(values, list) or not values:
        raise AccountingReviewError(f"import approval evidence missing {key}")
    strings = [str(value).strip() for value in values]
    if any(not value for value in strings):
        raise AccountingReviewError(f"import approval evidence has empty {key}")
    return strings


def _required_datetime(evidence: dict, key: str) -> datetime:
    value = evidence.get(key)
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str) and value.strip():
        return _utc(datetime.fromisoformat(value))
    raise AccountingReviewError(f"import approval evidence missing {key}")


def _has_manual_basis_value(details: ManualCostBasisDecision | None) -> bool:
    if details is None:
        return False
    if details.cost_basis_usd is not None and details.cost_basis_usd < Decimal("0"):
        raise AccountingReviewError("manual_cost_basis cost_basis_usd must be >= 0")
    if details.quantity is not None and details.quantity <= Decimal("0"):
        raise AccountingReviewError("manual_cost_basis quantity must be > 0")
    if details.unit_cost_usd is not None and details.unit_cost_usd < Decimal("0"):
        raise AccountingReviewError("manual_cost_basis unit_cost_usd must be >= 0")
    if (
        details.cost_basis_usd is not None
        and details.quantity is not None
        and details.unit_cost_usd is not None
    ):
        expected = (details.quantity * details.unit_cost_usd).quantize(
            Decimal("0.000001")
        )
        if details.cost_basis_usd != expected:
            raise AccountingReviewError(
                "manual_cost_basis total must match quantity * unit_cost_usd"
            )
    return details.cost_basis_usd is not None or (
        details.quantity is not None and details.unit_cost_usd is not None
    )
