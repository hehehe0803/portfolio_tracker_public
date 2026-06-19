from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetSnapshot(ContractBaseModel):
    symbol: str
    asset_type: str
    institution: str
    quantity: Decimal
    avg_buy_price_usd: Decimal | None = None
    current_price_usd: Decimal | None = None
    current_value_usd: Decimal | None = None
    total_cost_usd: Decimal | None = None
    unrealized_pnl_usd: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None


class TransactionRecord(ContractBaseModel):
    institution: str
    tx_type: str
    asset_symbol: str
    asset_type: str
    quantity: Decimal
    timestamp: datetime
    fingerprint: str
    price_usd: Decimal | None = None
    total_usd: Decimal | None = None
    fee: Decimal = Field(default=Decimal("0"))
    fee_currency: str = "USD"


class ImportArtifactContract(ContractBaseModel):
    institution: str
    filename: str
    file_type: str
    status: str
    parsed_count: int = 0
    committed_count: int = 0
    duplicate_count: int = 0
    created_at: datetime | None = None


class AlertRuleContract(ContractBaseModel):
    asset_symbol: str
    condition: str
    threshold: Decimal
    is_active: bool = True


class AlertEventContract(ContractBaseModel):
    rule_id: int
    message: str
    telegram_delivered: bool
    triggered_at: datetime | None = None
    delivered_at: datetime | None = None


class TagContract(ContractBaseModel):
    name: str
    color: str
    icon: str | None = None


class NoteContract(ContractBaseModel):
    entity_type: str
    entity_id: str
    content: str
    created_at: datetime | None = None


class IngestionEvent(ContractBaseModel):
    source: str
    artifact_id: int | None = None
    status: str
    message: str | None = None
    created_at: datetime | None = None


AccountingReviewAction = Literal[
    "internal_transfer",
    "personal_withdrawal",
    "import_approval",
    "manual_cost_basis",
    "unknown_cost_basis",
    "unknown",
]


class AccountingReviewTask(ContractBaseModel):
    task_id: str
    task_type: str
    status: str
    severity: str
    source: str
    asset_symbol: str
    quantity: Decimal | None = None
    amount_usd: Decimal | None = None
    occurred_at: datetime
    evidence: dict
    candidate_actions: list[dict]
    affected_metric_scopes: list[str]
    created_at: datetime | None = None


class AccountingReviewQueue(ContractBaseModel):
    review_type: Literal["accounting"] = "accounting"
    allowed_actions: list[AccountingReviewAction]
    tasks: list[AccountingReviewTask]


class InternalTransferDecision(ContractBaseModel):
    to_source: str
    to_evidence_key: str
    to_quantity: Decimal
    fee_quantity: Decimal | None = None
    fee_asset_symbol: str | None = None


class ManualCostBasisDecision(ContractBaseModel):
    quantity: Decimal | None = None
    cost_basis_usd: Decimal | None = None
    unit_cost_usd: Decimal | None = None
    basis_method: str | None = None


class AccountingReviewDecisionRequest(ContractBaseModel):
    task_id: str = Field(min_length=1, max_length=100)
    action: AccountingReviewAction
    idempotency_key: str = Field(min_length=1, max_length=120)
    rationale: str | None = None
    internal_transfer: InternalTransferDecision | None = None
    cost_basis: ManualCostBasisDecision | None = None


class AccountingReviewDecisionResponse(ContractBaseModel):
    task_id: str
    task_status: Literal["resolved"]
    decision_type: str
    decision_id: int
    replayed: bool = False
