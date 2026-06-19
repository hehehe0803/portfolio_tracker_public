from decimal import Decimal
from pathlib import Path

import pytest
from app.services.xtb_ingest import summarize_xtb_transactions
from app.services.xtb_parser import XTBExcelParser

from api.tests.xtb.private_fixtures import XLSX_FIXTURE_PATH

FIXTURE = Path(XLSX_FIXTURE_PATH)


@pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="private XTB workbook fixture is local-only under data/",
)
def test_xtb_reconciliation_totals():
    parser = XTBExcelParser(str(FIXTURE))
    transactions = parser.parse_and_normalize()

    summary = summarize_xtb_transactions(transactions)

    assert summary["count"] == len(transactions)
    assert summary["gross_amount"] == Decimal("23691.66")
    assert summary["by_type"]["buy"] == Decimal("-15794.52")
    assert summary["by_type"]["deposit"] == Decimal("7897.0")
    assert summary["by_type"]["fee"] == Decimal("-0.14")
