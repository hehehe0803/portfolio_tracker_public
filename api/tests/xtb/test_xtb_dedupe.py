from pathlib import Path

import pytest
from app.services.xtb_ingest import dedupe_xtb_transactions
from app.services.xtb_parser import XTBExcelParser

from api.tests.xtb.private_fixtures import XLSX_FIXTURE_PATH

FIXTURE = Path(XLSX_FIXTURE_PATH)


@pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="private XTB workbook fixture is local-only under data/",
)
def test_xtb_deduplication_is_idempotent():
    parser = XTBExcelParser(str(FIXTURE))
    transactions = parser.parse_and_normalize()

    first_pass = dedupe_xtb_transactions(transactions, existing_fingerprints=set())
    second_pass = dedupe_xtb_transactions(
        transactions,
        existing_fingerprints={tx.get_fingerprint() for tx in first_pass},
    )

    assert len(first_pass) == len(transactions)
    assert second_pass == []
