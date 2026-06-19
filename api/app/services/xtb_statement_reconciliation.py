from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Literal

from app.services.xtb_cash_ledger import calculate_xtb_cash_ledger

XtbStatementSourceKind = Literal["full_statement", "daily_pdf", "gmail_daily_pdf"]

AUTHORITATIVE_SOURCES = {"full_statement"}
PROVISIONAL_SOURCES = {"daily_pdf", "gmail_daily_pdf"}
FEE_TAX_TYPES = {"fee", "commission", "stamp_duty", "swap", "tax"}
CASH_LEDGER_TYPE_ALIASES = {"tax": "fee"}


@dataclass(frozen=True)
class XtbCurrentPositionEvidence:
    symbol: str
    quantity: Decimal
    market_price_usd: Decimal | None = None
    current_value_usd: Decimal | None = None


@dataclass(frozen=True)
class XtbCashActivityEvidence:
    tx_type: str
    amount_usd: Decimal
    symbol: str = "USD"
    description: str = ""
    fee_usd: Decimal = Decimal("0")


@dataclass(frozen=True)
class XtbClosedPositionPlEvidence:
    symbol: str
    gross_pl_usd: Decimal
    description: str = ""


@dataclass(frozen=True)
class XtbStatementEvidence:
    source_kind: XtbStatementSourceKind
    current_positions: Iterable[XtbCurrentPositionEvidence] = field(
        default_factory=tuple
    )
    current_positions_proved: bool = False
    cash_operations: Iterable[XtbCashActivityEvidence] = field(default_factory=tuple)
    closed_position_pl_rows: Iterable[XtbClosedPositionPlEvidence] = field(
        default_factory=tuple
    )
    broker_cash_balance_usd: Decimal | None = None
    reconciled_against_authoritative_statement: bool = False


@dataclass(frozen=True)
class XtbStatementIssue:
    code: str
    message: str
    scope: str
    symbol: str | None = None


@dataclass(frozen=True)
class XtbConfidenceScope:
    state: Literal["trusted", "warning", "provisional", "review_required", "blocked"]
    issues: tuple[XtbStatementIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class XtbBrokerCashSummary:
    amount_usd: Decimal
    trusted: bool
    issues: tuple[XtbStatementIssue, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class XtbAmountRollup:
    total_usd: Decimal
    count: int


@dataclass(frozen=True)
class XtbClosedPositionPlSummary(XtbAmountRollup):
    used_as_cash_proceeds: bool = False


@dataclass(frozen=True)
class XtbCurrentPositionSummary:
    symbol: str
    quantity: Decimal
    market_price_usd: Decimal
    current_value_usd: Decimal


@dataclass(frozen=True)
class XtbCurrentValueStatementSummary:
    source_authority: Literal["authoritative", "provisional"]
    current_positions: tuple[XtbCurrentPositionSummary, ...]
    current_positions_value_usd: Decimal
    broker_cash: XtbBrokerCashSummary
    current_value_usd: Decimal
    current_value_trusted: bool
    fees_taxes: XtbAmountRollup
    closed_position_pl: XtbClosedPositionPlSummary
    confidence: dict[str, XtbConfidenceScope]
    issues: tuple[XtbStatementIssue, ...]


def reconcile_xtb_current_value_statement(
    statement: XtbStatementEvidence,
    *,
    cash_statement_tolerance: Decimal = Decimal("0.01"),
) -> XtbCurrentValueStatementSummary:
    position_evidence = tuple(statement.current_positions)
    cash_operations = tuple(statement.cash_operations)
    closed_position_pl_rows = tuple(statement.closed_position_pl_rows)

    positions = _summarize_positions(position_evidence)
    position_issues = tuple(
        _position_issues(
            position_evidence,
            current_positions_proved=statement.current_positions_proved,
        )
    )
    cash_ledger = calculate_xtb_cash_ledger(
        _cash_ledger_rows(cash_operations),
        broker_cash_balance_usd=statement.broker_cash_balance_usd,
        cash_statement_tolerance=cash_statement_tolerance,
    )
    broker_cash_issues = tuple(
        XtbStatementIssue(
            code=issue.code,
            message=issue.message,
            scope="broker_cash",
            symbol=issue.asset_symbol,
        )
        for issue in cash_ledger.issues
    )

    source_issues = _source_issues(statement)
    issues = source_issues + position_issues + broker_cash_issues

    broker_cash = XtbBrokerCashSummary(
        amount_usd=Decimal(statement.broker_cash_balance_usd)
        if statement.broker_cash_balance_usd is not None
        else cash_ledger.cash_balance_usd,
        trusted=cash_ledger.trusted,
        issues=broker_cash_issues,
    )
    positions_value = sum(
        (position.current_value_usd for position in positions), Decimal("0")
    )
    current_value_state = _current_value_state(
        source_issues=source_issues,
        position_issues=position_issues,
        broker_cash=broker_cash,
    )
    current_value_trusted = current_value_state.state == "trusted"

    return XtbCurrentValueStatementSummary(
        source_authority=_source_authority(statement),
        current_positions=positions,
        current_positions_value_usd=positions_value,
        broker_cash=broker_cash,
        current_value_usd=positions_value + broker_cash.amount_usd,
        current_value_trusted=current_value_trusted,
        fees_taxes=_fees_taxes(cash_operations),
        closed_position_pl=_closed_position_pl(closed_position_pl_rows),
        confidence={
            "current_value": current_value_state,
            "broker_cash": XtbConfidenceScope(
                state="trusted" if broker_cash.trusted else "blocked",
                issues=broker_cash_issues,
            ),
            "position_existence": XtbConfidenceScope(
                state="trusted" if not position_issues else "blocked",
                issues=position_issues,
            ),
        },
        issues=issues,
    )


def _summarize_positions(
    positions: Iterable[XtbCurrentPositionEvidence],
) -> tuple[XtbCurrentPositionSummary, ...]:
    summaries: list[XtbCurrentPositionSummary] = []
    for position in positions:
        market_price = position.market_price_usd
        if market_price is None and position.current_value_usd is not None:
            quantity = Decimal(position.quantity)
            market_price = (
                Decimal("0") if quantity == 0 else position.current_value_usd / quantity
            )
        if market_price is None:
            continue

        current_value = (
            position.current_value_usd
            if position.current_value_usd is not None
            else position.quantity * market_price
        )
        summaries.append(
            XtbCurrentPositionSummary(
                symbol=position.symbol,
                quantity=Decimal(position.quantity),
                market_price_usd=Decimal(market_price),
                current_value_usd=Decimal(current_value),
            )
        )
    return tuple(summaries)


def _position_issues(
    positions: Iterable[XtbCurrentPositionEvidence],
    *,
    current_positions_proved: bool,
) -> tuple[XtbStatementIssue, ...]:
    issues: list[XtbStatementIssue] = []
    positions = tuple(positions)
    if not positions and not current_positions_proved:
        issues.append(
            XtbStatementIssue(
                code="missing_position_evidence",
                message=(
                    "XTB current value requires authoritative current position "
                    "evidence, even when the statement proves zero open positions."
                ),
                scope="position_existence",
            )
        )

    for position in positions:
        if position.market_price_usd is None and position.current_value_usd is None:
            issues.append(
                XtbStatementIssue(
                    code="missing_position_current_value",
                    message=(
                        "XTB current position requires market price or current "
                        "value evidence."
                    ),
                    scope="position_existence",
                    symbol=position.symbol,
                )
            )
    return tuple(issues)


def _cash_ledger_rows(
    cash_operations: Iterable[XtbCashActivityEvidence],
) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(
            institution="xtb",
            tx_type=CASH_LEDGER_TYPE_ALIASES.get(
                operation.tx_type.lower(), operation.tx_type
            ),
            asset_symbol=operation.symbol,
            quantity=abs(Decimal(operation.amount_usd)),
            price_usd=None,
            total_usd=abs(Decimal(operation.amount_usd)),
            fee=abs(Decimal(operation.fee_usd)),
            fee_currency="USD",
            description=operation.description,
            raw_data={},
        )
        for operation in cash_operations
    )


def _fees_taxes(
    cash_operations: Iterable[XtbCashActivityEvidence],
) -> XtbAmountRollup:
    rows = [
        operation
        for operation in cash_operations
        if operation.tx_type.lower() in FEE_TAX_TYPES
    ]
    attached_fee_rows = [
        operation
        for operation in cash_operations
        if operation.tx_type.lower() not in FEE_TAX_TYPES
        and Decimal(operation.fee_usd) != Decimal("0")
    ]
    return XtbAmountRollup(
        total_usd=sum((abs(Decimal(row.amount_usd)) for row in rows), Decimal("0"))
        + sum(
            (abs(Decimal(row.fee_usd)) for row in attached_fee_rows),
            Decimal("0"),
        ),
        count=len(rows) + len(attached_fee_rows),
    )


def _closed_position_pl(
    rows: Iterable[XtbClosedPositionPlEvidence],
) -> XtbClosedPositionPlSummary:
    pl_rows = tuple(rows)
    return XtbClosedPositionPlSummary(
        total_usd=sum((Decimal(row.gross_pl_usd) for row in pl_rows), Decimal("0")),
        count=len(pl_rows),
        used_as_cash_proceeds=False,
    )


def _source_authority(
    statement: XtbStatementEvidence,
) -> Literal["authoritative", "provisional"]:
    if statement.source_kind in AUTHORITATIVE_SOURCES:
        return "authoritative"
    return "provisional"


def _source_issues(statement: XtbStatementEvidence) -> tuple[XtbStatementIssue, ...]:
    if (
        statement.source_kind in PROVISIONAL_SOURCES
        and not statement.reconciled_against_authoritative_statement
    ):
        return (
            XtbStatementIssue(
                code="provisional_source_requires_full_statement",
                message=(
                    "XTB daily PDF and Gmail evidence remains provisional until "
                    "reconciled against an authoritative full statement."
                ),
                scope="current_value",
            ),
        )
    return ()


def _current_value_state(
    *,
    source_issues: tuple[XtbStatementIssue, ...],
    position_issues: tuple[XtbStatementIssue, ...],
    broker_cash: XtbBrokerCashSummary,
) -> XtbConfidenceScope:
    if source_issues:
        return XtbConfidenceScope(state="provisional", issues=source_issues)
    if position_issues:
        return XtbConfidenceScope(state="blocked", issues=position_issues)
    if not broker_cash.trusted:
        return XtbConfidenceScope(state="blocked", issues=broker_cash.issues)
    return XtbConfidenceScope(state="trusted")
