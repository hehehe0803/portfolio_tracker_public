from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

NO_DATA_SENTINEL = "No data matches the criteria."
QUOTE_ASSETS = ("USDT", "BUSD", "FDUSD", "USDC", "BTC", "ETH", "BNB")
STABLECOINS = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "DAI"}
MAX_ARCHIVE_MEMBERS = 100
MAX_ARCHIVE_MEMBER_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100

AMOUNT_ASSET_RE = re.compile(
    r"^\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Za-z0-9]+)?\s*$"
)
PAIR_PREFIX_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})\s+(\d{2}:\d{2}:\d{2})$")
UTC_OFFSET_RE = re.compile(r"UTC([+-]\d+)")
EXPLICIT_UTC_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\(UTC([+-]?\d+)\)$")
FULL_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
FULL_DATETIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2}:\d{2})$")


@dataclass(frozen=True)
class BinanceLedgerEntry:
    tx_type: str
    asset_symbol: str
    asset_type: str
    quantity: Decimal
    price_usd: Decimal | None
    total_usd: Decimal | None
    fee: Decimal
    fee_currency: str
    timestamp: datetime | None
    fingerprint: str
    raw_data: dict


class BinanceExportParserError(ValueError):
    pass


def _decimal(value: str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1]
    return Decimal(text)


def _parse_amount_asset(value: str) -> tuple[Decimal, str | None]:
    match = AMOUNT_ASSET_RE.match(value.strip())
    if not match:
        raise BinanceExportParserError(f"Unable to parse amount/asset value: {value}")
    amount = Decimal(match.group(1).replace(",", ""))
    asset = match.group(2).upper() if match.group(2) else None
    return amount, asset


def _asset_type(symbol: str) -> str:
    upper = symbol.upper()
    if upper in STABLECOINS:
        return "stablecoin" if upper != "USD" else "fiat"
    if upper in {"EUR", "GBP", "JPY"}:
        return "fiat"
    return "crypto"


def _extract_timezone(name: str) -> timezone:
    match = UTC_OFFSET_RE.search(name)
    if not match:
        return timezone(timedelta(hours=7))
    hours = int(match.group(1))
    return timezone(timedelta(hours=hours))


def _parse_timestamp(value: str, default_tz: timezone) -> datetime:
    text = value.strip()
    explicit = EXPLICIT_UTC_DATE_RE.match(text)
    if explicit:
        dt = datetime(
            int(explicit.group(1)),
            int(explicit.group(2)),
            int(explicit.group(3)),
            tzinfo=timezone(timedelta(hours=int(explicit.group(4)))),
        )
        return dt.astimezone(UTC)

    full_date = FULL_DATE_RE.match(text)
    if full_date:
        dt = datetime(
            int(full_date.group(1)),
            int(full_date.group(2)),
            int(full_date.group(3)),
            tzinfo=default_tz,
        )
        return dt.astimezone(UTC)

    full_dt = FULL_DATETIME_RE.match(text)
    if full_dt:
        dt = datetime(
            int(full_dt.group(1)),
            int(full_dt.group(2)),
            int(full_dt.group(3)),
            *map(int, full_dt.group(4).split(":")),
            tzinfo=default_tz,
        )
        return dt.astimezone(UTC)

    pair_prefix = PAIR_PREFIX_DATE_RE.match(text)
    if pair_prefix:
        year = 2000 + int(pair_prefix.group(1))
        dt = datetime(
            year,
            int(pair_prefix.group(2)),
            int(pair_prefix.group(3)),
            *map(int, pair_prefix.group(4).split(":")),
            tzinfo=default_tz,
        )
        return dt.astimezone(UTC)

    raise BinanceExportParserError(f"Unsupported timestamp format: {value}")


def _maybe_accounting_value(
    asset_symbol: str,
    quantity: Decimal,
    price_usd: Decimal | None,
    total_usd: Decimal | None,
) -> Decimal | None:
    if total_usd is not None:
        return total_usd
    if price_usd is not None:
        return quantity * price_usd
    if asset_symbol.upper() in STABLECOINS:
        return quantity
    return None


def _pair_assets(pair: str) -> tuple[str, str | None]:
    upper = pair.upper()
    for quote in QUOTE_ASSETS:
        if upper.endswith(quote) and len(upper) > len(quote):
            return upper[: -len(quote)], quote
    return upper, None


def fingerprint_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _fingerprint_part(part: object) -> str:
    if isinstance(part, Decimal):
        return fingerprint_decimal(part)
    return str(part)


def _fingerprint(source_type: str, *parts: object) -> str:
    raw = "|".join([source_type, *(_fingerprint_part(part) for part in parts)])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _iter_archive_members(filename: str, file_bytes: bytes) -> list[tuple[str, str]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        members: list[tuple[str, str]] = []
        total_uncompressed_bytes = 0
        csv_members = 0
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not info.filename.lower().endswith(".csv"):
                    continue
                csv_members += 1
                if csv_members > MAX_ARCHIVE_MEMBERS:
                    raise BinanceExportParserError(
                        "Binance archive contains too many CSV members"
                    )
                if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise BinanceExportParserError(
                        f"Binance archive member too large: {info.filename}"
                    )
                if (
                    info.compress_size > 0
                    and info.file_size / info.compress_size
                    > MAX_ARCHIVE_COMPRESSION_RATIO
                ):
                    raise BinanceExportParserError(
                        f"Suspicious Binance archive compression ratio: {info.filename}"
                    )
                total_uncompressed_bytes += info.file_size
                if total_uncompressed_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise BinanceExportParserError(
                        "Binance archive expands beyond allowed size"
                    )
                text = zf.read(info.filename).decode("utf-8-sig", errors="replace")
                members.append((info.filename, text))
        return members
    text = file_bytes.decode("utf-8-sig", errors="replace")
    return [(filename, text)]


def _iter_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    rows: list[dict[str, str]] = []
    for row in reader:
        if not row:
            continue
        values = [str(value or "").strip() for value in row.values()]
        if not any(values):
            continue
        if values[0] == NO_DATA_SENTINEL and not any(values[1:]):
            continue
        rows.append(
            {
                str(key or "").strip(): str(value or "").strip()
                for key, value in row.items()
            }
        )
    return header, rows


def _entry(
    *,
    tx_type: str,
    asset_symbol: str,
    quantity: Decimal,
    timestamp: datetime,
    source_type: str,
    raw_data: dict,
    price_usd: Decimal | None = None,
    total_usd: Decimal | None = None,
    fee: Decimal = Decimal("0"),
    fee_currency: str | None = None,
    fingerprint_parts: Iterable[object] = (),
) -> BinanceLedgerEntry:
    asset_symbol = asset_symbol.upper()
    accounting_value = _maybe_accounting_value(
        asset_symbol, quantity, price_usd, total_usd
    )
    payload = {
        **raw_data,
        "source_type": source_type,
    }
    if accounting_value is not None:
        payload.setdefault("accounting_value_usd", str(accounting_value))
    return BinanceLedgerEntry(
        tx_type=tx_type,
        asset_symbol=asset_symbol,
        asset_type=_asset_type(asset_symbol),
        quantity=quantity,
        price_usd=price_usd,
        total_usd=total_usd,
        fee=fee,
        fee_currency=(fee_currency or asset_symbol).upper(),
        timestamp=timestamp,
        fingerprint=_fingerprint(source_type, *fingerprint_parts),
        raw_data=payload,
    )


def fingerprint_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def normalize_lock_period(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def normalize_account_label(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    text = text.replace("_", " ")
    if text.startswith("SPOT"):
        return "SPOT"
    if text.startswith("FUNDING"):
        return "FUNDING"
    if text.startswith("EARN"):
        return "EARN"
    return text


def normalize_simple_earn_type(value: object | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"[^A-Z0-9]+", "_", str(value).strip().upper()).strip("_")
    if not text:
        return None
    if "BONUS" in text:
        return "BONUS"
    if "REALTIME" in text or "REAL_TIME" in text:
        return "REALTIME"
    if "LOCKED" in text and "REWARD" in text:
        return "LOCKED_REWARD"
    if text in {"AUTO", "AUTO_SUBSCRIBE"}:
        return "AUTO"
    if text in {"LOCKED_TRANSFER", "NEW_TRANSFERRED", "CONVERT"}:
        return "LOCKED_TRANSFER"
    if text in {"NORMAL", "STANDARD"}:
        return "NORMAL"
    if "FAST" in text:
        return "FAST"
    return text


def extract_p2p_order_number(value: object | None) -> str | None:
    if value is None:
        return None
    match = re.search(r"(\d{8,})", str(value))
    return match.group(1) if match else None


def deposit_withdraw_fingerprint_parts(
    *,
    txid: object | None,
    timestamp: datetime,
    asset: str,
    amount: Decimal,
    address: object | None,
) -> tuple[object, ...]:
    txid_text = str(txid or "").strip()
    normalized_address = str(address or "").strip() or None
    if txid_text:
        return (txid_text, asset.upper(), normalized_address)
    return (
        fingerprint_timestamp(timestamp),
        asset.upper(),
        amount,
        normalized_address,
    )


def convert_fingerprint_parts(
    *,
    timestamp: datetime,
    pair: str,
    side: str,
    sell_qty: Decimal,
    buy_qty: Decimal,
) -> tuple[object, ...]:
    return (
        fingerprint_timestamp(timestamp),
        pair.upper(),
        side.lower(),
        sell_qty,
        buy_qty,
    )


def c2c_fingerprint_parts(
    *,
    timestamp: datetime,
    account: object | None,
    operation: str,
    asset: str,
    signed_change: Decimal,
    remark: object | None,
    order_number: object | None = None,
) -> tuple[object, ...]:
    order_key = extract_p2p_order_number(order_number) or extract_p2p_order_number(
        remark
    )
    if order_key:
        return (order_key, asset.upper(), signed_change)
    return (
        fingerprint_timestamp(timestamp),
        normalize_account_label(account),
        operation,
        asset.upper(),
        signed_change,
        str(remark or "").strip() or None,
    )


def _parse_spot_trades(
    rows: list[dict[str, str]], member_name: str
) -> list[BinanceLedgerEntry]:
    tz = _extract_timezone(member_name)
    entries: list[BinanceLedgerEntry] = []
    for row in rows:
        timestamp = _parse_timestamp(row["Time"], tz)
        pair = row["Pair"].upper()
        base_asset, quote_asset = _pair_assets(pair)
        executed_qty, executed_asset = _parse_amount_asset(row["Executed"])
        amount_qty, amount_asset = _parse_amount_asset(row["Amount"])
        fee_qty, fee_asset = _parse_amount_asset(row["Fee"])
        price = _decimal(row["Price"])
        if executed_asset and executed_asset != base_asset:
            base_asset = executed_asset
        total_usd = amount_qty if amount_asset in STABLECOINS else None
        entries.append(
            _entry(
                tx_type="spot_trade_buy"
                if row["Side"].upper() == "BUY"
                else "spot_trade_sell",
                asset_symbol=base_asset,
                quantity=executed_qty,
                price_usd=price if quote_asset in STABLECOINS else None,
                total_usd=total_usd,
                fee=fee_qty,
                fee_currency=fee_asset or base_asset,
                timestamp=timestamp,
                source_type="spot_trade",
                raw_data={
                    "pair": pair,
                    "side": row["Side"].upper(),
                    "quote_asset": quote_asset,
                    "quote_amount": str(amount_qty),
                    "status": row.get("Status") or "SUCCESS",
                },
                fingerprint_parts=(
                    timestamp.isoformat(),
                    pair,
                    row["Side"],
                    executed_qty,
                    amount_qty,
                    fee_qty,
                ),
            )
        )
    return entries


def _parse_convert_orders(
    rows: list[dict[str, str]], member_name: str
) -> list[BinanceLedgerEntry]:
    tz = _extract_timezone(member_name)
    entries: list[BinanceLedgerEntry] = []
    for row in rows:
        if row.get("Status", "").lower() not in {"success", "successful"}:
            continue
        timestamp = _parse_timestamp(row["Time"], tz)
        sell_qty, sell_asset = _parse_amount_asset(row["Sell"])
        buy_qty, buy_asset = _parse_amount_asset(row["Buy"])
        sell_total = sell_qty if sell_asset in STABLECOINS else None
        buy_price = (
            (sell_qty / buy_qty) if sell_asset in STABLECOINS and buy_qty > 0 else None
        )
        buy_total = sell_qty if sell_asset in STABLECOINS else None
        sell_price = (
            (buy_qty / sell_qty) if buy_asset in STABLECOINS and sell_qty > 0 else None
        )
        sell_total_alt = buy_qty if buy_asset in STABLECOINS else sell_total
        entries.append(
            _entry(
                tx_type="convert_sell",
                asset_symbol=sell_asset or "UNKNOWN",
                quantity=sell_qty,
                price_usd=sell_price,
                total_usd=sell_total_alt,
                timestamp=timestamp,
                source_type="convert_order",
                raw_data={
                    "pair": row["Pair"],
                    "wallet": row.get("Wallet"),
                    "status": row.get("Status"),
                    "convert_to_asset": buy_asset,
                    "convert_to_quantity": str(buy_qty),
                },
                fingerprint_parts=convert_fingerprint_parts(
                    timestamp=timestamp,
                    pair=row["Pair"],
                    side="sell",
                    sell_qty=sell_qty,
                    buy_qty=buy_qty,
                ),
            )
        )
        entries.append(
            _entry(
                tx_type="convert_buy",
                asset_symbol=buy_asset or "UNKNOWN",
                quantity=buy_qty,
                price_usd=buy_price,
                total_usd=buy_total,
                timestamp=timestamp,
                source_type="convert_order",
                raw_data={
                    "pair": row["Pair"],
                    "wallet": row.get("Wallet"),
                    "status": row.get("Status"),
                    "convert_from_asset": sell_asset,
                    "convert_from_quantity": str(sell_qty),
                },
                fingerprint_parts=convert_fingerprint_parts(
                    timestamp=timestamp,
                    pair=row["Pair"],
                    side="buy",
                    sell_qty=sell_qty,
                    buy_qty=buy_qty,
                ),
            )
        )
    return entries


def _parse_deposits(
    rows: list[dict[str, str]], member_name: str
) -> list[BinanceLedgerEntry]:
    tz = _extract_timezone(member_name)
    return [
        _entry(
            tx_type="deposit",
            asset_symbol=row["Coin"],
            quantity=_decimal(row["Amount"]) or Decimal("0"),
            price_usd=Decimal("1") if row["Coin"].upper() in STABLECOINS else None,
            total_usd=(
                _decimal(row["Amount"]) if row["Coin"].upper() in STABLECOINS else None
            ),
            timestamp=_parse_timestamp(row["Time"], tz),
            source_type="deposit_history",
            raw_data={
                "network": row.get("Network"),
                "address": row.get("Address"),
                "txid": row.get("TXID"),
                "status": row.get("Status"),
            },
            fingerprint_parts=deposit_withdraw_fingerprint_parts(
                txid=row.get("TXID"),
                timestamp=_parse_timestamp(row["Time"], tz),
                asset=row["Coin"],
                amount=_decimal(row["Amount"]) or Decimal("0"),
                address=row.get("Address"),
            ),
        )
        for row in rows
        if row.get("Status", "").lower() == "completed"
    ]


def _parse_withdrawals(
    rows: list[dict[str, str]], member_name: str
) -> list[BinanceLedgerEntry]:
    tz = _extract_timezone(member_name)
    entries: list[BinanceLedgerEntry] = []
    for row in rows:
        if row.get("Status", "").lower() != "completed":
            continue
        amount = _decimal(row["Amount"]) or Decimal("0")
        fee = _decimal(row.get("Fee")) or Decimal("0")
        symbol = row["Coin"].upper()
        entries.append(
            _entry(
                tx_type="withdrawal",
                asset_symbol=symbol,
                quantity=amount,
                price_usd=Decimal("1") if symbol in STABLECOINS else None,
                total_usd=amount if symbol in STABLECOINS else None,
                fee=fee,
                fee_currency=symbol,
                timestamp=_parse_timestamp(row["Time"], tz),
                source_type="withdraw_history",
                raw_data={
                    "network": row.get("Network"),
                    "address": row.get("Address"),
                    "txid": row.get("TXID"),
                    "status": row.get("Status"),
                },
                fingerprint_parts=deposit_withdraw_fingerprint_parts(
                    txid=row.get("TXID"),
                    timestamp=_parse_timestamp(row["Time"], tz),
                    asset=symbol,
                    amount=amount,
                    address=row.get("Address"),
                ),
            )
        )
    return entries


def _parse_transaction_history(
    rows: list[dict[str, str]], member_name: str
) -> list[BinanceLedgerEntry]:
    tz = _extract_timezone(member_name)
    entries: list[BinanceLedgerEntry] = []
    for row in rows:
        operation = row.get("Operation", "")
        asset = row.get("Coin", "UNKNOWN").upper()
        change = _decimal(row.get("Change")) or Decimal("0")
        timestamp = _parse_timestamp(row["Time"], tz)
        if operation == "P2P Trading":
            tx_type = "external_deposit" if change >= 0 else "external_withdrawal"
            entries.append(
                _entry(
                    tx_type=tx_type,
                    asset_symbol=asset,
                    quantity=abs(change),
                    price_usd=Decimal("1") if asset in STABLECOINS else None,
                    total_usd=abs(change) if asset in STABLECOINS else None,
                    timestamp=timestamp,
                    source_type="transaction_history",
                    raw_data={
                        "account": row.get("Account"),
                        "operation": operation,
                        "remark": row.get("Remark"),
                    },
                    fingerprint_parts=c2c_fingerprint_parts(
                        timestamp=timestamp,
                        account=row.get("Account"),
                        operation=operation,
                        asset=asset,
                        signed_change=change,
                        remark=row.get("Remark"),
                    ),
                )
            )
        elif operation == "Transfer Between Main and Funding Wallet":
            tx_type = "transfer_in" if change > 0 else "transfer_out"
            entries.append(
                _entry(
                    tx_type=tx_type,
                    asset_symbol=asset,
                    quantity=abs(change),
                    price_usd=Decimal("1") if asset in STABLECOINS else None,
                    total_usd=abs(change) if asset in STABLECOINS else None,
                    timestamp=timestamp,
                    source_type="transaction_history",
                    raw_data={
                        "account": row.get("Account"),
                        "operation": operation,
                        "remark": row.get("Remark"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row.get("Account"),
                        operation,
                        asset,
                        change,
                    ),
                )
            )
    return entries


def _parse_simple_earn(
    rows: list[dict[str, str]], member_name: str, header: list[str]
) -> list[BinanceLedgerEntry]:
    tz = _extract_timezone(member_name)
    header_set = set(header)
    entries: list[BinanceLedgerEntry] = []

    if {
        "Subscription Date",
        "Product Name",
        "Coin",
        "Amount",
        "Type",
        "From",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() != "success":
                continue
            qty = _decimal(row["Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Subscription Date"], tz)
            entries.append(
                _entry(
                    tx_type="earn_subscribe",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="simple_earn_flexible_subscription",
                    raw_data={
                        "product_name": row.get("Product Name"),
                        "from_account": row.get("From"),
                        "subscription_type": row.get("Type"),
                        "stake_asset": row.get("Coin"),
                        "stake_amount": row.get("Amount"),
                    },
                    fingerprint_parts=(
                        fingerprint_timestamp(timestamp),
                        row["Coin"],
                        qty,
                        (row.get("Product Name") or row["Coin"]).upper(),
                        normalize_simple_earn_type(row.get("Type")),
                    ),
                )
            )
        return entries

    if {
        "Redemption Date",
        "Product Name",
        "Coin",
        "Principal Redeemed",
        "Method",
        "Redeem to",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() != "success":
                continue
            qty = _decimal(row["Principal Redeemed"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Redemption Date"], tz)
            entries.append(
                _entry(
                    tx_type="earn_redeem",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="simple_earn_flexible_redemption",
                    raw_data={
                        "product_name": row.get("Product Name"),
                        "method": row.get("Method"),
                        "redeem_to": row.get("Redeem to"),
                        "redeem_asset": row.get("Coin"),
                        "redeem_amount": row.get("Principal Redeemed"),
                        "principal_redeemed": row.get("Principal Redeemed"),
                    },
                    fingerprint_parts=(
                        fingerprint_timestamp(timestamp),
                        row["Coin"],
                        qty,
                        normalize_account_label(row.get("Redeem to")),
                    ),
                )
            )
        return entries

    if {"Time", "Coin", "Amount", "Type"}.issubset(header_set):
        for row in rows:
            qty = _decimal(row["Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Time"], tz)
            entries.append(
                _entry(
                    tx_type="earn_reward",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="simple_earn_flexible_reward",
                    raw_data={"reward_type": row.get("Type")},
                    fingerprint_parts=(
                        fingerprint_timestamp(timestamp),
                        row["Coin"],
                        qty,
                        normalize_simple_earn_type(row.get("Type")),
                    ),
                )
            )
        return entries

    if {
        "Subscription Date",
        "Coin",
        "Total Amount",
        "Lock Period",
        "Type",
        "From",
    }.issubset(header_set):
        for row in rows:
            qty = _decimal(row["Total Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Subscription Date"], tz)
            entries.append(
                _entry(
                    tx_type="earn_subscribe",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="simple_earn_locked_subscription",
                    raw_data={
                        "lock_period": row.get("Lock Period"),
                        "subscription_type": row.get("Type"),
                        "from_account": row.get("From"),
                        "stake_asset": row.get("Coin"),
                        "stake_amount": row.get("Total Amount"),
                    },
                    fingerprint_parts=(
                        fingerprint_timestamp(timestamp),
                        row["Coin"],
                        qty,
                        normalize_lock_period(row.get("Lock Period")),
                        normalize_simple_earn_type(row.get("Type")),
                    ),
                )
            )
        return entries

    if {
        "Redemption Date",
        "Coin",
        "Redemption Amount",
        "Redeem to",
        "Est. Arrival Time",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() != "success":
                continue
            qty = _decimal(row["Redemption Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Redemption Date"], tz)
            entries.append(
                _entry(
                    tx_type="earn_redeem",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="simple_earn_locked_redemption",
                    raw_data={
                        "redeem_to": row.get("Redeem to"),
                        "arrival_time": row.get("Est. Arrival Time"),
                        "redeem_asset": row.get("Coin"),
                        "redeem_amount": row.get("Redemption Amount"),
                        "principal_redeemed": row.get("Redemption Amount"),
                    },
                    fingerprint_parts=(
                        fingerprint_timestamp(timestamp),
                        row["Coin"],
                        qty,
                        normalize_account_label(row.get("Redeem to")),
                    ),
                )
            )
        return entries

    if {"Time", "Coin", "Interest", "Lock Period", "APR", "Type"}.issubset(header_set):
        for row in rows:
            qty = _decimal(row["Interest"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Time"], tz)
            entries.append(
                _entry(
                    tx_type="earn_reward",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="simple_earn_locked_reward",
                    raw_data={
                        "reward_type": row.get("Type"),
                        "lock_period": row.get("Lock Period"),
                        "apr": row.get("APR"),
                    },
                    fingerprint_parts=(
                        fingerprint_timestamp(timestamp),
                        row["Coin"],
                        qty,
                        normalize_simple_earn_type(row.get("Type")),
                        normalize_lock_period(row.get("Lock Period")),
                    ),
                )
            )
        return entries

    if {
        "Time",
        "Stake",
        "Stake Amount",
        "Distribute",
        "Distribute Amount",
        "Ratio",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() not in {"success", "successful"}:
                continue
            qty = _decimal(row["Distribute Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Time"], tz)
            entries.append(
                _entry(
                    tx_type="staking_subscribe",
                    asset_symbol=row["Distribute"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="eth_staking_subscription",
                    raw_data={
                        "stake_asset": row.get("Stake"),
                        "stake_amount": row.get("Stake Amount"),
                        "ratio": row.get("Ratio"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row.get("Stake"),
                        row.get("Distribute"),
                        row.get("Stake Amount"),
                        qty,
                    ),
                )
            )
        return entries

    if {
        "Stake Date",
        "Stake",
        "Stake Amount",
        "Receive",
        "Receive Amount",
        "Ratio",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() not in {"success", "successful"}:
                continue
            qty = _decimal(row["Receive Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Stake Date"], tz)
            entries.append(
                _entry(
                    tx_type="staking_subscribe",
                    asset_symbol=row["Receive"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="sol_staking_subscription",
                    raw_data={
                        "stake_asset": row.get("Stake"),
                        "stake_amount": row.get("Stake Amount"),
                        "ratio": row.get("Ratio"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row.get("Stake"),
                        row.get("Receive"),
                        row.get("Stake Amount"),
                        qty,
                    ),
                )
            )
        return entries

    if {"Date", "BNSOL Balance", "SOL Compound Amount", "APR"}.issubset(header_set):
        for row in rows:
            qty = _decimal(row["SOL Compound Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Date"], tz)
            entries.append(
                _entry(
                    tx_type="staking_reward",
                    asset_symbol="SOL",
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="sol_staking_reward",
                    raw_data={
                        "apr": row.get("APR"),
                        "bnsol_balance": row.get("BNSOL Balance"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        "SOL",
                        qty,
                        row.get("BNSOL Balance"),
                    ),
                )
            )
        return entries

    if {"Date", "Coin", "Amount", "BNSOL Amount"}.issubset(header_set):
        for row in rows:
            qty = _decimal(row["Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Date"], tz)
            entries.append(
                _entry(
                    tx_type="staking_reward",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="sol_staking_reward",
                    raw_data={"bnsol_amount": row.get("BNSOL Amount")},
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row["Coin"],
                        qty,
                        row.get("BNSOL Amount"),
                    ),
                )
            )
        return entries

    if {"Date", "Coin", "Amount", "Status"}.issubset(header_set):
        for row in rows:
            qty = _decimal(row["Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Date"], tz)
            entries.append(
                _entry(
                    tx_type="staking_reward",
                    asset_symbol=row["Coin"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="sol_staking_extra_reward",
                    raw_data={"status": row.get("Status")},
                    fingerprint_parts=(timestamp.isoformat(), row["Coin"], qty),
                )
            )
        return entries

    if {
        "Time",
        "Wrapped BETH Amount",
        "Distributed WBETH Amount",
        "Ratio",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() not in {"success", "successful"}:
                continue
            qty = _decimal(row["Distributed WBETH Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Time"], tz)
            entries.append(
                _entry(
                    tx_type="staking_subscribe",
                    asset_symbol="WBETH",
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="eth_staking_wrap",
                    raw_data={
                        "stake_asset": "BETH",
                        "stake_amount": row.get("Wrapped BETH Amount"),
                        "wrapped_beth_amount": row.get("Wrapped BETH Amount"),
                        "ratio": row.get("Ratio"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row.get("Wrapped BETH Amount"),
                        qty,
                        row.get("Ratio"),
                    ),
                )
            )
        return entries

    if {"Time", "Asset", "Ratio", "Amount", "Position Amount"}.issubset(header_set):
        for row in rows:
            qty = _decimal(row["Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Time"], tz)
            entries.append(
                _entry(
                    tx_type="staking_reward",
                    asset_symbol=row["Asset"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="eth_staking_reward",
                    raw_data={
                        "ratio": row.get("Ratio"),
                        "position_amount": row.get("Position Amount"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row["Asset"],
                        qty,
                        row.get("Position Amount"),
                    ),
                )
            )
        return entries

    if {
        "Time",
        "Redeem",
        "Redeem Amount",
        "Distribute",
        "Distribute Amount",
        "Ratio",
        "Status",
    }.issubset(header_set):
        for row in rows:
            if row.get("Status", "").lower() not in {"success", "successful"}:
                continue
            qty = _decimal(row["Distribute Amount"]) or Decimal("0")
            timestamp = _parse_timestamp(row["Time"], tz)
            entries.append(
                _entry(
                    tx_type="staking_redeem",
                    asset_symbol=row["Distribute"],
                    quantity=qty,
                    timestamp=timestamp,
                    source_type="eth_staking_redeem",
                    raw_data={
                        "redeem_asset": row.get("Redeem"),
                        "redeem_amount": row.get("Redeem Amount"),
                        "ratio": row.get("Ratio"),
                    },
                    fingerprint_parts=(
                        timestamp.isoformat(),
                        row.get("Redeem"),
                        row.get("Distribute"),
                        row.get("Redeem Amount"),
                        qty,
                    ),
                )
            )
        return entries

    return []


def _member_schema_supported(member_name: str, header: list[str]) -> bool:
    header_set = set(header)
    return any(
        (
            {"Time", "Pair", "Side", "Price", "Executed", "Amount", "Fee"}.issubset(
                header_set
            ),
            {
                "Time",
                "Wallet",
                "Pair",
                "Type",
                "Sell",
                "Buy",
                "Price",
                "Inverse Price",
                "Date Updated",
                "Status",
            }.issubset(header_set),
            {
                "Time",
                "Coin",
                "Network",
                "Amount",
                "Fee",
                "Address",
                "TXID",
                "Status",
            }.issubset(header_set),
            {
                "Time",
                "Coin",
                "Network",
                "Amount",
                "Address",
                "TXID",
                "Status",
            }.issubset(header_set),
            {
                "User ID",
                "Time",
                "Account",
                "Operation",
                "Coin",
                "Change",
                "Remark",
            }.issubset(header_set),
            "Simple-Earn" in member_name,
            "SimpleEarn" in member_name,
            "Staking" in member_name,
        )
    )


def _parse_member(member_name: str, text: str) -> list[BinanceLedgerEntry]:
    header, rows = _iter_rows(text)
    if not header or not rows:
        return []
    header_set = set(header)

    if {"Time", "Pair", "Side", "Price", "Executed", "Amount", "Fee"}.issubset(
        header_set
    ):
        return _parse_spot_trades(rows, member_name)
    if {
        "Time",
        "Wallet",
        "Pair",
        "Type",
        "Sell",
        "Buy",
        "Price",
        "Inverse Price",
        "Date Updated",
        "Status",
    }.issubset(header_set):
        return _parse_convert_orders(rows, member_name)
    if {
        "Time",
        "Coin",
        "Network",
        "Amount",
        "Fee",
        "Address",
        "TXID",
        "Status",
    }.issubset(header_set):
        return _parse_withdrawals(rows, member_name)
    if {"Time", "Coin", "Network", "Amount", "Address", "TXID", "Status"}.issubset(
        header_set
    ):
        return _parse_deposits(rows, member_name)
    if {"User ID", "Time", "Account", "Operation", "Coin", "Change", "Remark"}.issubset(
        header_set
    ):
        return _parse_transaction_history(rows, member_name)
    if (
        "Simple-Earn" in member_name
        or "SimpleEarn" in member_name
        or "Staking" in member_name
    ):
        return _parse_simple_earn(rows, member_name, header)
    return []


def parse_binance_exports(
    file_blobs: list[tuple[str, bytes]],
) -> list[BinanceLedgerEntry]:
    entries: list[BinanceLedgerEntry] = []
    supported_members = 0
    for filename, file_bytes in file_blobs:
        for member_name, text in _iter_archive_members(filename, file_bytes):
            header, rows = _iter_rows(text)
            if not header:
                continue
            if not _member_schema_supported(member_name, header):
                if rows:
                    raise BinanceExportParserError(
                        "Unsupported Binance export schema with data: "
                        f"{member_name} ({', '.join(header)})"
                    )
                continue
            supported_members += 1
            member_entries = _parse_member(member_name, text)
            if rows and not member_entries:
                raise BinanceExportParserError(
                    "Supported Binance export schema produced no importable rows: "
                    f"{member_name} ({', '.join(header)})"
                )
            entries.extend(member_entries)

    if supported_members == 0:
        raise BinanceExportParserError("No supported Binance export rows found")
    if not entries:
        raise BinanceExportParserError("Binance export contained no importable rows")

    deduped: dict[str, BinanceLedgerEntry] = {}
    for entry in entries:
        deduped.setdefault(entry.fingerprint, entry)
    return sorted(
        deduped.values(),
        key=lambda entry: (
            entry.timestamp or datetime.min.replace(tzinfo=UTC),
            entry.fingerprint,
        ),
    )


def summarize_binance_entries(
    entries: list[BinanceLedgerEntry],
) -> dict[str, Decimal | dict[str, Decimal] | int]:
    by_type: dict[str, Decimal] = {}
    by_source_type: dict[str, Decimal] = {}
    gross_accounting_value_usd = Decimal("0")
    for entry in entries:
        by_type[entry.tx_type] = by_type.get(entry.tx_type, Decimal("0")) + Decimal("1")
        source_type = str(entry.raw_data.get("source_type", "unknown"))
        by_source_type[source_type] = by_source_type.get(
            source_type, Decimal("0")
        ) + Decimal("1")
        if entry.total_usd is not None:
            gross_accounting_value_usd += entry.total_usd
    return {
        "count": len(entries),
        "by_type": by_type,
        "by_source_type": by_source_type,
        "gross_accounting_value_usd": gross_accounting_value_usd,
    }
