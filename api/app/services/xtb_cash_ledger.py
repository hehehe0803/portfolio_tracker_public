from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable


USD_CASH_SYMBOLS = {"USD", "USDT", "USDC"}

DEPOSIT_TYPES = {"deposit", "external_deposit"}
WITHDRAWAL_TYPES = {"withdrawal", "external_withdrawal"}
BUY_TYPES = {"buy", "open", "open_position"}
SELL_TYPES = {"sell", "close", "close_position"}
DIVIDEND_TYPES = {"dividend"}
CHARGE_TYPES = {"fee", "commission", "stamp_duty", "swap"}
NON_CASH_TYPES = {"split", "correction"}
KNOWN_XTB_TYPES = (
    DEPOSIT_TYPES
    | WITHDRAWAL_TYPES
    | BUY_TYPES
    | SELL_TYPES
    | DIVIDEND_TYPES
    | CHARGE_TYPES
)


@dataclass(frozen=True)
class XtbCashLedgerIssue:
    code: str
    message: str
    transaction_id: int | None = None
    asset_symbol: str | None = None


@dataclass(frozen=True)
class XtbCashLedger:
    cash_balance_usd: Decimal
    trusted: bool
    issues: tuple[XtbCashLedgerIssue, ...] = field(default_factory=tuple)


def calculate_xtb_cash_ledger(
    transactions: Iterable[Any],
    *,
    broker_cash_balance_usd: Decimal | None = None,
    cash_statement_tolerance: Decimal = Decimal("0.01"),
) -> XtbCashLedger:
    cash_balance_usd = Decimal("0")
    issues: list[XtbCashLedgerIssue] = []

    for tx in transactions:
        if _is_clearly_not_xtb(tx):
            continue

        tx_type = _normalized_tx_type(tx)
        if tx_type in NON_CASH_TYPES:
            continue

        if tx_type not in KNOWN_XTB_TYPES:
            issues.append(
                XtbCashLedgerIssue(
                    code="unknown_xtb_transaction_type",
                    message=f"Unknown XTB transaction type: {tx_type or 'missing'}",
                    transaction_id=_transaction_id(tx),
                    asset_symbol=_asset_symbol(tx),
                )
            )
            continue

        if _is_unreliable_profit_loss_sell(tx, tx_type):
            issues.append(
                XtbCashLedgerIssue(
                    code="sell_proceeds_not_reliable",
                    message=(
                        "XTB closed-position P/L row cannot be used as cash "
                        "sale proceeds."
                    ),
                    transaction_id=_transaction_id(tx),
                    asset_symbol=_asset_symbol(tx),
                )
            )
            continue

        value_usd = _reliable_value_usd(tx, tx_type)
        if value_usd is None:
            issues.append(
                XtbCashLedgerIssue(
                    code="missing_usd_amount",
                    message="Missing reliable USD amount for XTB cash ledger row.",
                    transaction_id=_transaction_id(tx),
                    asset_symbol=_asset_symbol(tx),
                )
            )
            continue

        fee_usd = _usd_fee(tx)

        if tx_type in DEPOSIT_TYPES or tx_type in DIVIDEND_TYPES:
            cash_balance_usd += value_usd
        elif tx_type in WITHDRAWAL_TYPES or tx_type in CHARGE_TYPES:
            cash_balance_usd -= value_usd
        elif tx_type in BUY_TYPES:
            cash_balance_usd -= value_usd + fee_usd
        elif tx_type in SELL_TYPES:
            cash_balance_usd += value_usd - fee_usd

    if not issues:
        if broker_cash_balance_usd is None:
            issues.append(
                XtbCashLedgerIssue(
                    code="missing_cash_control_total",
                    message=(
                        "XTB cash ledger requires an authoritative broker cash "
                        "control total before it can be trusted."
                    ),
                )
            )
        else:
            expected_cash = Decimal(broker_cash_balance_usd)
            if abs(cash_balance_usd - expected_cash) > cash_statement_tolerance:
                issues.append(
                    XtbCashLedgerIssue(
                        code="cash_control_total_mismatch",
                        message=(
                            "Calculated XTB cash ledger does not match broker "
                            "cash control total."
                        ),
                    )
                )

    return XtbCashLedger(
        cash_balance_usd=cash_balance_usd,
        trusted=not issues,
        issues=tuple(issues),
    )


def _reliable_value_usd(tx: Any, tx_type: str) -> Decimal | None:
    total_usd = getattr(tx, "total_usd", None)
    if total_usd is not None:
        return abs(Decimal(total_usd))

    quantity = getattr(tx, "quantity", None)
    price_usd = getattr(tx, "price_usd", None)
    if (
        tx_type in BUY_TYPES | SELL_TYPES
        and quantity is not None
        and price_usd is not None
    ):
        return abs(Decimal(quantity) * Decimal(price_usd))

    if _asset_symbol(tx) in USD_CASH_SYMBOLS and quantity is not None:
        return abs(Decimal(quantity))

    return None


def _usd_fee(tx: Any) -> Decimal:
    fee = getattr(tx, "fee", None)
    if fee is None:
        return Decimal("0")

    fee_currency = str(getattr(tx, "fee_currency", "") or "").upper()
    if fee_currency not in USD_CASH_SYMBOLS:
        return Decimal("0")

    return abs(Decimal(fee))


def _is_unreliable_profit_loss_sell(tx: Any, tx_type: str) -> bool:
    if tx_type not in SELL_TYPES or _asset_symbol(tx) in USD_CASH_SYMBOLS:
        return False

    description = _description(tx)
    if "@" in description:
        return False

    original_type = _raw_original_type(tx)
    return (
        tx_type == "close_position"
        or original_type == "close_position"
        or original_type == "close"
        or description.startswith("close ")
    )


def _is_clearly_not_xtb(tx: Any) -> bool:
    institution = getattr(tx, "institution", None)
    if institution is None:
        return False
    return str(institution).lower() != "xtb"


def _normalized_tx_type(tx: Any) -> str:
    tx_type = getattr(tx, "tx_type", "")
    if hasattr(tx_type, "value"):
        tx_type = tx_type.value
    return str(tx_type or "").lower()


def _asset_symbol(tx: Any) -> str | None:
    symbol = getattr(tx, "asset_symbol", None)
    if symbol is None:
        symbol = getattr(tx, "symbol", None)
    if symbol is None:
        return None
    return str(symbol).upper()


def _description(tx: Any) -> str:
    description = getattr(tx, "description", None)
    if description is None:
        raw_data = getattr(tx, "raw_data", None)
        if isinstance(raw_data, dict):
            description = raw_data.get("description")
    return str(description or "").lower()


def _raw_original_type(tx: Any) -> str:
    raw_data = getattr(tx, "raw_data", None)
    if not isinstance(raw_data, dict):
        return ""
    original_type = raw_data.get("original_type", "")
    if hasattr(original_type, "value"):
        original_type = original_type.value
    return str(original_type or "").lower()


def _transaction_id(tx: Any) -> int | None:
    value = getattr(tx, "id", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
