from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from app.services.xtb_parser import (
    PositionType,
    TransactionType,
    XTBDailyStatementPdfParser,
    XTBFormatError,
    parse_xtb_statement,
)

from api.tests.xtb.private_fixtures import ENCRYPTED_PDF_FIXTURE_PATH

PDF_TEXT_FIXTURE_PATH = Path("api/tests/fixtures/xtb/xtb_daily_statement_layout.txt")


def test_daily_statement_layout_text_parses_core_trade_fields():
    parser = XTBDailyStatementPdfParser.from_layout_text(
        PDF_TEXT_FIXTURE_PATH.read_text(encoding="utf-8")
    )

    parsed = parser.parse()

    assert len(parsed["daily_trades"]) == 6
    first = parsed["daily_trades"][0]
    assert first.order_id == 2565559355
    assert first.symbol == "ISLN.UK"
    assert first.instrument_name == "iShares, ACC, USD"
    assert first.quantity == Decimal("2.0000")
    assert first.trade_time == datetime(2026, 5, 12, 9, 3, 54)
    assert first.execution_price == Decimal("79.57250")
    assert first.total_value == Decimal("159.14500")
    assert first.currency == "USD"
    assert first.fx_rate == Decimal("1.0000")
    assert first.conversion_fee == Decimal("0.00")
    assert first.commission == Decimal("0.00")
    assert first.total_cost == Decimal("0.00")

    fractional = parsed["daily_trades"][-1]
    assert fractional.order_id == 2565576692
    assert fractional.symbol == "LAC.US"
    assert fractional.quantity == Decimal("0.2711")
    assert fractional.instrument_name == "Lithium Americas Corp"


def test_daily_statement_layout_text_normalizes_to_open_position_transactions():
    parser = XTBDailyStatementPdfParser.from_layout_text(
        PDF_TEXT_FIXTURE_PATH.read_text(encoding="utf-8")
    )

    transactions = parser.parse_and_normalize()

    assert len(transactions) == 6
    assert {tx.tx_type for tx in transactions} == {TransactionType.OPEN_POSITION}
    assert transactions[0].id == "2565559355"
    assert transactions[0].date == datetime(2026, 5, 12, 9, 3, 54)
    assert transactions[0].amount == Decimal("-159.14500")
    assert transactions[0].currency == "USD"
    assert transactions[0].symbol == "ISLN.UK"
    assert "price=79.57250" in transactions[0].description
    assert "commission=0.00" in transactions[0].description


def test_daily_statement_layout_text_detects_accented_sell_section():
    layout_text = PDF_TEXT_FIXTURE_PATH.read_text(encoding="utf-8").replace(
        "Lenh mua OMI da thuc hien (3)",
        "Lệnh bán OMI đã thực hiện (3)",
        1,
    )
    parser = XTBDailyStatementPdfParser.from_layout_text(layout_text)

    parsed = parser.parse()
    transactions = parser.parse_and_normalize()

    assert parsed["daily_trades"][0].position_type == PositionType.SELL
    assert transactions[0].tx_type == TransactionType.CLOSE_POSITION
    assert transactions[0].amount == Decimal("159.14500")


def test_encrypted_pdf_without_password_raises_clear_error():
    if not ENCRYPTED_PDF_FIXTURE_PATH.exists():
        pytest.skip("private XTB encrypted PDF fixture is local-only under data/")
    with pytest.raises(XTBFormatError, match="password"):
        parse_xtb_statement(ENCRYPTED_PDF_FIXTURE_PATH)
