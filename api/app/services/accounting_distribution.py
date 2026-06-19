from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

ConfidenceState = Literal[
    "trusted",
    "warning",
    "provisional",
    "review_required",
    "blocked",
]
DistributionAssetType = Literal[
    "crypto",
    "stocks_etfs",
    "commodities",
    "cash",
    "other",
]
PercentageState = Literal["visible", "suppressed"]
CashReserveKind = Literal["stablecoin", "broker_cash", "other_tracked_cash"]

CONFIDENCE_ORDER: dict[str, int] = {
    "trusted": 0,
    "warning": 1,
    "provisional": 2,
    "review_required": 3,
    "blocked": 4,
}

DISTRIBUTION_BUCKET_ORDER: tuple[DistributionAssetType, ...] = (
    "crypto",
    "stocks_etfs",
    "commodities",
    "cash",
    "other",
)
STABLECOIN_SYMBOLS = {"USDT", "USDC", "BUSD", "FDUSD", "DAI"}
CASH_SYMBOLS = {"USD", "EUR", "GBP", "CHF", "JPY", *STABLECOIN_SYMBOLS}
STOCK_ETF_TYPES = {"stock", "stocks", "equity", "equities", "etf", "fund"}
COMMODITY_TYPES = {"commodity", "commodities", "metal", "precious_metal"}
CASH_TYPES = {"cash", "fiat", "currency", "stablecoin", "money_market"}


@dataclass
class DistributionHolding:
    symbol: str
    asset_type: str
    current_value_usd: Decimal | None
    confidence_state: ConfidenceState = "trusted"
    reason_codes: tuple[str, ...] = ()
    cash_reserve_kind: CashReserveKind | str | None = None
    institution: str | None = None


@dataclass
class DistributionCurrentValue:
    value_usd: Decimal | None
    as_of: datetime
    holdings_reconciled: bool
    broker_cash_reconciled: bool
    stablecoin_reserve_reconciled: bool
    position_existence_reconciled: bool
    confidence_state: ConfidenceState = "trusted"
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DistributionBucket:
    asset_type: DistributionAssetType
    value_usd: Decimal
    percentage: Decimal | None
    percentage_state: PercentageState
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CashReserveBreakdown:
    stablecoin_usd: Decimal
    broker_cash_usd: Decimal
    other_tracked_cash_usd: Decimal
    total_usd: Decimal
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DistributionSummary:
    current_value_usd: Decimal | None
    total_allocated_usd: Decimal
    reconciliation_delta_usd: Decimal | None
    reconciliation_tolerance_usd: Decimal | None
    percentages_visible: bool
    asset_type_buckets: tuple[DistributionBucket, ...]
    cash_reserve: CashReserveBreakdown
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class _ConfidenceImpact:
    state: ConfidenceState
    reason_code: str


def calculate_asset_type_distribution(
    *,
    current_value: DistributionCurrentValue | Any,
    holdings: Sequence[DistributionHolding | Any],
    reconciliation_tolerance_usd: Decimal | None = None,
) -> DistributionSummary:
    current_value_usd = _decimal_or_none(_attr(current_value, "value_usd", None))
    bucket_values: dict[DistributionAssetType, Decimal] = {
        bucket: Decimal("0") for bucket in DISTRIBUTION_BUCKET_ORDER
    }
    bucket_impacts: dict[DistributionAssetType, list[_ConfidenceImpact]] = {
        bucket: [] for bucket in DISTRIBUTION_BUCKET_ORDER
    }
    cash_impacts: list[_ConfidenceImpact] = []
    global_impacts: list[_ConfidenceImpact] = []
    stablecoin_usd = Decimal("0")
    broker_cash_usd = Decimal("0")
    other_tracked_cash_usd = Decimal("0")

    for holding in holdings:
        symbol = _normalized_symbol(_attr(holding, "symbol", ""))
        value_usd = _decimal_or_none(_attr(holding, "current_value_usd", None))
        asset_type = _distribution_asset_type(holding, symbol=symbol)
        if value_usd is None:
            impact = _ConfidenceImpact("blocked", "missing_holding_current_value")
            bucket_impacts[asset_type].append(impact)
            global_impacts.append(impact)
            if asset_type == "cash":
                cash_impacts.append(impact)
            continue

        bucket_values[asset_type] += value_usd
        holding_state = _confidence_state(_attr(holding, "confidence_state", "trusted"))
        if holding_state != "trusted":
            reason_code = str(
                _first_or_none(_attr(holding, "reason_codes", ()))
                or f"holding_confidence_{holding_state}"
            )
            impact = _ConfidenceImpact(holding_state, reason_code)
            bucket_impacts[asset_type].append(impact)
            global_impacts.append(impact)
            if asset_type == "cash":
                cash_impacts.append(impact)

        if asset_type != "cash":
            continue

        reserve_kind = _cash_reserve_kind(holding, symbol=symbol)
        if reserve_kind == "stablecoin":
            stablecoin_usd += value_usd
        elif reserve_kind == "broker_cash":
            broker_cash_usd += value_usd
        else:
            other_tracked_cash_usd += value_usd

    global_impacts.extend(_current_value_impacts(current_value, current_value_usd))
    cash_impacts.extend(_cash_reserve_impacts(current_value))
    bucket_impacts["cash"].extend(cash_impacts)

    total_allocated_usd = sum(bucket_values.values(), Decimal("0"))
    tolerance_usd = _reconciliation_tolerance(
        current_value_usd, reconciliation_tolerance_usd
    )
    reconciliation_delta_usd = (
        total_allocated_usd - current_value_usd
        if current_value_usd is not None
        else None
    )
    if (
        current_value_usd is not None
        and reconciliation_delta_usd is not None
        and abs(reconciliation_delta_usd) > tolerance_usd
    ):
        global_impacts.append(
            _ConfidenceImpact("provisional", "distribution_total_mismatch")
        )

    percentages_visible = _percentages_visible(
        current_value=current_value,
        current_value_usd=current_value_usd,
        reconciliation_delta_usd=reconciliation_delta_usd,
        tolerance_usd=tolerance_usd,
        global_impacts=global_impacts,
    )

    if current_value_usd is None or current_value_usd <= Decimal("0"):
        global_impacts.append(
            _ConfidenceImpact("provisional", "weak_distribution_denominator")
        )

    percentage_state: PercentageState = (
        "visible" if percentages_visible else "suppressed"
    )
    buckets = tuple(
        DistributionBucket(
            asset_type=bucket,
            value_usd=value_usd,
            percentage=(
                value_usd / current_value_usd * Decimal("100")
                if percentages_visible and current_value_usd is not None
                else None
            ),
            percentage_state=percentage_state,
            confidence_state=_max_confidence(
                impact.state for impact in bucket_impacts[bucket]
            ),
            reason_codes=_reason_codes(bucket_impacts[bucket]),
        )
        for bucket, value_usd in bucket_values.items()
        if value_usd != Decimal("0")
    )

    cash_reason_codes = _reason_codes(cash_impacts)
    cash_confidence = _max_confidence(impact.state for impact in cash_impacts)
    cash_reserve = CashReserveBreakdown(
        stablecoin_usd=stablecoin_usd,
        broker_cash_usd=broker_cash_usd,
        other_tracked_cash_usd=other_tracked_cash_usd,
        total_usd=stablecoin_usd + broker_cash_usd + other_tracked_cash_usd,
        confidence_state=cash_confidence,
        reason_codes=cash_reason_codes,
    )

    all_impacts = [
        *global_impacts,
        *(impact for impacts in bucket_impacts.values() for impact in impacts),
    ]
    return DistributionSummary(
        current_value_usd=current_value_usd,
        total_allocated_usd=total_allocated_usd,
        reconciliation_delta_usd=reconciliation_delta_usd,
        reconciliation_tolerance_usd=tolerance_usd,
        percentages_visible=percentages_visible,
        asset_type_buckets=buckets,
        cash_reserve=cash_reserve,
        confidence_state=_max_confidence(impact.state for impact in all_impacts),
        reason_codes=_reason_codes(all_impacts),
    )


def _distribution_asset_type(
    holding: DistributionHolding | Any,
    *,
    symbol: str,
) -> DistributionAssetType:
    asset_type = str(_attr(holding, "asset_type", "") or "").lower()
    if symbol in STABLECOIN_SYMBOLS:
        return "cash"
    if asset_type in CASH_TYPES and (
        symbol in CASH_SYMBOLS or _attr(holding, "cash_reserve_kind", None) is not None
    ):
        return "cash"
    if asset_type == "crypto":
        return "crypto"
    if asset_type in STOCK_ETF_TYPES:
        return "stocks_etfs"
    if asset_type in COMMODITY_TYPES:
        return "commodities"
    return "other"


def _cash_reserve_kind(
    holding: DistributionHolding | Any,
    *,
    symbol: str,
) -> CashReserveKind:
    explicit_kind = str(_attr(holding, "cash_reserve_kind", "") or "").lower()
    if explicit_kind in {"stablecoin", "stablecoins"}:
        return "stablecoin"
    if explicit_kind in {"broker_cash", "broker", "brokerage_cash"}:
        return "broker_cash"
    if explicit_kind in {"other_tracked_cash", "tracked_cash", "other_cash"}:
        return "other_tracked_cash"

    asset_type = str(_attr(holding, "asset_type", "") or "").lower()
    if symbol in STABLECOIN_SYMBOLS or asset_type == "stablecoin":
        return "stablecoin"
    institution = str(_attr(holding, "institution", "") or "").lower()
    if symbol in CASH_SYMBOLS and institution in {"xtb", "broker", "brokerage"}:
        return "broker_cash"
    return "other_tracked_cash"


def _current_value_impacts(
    current_value: DistributionCurrentValue | Any,
    current_value_usd: Decimal | None,
) -> list[_ConfidenceImpact]:
    impacts: list[_ConfidenceImpact] = []
    if current_value_usd is None:
        impacts.append(_ConfidenceImpact("blocked", "missing_current_value"))
    coverage_reasons = {
        "holdings_reconciled": "holdings_unresolved",
        "broker_cash_reconciled": "broker_cash_unresolved",
        "stablecoin_reserve_reconciled": "stablecoin_reserve_unresolved",
        "position_existence_reconciled": "position_existence_unresolved",
    }
    for attr_name, reason_code in coverage_reasons.items():
        if not bool(_attr(current_value, attr_name, False)):
            impacts.append(_ConfidenceImpact("blocked", reason_code))

    confidence_state = _confidence_state(
        _attr(current_value, "confidence_state", "trusted")
    )
    if confidence_state != "trusted":
        impacts.append(
            _ConfidenceImpact(
                confidence_state,
                f"current_value_confidence_{confidence_state}",
            )
        )
    for reason_code in _attr(current_value, "reason_codes", ()) or ():
        impacts.append(_ConfidenceImpact(confidence_state, str(reason_code)))
    return impacts


def _cash_reserve_impacts(
    current_value: DistributionCurrentValue | Any,
) -> list[_ConfidenceImpact]:
    impacts: list[_ConfidenceImpact] = []
    if not bool(_attr(current_value, "broker_cash_reconciled", False)):
        impacts.append(_ConfidenceImpact("blocked", "broker_cash_unresolved"))
    if not bool(_attr(current_value, "stablecoin_reserve_reconciled", False)):
        impacts.append(_ConfidenceImpact("blocked", "stablecoin_reserve_unresolved"))
    return impacts


def _percentages_visible(
    *,
    current_value: DistributionCurrentValue | Any,
    current_value_usd: Decimal | None,
    reconciliation_delta_usd: Decimal | None,
    tolerance_usd: Decimal,
    global_impacts: Sequence[_ConfidenceImpact],
) -> bool:
    if current_value_usd is None or current_value_usd <= Decimal("0"):
        return False
    if (
        _confidence_state(_attr(current_value, "confidence_state", "trusted"))
        != "trusted"
    ):
        return False
    if (
        reconciliation_delta_usd is not None
        and abs(reconciliation_delta_usd) > tolerance_usd
    ):
        return False
    return not any(
        impact.state in {"review_required", "blocked"} for impact in global_impacts
    )


def _reconciliation_tolerance(
    current_value_usd: Decimal | None,
    override: Decimal | None,
) -> Decimal:
    if override is not None:
        return Decimal(override)
    if current_value_usd is None:
        return Decimal("0.01")
    return max(Decimal("0.01"), abs(current_value_usd) * Decimal("0.0001"))


def _reason_codes(impacts: Sequence[_ConfidenceImpact]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(impact.reason_code for impact in impacts))


def _max_confidence(states: Iterable[str]) -> ConfidenceState:
    max_state: ConfidenceState = "trusted"
    for state in states:
        normalized = _confidence_state(state)
        if CONFIDENCE_ORDER[normalized] > CONFIDENCE_ORDER[max_state]:
            max_state = normalized
    return max_state


def _confidence_state(value: Any) -> ConfidenceState:
    state = str(value or "trusted")
    if state in CONFIDENCE_ORDER:
        return state  # type: ignore[return-value]
    return "provisional"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalized_symbol(value: Any) -> str:
    return str(value or "").upper()


def _first_or_none(values: Any) -> Any:
    for value in values or ():
        return value
    return None


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
