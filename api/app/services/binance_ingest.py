from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityLog, ImportArtifact, Transaction
from app.services.binance_export_parser import (
    BinanceLedgerEntry,
    parse_binance_exports,
    summarize_binance_entries,
)

logger = logging.getLogger(__name__)


def _entry_to_db(entry: BinanceLedgerEntry, import_id: int) -> Transaction:
    return Transaction(
        institution="binance",
        tx_type=entry.tx_type,
        asset_symbol=entry.asset_symbol,
        asset_type=entry.asset_type,
        quantity=entry.quantity,
        price_usd=entry.price_usd,
        total_usd=entry.total_usd,
        fee=entry.fee,
        fee_currency=entry.fee_currency,
        timestamp=entry.timestamp or datetime.now(UTC),
        fingerprint=entry.fingerprint,
        raw_data=entry.raw_data,
        import_id=import_id,
    )


def _serialize_preview_summary(summary: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in summary.items():
        if isinstance(value, dict):
            serialized[key] = {
                nested_key: float(nested_value)
                if hasattr(nested_value, "quantize")
                else nested_value
                for nested_key, nested_value in value.items()
            }
        elif hasattr(value, "quantize"):
            serialized[key] = float(value)
        else:
            serialized[key] = value
    return serialized


async def _existing_fingerprints(
    session: AsyncSession, fingerprints: list[str]
) -> set[str]:
    if not fingerprints:
        return set()
    result = await session.execute(
        select(Transaction.fingerprint).where(Transaction.fingerprint.in_(fingerprints))
    )
    return {row[0] for row in result.all()}


async def parse_binance_file(
    file_bytes: bytes, filename: str, session: AsyncSession
) -> ImportArtifact:
    suffix = Path(filename).suffix.lower().lstrip(".") or "zip"
    if suffix == "csv" and "UTC" not in filename.upper():
        raise ValueError(
            "Direct Binance CSV uploads must use the original Binance filename "
            "with timezone marker"
        )
    artifact = ImportArtifact(
        institution="binance",
        filename=filename,
        file_type=suffix,
        file_data=file_bytes,
        status="parsing",
    )
    session.add(artifact)
    await session.flush()

    try:
        entries = parse_binance_exports([(filename, file_bytes)])
        if not entries:
            raise ValueError("Binance export contained no importable rows")
        fingerprints = [entry.fingerprint for entry in entries]
        existing = await _existing_fingerprints(session, fingerprints)
        new_entries = [entry for entry in entries if entry.fingerprint not in existing]
        summary = summarize_binance_entries(entries)

        artifact.status = "reviewed"
        artifact.parsed_count = len(entries)
        artifact.duplicate_count = len(entries) - len(new_entries)
        artifact.parse_preview = {
            "total_parsed": len(entries),
            "new": len(new_entries),
            "duplicates": len(entries) - len(new_entries),
            "sample": [
                {
                    "timestamp": entry.timestamp.isoformat()
                    if entry.timestamp
                    else None,
                    "type": entry.tx_type,
                    "asset": entry.asset_symbol,
                    "quantity": float(entry.quantity),
                    "source_type": entry.raw_data.get("source_type"),
                }
                for entry in new_entries[:10]
            ],
            "summary": _serialize_preview_summary(summary),
        }
        await session.commit()
        return artifact
    except Exception as exc:
        artifact.status = "failed"
        artifact.error_msg = str(exc)
        await session.commit()
        logger.error("Binance parse failed for %s: %s", filename, exc)
        raise


async def confirm_binance_import(
    artifact_id: int, session: AsyncSession
) -> dict[str, int]:
    artifact = (
        await session.execute(
            select(ImportArtifact).where(ImportArtifact.id == artifact_id)
        )
    ).scalar_one_or_none()
    if not artifact:
        raise ValueError(f"ImportArtifact {artifact_id} not found")
    if artifact.status not in {"reviewed"}:
        raise ValueError(
            "Import "
            f"{artifact_id} is not in 'reviewed' state "
            f"(current: {artifact.status})"
        )

    entries = parse_binance_exports([(artifact.filename, artifact.file_data)])
    fingerprints = [entry.fingerprint for entry in entries]
    existing = await _existing_fingerprints(session, fingerprints)

    committed = 0
    for entry in entries:
        if entry.fingerprint in existing:
            continue
        session.add(_entry_to_db(entry, artifact.id))
        committed += 1

    artifact.status = "committed"
    artifact.committed_count = committed
    artifact.committed_at = datetime.now(UTC)
    session.add(
        ActivityLog(
            source="imports.binance_baseline",
            status="confirmed",
            message=(
                "Confirmed Binance export baseline import. "
                "API delta sync may extend this baseline."
            ),
            artifact_id=artifact.id,
        )
    )
    await session.commit()
    return {
        "committed": committed,
        "duplicates_skipped": len(entries) - committed,
        "artifact_id": artifact_id,
    }
