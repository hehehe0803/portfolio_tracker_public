from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

STABLE_QUOTES = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "DAI"}
ASTER_AMOUNT_RE = re.compile(
    r"^\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s+([A-Za-z0-9]+)\s*$"
)


@dataclass(frozen=True)
class CryptoCsvLedgerEntry:
    institution: str
    tx_type: str
    asset_symbol: str
    asset_type: str
    quantity: Decimal
    price_usd: Decimal | None
    total_usd: Decimal | None
    fee: Decimal
    fee_currency: str
    timestamp: datetime
    fingerprint: str
    raw_data: dict


class CryptoCsvParserError(ValueError):
    pass


def _decimal(value: str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    return Decimal(text)


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key)
    if value is None or not str(value).strip():
        raise CryptoCsvParserError(f"Missing required CSV column value: {key}")
    return str(value).strip()


def _fingerprint(source_type: str, *parts: object) -> str:
    raw = "|".join([source_type, *(str(part) for part in parts)])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _read_rows(csv_text: str | bytes) -> list[dict[str, str]]:
    text = csv_text.decode("utf-8-sig") if isinstance(csv_text, bytes) else csv_text
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CryptoCsvParserError("CSV has no header row")
    return [dict(row) for row in reader]


def _parse_aster_timestamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _parse_hyperliquid_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.isdigit():
        epoch = int(text)
        if epoch > 10_000_000_000:
            epoch /= 1000
        return datetime.fromtimestamp(epoch, tz=UTC)
    if text.endswith("Z"):
        return datetime.fromisoformat(text[:-1] + "+00:00").astimezone(UTC)
    if "T" in text:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return datetime.strptime(text, "%m/%d/%Y - %H:%M:%S").replace(tzinfo=UTC)


def _parse_aster_amount(value: str) -> tuple[Decimal, str]:
    match = ASTER_AMOUNT_RE.match(value)
    if not match:
        raise CryptoCsvParserError(f"Unable to parse Aster amount: {value}")
    return Decimal(match.group(1).replace(",", "")), match.group(2).upper()


def _asset_type(symbol: str) -> str:
    return "stablecoin" if symbol.upper() in STABLE_QUOTES else "crypto"


def _aster_transfer_entry(row: dict[str, str], row_index: int) -> CryptoCsvLedgerEntry:
    timestamp = _parse_aster_timestamp(_required(row, "Time"))
    amount, asset = _parse_aster_amount(_required(row, "Amount"))
    return CryptoCsvLedgerEntry(
        institution="aster",
        tx_type="aster_transfer_candidate",
        asset_symbol=asset,
        asset_type=_asset_type(asset),
        quantity=amount,
        price_usd=None,
        total_usd=amount if asset in STABLE_QUOTES else None,
        fee=Decimal("0"),
        fee_currency="USD",
        timestamp=timestamp,
        fingerprint=_fingerprint(
            "aster_transfer",
            timestamp.isoformat(),
            asset,
            amount,
            row_index,
        ),
        raw_data={
            "source_type": "aster_csv",
            "row_type": _required(row, "Type"),
            "custody_movement_candidate": True,
            "raw_amount": _required(row, "Amount"),
            "symbol_column": row.get("Symbol") or "",
        },
    )


def _build_aster_trade_entry(
    timestamp: datetime,
    legs: list[tuple[int, dict[str, str], Decimal, str]],
) -> CryptoCsvLedgerEntry | None:
    net_by_asset: dict[str, Decimal] = defaultdict(Decimal)
    for _, _, amount, asset in legs:
        net_by_asset[asset] += amount

    base_candidates = [
        (asset, quantity)
        for asset, quantity in net_by_asset.items()
        if asset not in STABLE_QUOTES and quantity != 0
    ]
    quote_candidates = [
        (asset, quantity)
        for asset, quantity in net_by_asset.items()
        if asset in STABLE_QUOTES and quantity != 0
    ]
    if len(base_candidates) != 1 or len(quote_candidates) != 1:
        return None

    base_asset, base_quantity = base_candidates[0]
    quote_asset, quote_quantity = quote_candidates[0]
    side = "buy" if base_quantity > 0 else "sell"
    quantity = abs(base_quantity)
    quote_abs = abs(quote_quantity)
    price_usd = (
        quote_abs / quantity if quote_asset in STABLE_QUOTES and quantity else None
    )
    total_usd = quote_abs if quote_asset in STABLE_QUOTES else None
    raw_leg_amounts = [
        {"row_index": row_index, "amount": str(amount), "asset": asset}
        for row_index, _, amount, asset in legs
    ]

    return CryptoCsvLedgerEntry(
        institution="aster",
        tx_type="aster_trade",
        asset_symbol=base_asset,
        asset_type="crypto",
        quantity=quantity,
        price_usd=price_usd,
        total_usd=total_usd,
        fee=Decimal("0"),
        fee_currency=quote_asset,
        timestamp=timestamp,
        fingerprint=_fingerprint(
            "aster_trade",
            timestamp.isoformat(),
            base_asset,
            base_quantity,
            quote_asset,
            quote_quantity,
            len(legs),
        ),
        raw_data={
            "source_type": "aster_csv",
            "side": side,
            "base_asset": base_asset,
            "signed_base_quantity": str(base_quantity),
            "quote_asset": quote_asset,
            "quote_quantity": str(quote_abs),
            "signed_quote_quantity": str(quote_quantity),
            "grouped_leg_count": len(legs),
            "legs": raw_leg_amounts,
        },
    )


def _aster_trade_leg_entry(
    timestamp: datetime,
    row: dict[str, str],
    row_index: int,
    amount: Decimal,
    asset: str,
) -> CryptoCsvLedgerEntry:
    return CryptoCsvLedgerEntry(
        institution="aster",
        tx_type="aster_trade_leg",
        asset_symbol=asset,
        asset_type=_asset_type(asset),
        quantity=amount,
        price_usd=None,
        total_usd=amount if asset in STABLE_QUOTES else None,
        fee=Decimal("0"),
        fee_currency="USD",
        timestamp=timestamp,
        fingerprint=_fingerprint(
            "aster_trade_leg",
            timestamp.isoformat(),
            asset,
            amount,
            row_index,
        ),
        raw_data={
            "source_type": "aster_csv",
            "row_type": _required(row, "Type"),
            "raw_amount": _required(row, "Amount"),
            "grouped": False,
        },
    )


def parse_aster_csv(csv_text: str | bytes) -> list[CryptoCsvLedgerEntry]:
    rows = _read_rows(csv_text)
    entries: list[CryptoCsvLedgerEntry] = []
    trade_groups: dict[datetime, list[tuple[int, dict[str, str], Decimal, str]]] = (
        defaultdict(list)
    )

    for row_index, row in enumerate(rows, start=1):
        row_type = _required(row, "Type").strip().lower()
        if row_type == "transfer":
            entries.append(_aster_transfer_entry(row, row_index))
            continue
        if row_type == "trade":
            timestamp = _parse_aster_timestamp(_required(row, "Time"))
            amount, asset = _parse_aster_amount(_required(row, "Amount"))
            trade_groups[timestamp].append((row_index, row, amount, asset))
            continue
        raise CryptoCsvParserError(f"Unsupported Aster row type: {row.get('Type')}")

    for timestamp in sorted(trade_groups, reverse=True):
        legs = trade_groups[timestamp]
        grouped = _build_aster_trade_entry(timestamp, legs)
        if grouped is not None:
            entries.append(grouped)
            continue
        entries.extend(
            _aster_trade_leg_entry(timestamp, row, row_index, amount, asset)
            for row_index, row, amount, asset in legs
        )

    return entries


def _split_pair(pair: str) -> tuple[str, str]:
    parts = [part.strip().upper() for part in pair.split("/")]
    if len(parts) != 2 or not all(parts):
        raise CryptoCsvParserError(f"Unsupported Hyperliquid pair: {pair}")
    return parts[0], parts[1]


def _get_first(row: dict[str, Any], *keys: str) -> str | None:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def parse_hyperliquid_ledger_csv(csv_text: str | bytes) -> list[CryptoCsvLedgerEntry]:
    """Parse Hyperliquid non-funding ledger/deposit export rows.

    Hyperliquid deposit data may arrive as a UI CSV or as a CSV converted from
    the `userNonFundingLedgerUpdates` Info API. Keep this parser intentionally
    narrow: custody movements become candidate rows for review/reconciliation;
    derivative fills stay in `parse_hyperliquid_csv`.
    """
    entries: list[CryptoCsvLedgerEntry] = []
    for row_index, row in enumerate(_read_rows(csv_text), start=1):
        movement = (
            _get_first(row, "type", "kind", "delta_type", "delta.type") or ""
        ).lower()
        if "deposit" in movement:
            canonical_movement = "deposit"
        elif "withdraw" in movement:
            canonical_movement = "withdrawal"
        else:
            raise CryptoCsvParserError(
                f"Unsupported Hyperliquid ledger row type: {movement or row}"
            )

        raw_time = _get_first(row, "time", "timestamp", "datetime", "created_at")
        raw_asset = _get_first(row, "coin", "asset", "token", "currency")
        raw_amount = _get_first(row, "amount", "delta", "sz", "quantity")
        if raw_time is None or raw_asset is None or raw_amount is None:
            raise CryptoCsvParserError("Missing Hyperliquid ledger time/asset/amount")

        timestamp = _parse_hyperliquid_timestamp(raw_time)
        asset = raw_asset.upper()
        amount = _decimal(raw_amount)
        if amount is None:
            raise CryptoCsvParserError("Missing numeric Hyperliquid ledger amount")
        quantity = abs(amount) if canonical_movement == "deposit" else -abs(amount)
        external_id = _get_first(
            row,
            "hash",
            "tx_hash",
            "txhash",
            "transaction_hash",
            "id",
        )

        entries.append(
            CryptoCsvLedgerEntry(
                institution="hyperliquid",
                tx_type=f"hyperliquid_{canonical_movement}_candidate",
                asset_symbol=asset,
                asset_type=_asset_type(asset),
                quantity=quantity,
                price_usd=None,
                total_usd=quantity if asset in STABLE_QUOTES else None,
                fee=Decimal("0"),
                fee_currency="USD",
                timestamp=timestamp,
                fingerprint=_fingerprint(
                    f"hyperliquid_{canonical_movement}",
                    timestamp.isoformat(),
                    asset,
                    quantity,
                    external_id or "",
                    row_index,
                ),
                raw_data={
                    "source_type": "hyperliquid_ledger_csv",
                    "movement": canonical_movement,
                    "custody_movement_candidate": True,
                    "external_id": external_id,
                    "raw_amount": raw_amount,
                    "schema": "partial",
                },
            )
        )
    return entries


def parse_hyperliquid_csv(csv_text: str | bytes) -> list[CryptoCsvLedgerEntry]:
    entries: list[CryptoCsvLedgerEntry] = []
    for row_index, row in enumerate(_read_rows(csv_text), start=1):
        timestamp = _parse_hyperliquid_timestamp(_required(row, "time"))
        base_asset, quote_asset = _split_pair(_required(row, "coin"))
        side = _required(row, "dir").lower()
        if side not in {"buy", "sell"}:
            raise CryptoCsvParserError(
                f"Unsupported Hyperliquid direction: {row.get('dir')}"
            )
        price = _decimal(_required(row, "px"))
        size = _decimal(_required(row, "sz"))
        notional = _decimal(_required(row, "ntl"))
        fee = _decimal(_required(row, "fee")) or Decimal("0")
        closed_pnl = _decimal(row.get("closedPnl"))
        if price is None or size is None or notional is None:
            raise CryptoCsvParserError("Missing numeric Hyperliquid fill value")

        signed_base_quantity = size if side == "buy" else -size
        entries.append(
            CryptoCsvLedgerEntry(
                institution="hyperliquid",
                tx_type="hyperliquid_derivative_fill",
                asset_symbol=base_asset,
                asset_type="derivative",
                quantity=size,
                price_usd=price if quote_asset in STABLE_QUOTES else None,
                total_usd=notional if quote_asset in STABLE_QUOTES else None,
                fee=fee,
                fee_currency=quote_asset,
                timestamp=timestamp,
                fingerprint=_fingerprint(
                    "hyperliquid_derivative_fill",
                    timestamp.isoformat(),
                    base_asset,
                    quote_asset,
                    side,
                    size,
                    price,
                    notional,
                    fee,
                    closed_pnl,
                    row_index,
                ),
                raw_data={
                    "source_type": "hyperliquid_csv",
                    "side": side,
                    "base_asset": base_asset,
                    "quote_asset": quote_asset,
                    "signed_base_quantity": str(signed_base_quantity),
                    "notional": str(notional),
                    "closed_pnl": str(closed_pnl) if closed_pnl is not None else None,
                    "raw_coin": _required(row, "coin"),
                },
            )
        )
    return entries
