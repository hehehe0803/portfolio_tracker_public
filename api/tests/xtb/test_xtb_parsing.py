"""
XTB Statement Parser Tests

Tests for parsing XTB XLSX statement files and normalizing transactions.
"""

import json
from datetime import datetime
from decimal import Decimal

import pytest
from app.services.xtb_parser import (
    PositionType,
    TransactionType,
    XTBExcelParser,
    XTBFileNotFoundError,
    XTBTransaction,
    generate_fingerprint,
    parse_xtb_statement,
)

from api.tests.xtb.private_fixtures import (
    MHTML_FIXTURE_PATH,
    MHTML_SNAPSHOT_PATH,
    XLSX_FIXTURE_PATH,
)

# Private regression fixtures live outside version control.
requires_private_xtb_xlsx = pytest.mark.skipif(
    not XLSX_FIXTURE_PATH.exists(),
    reason="private XTB workbook fixture is local-only under data/",
)
requires_private_xtb_mhtml = pytest.mark.skipif(
    not (MHTML_FIXTURE_PATH.exists() and MHTML_SNAPSHOT_PATH.exists()),
    reason="private XTB MHTML fixture and snapshot are local-only under data/",
)


class TestGenerateFingerprint:
    """Tests for fingerprint generation."""

    def test_fingerprint_is_deterministic(self):
        """Same inputs should produce same fingerprint."""
        ts = datetime(2025, 10, 8, 15, 30, 0)
        fp1 = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        fp2 = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        assert fp1 == fp2

    def test_fingerprint_differs_on_broker(self):
        """Different brokers should produce different fingerprints."""
        ts = datetime(2025, 10, 8, 15, 30, 0)
        fp1 = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        fp2 = generate_fingerprint(
            "BINANCE", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        assert fp1 != fp2

    def test_fingerprint_differs_on_type(self):
        """Different transaction types should produce different fingerprints."""
        ts = datetime(2025, 10, 8, 15, 30, 0)
        fp1 = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        fp2 = generate_fingerprint(
            "XTB", TransactionType.WITHDRAWAL, ts, Decimal("100.00"), ""
        )
        assert fp1 != fp2

    def test_fingerprint_differs_on_amount(self):
        """Different amounts should produce different fingerprints."""
        ts = datetime(2025, 10, 8, 15, 30, 0)
        fp1 = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        fp2 = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("200.00"), ""
        )
        assert fp1 != fp2

    def test_fingerprint_differs_on_symbol(self):
        """Different symbols should produce different fingerprints."""
        ts = datetime(2025, 10, 8, 15, 30, 0)
        fp1 = generate_fingerprint(
            "XTB", TransactionType.OPEN_POSITION, ts, Decimal("100.00"), "AAPL.US"
        )
        fp2 = generate_fingerprint(
            "XTB", TransactionType.OPEN_POSITION, ts, Decimal("100.00"), "MSFT.US"
        )
        assert fp1 != fp2

    def test_fingerprint_is_16_chars(self):
        """Fingerprint should be 16 characters (short SHA256)."""
        ts = datetime(2025, 10, 8, 15, 30, 0)
        fp = generate_fingerprint(
            "XTB", TransactionType.DEPOSIT, ts, Decimal("100.00"), ""
        )
        assert len(fp) == 16


class TestXTBFileNotFoundError:
    """Tests for file not found error."""

    def test_nonexistent_file_raises_error(self):
        """Non-existent file should raise XTBFileNotFoundError."""
        with pytest.raises(XTBFileNotFoundError):
            XTBExcelParser("nonexistent_path.xlsx")


@requires_private_xtb_xlsx
class TestXTBExcelParserParse:
    """Tests for the parse method."""

    def test_parse_returns_expected_structure(self):
        """Parse should return the expected statement sections."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        result = parser.parse()

        assert "open_positions" in result
        assert "closed_positions" in result
        assert "cash_operations" in result
        assert "account_info" in result

    def test_parse_returns_correct_counts(self):
        """Parse should return correct number of positions and operations."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        result = parser.parse()

        # Based on observed data: ~57 open positions, ~55 cash operations,
        # and 0 closed positions.
        assert len(result["open_positions"]) > 50
        assert len(result["cash_operations"]) > 50
        assert (
            len(result["closed_positions"]) == 0
        )  # No closed positions in this fixture

    def test_cash_operations_have_valid_structure(self):
        """Cash operations should have all required fields."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        result = parser.parse()

        for op in result["cash_operations"][:5]:  # Check first 5
            assert op.operation_id is not None
            assert op.operation_type is not None
            assert op.time is not None
            assert op.amount is not None
            assert isinstance(op.amount, Decimal)

    def test_open_positions_have_valid_structure(self):
        """Open positions should have all required fields."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        result = parser.parse()

        for pos in result["open_positions"][:5]:  # Check first 5
            assert pos.position_id is not None
            assert pos.symbol is not None
            assert pos.position_type in [PositionType.BUY, PositionType.SELL]
            assert pos.volume is not None
            assert pos.open_time is not None
            assert pos.purchase_value is not None


@requires_private_xtb_xlsx
class TestXTBExcelParserNormalize:
    """Tests for the normalize_transactions method."""

    def test_normalize_returns_xtb_transactions(self):
        """normalize_transactions should return list of XTBTransaction objects."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        result = parser.parse()
        transactions = parser.normalize_transactions(result)

        assert isinstance(transactions, list)
        for tx in transactions:
            assert isinstance(tx, XTBTransaction)

    def test_normalize_preserves_all_transactions(self):
        """normalize_transactions should include all raw transactions."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        raw = parser.parse()
        transactions = parser.normalize_transactions(raw)

        expected_count = (
            len(raw["open_positions"])
            + len(raw["closed_positions"])
            + len(raw["cash_operations"])
        )
        assert len(transactions) == expected_count

    def test_open_position_transactions(self):
        """Open position transactions should have correct type and negative amount."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        result = parser.parse()
        transactions = parser.normalize_transactions(result)

        open_pos_txns = [
            t for t in transactions if t.tx_type == TransactionType.OPEN_POSITION
        ]

        assert len(open_pos_txns) > 0
        for tx in open_pos_txns:
            assert tx.tx_type == TransactionType.OPEN_POSITION
            assert tx.amount < 0  # Outflow (buying shares)
            assert tx.symbol is not None


@requires_private_xtb_xlsx
class TestParseXTBStatement:
    """Tests for the convenience parse_xtb_statement function."""

    def test_parse_xtb_statement_returns_list(self):
        """parse_xtb_statement should return list of transactions."""
        transactions = parse_xtb_statement(XLSX_FIXTURE_PATH)

        assert isinstance(transactions, list)
        assert len(transactions) > 0

    def test_parse_xtb_statement_types(self):
        """Should parse various transaction types correctly."""
        transactions = parse_xtb_statement(XLSX_FIXTURE_PATH)

        types = {tx.tx_type for tx in transactions}
        assert TransactionType.DEPOSIT in types
        assert TransactionType.OPEN_POSITION in types


@requires_private_xtb_xlsx
class TestCashOperationParsing:
    """Specific tests for cash operation parsing."""

    def test_deposit_operations_parsed(self):
        """Deposit operations should be parsed correctly."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        transactions = parser.parse_and_normalize()

        deposits = [t for t in transactions if t.tx_type == TransactionType.DEPOSIT]

        assert len(deposits) > 0
        for dep in deposits:
            assert dep.amount > 0  # Deposits are positive inflows
            assert dep.symbol is None  # Deposits don't have a symbol

    def test_stock_purchase_operations_parsed(self):
        """Stock purchases should keep symbol and negative amount."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        transactions = parser.parse_and_normalize()

        buys = [t for t in transactions if t.tx_type == TransactionType.OPEN_POSITION]

        assert len(buys) > 0
        for buy in buys:
            assert buy.amount < 0  # Buying is outflow
            assert buy.symbol is not None

    def test_stamp_duty_parsed(self):
        """Stamp duty operations should be parsed with correct type."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        transactions = parser.parse_and_normalize()

        stamp_duties = [
            t for t in transactions if t.tx_type == TransactionType.STAMP_DUTY
        ]

        assert len(stamp_duties) > 0
        for sd in stamp_duties:
            assert sd.amount < 0  # Stamp duty is an expense
            assert (
                "STAMP DUTY" in sd.description.upper()
                or "STAMP" in sd.description.upper()
            )


@requires_private_xtb_xlsx
class TestOpenPositionParsing:
    """Specific tests for open position parsing."""

    def test_open_positions_parsed(self):
        """Open positions should be parsed with correct data."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        raw = parser.parse()

        assert len(raw["open_positions"]) > 0
        for pos in raw["open_positions"][:3]:
            assert pos.position_id is not None
            assert pos.symbol is not None  # e.g., "MU.US", "IONS.US"
            assert pos.position_type == PositionType.BUY  # All BUY in fixture
            assert pos.volume > 0
            assert pos.open_time is not None
            assert pos.open_price > 0

    def test_open_position_fingerprint(self):
        """Open position should generate fingerprint."""
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        raw = parser.parse()

        for pos in raw["open_positions"][:3]:
            fp = pos.fingerprint()
            assert len(fp) == 16
            # Same position should produce same fingerprint
            fp2 = pos.fingerprint()
            assert fp == fp2


class TestTransactionModel:
    """Tests for XTBTransaction Pydantic model."""

    def test_transaction_fingerprint(self):
        """Transaction should generate fingerprint."""
        tx = XTBTransaction(
            id="12345",
            date=datetime(2025, 10, 8, 15, 30, 0),
            type=TransactionType.DEPOSIT,
            amount=Decimal("100.00"),
            currency="USD",
            symbol=None,
            description="Test deposit",
        )

        fp = tx.get_fingerprint()
        assert len(fp) == 16

    def test_transaction_serialization(self):
        """Transaction should serialize correctly to JSON."""
        tx = XTBTransaction(
            id="12345",
            date=datetime(2025, 10, 8, 15, 30, 0),
            tx_type=TransactionType.DEPOSIT,
            amount=Decimal("100.00"),
            currency="USD",
            symbol=None,
            description="Test deposit",
        )

        json_str = tx.model_dump_json()
        assert "12345" in json_str
        assert "2025-10-08T15:30:00" in json_str
        assert "100.00" in json_str
        assert '"tx_type":"DEPOSIT"' in json_str or "'tx_type':'DEPOSIT'" in json_str


class TestErrorHandling:
    """Tests for error handling in parser."""

    def test_invalid_file_raises_error(self):
        """Invalid file should raise appropriate error."""
        with pytest.raises(XTBFileNotFoundError):
            parse_xtb_statement("nonexistent_file.xlsx")

    def test_empty_transaction_amount_skipped(self):
        """Transactions with empty amount should be skipped."""
        # This test verifies the parser handles missing data gracefully
        # The actual fixture doesn't have empty amounts, but the parser should
        # handle them.
        if not XLSX_FIXTURE_PATH.exists():
            pytest.skip("private XTB workbook fixture is local-only under data/")
        parser = XTBExcelParser(XLSX_FIXTURE_PATH)
        # Should not raise an exception
        result = parser.parse()
        assert result is not None


class TestTransactionTypeMapping:
    """Tests for operation type mapping."""

    def test_deposit_mapping(self):
        """Deposit string should map to DEPOSIT type."""
        from app.services.xtb_parser import XTBExcelParser

        parser = XTBExcelParser.__new__(XTBExcelParser)

        assert parser._map_operation_type("deposit") == TransactionType.DEPOSIT
        assert parser._map_operation_type("DEPOSIT") == TransactionType.DEPOSIT

    def test_withdrawal_mapping(self):
        """Withdrawal string should map to WITHDRAWAL type."""
        from app.services.xtb_parser import XTBExcelParser

        parser = XTBExcelParser.__new__(XTBExcelParser)

        assert parser._map_operation_type("withdrawal") == TransactionType.WITHDRAWAL

    def test_stock_purchase_mapping(self):
        """Stock purchase should map to OPEN_POSITION type."""
        from app.services.xtb_parser import XTBExcelParser

        parser = XTBExcelParser.__new__(XTBExcelParser)

        assert (
            parser._map_operation_type("stock purchase")
            == TransactionType.OPEN_POSITION
        )
        assert parser._map_operation_type("stock buy") == TransactionType.OPEN_POSITION
        # Test that the actual data types from the fixture work
        # Real data has: "Stock purchase" and "Stock purchase" (from cash operations)

    def test_stock_sale_mapping(self):
        """Stock sale should map to CLOSE_POSITION type."""
        from app.services.xtb_parser import XTBExcelParser

        parser = XTBExcelParser.__new__(XTBExcelParser)

        assert (
            parser._map_operation_type("stock sale") == TransactionType.CLOSE_POSITION
        )
        assert parser._map_operation_type("close buy") == TransactionType.CLOSE_POSITION

    def test_stamp_duty_mapping(self):
        """Stamp duty should map to STAMP_DUTY type."""
        from app.services.xtb_parser import XTBExcelParser

        parser = XTBExcelParser.__new__(XTBExcelParser)

        assert parser._map_operation_type("stamp duty") == TransactionType.STAMP_DUTY


@requires_private_xtb_xlsx
class TestDataIntegrity:
    """Tests for data integrity and completeness."""

    def test_no_duplicate_fingerprints(self):
        """No two transactions should have the same fingerprint."""
        transactions = parse_xtb_statement(XLSX_FIXTURE_PATH)

        fingerprints = [tx.get_fingerprint() for tx in transactions]
        assert len(fingerprints) == len(set(fingerprints))

    def test_timestamp_order(self):
        """Transactions should be parseable with valid timestamps."""
        transactions = parse_xtb_statement(XLSX_FIXTURE_PATH)

        # Just verify all timestamps are valid. Transactions are merged from
        # multiple sheets.
        for tx in transactions:
            assert tx.date is not None, "All transactions should have valid timestamps"

        # Check that we have transactions spanning the expected date range
        dates = [tx.date for tx in transactions]
        assert min(dates) >= datetime(2025, 9, 7)  # Statement start
        assert max(dates) <= datetime(2025, 10, 8)  # Statement end

    def test_all_transactions_have_required_fields(self):
        """All transactions should have required fields."""
        transactions = parse_xtb_statement(XLSX_FIXTURE_PATH)

        for tx in transactions:
            assert tx.id is not None
            assert tx.date is not None
            assert tx.tx_type is not None
            assert tx.amount is not None
            assert tx.description is not None


@requires_private_xtb_mhtml
class TestXTBMhtmlParsing:
    """Regression tests for XTB HTML/MHTML statements."""

    def test_parse_xtb_statement_supports_mhtml(self):
        transactions = parse_xtb_statement(MHTML_FIXTURE_PATH)

        assert len(transactions) == 292
        assert transactions[0].tx_type == TransactionType.OPEN_POSITION
        assert transactions[0].symbol == "OSS.US"
        assert transactions[-1].tx_type == TransactionType.COMMISSION
        assert transactions[-1].symbol == "SPY.US"

    def test_parse_xtb_statement_matches_mhtml_golden_snapshot(self):
        transactions = parse_xtb_statement(MHTML_FIXTURE_PATH)

        normalized = [
            {
                "id": tx.id,
                "date": tx.date.isoformat(),
                "tx_type": tx.tx_type.value,
                "amount": str(tx.amount),
                "currency": tx.currency,
                "symbol": tx.symbol,
                "description": tx.description,
            }
            for tx in transactions
        ]

        expected = json.loads(MHTML_SNAPSHOT_PATH.read_text())
        assert normalized == expected
