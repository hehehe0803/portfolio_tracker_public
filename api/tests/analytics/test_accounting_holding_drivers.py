# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.accounting_holding_drivers import (
    HoldingDriverInput,
    calculate_holding_drivers,
)

AS_OF = datetime(2026, 6, 19, tzinfo=UTC)


def _driver(period, symbol: str):
    return next(driver for driver in period.drivers if driver.symbol == symbol)


def test_default_rolling_periods_identify_positive_driver() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[
            HoldingDriverInput(
                symbol="BTC",
                period_days=7,
                starting_value_usd=Decimal("1000"),
                ending_value_usd=Decimal("1120"),
            ),
            HoldingDriverInput(
                symbol="ETH",
                period_days=7,
                starting_value_usd=Decimal("700"),
                ending_value_usd=Decimal("670"),
            ),
            HoldingDriverInput(
                symbol="BTC",
                period_days=30,
                starting_value_usd=Decimal("900"),
                ending_value_usd=Decimal("1200"),
            ),
            HoldingDriverInput(
                symbol="SOL",
                period_days=30,
                starting_value_usd=Decimal("400"),
                ending_value_usd=Decimal("450"),
            ),
            HoldingDriverInput(
                symbol="BTC",
                period_days=90,
                starting_value_usd=Decimal("700"),
                ending_value_usd=Decimal("900"),
            ),
        ],
    )

    assert [period.label for period in summary.periods] == ["7D", "30D", "90D"]
    assert summary.default_period_label == "30D"

    period = summary.default_period
    assert period is not None
    assert period.start_at == AS_OF - timedelta(days=30)
    assert period.end_at == AS_OF
    assert period.status == "ok"
    assert period.total_known_movement_usd == Decimal("350")
    assert period.total_absolute_known_movement_usd == Decimal("350")
    assert [driver.symbol for driver in period.drivers] == ["BTC", "SOL"]

    btc = _driver(period, "BTC")
    assert btc.direction == "positive"
    assert btc.movement_usd == Decimal("300")
    assert btc.share_of_known_movement_pct == (
        Decimal("300") / Decimal("350") * Decimal("100")
    )
    assert btc.value_state == "visible"
    assert btc.confidence_state == "trusted"


def test_negative_driver_is_reported_in_dollars_first() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[
            HoldingDriverInput(
                symbol="SOL",
                period_days=30,
                starting_value_usd=Decimal("600"),
                ending_value_usd=Decimal("420"),
            ),
            HoldingDriverInput(
                symbol="BTC",
                period_days=30,
                starting_value_usd=Decimal("1000"),
                ending_value_usd=Decimal("1060"),
            ),
        ],
        periods_days=(30,),
    )

    period = summary.periods[0]

    assert period.status == "ok"
    assert [driver.symbol for driver in period.drivers] == ["SOL", "BTC"]
    assert period.total_known_movement_usd == Decimal("-120")

    sol = _driver(period, "SOL")
    assert sol.direction == "negative"
    assert sol.movement_usd == Decimal("-180")
    assert sol.share_of_known_movement_pct == (
        Decimal("180") / Decimal("240") * Decimal("100")
    )
    assert sol.value_state == "visible"


def test_low_confidence_driver_is_flagged_without_precise_value() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[
            HoldingDriverInput(
                symbol="HYPE",
                period_days=30,
                starting_value_usd=Decimal("100"),
                ending_value_usd=Decimal("190"),
                confidence_state="review_required",
                reason_codes=("missing_cost_basis",),
            )
        ],
        periods_days=(30,),
    )

    period = summary.periods[0]
    driver = _driver(period, "HYPE")

    assert period.status == "insufficient_data"
    assert period.confidence_state == "review_required"
    assert "missing_cost_basis" in period.reason_codes
    assert driver.confidence_state == "review_required"
    assert driver.value_state == "hidden"
    assert driver.movement_usd is None
    assert driver.share_of_known_movement_pct is None
    assert driver.reason_codes == ("missing_cost_basis",)


def test_provisional_driver_keeps_values_flagged_and_period_insufficient() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[
            HoldingDriverInput(
                symbol="ETH",
                period_days=30,
                starting_value_usd=Decimal("700"),
                ending_value_usd=Decimal("790"),
                confidence_state="provisional",
                reason_codes=("estimated_boundary_value",),
            )
        ],
        periods_days=(30,),
    )

    period = summary.periods[0]
    driver = _driver(period, "ETH")

    assert period.status == "insufficient_data"
    assert period.confidence_state == "provisional"
    assert "estimated_boundary_value" in period.reason_codes
    assert driver.value_state == "flagged"
    assert driver.movement_usd == Decimal("90")
    assert driver.share_of_known_movement_pct == Decimal("100")
    assert driver.confidence_state == "provisional"


def test_top_n_limits_returned_drivers_without_changing_period_totals() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[
            HoldingDriverInput(
                symbol="BTC",
                period_days=30,
                starting_value_usd=Decimal("1000"),
                ending_value_usd=Decimal("1200"),
            ),
            HoldingDriverInput(
                symbol="ETH",
                period_days=30,
                starting_value_usd=Decimal("500"),
                ending_value_usd=Decimal("400"),
            ),
            HoldingDriverInput(
                symbol="SOL",
                period_days=30,
                starting_value_usd=Decimal("300"),
                ending_value_usd=Decimal("350"),
            ),
        ],
        periods_days=(30,),
        max_drivers_per_period=1,
    )

    period = summary.periods[0]

    assert [driver.symbol for driver in period.drivers] == ["BTC"]
    assert period.total_known_movement_usd == Decimal("150")
    assert period.total_absolute_known_movement_usd == Decimal("350")
    assert period.drivers[0].share_of_known_movement_pct == (
        Decimal("200") / Decimal("350") * Decimal("100")
    )


def test_top_n_keeps_visible_driver_ahead_of_hidden_low_confidence_driver() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[
            HoldingDriverInput(
                symbol="HYPE",
                period_days=30,
                starting_value_usd=Decimal("100"),
                ending_value_usd=Decimal("1100"),
                confidence_state="review_required",
                reason_codes=("unmatched_transfer",),
            ),
            HoldingDriverInput(
                symbol="BTC",
                period_days=30,
                starting_value_usd=Decimal("1000"),
                ending_value_usd=Decimal("1080"),
            ),
        ],
        periods_days=(30,),
        max_drivers_per_period=1,
    )

    period = summary.periods[0]

    assert period.status == "insufficient_data"
    assert period.confidence_state == "review_required"
    assert "unmatched_transfer" in period.reason_codes
    assert [driver.symbol for driver in period.drivers] == ["BTC"]
    assert period.drivers[0].movement_usd == Decimal("80")
    assert period.drivers[0].value_state == "visible"


def test_no_data_state_is_explicit_for_empty_period() -> None:
    summary = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=[],
        periods_days=(30,),
    )

    period = summary.periods[0]

    assert period.label == "30D"
    assert period.status == "no_data"
    assert period.confidence_state == "provisional"
    assert period.reason_codes == ("no_holding_driver_data",)
    assert period.drivers == ()
    assert period.total_known_movement_usd is None
