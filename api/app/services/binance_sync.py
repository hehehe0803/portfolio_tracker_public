"""
Binance sync service: fetches balances and trades, normalizes into Transaction records.
"""

import hashlib
import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import ActivityLog, Asset, Institution, PendingOrder, Transaction
from app.services import analytics
from app.services.binance_client import (
    BinanceError,
    create_binance_client,
)
from app.services.binance_export_parser import (
    STABLECOINS,
    c2c_fingerprint_parts,
    convert_fingerprint_parts,
    deposit_withdraw_fingerprint_parts,
    fingerprint_timestamp,
    normalize_account_label,
    normalize_lock_period,
    normalize_simple_earn_type,
)
from app.services.binance_export_parser import (
    _entry as build_ledger_entry,
)
from app.services.credentials import CredentialConfigError

logger = logging.getLogger(__name__)

DELTA_COVERAGE_NOTE = (
    "API delta sync currently covers deposits, withdrawals, convert, Simple Earn, "
    "and C2C/P2P only. Spot trades, internal transfers, dividends, and dust "
    "remain export-only; import a fresh Binance export after that activity."
)
DEPOSIT_WITHDRAW_WINDOW = timedelta(days=90)
SIMPLE_EARN_WINDOW = timedelta(days=30)
CONVERT_WINDOW = timedelta(days=30)

API_DELTA_OVERLAP = timedelta(days=1)
HISTORY_PAGE_LIMIT = 100
BINANCE_EXPORT_TZ = timezone(timedelta(hours=7))

ASSET_TYPE_MAP: dict[str, str] = {
    "BTC": "crypto",
    "ETH": "crypto",
    "BNB": "crypto",
    "SOL": "crypto",
    "ADA": "crypto",
    "XRP": "crypto",
    "DOT": "crypto",
    "DOGE": "crypto",
    "AVAX": "crypto",
    "MATIC": "crypto",
    "LINK": "crypto",
    "UNI": "crypto",
    "ATOM": "crypto",
    "LTC": "crypto",
    "BCH": "crypto",
    "NEAR": "crypto",
    "ALGO": "crypto",
    "VET": "crypto",
    "FIL": "crypto",
    "TRX": "crypto",
    "SHIB": "crypto",
    "USDT": "stablecoin",
    "USDC": "stablecoin",
    "BUSD": "stablecoin",
    "DAI": "stablecoin",
    "FDUSD": "stablecoin",
    "USD": "fiat",
    "EUR": "fiat",
    "GBP": "fiat",
    "XAU": "commodity",
}


def _fingerprint(institution: str, tx_type: str, asset: str, qty: str, ts: str) -> str:
    raw = f"{institution}|{tx_type}|{asset}|{qty}|{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _asset_type(symbol: str) -> str:
    return ASSET_TYPE_MAP.get(symbol.upper(), "crypto")


def _canonical_quantity(value: Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _binance_export_day(timestamp: datetime) -> str:
    return timestamp.astimezone(BINANCE_EXPORT_TZ).date().isoformat()


def _convert_pair(sell_asset: str, buy_asset: str) -> str:
    if sell_asset in STABLECOINS and buy_asset not in STABLECOINS:
        return f"{buy_asset}{sell_asset}"
    if buy_asset in STABLECOINS and sell_asset not in STABLECOINS:
        return f"{sell_asset}{buy_asset}"
    return f"{sell_asset}{buy_asset}"


def _source_specific_overlap_key(tx: Transaction) -> tuple[Any, ...] | None:
    payload = tx.raw_data if isinstance(tx.raw_data, dict) else {}
    source_type = payload.get("source_type")
    event_day = _binance_export_day(tx.timestamp)
    quantity = _canonical_quantity(tx.quantity)

    if tx.tx_type == "earn_reward" and source_type == "simple_earn_locked_reward":
        return (
            source_type,
            tx.asset_symbol.upper(),
            quantity,
            normalize_lock_period(payload.get("lock_period")),
            event_day,
        )

    if tx.tx_type == "earn_redeem" and source_type == "simple_earn_locked_redemption":
        return (
            source_type,
            tx.asset_symbol.upper(),
            quantity,
            event_day,
        )

    return None


def _build_source_specific_overlap_counts(
    transactions: list[Transaction],
) -> Counter[tuple[Any, ...]]:
    counts: Counter[tuple[Any, ...]] = Counter()
    for tx in transactions:
        key = _source_specific_overlap_key(tx)
        if key is not None:
            counts[key] += 1
    return counts


def _api_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    text = str(value or "").strip()
    if not text:
        raise ValueError("Missing Binance API timestamp")
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=UTC)
    normalized = text.replace("Z", "+00:00")
    for parser in (
        lambda raw: datetime.fromisoformat(raw),
        lambda raw: datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"),
        lambda raw: datetime.strptime(raw, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(normalized)
            return (
                parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            )
        except ValueError:
            continue
    raise ValueError(f"Unsupported Binance API timestamp: {value}")


def _history_rows(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "row", "list", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [payload]
    return []


def _is_completed(status: Any, completed_values: set[str]) -> bool:
    return str(status or "").strip().lower() in completed_values


def _ledger_transaction(entry) -> Transaction:
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
        timestamp=entry.timestamp,
        fingerprint=entry.fingerprint,
        raw_data=entry.raw_data,
    )


def _api_record_common(
    *, source_endpoint: str, source_id: str | None, extra: dict[str, Any]
) -> dict[str, Any]:
    payload = {**extra, "source_endpoint": source_endpoint}
    if source_id:
        payload["source_id"] = source_id
    return payload


def _normalize_deposit_history(payload: Any) -> list[Transaction]:
    records: list[Transaction] = []
    for row in _history_rows(payload):
        if not _is_completed(
            row.get("status"), {"1", "success", "successful", "completed"}
        ):
            continue
        timestamp = _api_time(
            row.get("insertTime") or row.get("completeTime") or row.get("successTime")
        )
        asset = str(row.get("coin") or row.get("asset") or "UNKNOWN").upper()
        amount = Decimal(str(row.get("amount") or row.get("qty") or "0"))
        txid = str(row.get("txId") or row.get("id") or "").strip() or None
        address = row.get("address")
        records.append(
            _ledger_transaction(
                build_ledger_entry(
                    tx_type="deposit",
                    asset_symbol=asset,
                    quantity=amount,
                    price_usd=Decimal("1") if asset in STABLECOINS else None,
                    total_usd=amount if asset in STABLECOINS else None,
                    timestamp=timestamp,
                    source_type="deposit_history",
                    raw_data=_api_record_common(
                        source_endpoint="deposit_history",
                        source_id=txid,
                        extra={
                            "network": row.get("network"),
                            "address": address,
                            "txid": txid,
                            "status": str(row.get("status")),
                        },
                    ),
                    fingerprint_parts=deposit_withdraw_fingerprint_parts(
                        txid=txid,
                        timestamp=timestamp,
                        asset=asset,
                        amount=amount,
                        address=address,
                    ),
                )
            )
        )
    return records


def _normalize_withdraw_history(payload: Any) -> list[Transaction]:
    records: list[Transaction] = []
    for row in _history_rows(payload):
        if not _is_completed(
            row.get("status"), {"6", "completed", "success", "successful"}
        ):
            continue
        timestamp = _api_time(
            row.get("completeTime") or row.get("successTime") or row.get("applyTime")
        )
        asset = str(row.get("coin") or row.get("asset") or "UNKNOWN").upper()
        amount = Decimal(str(row.get("amount") or row.get("qty") or "0"))
        fee = Decimal(str(row.get("transactionFee") or row.get("fee") or "0"))
        txid = str(row.get("txId") or row.get("id") or "").strip() or None
        address = row.get("address")
        records.append(
            _ledger_transaction(
                build_ledger_entry(
                    tx_type="withdrawal",
                    asset_symbol=asset,
                    quantity=amount,
                    price_usd=Decimal("1") if asset in STABLECOINS else None,
                    total_usd=amount if asset in STABLECOINS else None,
                    fee=fee,
                    fee_currency=asset,
                    timestamp=timestamp,
                    source_type="withdraw_history",
                    raw_data=_api_record_common(
                        source_endpoint="withdraw_history",
                        source_id=txid,
                        extra={
                            "network": row.get("network"),
                            "address": address,
                            "txid": txid,
                            "status": str(row.get("status")),
                        },
                    ),
                    fingerprint_parts=deposit_withdraw_fingerprint_parts(
                        txid=txid,
                        timestamp=timestamp,
                        asset=asset,
                        amount=amount,
                        address=address,
                    ),
                )
            )
        )
    return records


def _normalize_convert_history(payload: Any) -> list[Transaction]:
    records: list[Transaction] = []
    for row in _history_rows(payload):
        if not _is_completed(
            row.get("status") or row.get("orderStatus"),
            {"success", "successful", "completed"},
        ):
            continue
        timestamp = _api_time(
            row.get("createTime") or row.get("createDate") or row.get("time")
        )
        sell_asset = str(
            row.get("fromAsset") or row.get("quoteAsset") or "UNKNOWN"
        ).upper()
        buy_asset = str(row.get("toAsset") or row.get("baseAsset") or "UNKNOWN").upper()
        sell_qty = Decimal(str(row.get("fromAmount") or row.get("fromQty") or "0"))
        buy_qty = Decimal(str(row.get("toAmount") or row.get("toQty") or "0"))
        pair = _convert_pair(sell_asset, buy_asset)
        order_id = str(row.get("orderId") or row.get("quoteId") or "").strip() or None
        buy_price = (
            (sell_qty / buy_qty) if sell_asset in STABLECOINS and buy_qty > 0 else None
        )
        buy_total = sell_qty if sell_asset in STABLECOINS else None
        sell_price = (
            (buy_qty / sell_qty) if buy_asset in STABLECOINS and sell_qty > 0 else None
        )
        sell_total = buy_qty if buy_asset in STABLECOINS else None
        common = _api_record_common(
            source_endpoint="convert_trade_history",
            source_id=order_id,
            extra={
                "pair": pair,
                "status": str(row.get("status") or row.get("orderStatus")),
            },
        )
        records.append(
            _ledger_transaction(
                build_ledger_entry(
                    tx_type="convert_sell",
                    asset_symbol=sell_asset,
                    quantity=sell_qty,
                    price_usd=sell_price,
                    total_usd=sell_total,
                    timestamp=timestamp,
                    source_type="convert_order",
                    raw_data={
                        **common,
                        "convert_to_asset": buy_asset,
                        "convert_to_quantity": str(buy_qty),
                    },
                    fingerprint_parts=convert_fingerprint_parts(
                        timestamp=timestamp,
                        pair=pair,
                        side="sell",
                        sell_qty=sell_qty,
                        buy_qty=buy_qty,
                    ),
                )
            )
        )
        records.append(
            _ledger_transaction(
                build_ledger_entry(
                    tx_type="convert_buy",
                    asset_symbol=buy_asset,
                    quantity=buy_qty,
                    price_usd=buy_price,
                    total_usd=buy_total,
                    timestamp=timestamp,
                    source_type="convert_order",
                    raw_data={
                        **common,
                        "convert_from_asset": sell_asset,
                        "convert_from_quantity": str(sell_qty),
                    },
                    fingerprint_parts=convert_fingerprint_parts(
                        timestamp=timestamp,
                        pair=pair,
                        side="buy",
                        sell_qty=sell_qty,
                        buy_qty=buy_qty,
                    ),
                )
            )
        )
    return records


def _normalize_simple_earn_history(payload: Any, *, kind: str) -> list[Transaction]:
    config = {
        "flexible_subscription": (
            "earn_subscribe",
            "simple_earn_flexible_subscription",
            "simple_earn_flexible_subscriptions",
        ),
        "flexible_redemption": (
            "earn_redeem",
            "simple_earn_flexible_redemption",
            "simple_earn_flexible_redemptions",
        ),
        "flexible_reward": (
            "earn_reward",
            "simple_earn_flexible_reward",
            "simple_earn_flexible_rewards",
        ),
        "locked_subscription": (
            "earn_subscribe",
            "simple_earn_locked_subscription",
            "simple_earn_locked_subscriptions",
        ),
        "locked_redemption": (
            "earn_redeem",
            "simple_earn_locked_redemption",
            "simple_earn_locked_redemptions",
        ),
        "locked_reward": (
            "earn_reward",
            "simple_earn_locked_reward",
            "simple_earn_locked_rewards",
        ),
    }[kind]
    tx_type, source_type, source_endpoint = config
    records: list[Transaction] = []
    for row in _history_rows(payload):
        status = row.get("status")
        if status is not None and not _is_completed(
            status, {"success", "successful", "completed", "paid"}
        ):
            continue
        timestamp = _api_time(
            row.get("time")
            or row.get("createTime")
            or row.get("purchaseTime")
            or row.get("redeemTime")
        )
        asset = str(row.get("asset") or row.get("coin") or "UNKNOWN").upper()
        quantity_field = "rewards" if kind == "flexible_reward" else "amount"
        quantity = Decimal(
            str(
                row.get(quantity_field)
                or row.get("rewards")
                or row.get("amount")
                or row.get("totalAmount")
                or "0"
            )
        )
        record_id = (
            str(
                row.get("purchaseId")
                or row.get("redeemId")
                or row.get("positionId")
                or row.get("projectId")
                or ""
            ).strip()
            or None
        )
        extra: dict[str, Any]
        fingerprint_parts: tuple[Any, ...]
        if kind.endswith("subscription"):
            extra = {
                "product_name": row.get("productName"),
                "from_account": row.get("sourceAccount") or row.get("fromAccount"),
                "subscription_type": row.get("type"),
                "stake_asset": asset,
                "stake_amount": str(quantity),
                "lock_period": row.get("lockPeriod"),
            }
            if kind == "locked_subscription":
                fingerprint_parts = (
                    fingerprint_timestamp(timestamp),
                    asset,
                    quantity,
                    normalize_lock_period(row.get("lockPeriod")),
                    normalize_simple_earn_type(row.get("type")),
                )
            else:
                fingerprint_parts = (
                    fingerprint_timestamp(timestamp),
                    asset,
                    quantity,
                    str(row.get("productName") or asset).upper(),
                    normalize_simple_earn_type(row.get("type")),
                )
        elif kind.endswith("redemption"):
            redeem_to = row.get("destAccount") or row.get("redeemTo")
            extra = {
                "product_name": row.get("productName"),
                "method": row.get("redeemType") or row.get("type"),
                "redeem_to": redeem_to,
                "redeem_asset": asset,
                "redeem_amount": str(quantity),
                "principal_redeemed": str(quantity),
                "lock_period": row.get("lockPeriod"),
            }
            if kind == "locked_redemption":
                fingerprint_parts = (
                    fingerprint_timestamp(timestamp),
                    asset,
                    quantity,
                    normalize_account_label(redeem_to),
                )
            else:
                fingerprint_parts = (
                    fingerprint_timestamp(timestamp),
                    asset,
                    quantity,
                    normalize_account_label(redeem_to),
                )
        else:
            extra = {
                "reward_type": row.get("type"),
                "lock_period": row.get("lockPeriod"),
                "apr": row.get("apr"),
                "product_name": row.get("productName"),
            }
            if kind == "flexible_reward":
                fingerprint_parts = (
                    fingerprint_timestamp(timestamp),
                    asset,
                    quantity,
                    normalize_simple_earn_type(row.get("type")),
                )
            else:
                fingerprint_parts = (
                    fingerprint_timestamp(timestamp),
                    asset,
                    quantity,
                    normalize_simple_earn_type(row.get("type")),
                    normalize_lock_period(row.get("lockPeriod")),
                )
        records.append(
            _ledger_transaction(
                build_ledger_entry(
                    tx_type=tx_type,
                    asset_symbol=asset,
                    quantity=quantity,
                    timestamp=timestamp,
                    source_type=source_type,
                    raw_data=_api_record_common(
                        source_endpoint=source_endpoint,
                        source_id=record_id,
                        extra=extra,
                    ),
                    fingerprint_parts=fingerprint_parts,
                )
            )
        )
    return records


def _normalize_c2c_history(payload: Any) -> list[Transaction]:
    records: list[Transaction] = []
    for row in _history_rows(payload):
        if not _is_completed(
            row.get("status") or row.get("orderStatus"),
            {"completed", "success", "successful"},
        ):
            continue
        trade_type = str(row.get("tradeType") or "").upper()
        if trade_type not in {"BUY", "SELL"}:
            continue
        timestamp = _api_time(
            row.get("createTime") or row.get("orderTime") or row.get("time")
        )
        asset = str(row.get("asset") or row.get("coin") or "USDT").upper()
        amount = Decimal(
            str(
                row.get("takerAmount")
                or row.get("amount")
                or row.get("cryptoAmount")
                or "0"
            )
        )
        signed_change = amount if trade_type == "BUY" else -amount
        remark = f"P2P - {row.get('orderNumber') or row.get('advNo') or 'unknown'}"
        order_number = (
            str(row.get("orderNumber") or row.get("advNo") or "").strip() or None
        )
        records.append(
            _ledger_transaction(
                build_ledger_entry(
                    tx_type="external_deposit"
                    if trade_type == "BUY"
                    else "external_withdrawal",
                    asset_symbol=asset,
                    quantity=amount,
                    price_usd=Decimal("1") if asset in STABLECOINS else None,
                    total_usd=amount if asset in STABLECOINS else None,
                    timestamp=timestamp,
                    source_type="transaction_history",
                    raw_data=_api_record_common(
                        source_endpoint="c2c_trade_history",
                        source_id=order_number,
                        extra={
                            "account": "Funding",
                            "operation": "P2P Trading",
                            "remark": remark,
                            "trade_type": trade_type,
                            "fiat": row.get("fiat") or row.get("fiatSymbol"),
                            "total_price": row.get("totalPrice"),
                        },
                    ),
                    fingerprint_parts=c2c_fingerprint_parts(
                        timestamp=timestamp,
                        account="Funding",
                        operation="P2P Trading",
                        asset=asset,
                        signed_change=signed_change,
                        remark=remark,
                        order_number=order_number,
                    ),
                )
            )
        )
    return records


def _iter_time_windows(
    start_time: datetime | None,
    end_time: datetime,
    max_span: timedelta,
) -> list[tuple[datetime | None, datetime]]:
    if start_time is None:
        return [(None, end_time)]

    windows: list[tuple[datetime | None, datetime]] = []
    cursor = start_time
    while cursor < end_time:
        window_end = min(cursor + max_span, end_time)
        windows.append((cursor, window_end))
        if window_end >= end_time:
            break
        cursor = window_end + timedelta(microseconds=1)
    return windows


def _filter_normalized_records(
    records: list[Transaction],
    *,
    start_time: datetime | None,
    end_time: datetime,
) -> list[Transaction]:
    return [
        record
        for record in records
        if record.timestamp <= end_time
        and (start_time is None or record.timestamp >= start_time)
    ]


def _append_unique_records(
    destination: list[Transaction],
    seen_fingerprints: set[str],
    page_records: list[Transaction],
) -> None:
    for record in page_records:
        if record.fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(record.fingerprint)
        destination.append(record)


def _fetch_offset_records(
    *,
    label: str,
    fetch_page: Callable[[datetime | None, datetime, int, int], Any],
    normalize: Callable[[Any], list[Transaction]],
    start_time: datetime | None,
    end_time: datetime,
    limit: int = 1000,
    max_span: timedelta | None = None,
) -> tuple[list[Transaction], str | None]:
    records: list[Transaction] = []
    seen_fingerprints: set[str] = set()
    warning: str | None = None

    windows = (
        _iter_time_windows(start_time, end_time, max_span)
        if max_span is not None
        else [(start_time, end_time)]
    )

    for window_start, window_end in windows:
        offset = 0
        while True:
            try:
                payload = fetch_page(window_start, window_end, limit, offset)
            except BinanceError as exc:
                warning = f"{label}: {exc}"
                logger.warning("Skipping Binance history endpoint %s: %s", label, exc)
                break
            rows = _history_rows(payload)
            page_records = _filter_normalized_records(
                normalize(payload),
                start_time=window_start,
                end_time=window_end,
            )
            _append_unique_records(records, seen_fingerprints, page_records)
            if len(rows) < limit:
                break
            offset += limit
        if warning:
            break

    return records, warning


def _fetch_current_page_records(
    *,
    label: str,
    fetch_page: Callable[[datetime | None, datetime, int, int], Any],
    normalize: Callable[[Any], list[Transaction]],
    start_time: datetime | None,
    end_time: datetime,
    limit: int = HISTORY_PAGE_LIMIT,
    max_span: timedelta | None = None,
) -> tuple[list[Transaction], str | None]:
    records: list[Transaction] = []
    seen_fingerprints: set[str] = set()
    warning: str | None = None

    windows = (
        _iter_time_windows(start_time, end_time, max_span)
        if max_span is not None
        else [(start_time, end_time)]
    )

    for window_start, window_end in windows:
        current = 1
        while True:
            try:
                payload = fetch_page(window_start, window_end, limit, current)
            except BinanceError as exc:
                warning = f"{label}: {exc}"
                logger.warning("Skipping Binance history endpoint %s: %s", label, exc)
                break
            rows = _history_rows(payload)
            page_records = _filter_normalized_records(
                normalize(payload),
                start_time=window_start,
                end_time=window_end,
            )
            _append_unique_records(records, seen_fingerprints, page_records)
            if len(rows) < limit:
                break
            current += 1
        if warning:
            break

    return records, warning


def _fetch_single_window_records(
    *,
    label: str,
    fetch_page: Callable[[datetime | None, datetime, int], Any],
    normalize: Callable[[Any], list[Transaction]],
    start_time: datetime | None,
    end_time: datetime,
    limit: int = HISTORY_PAGE_LIMIT,
    max_span: timedelta | None = None,
) -> tuple[list[Transaction], str | None]:
    records: list[Transaction] = []
    seen_fingerprints: set[str] = set()

    windows = (
        _iter_time_windows(start_time, end_time, max_span)
        if max_span is not None
        else [(start_time, end_time)]
    )

    for window_start, window_end in windows:
        try:
            payload = fetch_page(window_start, window_end, limit)
        except BinanceError as exc:
            logger.warning("Skipping Binance history endpoint %s: %s", label, exc)
            return records, f"{label}: {exc}"
        rows = _history_rows(payload)
        page_warning = None
        if len(rows) >= limit:
            page_warning = (
                f"{label}: result hit page limit {limit}; "
                "additional rows may require a fresh export"
            )
        page_records = _filter_normalized_records(
            normalize(payload),
            start_time=window_start,
            end_time=window_end,
        )
        _append_unique_records(records, seen_fingerprints, page_records)
        if page_warning is not None:
            return records, page_warning

    return records, None


def _default_start_times() -> dict[str, datetime | None]:
    return {
        "deposit_history": None,
        "withdraw_history": None,
        "convert_trade_history": None,
        "simple_earn_flexible_subscriptions": None,
        "simple_earn_flexible_redemptions": None,
        "simple_earn_flexible_rewards[BONUS]": None,
        "simple_earn_flexible_rewards[REALTIME]": None,
        "simple_earn_locked_subscriptions": None,
        "simple_earn_locked_redemptions": None,
        "simple_earn_locked_rewards": None,
        "c2c_trade_history[BUY]": None,
        "c2c_trade_history[SELL]": None,
    }


def _supports(client: Any, method_name: str) -> bool:
    return callable(getattr(client, method_name, None))


def _fetch_c2c_page(
    client: Any,
    trade_type: str,
    cursor: datetime | None,
    stop: datetime,
    limit: int,
    current: int,
):
    return client.get_c2c_trade_history(
        cursor,
        stop,
        limit=limit,
        trade_type=trade_type,
        page=current,
    )


def build_delta_records(
    client: Any,
    start_time: datetime | dict[str, datetime | None] | None,
    end_time: datetime,
) -> tuple[list[Transaction], list[str]]:
    start_times = _default_start_times()
    if isinstance(start_time, dict):
        start_times.update(start_time)
    else:
        for label in start_times:
            start_times[label] = start_time

    records: list[Transaction] = []
    warnings: list[str] = []

    if _supports(client, "get_deposit_history"):
        endpoint_records, warning = _fetch_offset_records(
            label="deposit_history",
            normalize=_normalize_deposit_history,
            fetch_page=lambda cursor, stop, limit, offset: client.get_deposit_history(
                cursor,
                stop,
                limit=limit,
                offset=offset,
            ),
            start_time=start_times["deposit_history"],
            end_time=end_time,
            max_span=DEPOSIT_WITHDRAW_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    if _supports(client, "get_withdraw_history"):
        endpoint_records, warning = _fetch_offset_records(
            label="withdraw_history",
            normalize=_normalize_withdraw_history,
            fetch_page=lambda cursor, stop, limit, offset: client.get_withdraw_history(
                cursor,
                stop,
                limit=limit,
                offset=offset,
            ),
            start_time=start_times["withdraw_history"],
            end_time=end_time,
            max_span=DEPOSIT_WITHDRAW_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    if _supports(client, "get_convert_trade_history"):
        endpoint_records, warning = _fetch_single_window_records(
            label="convert_trade_history",
            normalize=_normalize_convert_history,
            fetch_page=lambda cursor, stop, limit: client.get_convert_trade_history(
                cursor,
                stop,
                limit=1000,
            ),
            start_time=start_times["convert_trade_history"],
            end_time=end_time,
            limit=1000,
            max_span=CONVERT_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    if _supports(client, "get_flexible_subscription_records"):
        endpoint_records, warning = _fetch_current_page_records(
            label="simple_earn_flexible_subscriptions",
            normalize=lambda payload: _normalize_simple_earn_history(
                payload, kind="flexible_subscription"
            ),
            fetch_page=lambda cursor, stop, limit, current: (
                client.get_flexible_subscription_records(
                    cursor,
                    stop,
                    limit=limit,
                    current=current,
                )
            ),
            start_time=start_times["simple_earn_flexible_subscriptions"],
            end_time=end_time,
            max_span=SIMPLE_EARN_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    if _supports(client, "get_flexible_redemption_records"):
        endpoint_records, warning = _fetch_current_page_records(
            label="simple_earn_flexible_redemptions",
            normalize=lambda payload: _normalize_simple_earn_history(
                payload, kind="flexible_redemption"
            ),
            fetch_page=lambda cursor, stop, limit, current: (
                client.get_flexible_redemption_records(
                    cursor,
                    stop,
                    limit=limit,
                    current=current,
                )
            ),
            start_time=start_times["simple_earn_flexible_redemptions"],
            end_time=end_time,
            max_span=SIMPLE_EARN_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    for reward_type in ("BONUS", "REALTIME"):
        label = f"simple_earn_flexible_rewards[{reward_type}]"
        if _supports(client, "get_flexible_rewards_history"):
            endpoint_records, warning = _fetch_single_window_records(
                label=label,
                normalize=lambda payload: _normalize_simple_earn_history(
                    payload, kind="flexible_reward"
                ),
                fetch_page=lambda cursor, stop, limit, reward_type=reward_type: (
                    client.get_flexible_rewards_history(
                        reward_type,
                        cursor,
                        stop,
                        limit=limit,
                    )
                ),
                start_time=start_times[label],
                end_time=end_time,
                max_span=SIMPLE_EARN_WINDOW,
            )
            records.extend(endpoint_records)
            if warning:
                warnings.append(warning)
    if _supports(client, "get_locked_subscription_records"):
        endpoint_records, warning = _fetch_current_page_records(
            label="simple_earn_locked_subscriptions",
            normalize=lambda payload: _normalize_simple_earn_history(
                payload, kind="locked_subscription"
            ),
            fetch_page=lambda cursor, stop, limit, current: (
                client.get_locked_subscription_records(
                    cursor,
                    stop,
                    limit=limit,
                    current=current,
                )
            ),
            start_time=start_times["simple_earn_locked_subscriptions"],
            end_time=end_time,
            max_span=SIMPLE_EARN_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    if _supports(client, "get_locked_redemption_records"):
        endpoint_records, warning = _fetch_current_page_records(
            label="simple_earn_locked_redemptions",
            normalize=lambda payload: _normalize_simple_earn_history(
                payload, kind="locked_redemption"
            ),
            fetch_page=lambda cursor, stop, limit, current: (
                client.get_locked_redemption_records(
                    cursor,
                    stop,
                    limit=limit,
                    current=current,
                )
            ),
            start_time=start_times["simple_earn_locked_redemptions"],
            end_time=end_time,
            max_span=SIMPLE_EARN_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    if _supports(client, "get_locked_rewards_history"):
        endpoint_records, warning = _fetch_current_page_records(
            label="simple_earn_locked_rewards",
            normalize=lambda payload: _normalize_simple_earn_history(
                payload, kind="locked_reward"
            ),
            fetch_page=lambda cursor, stop, limit, current: (
                client.get_locked_rewards_history(
                    cursor,
                    stop,
                    limit=limit,
                    current=current,
                )
            ),
            start_time=start_times["simple_earn_locked_rewards"],
            end_time=end_time,
            max_span=SIMPLE_EARN_WINDOW,
        )
        records.extend(endpoint_records)
        if warning:
            warnings.append(warning)
    for trade_type in ("BUY", "SELL"):
        label = f"c2c_trade_history[{trade_type}]"
        if _supports(client, "get_c2c_trade_history"):
            endpoint_records, warning = _fetch_current_page_records(
                label=label,
                normalize=_normalize_c2c_history,
                fetch_page=partial(_fetch_c2c_page, client, trade_type),
                start_time=start_times[label],
                end_time=end_time,
                max_span=DEPOSIT_WITHDRAW_WINDOW,
            )
            records.extend(endpoint_records)
            if warning:
                warnings.append(warning)
    return records, warnings


async def _api_history_start_time(
    session: AsyncSession,
) -> dict[str, datetime | None]:
    result = await session.execute(
        select(Transaction.timestamp, Transaction.tx_type, Transaction.raw_data).where(
            Transaction.institution == "binance",
            ~Transaction.tx_type.like("balance_snapshot_%"),
            Transaction.tx_type != "staking_position",
        )
    )
    latest_by_label = _default_start_times()
    for timestamp, tx_type, raw_data in result.all():
        payload = raw_data if isinstance(raw_data, dict) else {}
        source_type = payload.get("source_type")
        labels: list[str] = []
        if tx_type == "deposit":
            labels.append("deposit_history")
        elif tx_type == "withdrawal":
            labels.append("withdraw_history")
        elif tx_type in {"convert_buy", "convert_sell"}:
            labels.append("convert_trade_history")
        elif tx_type == "earn_subscribe":
            if source_type == "simple_earn_flexible_subscription":
                labels.append("simple_earn_flexible_subscriptions")
            elif source_type == "simple_earn_locked_subscription":
                labels.append("simple_earn_locked_subscriptions")
        elif tx_type == "earn_redeem":
            if source_type == "simple_earn_flexible_redemption":
                labels.append("simple_earn_flexible_redemptions")
            elif source_type == "simple_earn_locked_redemption":
                labels.append("simple_earn_locked_redemptions")
        elif tx_type == "earn_reward":
            if source_type == "simple_earn_flexible_reward":
                reward_type = str(payload.get("reward_type") or "").upper()
                if "REALTIME" in reward_type:
                    labels.append("simple_earn_flexible_rewards[REALTIME]")
                else:
                    labels.append("simple_earn_flexible_rewards[BONUS]")
            elif source_type == "simple_earn_locked_reward":
                labels.append("simple_earn_locked_rewards")
        elif (
            tx_type == "external_deposit" and payload.get("operation") == "P2P Trading"
        ):
            labels.append("c2c_trade_history[BUY]")
        elif (
            tx_type == "external_withdrawal"
            and payload.get("operation") == "P2P Trading"
        ):
            labels.append("c2c_trade_history[SELL]")

        for label in labels:
            current = latest_by_label[label]
            if current is None or timestamp > current:
                latest_by_label[label] = timestamp

    return {
        label: value - API_DELTA_OVERLAP if value is not None else None
        for label, value in latest_by_label.items()
    }


def build_snapshot_records(summary, captured_at: datetime) -> list[Transaction]:
    records: list[Transaction] = []
    ts_key = captured_at.isoformat()[:16]

    all_balances = (
        summary.spot_balances + summary.funding_balances + summary.earn_balances
    )
    for balance in all_balances:
        if balance.total <= 0:
            continue
        asset = balance.asset.upper()
        qty = Decimal(str(balance.total))
        tx_type = f"balance_snapshot_{balance.account_type.value}"
        records.append(
            Transaction(
                institution="binance",
                tx_type=tx_type,
                asset_symbol=asset,
                asset_type=_asset_type(asset),
                quantity=qty,
                price_usd=None,
                total_usd=None,
                fee=Decimal("0"),
                fee_currency="BNB",
                timestamp=captured_at,
                fingerprint=_fingerprint("binance", tx_type, asset, str(qty), ts_key),
                raw_data={
                    "free": balance.free,
                    "locked": balance.locked,
                    "account_type": balance.account_type.value,
                },
            )
        )

    for position in summary.staking_positions:
        if position.amount <= 0:
            continue
        asset = position.asset.upper()
        qty = Decimal(str(position.amount))
        records.append(
            Transaction(
                institution="binance",
                tx_type="staking_position",
                asset_symbol=asset,
                asset_type=_asset_type(asset),
                quantity=qty,
                price_usd=None,
                total_usd=None,
                fee=Decimal("0"),
                fee_currency="BNB",
                timestamp=captured_at,
                fingerprint=_fingerprint(
                    "binance",
                    "staking_position",
                    asset,
                    str(qty),
                    ts_key,
                ),
                raw_data={
                    "position_id": position.position_id,
                    "apy": position.apy,
                    "status": position.status,
                },
            )
        )

    return records


def summarize_snapshot_totals(records: list[Transaction]) -> dict[str, Decimal]:
    return analytics.latest_binance_snapshot_aggregation(
        records,
        include_cash=True,
    ).quantities


def _normalize_pending_order_status(raw_status: str) -> str:
    normalized = str(raw_status or "").strip().upper()
    if normalized in {"NEW", "PARTIALLY_FILLED"}:
        return "open"
    if normalized in {"PENDING_NEW", "PENDING_CANCEL", "PENDING_REPLACE"}:
        return "pending"
    if normalized == "FILLED":
        return "filled"
    if normalized in {"CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}:
        return "closed"
    return normalized.lower() or "open"


async def _sync_pending_orders(session: AsyncSession, client: Any) -> None:
    if not _supports(client, "get_open_orders"):
        return

    raw_orders = client.get_open_orders()
    order_rows: list[dict[str, Any]] = []
    asset_symbols: set[str] = set()
    seen_order_ids: set[str] = set()

    for order in raw_orders:
        asset_symbol = str(order.symbol or "").upper()
        external_order_id = str(order.order_id or "").strip()
        if not asset_symbol or not external_order_id:
            continue

        asset_symbols.add(asset_symbol)
        seen_order_ids.add(external_order_id)
        order_rows.append(
            {
                "asset_symbol": asset_symbol,
                "institution": "binance",
                "external_order_id": external_order_id,
                "symbol": asset_symbol,
                "order_type": str(order.order_type or "unknown").lower(),
                "status": _normalize_pending_order_status(order.status),
                "side": str(order.side or "buy").lower(),
                "quantity": Decimal(str(order.quantity)),
                "limit_price": (
                    Decimal(str(order.limit_price))
                    if order.limit_price is not None
                    else None
                ),
                "stop_price": (
                    Decimal(str(order.stop_price))
                    if order.stop_price is not None
                    else None
                ),
                "placed_at": order.placed_at,
            }
        )

    if asset_symbols:
        asset_insert = pg_insert(Asset).values(
            [
                {
                    "symbol": symbol,
                    "asset_type": _asset_type(symbol),
                    "last_price_usd": None,
                    "last_seen_at": None,
                }
                for symbol in sorted(asset_symbols)
            ]
        )
        await session.execute(
            asset_insert.on_conflict_do_nothing(constraint="uq_assets_symbol")
        )

        asset_rows = (
            (
                await session.execute(
                    select(Asset).where(Asset.symbol.in_(asset_symbols))
                )
            )
            .scalars()
            .all()
        )
        asset_ids_by_symbol = {asset.symbol: asset.id for asset in asset_rows}

        if order_rows:
            pending_order_insert = pg_insert(PendingOrder).values(
                [
                    {
                        "asset_id": asset_ids_by_symbol[row["asset_symbol"]],
                        "institution": row["institution"],
                        "external_order_id": row["external_order_id"],
                        "symbol": row["symbol"],
                        "order_type": row["order_type"],
                        "status": row["status"],
                        "side": row["side"],
                        "quantity": row["quantity"],
                        "limit_price": row["limit_price"],
                        "stop_price": row["stop_price"],
                        "placed_at": row["placed_at"],
                    }
                    for row in order_rows
                ]
            )
            await session.execute(
                pending_order_insert.on_conflict_do_update(
                    constraint="uq_pending_orders_institution_external_order_id",
                    set_={
                        "asset_id": pending_order_insert.excluded.asset_id,
                        "symbol": pending_order_insert.excluded.symbol,
                        "order_type": pending_order_insert.excluded.order_type,
                        "status": pending_order_insert.excluded.status,
                        "side": pending_order_insert.excluded.side,
                        "quantity": pending_order_insert.excluded.quantity,
                        "limit_price": pending_order_insert.excluded.limit_price,
                        "stop_price": pending_order_insert.excluded.stop_price,
                        "placed_at": pending_order_insert.excluded.placed_at,
                    },
                )
            )

    stale_orders = (
        (
            await session.execute(
                select(PendingOrder).where(
                    PendingOrder.institution == "binance",
                    PendingOrder.status.in_(("open", "pending")),
                )
            )
        )
        .scalars()
        .all()
    )
    for stale_order in stale_orders:
        if stale_order.external_order_id not in seen_order_ids:
            stale_order.status = "closed"


async def sync_binance(session: AsyncSession) -> dict:
    """
    Pull Binance balances and normalize them as snapshot transactions.
    Returns a summary dict with counts.
    """
    # Prefer keys stored in the Institution row (set via Settings page) over .env
    inst_row = (
        await session.execute(select(Institution).where(Institution.name == "binance"))
    ).scalar_one_or_none()

    credentials = (
        inst_row.get_api_credentials()
        if inst_row is not None
        else {"api_key": None, "api_secret": None}
    )
    db_key = credentials["api_key"]
    db_secret = credentials["api_secret"]

    if (
        (not db_key or not db_secret)
        and settings.BINANCE_API_KEY
        and settings.BINANCE_API_SECRET
    ):
        if inst_row is None:
            inst_row = Institution(name="binance")
            session.add(inst_row)
        try:
            inst_row.set_api_credentials(
                settings.BINANCE_API_KEY,
                settings.BINANCE_API_SECRET,
                rotated=False,
            )
        except CredentialConfigError:
            raise
        db_key = settings.BINANCE_API_KEY
        db_secret = settings.BINANCE_API_SECRET

    if not db_key or not db_secret:
        return {
            "error": "Binance encrypted API credentials not configured",
            "synced": 0,
        }

    client = create_binance_client(api_key=db_key, api_secret=db_secret)
    if not client.api_key:
        return {"error": "Binance API key not configured", "synced": 0}

    now = datetime.now(UTC)
    baseline_result = await session.execute(
        select(ActivityLog.id)
        .where(
            ActivityLog.source == "imports.binance_baseline",
            ActivityLog.status == "confirmed",
        )
        .order_by(ActivityLog.created_at.desc())
        .limit(1)
    )
    has_export_baseline = baseline_result.scalar_one_or_none() is not None
    api_since = await _api_history_start_time(session)
    api_since_values = [value for value in api_since.values() if value is not None]
    new_count = 0
    skip_count = 0
    snapshot_new_count = 0
    snapshot_skip_count = 0
    delta_new_count = 0
    delta_skip_count = 0
    snapshot_warnings: list[str] = []
    pending_order_warnings: list[str] = []

    spot_balances: list = []
    funding_balances: list = []
    earn_balances: list = []
    staking_positions: list = []
    try:
        spot_balances = client.get_spot_balances()
        funding_balances = client.get_funding_balances(suppress_errors=False)
        earn_balances = client.get_flexible_products(suppress_errors=False)
        staking_positions = client.get_staking_positions(suppress_errors=False)
    except BinanceError as exc:
        snapshot_warnings.append(f"snapshot: {exc}")
    except Exception as exc:
        snapshot_warnings.append(f"snapshot: {exc}")

    snapshot_records: list[Transaction] = []
    if not snapshot_warnings:
        summary = SimpleNamespace(
            spot_balances=spot_balances,
            funding_balances=funding_balances,
            earn_balances=earn_balances,
            staking_positions=staking_positions,
        )
        snapshot_records = build_snapshot_records(summary, now)

    try:
        await _sync_pending_orders(session, client)
    except BinanceError as exc:
        pending_order_warnings.append(f"pending_orders: {exc}")
    except Exception as exc:
        pending_order_warnings.append(f"pending_orders: {exc}")

    delta_warnings: list[str] = []
    delta_records: list[Transaction] = []
    coverage_notes: list[str] = []
    if has_export_baseline:
        delta_records, delta_warnings = build_delta_records(client, api_since, now)
        coverage_notes = [DELTA_COVERAGE_NOTE]
    else:
        delta_warnings = [
            "export baseline required before Binance API delta sync can extend history"
        ]

    all_records = [
        *snapshot_records,
        *delta_records,
    ]

    existing_transactions = (
        (
            await session.execute(
                select(Transaction).where(
                    Transaction.institution == "binance",
                    Transaction.import_id.is_not(None),
                    ~Transaction.tx_type.like("balance_snapshot_%"),
                    Transaction.tx_type != "staking_position",
                )
            )
        )
        .scalars()
        .all()
    )
    overlap_counts = _build_source_specific_overlap_counts(existing_transactions)

    for tx in all_records:
        fp = tx.fingerprint
        existing = await session.execute(
            select(Transaction.id, Transaction.import_id).where(
                Transaction.fingerprint == fp
            )
        )
        existing_row = existing.first()
        if existing_row is not None:
            _, existing_import_id = existing_row
            overlap_key = _source_specific_overlap_key(tx)
            if (
                existing_import_id is not None
                and overlap_key is not None
                and overlap_counts[overlap_key] > 0
            ):
                overlap_counts[overlap_key] -= 1
            skip_count += 1
            if (
                tx.tx_type.startswith("balance_snapshot_")
                or tx.tx_type == "staking_position"
            ):
                snapshot_skip_count += 1
            else:
                delta_skip_count += 1
            continue
        overlap_key = _source_specific_overlap_key(tx)
        if overlap_key is not None and overlap_counts[overlap_key] > 0:
            overlap_counts[overlap_key] -= 1
            skip_count += 1
            delta_skip_count += 1
            continue
        session.add(tx)
        new_count += 1
        if (
            tx.tx_type.startswith("balance_snapshot_")
            or tx.tx_type == "staking_position"
        ):
            snapshot_new_count += 1
        else:
            delta_new_count += 1

    # Update institution last_sync (reuse inst_row fetched above)
    if inst_row:
        inst_row.last_sync_at = now
    else:
        session.add(Institution(name="binance", last_sync_at=now))

    degraded = bool(delta_warnings or snapshot_warnings or pending_order_warnings)
    activity_status = "degraded" if degraded else "success"
    combined_warnings = [
        *snapshot_warnings,
        *pending_order_warnings,
        *delta_warnings,
    ]
    activity_message = (
        "; ".join(combined_warnings)
        if combined_warnings
        else "Binance delta sync completed successfully"
    )
    session.add(
        ActivityLog(
            source="sync.binance",
            status=activity_status,
            message=activity_message,
        )
    )
    await session.commit()
    logger.info(f"Binance sync complete: {new_count} new, {skip_count} skipped")
    return {
        "synced": new_count,
        "skipped": skip_count,
        "snapshot_synced": snapshot_new_count,
        "snapshot_skipped": snapshot_skip_count,
        "delta_synced": delta_new_count,
        "delta_skipped": delta_skip_count,
        "api_since": min(api_since_values).isoformat() if api_since_values else None,
        "degraded": degraded,
        "warnings": combined_warnings,
        "notes": coverage_notes,
        "synced_at": now.isoformat(),
    }
