from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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
