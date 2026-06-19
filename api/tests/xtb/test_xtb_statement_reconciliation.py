from decimal import Decimal

from app.services.xtb_statement_reconciliation import (
    XtbCashActivityEvidence,
    XtbClosedPositionPlEvidence,
    XtbCurrentPositionEvidence,
    XtbStatementEvidence,
    reconcile_xtb_current_value_statement,
)


def test_full_statement_with_cash_control_total_trusts_current_value():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[
                XtbCurrentPositionEvidence(
                    symbol="AAPL.US",
                    quantity=Decimal("2"),
                    market_price_usd=Decimal("110"),
                ),
                XtbCurrentPositionEvidence(
                    symbol="MSFT.US",
                    quantity=Decimal("1.5"),
                    market_price_usd=Decimal("200"),
                ),
            ],
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("1000")),
                XtbCashActivityEvidence("buy", Decimal("500"), symbol="AAPL.US"),
                XtbCashActivityEvidence("stamp_duty", Decimal("3.50")),
            ],
            closed_position_pl_rows=[
                XtbClosedPositionPlEvidence(
                    symbol="TSLA.US",
                    gross_pl_usd=Decimal("25"),
                )
            ],
            broker_cash_balance_usd=Decimal("496.50"),
        )
    )

    assert summary.source_authority == "authoritative"
    assert summary.current_value_trusted is True
    assert summary.current_positions_value_usd == Decimal("520.0")
    assert summary.broker_cash.amount_usd == Decimal("496.50")
    assert summary.broker_cash.trusted is True
    assert summary.current_value_usd == Decimal("1016.50")
    assert summary.fees_taxes.total_usd == Decimal("3.50")
    assert summary.closed_position_pl.total_usd == Decimal("25")
    assert summary.closed_position_pl.used_as_cash_proceeds is False
    assert summary.confidence["current_value"].state == "trusted"


def test_full_statement_without_broker_cash_control_total_blocks_trusted_cash():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[
                XtbCurrentPositionEvidence(
                    symbol="AAPL.US",
                    quantity=Decimal("2"),
                    market_price_usd=Decimal("110"),
                )
            ],
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("1000")),
                XtbCashActivityEvidence("buy", Decimal("220"), symbol="AAPL.US"),
            ],
            broker_cash_balance_usd=None,
        )
    )

    assert summary.current_value_trusted is False
    assert summary.broker_cash.trusted is False
    assert summary.confidence["broker_cash"].state == "blocked"
    assert summary.confidence["current_value"].state == "blocked"
    assert summary.issues[0].code == "missing_cash_control_total"


def test_daily_pdf_statement_remains_provisional_without_reconciliation():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="daily_pdf",
            current_positions=[],
            cash_operations=[
                XtbCashActivityEvidence("buy", Decimal("100"), symbol="AAPL.US"),
            ],
            broker_cash_balance_usd=Decimal("900"),
        )
    )

    assert summary.source_authority == "provisional"
    assert summary.current_value_trusted is False
    assert summary.confidence["current_value"].state == "provisional"
    assert summary.issues[0].code == "provisional_source_requires_full_statement"


def test_gmail_daily_pdf_statement_remains_provisional_without_reconciliation():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="gmail_daily_pdf",
            current_positions=[],
            cash_operations=[
                XtbCashActivityEvidence("sell", Decimal("125"), symbol="AAPL.US"),
            ],
            broker_cash_balance_usd=Decimal("125"),
        )
    )

    assert summary.source_authority == "provisional"
    assert summary.current_value_trusted is False
    assert summary.confidence["current_value"].state == "provisional"
    assert summary.issues[0].code == "provisional_source_requires_full_statement"


def test_closed_position_pl_rows_are_separate_from_broker_cash():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[],
            current_positions_proved=True,
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("100")),
                XtbCashActivityEvidence("buy", Decimal("100"), symbol="AAPL.US"),
            ],
            closed_position_pl_rows=[
                XtbClosedPositionPlEvidence(
                    symbol="AAPL.US",
                    gross_pl_usd=Decimal("12.34"),
                )
            ],
            broker_cash_balance_usd=Decimal("0"),
        )
    )

    assert summary.current_value_trusted is True
    assert summary.current_value_usd == Decimal("0")
    assert summary.broker_cash.amount_usd == Decimal("0")
    assert summary.closed_position_pl.total_usd == Decimal("12.34")
    assert summary.closed_position_pl.used_as_cash_proceeds is False


def test_full_statement_without_position_evidence_blocks_current_value():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[],
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("1000")),
            ],
            broker_cash_balance_usd=Decimal("1000"),
        )
    )

    assert summary.current_value_trusted is False
    assert summary.confidence["position_existence"].state == "blocked"
    assert summary.confidence["current_value"].state == "blocked"
    assert summary.issues[0].code == "missing_position_evidence"


def test_full_statement_with_proven_zero_positions_can_trust_current_value():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[],
            current_positions_proved=True,
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("1000")),
            ],
            broker_cash_balance_usd=Decimal("1000"),
        )
    )

    assert summary.current_value_trusted is True
    assert summary.confidence["position_existence"].state == "trusted"
    assert summary.current_positions_value_usd == Decimal("0")
    assert summary.current_value_usd == Decimal("1000")
    assert summary.issues == ()


def test_trade_row_fees_are_included_in_fee_tax_rollup():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[],
            current_positions_proved=True,
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("1000")),
                XtbCashActivityEvidence(
                    "buy",
                    Decimal("100"),
                    symbol="AAPL.US",
                    fee_usd=Decimal("2"),
                ),
            ],
            broker_cash_balance_usd=Decimal("898"),
        )
    )

    assert summary.current_value_trusted is True
    assert summary.broker_cash.amount_usd == Decimal("898")
    assert summary.fees_taxes.total_usd == Decimal("2")
    assert summary.fees_taxes.count == 1


def test_tax_rows_decrease_cash_without_blocking_statement_trust():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[],
            current_positions_proved=True,
            cash_operations=[
                XtbCashActivityEvidence("deposit", Decimal("100")),
                XtbCashActivityEvidence("tax", Decimal("7.25")),
            ],
            broker_cash_balance_usd=Decimal("92.75"),
        )
    )

    assert summary.current_value_trusted is True
    assert summary.broker_cash.amount_usd == Decimal("92.75")
    assert summary.fees_taxes.total_usd == Decimal("7.25")
    assert summary.fees_taxes.count == 1
    assert summary.issues == ()


def test_zero_quantity_position_with_current_value_does_not_crash():
    summary = reconcile_xtb_current_value_statement(
        XtbStatementEvidence(
            source_kind="full_statement",
            current_positions=[
                XtbCurrentPositionEvidence(
                    symbol="AAPL.US",
                    quantity=Decimal("0"),
                    current_value_usd=Decimal("0"),
                )
            ],
            cash_operations=[],
            broker_cash_balance_usd=Decimal("0"),
        )
    )

    assert summary.current_value_trusted is True
    assert summary.current_positions[0].market_price_usd == Decimal("0")
    assert summary.current_positions_value_usd == Decimal("0")
