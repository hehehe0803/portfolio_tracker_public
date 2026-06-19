"""
XTB ingest service: wrap existing XTB XLSX parser and persist to DB.
Flow: upload → parse preview → user confirms → commit.
"""

import hashlib
import logging
import os
import re
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ImportArtifact, Transaction
from app.services.xtb_parser import TransactionType as XTBTxType
from app.services.xtb_parser import XTBTransaction, parse_xtb_statement

logger = logging.getLogger(__name__)

ASSET_TYPE_MAP: dict[str, str] = {
    "XAUUSD": "commodity",
    "GOLD": "commodity",
    "EURUSD": "fiat",
    "GBPUSD": "fiat",
    "USDJPY": "fiat",
    "BTC": "crypto",
    "ETH": "crypto",
    "BNB": "crypto",
}

XTB_TO_SIDE = {
    XTBTxType.OPEN_POSITION: "buy",
    XTBTxType.CLOSE_POSITION: "sell",
    XTBTxType.DEPOSIT: "deposit",
    XTBTxType.WITHDRAWAL: "withdrawal",
    XTBTxType.DIVIDEND: "dividend",
    XTBTxType.COMMISSION: "fee",
    XTBTxType.STAMP_DUTY: "fee",
    XTBTxType.SWAP: "fee",
}

XTB_CASHFLOW_TYPES = {
    XTBTxType.DEPOSIT,
    XTBTxType.WITHDRAWAL,
    XTBTxType.DIVIDEND,
    XTBTxType.COMMISSION,
    XTBTxType.SWAP,
    XTBTxType.STAMP_DUTY,
}


XTB_SHARE_COUNT_RE = re.compile(
    r"^(?:OPEN|CLOSE)\s+(?:BUY|SELL)\s+([0-9]+(?:\.[0-9]+)?(?:/[0-9]+(?:\.[0-9]+)?)?)\b",
    re.IGNORECASE,
)

# Patterns for special XTB rows.
SPLIT_HINT_RE = re.compile(r"\bsplit\b", re.IGNORECASE)
SPLIT_RATIO_RE = re.compile(
    r"\bsplit\s+([0-9]+(?:\.[0-9]+)?)\s+for\s+([0-9]+(?:\.[0-9]+)?)\b",
    re.IGNORECASE,
)
CORRECTION_RE = re.compile(r"^corr\b", re.IGNORECASE)


def _parse_bytes(
    file_bytes: bytes, filename: str, *, pdf_password: str | None = None
) -> list[XTBTransaction]:
    """Write bytes to a temp file, parse, then delete."""
    suffix = Path(filename).suffix.lower() or ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name
    try:
        return parse_xtb_statement(tmp_path, pdf_password=pdf_password)
    finally:
        os.unlink(tmp_path)


def _infer_asset_type(symbol: str) -> str:
    sym = symbol.upper()
    for k, v in ASSET_TYPE_MAP.items():
        if k in sym:
            return v
    # Forex pairs (6 letters, no numbers) → fiat derivative
    if len(sym) == 6 and sym.isalpha():
        return "equity"
    if sym.endswith("USD") and len(sym) <= 10:
        return "crypto"
    return "equity"


def _has_split_hint(description: str | None) -> bool:
    if not description:
        return False
    return bool(SPLIT_HINT_RE.search(description.strip()))


def _is_correction_description(description: str | None) -> bool:
    if not description:
        return False
    return bool(CORRECTION_RE.match(description.strip()))


def _is_split(xtx: XTBTransaction) -> bool:
    return _parse_split_ratio(xtx.description or "") is not None


def _parse_split_ratio(description: str) -> Decimal | None:
    if not description:
        return None

    match = SPLIT_RATIO_RE.search(description.strip())
    if not match:
        return None

    try:
        numerator = Decimal(match.group(1))
        denominator = Decimal(match.group(2))
    except Exception:
        return None

    if denominator <= 0 or numerator <= 0:
        return None

    return numerator / denominator


def _validate_supported_split_description(xtx: XTBTransaction) -> None:
    description = xtx.description or ""
    if _has_split_hint(description) and _parse_split_ratio(description) is None:
        raise ValueError(f"Unsupported XTB split description: {description}")


def _normalized_xtb_type(xtx: XTBTransaction) -> str:
    if _is_correction_description(xtx.description or ""):
        return "correction"
    if _is_split(xtx):
        return "split"
    return XTB_TO_SIDE.get(
        xtx.tx_type,
        xtx.tx_type.value if hasattr(xtx.tx_type, "value") else str(xtx.tx_type),
    )


def _split_fingerprint(*, timestamp: datetime, symbol: str, description: str) -> str:
    ts_normalized = _normalize_xtb_timestamp(timestamp).replace(second=0, microsecond=0)
    payload = (
        f"XTB:split:{ts_normalized.isoformat()}:{symbol.upper()}:"
        f"{description.strip()}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _split_dedupe_key(*, timestamp: datetime, symbol: str, description: str) -> str:
    ts_normalized = _normalize_xtb_timestamp(timestamp).replace(second=0, microsecond=0)
    return (
        f"{ts_normalized.isoformat()}::{symbol.upper()}::"
        f"{description.strip().lower()}"
    )


def _normalized_fingerprint(xtx: XTBTransaction) -> str:
    if not _is_split(xtx):
        return xtx.get_fingerprint()
    return _split_fingerprint(
        timestamp=xtx.date,
        symbol=xtx.symbol or "UNKNOWN",
        description=xtx.description or "",
    )


def _is_split_or_correction(xtx: XTBTransaction) -> bool:
    """Detect corrective rows that should be skipped."""
    desc = (xtx.description or "").strip()
    if _is_correction_description(desc):
        return True
    return False


def _parse_share_count_from_description(description: str) -> Decimal | None:
    if not description:
        return None

    match = XTB_SHARE_COUNT_RE.search(description.strip())
    if not match:
        return None

    raw_quantity = match.group(1).split("/", 1)[0]
    try:
        quantity = Decimal(raw_quantity)
    except Exception:
        return None
    return quantity if quantity > 0 else None


def _derive_xtb_quantity_and_price(
    xtx: XTBTransaction,
) -> tuple[Decimal, Decimal | None]:
    quantity = abs(xtx.amount) if xtx.amount else Decimal("0")
    price_usd: Decimal | None = None

    share_count = _parse_share_count_from_description(xtx.description)
    if share_count is None:
        return quantity, price_usd

    quantity = share_count
    if xtx.amount and quantity > 0:
        price_usd = abs(xtx.amount) / quantity

    return quantity, price_usd


def _collapse_duplicate_close_positions(
    transactions: list[XTBTransaction],
) -> list[XTBTransaction]:
    """Prefer cash-operation stock sells over closed-position-sheet rows.

    Newer XTB XLSX exports include both:
    - Cash Operations "Stock sell" rows with gross sale cashflow
      (description contains '@')
    - Closed Positions rows with realized P/L for the same trade

    For holdings reconciliation we want the cash-operation sell rows.
    When a file contains any close-position descriptions with '@',
    treat those as the authoritative sell feed and drop the
    closed-position-sheet rows with parsed share quantities.
    """
    grouped: dict[tuple[datetime, str, Decimal], list[XTBTransaction]] = (
        defaultdict(list)
    )
    passthrough: list[XTBTransaction] = []

    for tx in transactions:
        if tx.tx_type != XTBTxType.CLOSE_POSITION:
            passthrough.append(tx)
            continue

        qty = _parse_share_count_from_description(tx.description)
        if qty is None or not tx.symbol or not isinstance(tx.date, datetime):
            passthrough.append(tx)
            continue

        key = (tx.date.replace(second=0, microsecond=0), tx.symbol.upper(), qty)
        grouped[key].append(tx)

    has_cash_operation_close_rows = any(
        '@' in (tx.description or '')
        for group in grouped.values()
        for tx in group
    )

    deduped_close_positions: list[XTBTransaction] = []
    for group in grouped.values():
        cash_operation_rows = [tx for tx in group if '@' in (tx.description or '')]
        if cash_operation_rows:
            deduped_close_positions.extend(cash_operation_rows)
        elif not has_cash_operation_close_rows:
            deduped_close_positions.extend(group)

    return passthrough + deduped_close_positions


def _normalize_xtb_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _xtb_tx_to_db(
    xtx: XTBTransaction,
    import_id: int,
) -> Transaction:
    is_split = _is_split(xtx)
    tx_type_str = _normalized_xtb_type(xtx)
    symbol = (xtx.symbol or "UNKNOWN").upper()[:20]
    qty, price_usd = _derive_xtb_quantity_and_price(xtx)
    total_usd = xtx.amount
    if is_split:
        split_ratio = _parse_split_ratio(xtx.description)
        if split_ratio is None:
            raise ValueError(f"Unable to parse XTB split ratio from: {xtx.description}")
        qty = split_ratio
        price_usd = None
        total_usd = None
    # Cashflow rows should always hit the account currency rather than the
    # quoted equity ticker.
    if xtx.tx_type in XTB_CASHFLOW_TYPES:
        symbol = (xtx.currency or "USD").upper()[:20]
        price_usd = None
    # For deposits/withdrawals or cash ops with no symbol, use currency as asset
    elif not xtx.symbol or symbol == "UNKNOWN":
        if xtx.currency:
            symbol = xtx.currency.upper()[:20]

    return Transaction(
        institution="xtb",
        tx_type=tx_type_str,
        asset_symbol=symbol,
        asset_type=_infer_asset_type(symbol),
        quantity=qty,
        price_usd=price_usd,
        total_usd=total_usd,
        fee=Decimal("0"),
        fee_currency=xtx.currency or "USD",
        timestamp=_normalize_xtb_timestamp(xtx.date)
        if isinstance(xtx.date, datetime)
        else datetime.combine(xtx.date, datetime.min.time(), tzinfo=UTC)
        if xtx.date
        else datetime.now(UTC),
        fingerprint=_normalized_fingerprint(xtx),
        raw_data={
            "id": xtx.id,
            "description": xtx.description,
            "currency": xtx.currency,
            "original_type": xtx.tx_type.value
            if hasattr(xtx.tx_type, "value")
            else str(xtx.tx_type),
        },
        import_id=import_id,
    )


async def _existing_split_keys(session: AsyncSession) -> set[str]:
    result = await session.execute(
        select(Transaction).where(Transaction.institution == "xtb")
    )
    transactions = result.scalars().all()
    keys: set[str] = set()
    for tx in transactions:
        description = str(tx.raw_data.get("description") or "").strip()
        if not description:
            continue
        if _is_correction_description(description):
            continue
        if _parse_split_ratio(description) is None:
            continue
        keys.add(
            _split_dedupe_key(
                timestamp=tx.timestamp,
                symbol=tx.asset_symbol,
                description=description,
            )
        )
    return keys


async def _repair_legacy_xtb_split_transactions(session: AsyncSession) -> int:
    result = await session.execute(
        select(Transaction)
        .where(Transaction.institution == "xtb")
        .order_by(Transaction.timestamp.asc(), Transaction.id.asc())
    )
    transactions = result.scalars().all()
    repaired = 0
    seen_split_events: set[str] = set()
    seen_fingerprints = {
        tx.fingerprint
        for tx in transactions
        if _parse_split_ratio(str(tx.raw_data.get("description") or "").strip()) is None
        or _is_correction_description(str(tx.raw_data.get("description") or "").strip())
    }

    for tx in transactions:
        description = str(tx.raw_data.get("description") or "").strip()
        if not description:
            continue
        if _is_correction_description(description):
            continue

        split_ratio = _parse_split_ratio(description)
        if split_ratio is None:
            if _has_split_hint(description):
                raise ValueError(f"Unsupported legacy XTB split description: {description}")
            continue

        split_event_key = _split_dedupe_key(
            timestamp=tx.timestamp,
            symbol=tx.asset_symbol,
            description=description,
        )
        normalized_fingerprint = _split_fingerprint(
            timestamp=tx.timestamp,
            symbol=tx.asset_symbol,
            description=description,
        )

        if split_event_key in seen_split_events or (
            normalized_fingerprint in seen_fingerprints
            and tx.fingerprint != normalized_fingerprint
        ):
            await session.delete(tx)
            repaired += 1
            continue

        seen_split_events.add(split_event_key)
        seen_fingerprints.add(normalized_fingerprint)

        normalized_timestamp = _normalize_xtb_timestamp(tx.timestamp)
        needs_update = (
            tx.tx_type != "split"
            or tx.quantity != split_ratio
            or tx.price_usd is not None
            or tx.total_usd is not None
            or tx.fingerprint != normalized_fingerprint
            or tx.timestamp != normalized_timestamp
        )
        if not needs_update:
            continue

        tx.tx_type = "split"
        tx.quantity = split_ratio
        tx.price_usd = None
        tx.total_usd = None
        tx.timestamp = normalized_timestamp
        tx.fingerprint = normalized_fingerprint
        repaired += 1

    return repaired


async def repair_xtb_split_transactions(session: AsyncSession) -> int:
    return await _repair_legacy_xtb_split_transactions(session)


def dedupe_xtb_transactions(
    transactions: list[XTBTransaction],
    existing_fingerprints: set[str],
    existing_split_keys: set[str] | None = None,
) -> list[XTBTransaction]:
    collapsed = _collapse_duplicate_close_positions(transactions)
    existing_split_keys = existing_split_keys or set()
    seen_fingerprints = set(existing_fingerprints)
    seen_split_keys = set(existing_split_keys)
    deduped: list[XTBTransaction] = []
    for tx in collapsed:
        if _is_split_or_correction(tx):
            continue
        _validate_supported_split_description(tx)
        fingerprint = _normalized_fingerprint(tx)
        if fingerprint in seen_fingerprints:
            continue
        split_key: str | None = None
        if _is_split(tx):
            split_key = _split_dedupe_key(
                timestamp=tx.date,
                symbol=tx.symbol or "UNKNOWN",
                description=tx.description or "",
            )
            if split_key in seen_split_keys:
                continue
        deduped.append(tx)
        seen_fingerprints.add(fingerprint)
        if split_key is not None:
            seen_split_keys.add(split_key)
    return deduped


def summarize_xtb_transactions(transactions: list[XTBTransaction]) -> dict[str, Any]:
    by_type: dict[str, Decimal] = {}
    gross_amount = Decimal("0")

    for tx in transactions:
        tx_type = _normalized_xtb_type(tx)
        by_type[tx_type] = by_type.get(tx_type, Decimal("0")) + tx.amount
        if tx_type != "split":
            gross_amount += abs(tx.amount)

    return {
        "count": len(transactions),
        "gross_amount": gross_amount,
        "by_type": by_type,
    }


async def parse_xtb_file(
    file_bytes: bytes,
    filename: str,
    session: AsyncSession,
    *,
    pdf_password: str | None = None,
) -> ImportArtifact:
    """
    Parse an XTB statement file and create an ImportArtifact with preview data.
    Does NOT commit transactions yet – caller must call confirm_import().
    """
    suffix = Path(filename).suffix.lower().lstrip(".") or "xlsx"
    artifact = ImportArtifact(
        institution="xtb",
        filename=filename,
        file_type=suffix,
        file_data=file_bytes,
        status="parsing",
    )
    session.add(artifact)
    await session.flush()  # get artifact.id

    try:
        transactions = _parse_bytes(file_bytes, filename, pdf_password=pdf_password)

        # Check for duplicates against existing fingerprints
        fps = [_normalized_fingerprint(tx) for tx in transactions]
        existing = set()
        existing_split_keys = await _existing_split_keys(session)
        if fps:
            result = await session.execute(
                select(Transaction.fingerprint).where(Transaction.fingerprint.in_(fps))
            )
            existing = {row[0] for row in result.all()}

        new_txs = dedupe_xtb_transactions(transactions, existing, existing_split_keys)
        dup_count = len(transactions) - len(new_txs)
        summary = summarize_xtb_transactions(transactions)

        artifact.status = "reviewed"
        artifact.parsed_count = len(transactions)
        artifact.duplicate_count = dup_count
        artifact.parse_preview = {
            "total_parsed": len(transactions),
            "new": len(new_txs),
            "duplicates": dup_count,
            "sample": [
                {
                    "id": tx.id,
                    "date": str(tx.date),
                    "type": _normalized_xtb_type(tx),
                    "symbol": tx.symbol,
                    "amount": float(tx.amount) if tx.amount else None,
                    "fingerprint": _normalized_fingerprint(tx),
                    "description": tx.description,
                }
                for tx in new_txs[:10]
            ],
            "summary": {
                "gross_amount": float(summary["gross_amount"]),
                "by_type": {
                    key: float(value) for key, value in summary["by_type"].items()
                },
            },
        }
        await session.commit()
        return artifact

    except Exception as e:
        artifact.status = "failed"
        artifact.error_msg = str(e)
        await session.commit()
        logger.error(f"XTB parse failed for {filename}: {e}")
        raise


async def confirm_import(artifact_id: int, session: AsyncSession) -> dict:
    """
    Commit parsed XTB transactions to the DB.
    Skips duplicates via fingerprint constraint.
    """
    result = await session.execute(
        select(ImportArtifact).where(ImportArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if not artifact:
        raise ValueError(f"ImportArtifact {artifact_id} not found")
    if artifact.status not in ("reviewed",):
        raise ValueError(
            f"Import {artifact_id} is not in 'reviewed' state "
            f"(current: {artifact.status})"
        )

    await _repair_legacy_xtb_split_transactions(session)

    transactions = _parse_bytes(artifact.file_data, artifact.filename)

    fps = [_normalized_fingerprint(tx) for tx in transactions]
    existing = set()
    existing_split_keys = await _existing_split_keys(session)
    if fps:
        result2 = await session.execute(
            select(Transaction.fingerprint).where(Transaction.fingerprint.in_(fps))
        )
        existing = {row[0] for row in result2.all()}

    committed = 0
    for xtx in dedupe_xtb_transactions(transactions, existing, existing_split_keys):
        db_tx = _xtb_tx_to_db(xtx, artifact.id)
        session.add(db_tx)
        committed += 1

    artifact.status = "committed"
    artifact.committed_count = committed
    artifact.committed_at = datetime.now(UTC)
    await session.commit()

    return {
        "committed": committed,
        "duplicates_skipped": len(transactions) - committed,
        "artifact_id": artifact_id,
    }
