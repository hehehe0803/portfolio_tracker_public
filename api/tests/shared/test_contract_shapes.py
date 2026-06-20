# ruff: noqa: S101

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from shared.python.contracts import (
    AccountingReviewDecisionRequest,
    AccountingReviewDecisionResponse,
    AccountingReviewQueue,
    AccountingReviewTask,
    AlertEventContract,
    AlertRuleContract,
    AssetDetailContract,
    AssetSnapshot,
    DashboardContract,
    ImportArtifactContract,
    IngestionEvent,
    NoteContract,
    TagContract,
    TransactionRecord,
)


def test_python_contracts_expose_expected_fields():
    assert set(AssetSnapshot.model_fields) >= {
        "symbol",
        "asset_type",
        "institution",
        "quantity",
        "current_price_usd",
        "current_value_usd",
    }
    assert set(TransactionRecord.model_fields) >= {
        "institution",
        "tx_type",
        "asset_symbol",
        "asset_type",
        "quantity",
        "timestamp",
        "fingerprint",
    }
    assert set(ImportArtifactContract.model_fields) >= {
        "institution",
        "filename",
        "file_type",
        "status",
        "parsed_count",
        "duplicate_count",
    }
    assert set(AlertRuleContract.model_fields) >= {
        "asset_symbol",
        "condition",
        "threshold",
    }
    assert set(AlertEventContract.model_fields) >= {
        "rule_id",
        "message",
        "telegram_delivered",
    }
    assert set(TagContract.model_fields) >= {"name", "color"}
    assert set(NoteContract.model_fields) >= {"entity_type", "entity_id", "content"}
    assert set(IngestionEvent.model_fields) >= {"source", "artifact_id", "status"}
    assert set(AccountingReviewTask.model_fields) >= {
        "task_id",
        "task_type",
        "candidate_actions",
        "affected_metric_scopes",
    }
    assert set(AccountingReviewQueue.model_fields) >= {
        "review_type",
        "allowed_actions",
        "tasks",
    }
    assert set(AccountingReviewDecisionRequest.model_fields) >= {
        "task_id",
        "action",
        "idempotency_key",
        "internal_transfer",
        "cost_basis",
    }
    assert set(AccountingReviewDecisionResponse.model_fields) >= {
        "task_id",
        "task_status",
        "decision_type",
        "decision_id",
        "replayed",
    }
    assert set(DashboardContract.model_fields) >= {
        "current_total_value_usd",
        "rolling_30d",
        "lifetime",
        "confidence_state",
        "asset_type_distribution",
        "cash_reserve",
        "holding_drivers",
        "top_reconciliation_action",
    }
    assert set(AssetDetailContract.model_fields) >= {
        "symbol",
        "current_position",
        "capital_allocated_usd",
        "lifetime",
        "recent_movement",
        "driver_explanation",
        "trust_blockers",
    }


def test_typescript_contracts_define_matching_exports():
    contents = Path("shared/typescript/contracts.ts").read_text()

    for export_name in (
        "AssetSnapshot",
        "TransactionRecord",
        "ImportArtifactContract",
        "AlertRuleContract",
        "AlertEventContract",
        "TagContract",
        "NoteContract",
        "IngestionEvent",
        "AccountingReviewTask",
        "AccountingReviewQueue",
        "InternalTransferDecision",
        "ManualCostBasisDecision",
        "AccountingReviewDecisionRequest",
        "AccountingReviewDecisionResponse",
        "DashboardContract",
        "DashboardRollingPeriod",
        "AssetDetailContract",
        "AssetCurrentPosition",
    ):
        assert f"export interface {export_name}" in contents
    assert "export type AccountingReviewAction" in contents
    assert "export type ConfidenceState" in contents
    assert "'unknown'" in contents


def test_shared_contracts_import_from_api_service_context():
    repo_root = Path(__file__).resolve().parents[3]
    api_dir = repo_root / "api"
    script = (
        "from shared.python.contracts import AssetSnapshot, "
        "AccountingReviewDecisionRequest, DashboardContract, AssetDetailContract; "
        "print(AssetSnapshot.__name__, AccountingReviewDecisionRequest.__name__, "
        "DashboardContract.__name__, AssetDetailContract.__name__)"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        cwd=api_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.strip()
        == "AssetSnapshot AccountingReviewDecisionRequest DashboardContract "
        "AssetDetailContract"
    )
