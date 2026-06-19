from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from app.services.accounting_history import ConfidenceState

DriverDirection = Literal["positive", "negative", "flat", "unknown"]
DriverValueState = Literal["visible", "flagged", "hidden"]
HoldingDriverPeriodStatus = Literal["ok", "no_data", "insufficient_data"]

_CONFIDENCE_RANK: dict[str, int] = {
    "trusted": 0,
    "warning": 1,
    "provisional": 2,
    "review_required": 3,
    "blocked": 4,
}
_DEFAULT_PERIOD_DAYS = (7, 30, 90)
_VISIBLE_CONFIDENCE_STATES = {"trusted", "warning"}
_FLAGGED_CONFIDENCE_STATES = {"provisional"}


@dataclass(frozen=True)
class HoldingDriverInput:
    symbol: str
    period_days: int
    starting_value_usd: Decimal | None
    ending_value_usd: Decimal | None
    deposits_usd: Decimal = Decimal("0")
    withdrawals_usd: Decimal = Decimal("0")
    confidence_state: ConfidenceState = "trusted"
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class HoldingDriver:
    symbol: str
    movement_usd: Decimal | None
    share_of_known_movement_pct: Decimal | None
    direction: DriverDirection
    starting_value_usd: Decimal | None
    ending_value_usd: Decimal | None
    deposits_usd: Decimal
    withdrawals_usd: Decimal
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...]
    value_state: DriverValueState


@dataclass(frozen=True)
class HoldingDriverPeriod:
    label: str
    days: int
    start_at: datetime
    end_at: datetime
    status: HoldingDriverPeriodStatus
    total_known_movement_usd: Decimal | None
    total_absolute_known_movement_usd: Decimal | None
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...]
    drivers: tuple[HoldingDriver, ...]


@dataclass(frozen=True)
class HoldingDriverSummary:
    as_of: datetime
    default_period_label: str
    periods: tuple[HoldingDriverPeriod, ...]

    @property
    def default_period(self) -> HoldingDriverPeriod | None:
        for period in self.periods:
            if period.label == self.default_period_label:
                return period
        return None


@dataclass(frozen=True)
class _RawDriver:
    symbol: str
    raw_movement_usd: Decimal | None
    direction: DriverDirection
    starting_value_usd: Decimal | None
    ending_value_usd: Decimal | None
    deposits_usd: Decimal
    withdrawals_usd: Decimal
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...]
    value_state: DriverValueState


def calculate_holding_drivers(
    *,
    as_of: datetime,
    holdings: Sequence[HoldingDriverInput | Any],
    periods_days: Sequence[int] = _DEFAULT_PERIOD_DAYS,
    default_period_days: int = 30,
    max_drivers_per_period: int | None = None,
) -> HoldingDriverSummary:
    periods = tuple(
        _calculate_period(
            as_of=as_of,
            days=days,
            holdings=holdings,
            max_drivers_per_period=max_drivers_per_period,
        )
        for days in periods_days
    )
    return HoldingDriverSummary(
        as_of=as_of,
        default_period_label=_period_label(default_period_days),
        periods=periods,
    )


def _calculate_period(
    *,
    as_of: datetime,
    days: int,
    holdings: Sequence[HoldingDriverInput | Any],
    max_drivers_per_period: int | None,
) -> HoldingDriverPeriod:
    start_at = as_of - timedelta(days=days)
    period_holdings = tuple(
        holding
        for holding in holdings
        if _period_days(_attr(holding, "period_days", None)) == days
    )
    if not period_holdings:
        return HoldingDriverPeriod(
            label=_period_label(days),
            days=days,
            start_at=start_at,
            end_at=as_of,
            status="no_data",
            total_known_movement_usd=None,
            total_absolute_known_movement_usd=None,
            confidence_state="provisional",
            reason_codes=("no_holding_driver_data",),
            drivers=(),
        )

    raw_drivers = tuple(_raw_driver(holding) for holding in period_holdings)
    ordered_raw_drivers = tuple(
        sorted(
            raw_drivers,
            key=lambda driver: (
                -_driver_sort_magnitude(driver),
                driver.symbol,
            ),
        )
    )

    visible_movements = tuple(
        driver.raw_movement_usd
        for driver in ordered_raw_drivers
        if driver.raw_movement_usd is not None and driver.value_state != "hidden"
    )
    total_known_movement_usd = (
        sum(visible_movements, Decimal("0")) if visible_movements else None
    )
    total_absolute_known_movement_usd = (
        sum((abs(value) for value in visible_movements), Decimal("0"))
        if visible_movements
        else None
    )
    all_public_drivers = tuple(
        _public_driver(
            driver,
            total_absolute_known_movement_usd=total_absolute_known_movement_usd,
        )
        for driver in ordered_raw_drivers
    )
    display_drivers = tuple(
        sorted(
            all_public_drivers,
            key=lambda driver: (
                _display_value_state_rank(driver.value_state),
                -_public_driver_sort_magnitude(driver),
                driver.symbol,
            ),
        )
    )
    public_drivers = (
        display_drivers[:max_drivers_per_period]
        if max_drivers_per_period is not None
        else display_drivers
    )

    confidence_state = _max_confidence(
        driver.confidence_state for driver in ordered_raw_drivers
    )
    reason_codes = _period_reason_codes(
        drivers=all_public_drivers,
        confidence_state=confidence_state,
        has_visible_movement=bool(visible_movements),
    )

    return HoldingDriverPeriod(
        label=_period_label(days),
        days=days,
        start_at=start_at,
        end_at=as_of,
        status=_period_status(
            confidence_state=confidence_state,
            has_visible_movement=bool(visible_movements),
        ),
        total_known_movement_usd=total_known_movement_usd,
        total_absolute_known_movement_usd=total_absolute_known_movement_usd,
        confidence_state=confidence_state,
        reason_codes=reason_codes,
        drivers=public_drivers,
    )


def _raw_driver(holding: HoldingDriverInput | Any) -> _RawDriver:
    starting_value = _decimal_or_none(_attr(holding, "starting_value_usd", None))
    ending_value = _decimal_or_none(_attr(holding, "ending_value_usd", None))
    deposits = _decimal_or_zero(_attr(holding, "deposits_usd", Decimal("0")))
    withdrawals = _decimal_or_zero(_attr(holding, "withdrawals_usd", Decimal("0")))
    input_confidence = _confidence_state(_attr(holding, "confidence_state", "trusted"))
    reason_codes = list(
        str(code) for code in (_attr(holding, "reason_codes", ()) or ())
    )
    confidence_states: list[ConfidenceState] = [input_confidence]

    if starting_value is None:
        confidence_states.append("blocked")
        reason_codes.append("missing_holding_start_value")
    if ending_value is None:
        confidence_states.append("blocked")
        reason_codes.append("missing_holding_end_value")
    if input_confidence != "trusted" and not reason_codes:
        reason_codes.append(f"holding_driver_confidence_{input_confidence}")

    confidence_state = _max_confidence(confidence_states)
    raw_movement = (
        ending_value - starting_value - deposits + withdrawals
        if starting_value is not None and ending_value is not None
        else None
    )
    value_state = _driver_value_state(confidence_state, raw_movement)

    return _RawDriver(
        symbol=_normalized_symbol(_attr(holding, "symbol", "")),
        raw_movement_usd=raw_movement,
        direction=_direction(raw_movement),
        starting_value_usd=starting_value,
        ending_value_usd=ending_value,
        deposits_usd=deposits,
        withdrawals_usd=withdrawals,
        confidence_state=confidence_state,
        reason_codes=_dedupe_reason_codes(reason_codes),
        value_state=value_state,
    )


def _public_driver(
    driver: _RawDriver,
    *,
    total_absolute_known_movement_usd: Decimal | None,
) -> HoldingDriver:
    movement = driver.raw_movement_usd if driver.value_state != "hidden" else None
    share_pct = None
    if (
        movement is not None
        and total_absolute_known_movement_usd is not None
        and total_absolute_known_movement_usd > Decimal("0")
    ):
        share_pct = abs(movement) / total_absolute_known_movement_usd * Decimal("100")

    return HoldingDriver(
        symbol=driver.symbol,
        movement_usd=movement,
        share_of_known_movement_pct=share_pct,
        direction=driver.direction,
        starting_value_usd=driver.starting_value_usd,
        ending_value_usd=driver.ending_value_usd,
        deposits_usd=driver.deposits_usd,
        withdrawals_usd=driver.withdrawals_usd,
        confidence_state=driver.confidence_state,
        reason_codes=driver.reason_codes,
        value_state=driver.value_state,
    )


def _period_status(
    *,
    confidence_state: ConfidenceState,
    has_visible_movement: bool,
) -> HoldingDriverPeriodStatus:
    if not has_visible_movement:
        return "insufficient_data"
    if confidence_state not in _VISIBLE_CONFIDENCE_STATES:
        return "insufficient_data"
    return "ok"


def _period_reason_codes(
    *,
    drivers: Sequence[HoldingDriver],
    confidence_state: ConfidenceState,
    has_visible_movement: bool,
) -> tuple[str, ...]:
    reason_codes = [
        reason_code for driver in drivers for reason_code in driver.reason_codes
    ]
    if not has_visible_movement:
        reason_codes.append("holding_driver_values_unavailable")
    if confidence_state not in _VISIBLE_CONFIDENCE_STATES and not reason_codes:
        reason_codes.append("low_confidence_holding_drivers")
    return _dedupe_reason_codes(reason_codes)


def _driver_value_state(
    confidence_state: ConfidenceState,
    raw_movement: Decimal | None,
) -> DriverValueState:
    if raw_movement is None:
        return "hidden"
    if confidence_state in _VISIBLE_CONFIDENCE_STATES:
        return "visible"
    if confidence_state in _FLAGGED_CONFIDENCE_STATES:
        return "flagged"
    return "hidden"


def _driver_sort_magnitude(driver: _RawDriver) -> Decimal:
    if driver.raw_movement_usd is None:
        return Decimal("-1")
    return abs(driver.raw_movement_usd)


def _public_driver_sort_magnitude(driver: HoldingDriver) -> Decimal:
    if driver.movement_usd is None:
        return Decimal("-1")
    return abs(driver.movement_usd)


def _display_value_state_rank(value_state: DriverValueState) -> int:
    if value_state == "visible":
        return 0
    if value_state == "flagged":
        return 1
    return 2


def _direction(value: Decimal | None) -> DriverDirection:
    if value is None:
        return "unknown"
    if value > Decimal("0"):
        return "positive"
    if value < Decimal("0"):
        return "negative"
    return "flat"


def _period_days(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _period_label(days: int) -> str:
    return f"{days}D"


def _max_confidence(states: Iterable[ConfidenceState]) -> ConfidenceState:
    max_state: ConfidenceState = "trusted"
    for state in states:
        if _CONFIDENCE_RANK[state] > _CONFIDENCE_RANK[max_state]:
            max_state = state
    return max_state


def _confidence_state(value: Any) -> ConfidenceState:
    state = str(value or "trusted")
    if state in _CONFIDENCE_RANK:
        return cast(ConfidenceState, state)
    return "blocked"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _decimal_or_zero(value: Any) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None:
        return Decimal("0")
    return parsed


def _dedupe_reason_codes(reason_codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason_codes))


def _normalized_symbol(value: Any) -> str:
    return str(value or "").upper()


def _attr(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)
