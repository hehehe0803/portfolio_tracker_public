from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.xtb_cash_ledger import calculate_xtb_cash_ledger


def _tx(
    tx_type: str,
    symbol: str,
    quantity: str,
    *,
    price: str | None = None,
    total: str | None = None,
    fee: str = "0",
    fee_currency: str = "USD",
    description: str = "",
    timestamp: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        institution="xtb",
        tx_type=tx_type,
        asset_symbol=symbol,
        quantity=Decimal(str(quantity)),
        price_usd=Decimal(str(price)) if price is not None else None,
        total_usd=Decimal(str(total)) if total is not None else None,
        fee=Decimal(str(fee)),
        fee_currency=fee_currency,
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=UTC),
        description=description,
        raw_data={},
    )


def test_xtb_stock_buy_consumes_usd_cash():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "1000", total="1000"),
            _tx("buy", "AAPL.US", "2", price="100", total="200"),
        ],
        broker_cash_balance_usd=Decimal("800"),
    )

    assert ledger.cash_balance_usd == Decimal("800")
    assert ledger.trusted is True
    assert ledger.issues == ()


def test_xtb_stock_sell_increases_usd_cash_by_proceeds_minus_fees():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "100", total="100"),
            _tx(
                "sell",
                "AAPL.US",
                "3",
                price="50",
                total="150",
                fee="1.25",
                description="Stock sell 3 AAPL.US @ 50",
            ),
        ],
        broker_cash_balance_usd=Decimal("248.75"),
    )

    assert ledger.cash_balance_usd == Decimal("248.75")
    assert ledger.trusted is True
    assert ledger.issues == ()


def test_xtb_dividend_increases_usd_cash():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "100", total="100"),
            _tx("dividend", "USD", "12.34", total="12.34"),
        ],
        broker_cash_balance_usd=Decimal("112.34"),
    )

    assert ledger.cash_balance_usd == Decimal("112.34")
    assert ledger.trusted is True
    assert ledger.issues == ()


@pytest.mark.parametrize("tx_type", ["fee", "commission", "stamp_duty", "swap"])
def test_xtb_cash_charges_decrease_usd_cash(tx_type: str):
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "100", total="100"),
            _tx(tx_type, "USD", "3.50", total="3.50"),
        ],
        broker_cash_balance_usd=Decimal("96.50"),
    )

    assert ledger.cash_balance_usd == Decimal("96.50")
    assert ledger.trusted is True
    assert ledger.issues == ()


def test_xtb_withdrawal_decreases_usd_cash():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "500", total="500"),
            _tx("withdrawal", "USD", "125", total="125"),
        ],
        broker_cash_balance_usd=Decimal("375"),
    )

    assert ledger.cash_balance_usd == Decimal("375")
    assert ledger.trusted is True
    assert ledger.issues == ()


def test_xtb_missing_reliable_usd_amount_creates_issue_and_untrusted_ledger():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "1000", total="1000"),
            _tx("buy", "AAPL.US", "2"),
        ]
    )

    assert ledger.cash_balance_usd == Decimal("1000")
    assert ledger.trusted is False
    assert len(ledger.issues) == 1
    assert ledger.issues[0].code == "missing_usd_amount"
    assert ledger.issues[0].asset_symbol == "AAPL.US"


def test_xtb_cash_ledger_without_broker_cash_control_total_is_untrusted():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "1000", total="1000"),
            _tx("buy", "AAPL.US", "2", price="100", total="200"),
        ]
    )

    assert ledger.cash_balance_usd == Decimal("800")
    assert ledger.trusted is False
    assert ledger.issues[0].code == "missing_cash_control_total"


def test_xtb_cash_ledger_cash_control_total_mismatch_is_untrusted():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "1000", total="1000"),
            _tx("buy", "AAPL.US", "2", price="100", total="200"),
        ],
        broker_cash_balance_usd=Decimal("801"),
    )

    assert ledger.cash_balance_usd == Decimal("800")
    assert ledger.trusted is False
    assert ledger.issues[0].code == "cash_control_total_mismatch"


def test_xtb_closed_position_profit_loss_row_does_not_become_sell_proceeds():
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "100", total="100"),
            _tx("buy", "AAPL.US", "1", total="100"),
            _tx(
                "close_position",
                "AAPL.US",
                "1",
                total="10",
                description="CLOSE BUY 1 AAPL.US",
            ),
        ],
        broker_cash_balance_usd=Decimal("110"),
    )

    assert ledger.cash_balance_usd == Decimal("0")
    assert ledger.trusted is False
    assert ledger.issues[0].code == "sell_proceeds_not_reliable"


@pytest.mark.parametrize("tx_type", ["split", "correction"])
def test_xtb_non_cash_events_do_not_block_cash_ledger_trust(tx_type: str):
    ledger = calculate_xtb_cash_ledger(
        [
            _tx("deposit", "USD", "1000", total="1000"),
            _tx(tx_type, "XLU.US", "2", description="XLU.US split 2 for 1"),
        ],
        broker_cash_balance_usd=Decimal("1000"),
    )

    assert ledger.cash_balance_usd == Decimal("1000")
    assert ledger.trusted is True
    assert ledger.issues == ()
