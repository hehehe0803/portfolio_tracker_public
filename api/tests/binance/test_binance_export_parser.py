from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import pytest

from app.services.binance_export_parser import (
    BinanceExportParserError,
    BinanceLedgerEntry,
    parse_binance_exports,
    summarize_binance_entries,
)


def _build_zip(member_name: str, csv_text: str) -> bytes:
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, csv_text)
    return buff.getvalue()


def _entry_by_type(
    entries: list[BinanceLedgerEntry], tx_type: str
) -> BinanceLedgerEntry:
    return next(entry for entry in entries if entry.tx_type == tx_type)


def test_parse_binance_exports_maps_spot_deposit_and_transaction_history_rows():
    spot_zip = _build_zip(
        "Binance-Spot-Trade-History-202604201027(UTC+7).csv",
        "Time,Pair,Side,Price,Executed,Amount,Fee\n"
        "25-10-11 01:01:13,BTCUSDT,BUY,60000,0.01000000BTC,600.00000000USDT,0.00001000BTC\n"
        "25-10-11 02:01:13,BTCUSDT,SELL,65000,0.00500000BTC,325.00000000USDT,0.32500000USDT\n",
    )
    deposit_zip = _build_zip(
        "Binance-Deposit-History-202604201017(UTC+7).csv",
        "Time,Coin,Network,Amount,Address,TXID,Status\n"
        "25-10-10 15:28:51,USDT,BSC,100.5,0xabc,tx-1,Completed\n",
    )
    tx_history_zip = _build_zip(
        "Binance-Transaction-History-202604201017(UTC+7).csv",
        "User ID,Time,Account,Operation,Coin,Change,Remark\n"
        "1,25-10-10 13:00:00,Funding,P2P Trading,USDT,250.00,P2P - order-1\n"
        "1,25-10-10 13:05:00,Funding,Transfer Between Main and Funding Wallet,USDT,-100.00,\n"
        "1,25-10-10 13:05:00,Spot,Transfer Between Main and Funding Wallet,USDT,100.00,\n",
    )

    entries = parse_binance_exports(
        [
            ("spot.zip", spot_zip),
            ("deposit.zip", deposit_zip),
            ("transaction.zip", tx_history_zip),
        ]
    )

    assert len(entries) == 6

    buy_entry = _entry_by_type(entries, "spot_trade_buy")
    assert buy_entry.asset_symbol == "BTC"
    assert buy_entry.quantity == Decimal("0.01000000")
    assert buy_entry.price_usd == Decimal("60000")
    assert buy_entry.total_usd == Decimal("600.00000000")
    assert buy_entry.fee == Decimal("0.00001000")
    assert buy_entry.fee_currency == "BTC"
    assert buy_entry.timestamp.isoformat() == "2025-10-10T18:01:13+00:00"
    assert buy_entry.raw_data["pair"] == "BTCUSDT"
    assert buy_entry.raw_data["quote_asset"] == "USDT"

    sell_entry = _entry_by_type(entries, "spot_trade_sell")
    assert sell_entry.quantity == Decimal("0.00500000")
    assert sell_entry.total_usd == Decimal("325.00000000")
    assert sell_entry.fee_currency == "USDT"

    deposit_entry = _entry_by_type(entries, "deposit")
    assert deposit_entry.asset_symbol == "USDT"
    assert deposit_entry.total_usd == Decimal("100.5")
    assert deposit_entry.raw_data["txid"] == "tx-1"

    p2p_entry = _entry_by_type(entries, "external_deposit")
    assert p2p_entry.asset_symbol == "USDT"
    assert p2p_entry.total_usd == Decimal("250.00")
    assert p2p_entry.raw_data["operation"] == "P2P Trading"

    transfer_entry = _entry_by_type(entries, "transfer_out")
    assert transfer_entry.asset_symbol == "USDT"
    assert transfer_entry.quantity == Decimal("100.00")
    assert transfer_entry.raw_data["account"] == "Funding"


def test_parse_binance_exports_supports_rewards_locked_amounts_and_empty_exports():
    rewards_zip = _build_zip(
        "Binance-Simple-Earn—Flexible-History-202604201020(UTC+7).csv",
        "Time,Coin,Amount,Type\n2026-04-19,BTC,0.00000006,Bonus Tiered APR Rewards\n",
    )
    locked_zip = _build_zip(
        "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
        "Subscription Date,Coin,Total Amount,Lock Period,Type,From\n"
        '26-03-10 14:48:21,FET,"3,024.12030413",120 Days,Normal,SPOT Wallet\n',
    )
    empty_zip = _build_zip(
        "Binance-Simple-Earn—Trial-Funds-History-202604201024(UTC+7).csv",
        "Time,Coin,Voucher No,Amount\nNo data matches the criteria.\n",
    )

    entries = parse_binance_exports(
        [
            ("rewards.zip", rewards_zip),
            ("locked.zip", locked_zip),
            ("empty.zip", empty_zip),
        ]
    )

    assert len(entries) == 2

    reward_entry = _entry_by_type(entries, "earn_reward")
    assert reward_entry.asset_symbol == "BTC"
    assert reward_entry.quantity == Decimal("0.00000006")
    assert reward_entry.price_usd is None
    assert reward_entry.raw_data["reward_type"] == "Bonus Tiered APR Rewards"

    locked_entry = _entry_by_type(entries, "earn_subscribe")
    assert locked_entry.asset_symbol == "FET"
    assert locked_entry.quantity == Decimal("3024.12030413")
    assert locked_entry.raw_data["lock_period"] == "120 Days"
    assert locked_entry.raw_data["stake_asset"] == "FET"
    assert locked_entry.raw_data["stake_amount"] == "3,024.12030413"


def test_parse_binance_exports_supports_eth_staking_wrap_and_reward_schemas():
    wrap_zip = _build_zip(
        "Binance-Simple-Earn—ETH-Staking-History-202604201023(UTC+7).csv",
        "Time,Wrapped BETH Amount,Distributed WBETH Amount,Ratio,Status\n"
        "24-12-13 15:53:00,1.45721167,1.37854386,1:0.9460148424436261528298814751,Success\n",
    )
    reward_zip = _build_zip(
        "Binance-Simple-Earn—ETH-Staking-History-202604201023(UTC+7).csv",
        "Time,Asset,Ratio,Amount,Position Amount\n"
        "2026-04-18(UTC0),ETH,2.63%,0.00012546,1.59015370 WBETH\n",
    )

    entries = parse_binance_exports(
        [("wrap.zip", wrap_zip), ("reward.zip", reward_zip)]
    )

    assert len(entries) == 2

    wrap_entry = _entry_by_type(entries, "staking_subscribe")
    assert wrap_entry.asset_symbol == "WBETH"
    assert wrap_entry.quantity == Decimal("1.37854386")
    assert wrap_entry.raw_data["source_type"] == "eth_staking_wrap"
    assert wrap_entry.raw_data["stake_asset"] == "BETH"
    assert wrap_entry.raw_data["stake_amount"] == "1.45721167"

    reward_entry = _entry_by_type(entries, "staking_reward")
    assert reward_entry.asset_symbol == "ETH"
    assert reward_entry.quantity == Decimal("0.00012546")
    assert reward_entry.raw_data["position_amount"] == "1.59015370 WBETH"


def test_parse_binance_exports_rejects_zip_archives_with_too_many_members():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx in range(101):
            zf.writestr(
                f"member-{idx}.csv",
                "Time,Coin,Amount,To,Status\n25-10-11 00:00:00,USDT,1.0,spot,Completed\n",
            )

    with pytest.raises(BinanceExportParserError, match="too many CSV members"):
        parse_binance_exports([("too-many-members.zip", buffer.getvalue())])


def test_parse_binance_exports_preserves_convert_pair_metadata_for_non_usd_swaps():
    convert_zip = _build_zip(
        "Binance-Convert-Order-History-202604201027(UTC+7).csv",
        "Time,Wallet,Pair,Type,Sell,Buy,Price,Inverse Price,Date Updated,Status\n"
        "25-10-11 01:01:13,Spot,ETHBNB,Market,1.00000000ETH,10.00000000BNB,,,,Success\n",
    )

    entries = parse_binance_exports([("convert.zip", convert_zip)])

    sell_entry = _entry_by_type(entries, "convert_sell")
    buy_entry = _entry_by_type(entries, "convert_buy")

    assert sell_entry.asset_symbol == "ETH"
    assert sell_entry.total_usd is None
    assert sell_entry.raw_data["convert_to_asset"] == "BNB"
    assert sell_entry.raw_data["convert_to_quantity"] == "10.00000000"
    assert buy_entry.asset_symbol == "BNB"
    assert buy_entry.total_usd is None
    assert buy_entry.raw_data["convert_from_asset"] == "ETH"
    assert buy_entry.raw_data["convert_from_quantity"] == "1.00000000"


def test_parse_binance_exports_rejects_unsupported_files_instead_of_succeeding_empty():
    unsupported_csv = b"foo,bar\n1,2\n"

    with pytest.raises(BinanceExportParserError, match="Unsupported Binance export schema"):
        parse_binance_exports([("unsupported.csv", unsupported_csv)])


def test_parse_binance_exports_rejects_unsupported_members_even_when_zip_has_supported_rows():
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "Binance-Spot-Trade-History-202604201027(UTC+7).csv",
            "Time,Pair,Side,Price,Executed,Amount,Fee\n"
            "25-10-11 01:01:13,BTCUSDT,BUY,60000,0.01000000BTC,600.00000000USDT,0.00001000BTC\n",
        )
        zf.writestr("unknown-binance-export.csv", "foo,bar\n1,2\n")

    with pytest.raises(BinanceExportParserError, match="Unsupported Binance export schema"):
        parse_binance_exports([("mixed.zip", buff.getvalue())])


def test_parse_binance_exports_allows_empty_unsupported_members_in_mixed_archives():
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "Binance-Spot-Trade-History-202604201027(UTC+7).csv",
            "Time,Pair,Side,Price,Executed,Amount,Fee\n"
            "25-10-11 01:01:13,BTCUSDT,BUY,60000,0.01000000BTC,600.00000000USDT,0.00001000BTC\n",
        )
        zf.writestr(
            "Binance-Advanced-Earn-History-202604201027(UTC+7).csv",
            "Time,Coin,Protocol,Amount,Status\nNo data matches the criteria.\n",
        )

    entries = parse_binance_exports([("mixed-empty.zip", buff.getvalue())])

    assert len(entries) == 1
    assert entries[0].tx_type == "spot_trade_buy"


def test_parse_binance_exports_rejects_supported_named_members_with_unmapped_data():
    unsupported_simple_earn = _build_zip(
        "Binance-Simple-Earn-History-202604201027(UTC+7).csv",
        "Time,Coin,Unsupported Column\n2026-04-19,BTC,value\n",
    )

    with pytest.raises(
        BinanceExportParserError,
        match="Supported Binance export schema produced no importable rows",
    ):
        parse_binance_exports([("simple-earn-unsupported.zip", unsupported_simple_earn)])


def test_parse_binance_exports_rejects_supported_empty_exports_without_rows():
    empty_supported_zip = _build_zip(
        "Binance-Simple-Earn—Trial-Funds-History-202604201024(UTC+7).csv",
        "Time,Coin,Voucher No,Amount\nNo data matches the criteria.\n",
    )

    with pytest.raises(
        BinanceExportParserError, match="Binance export contained no importable rows"
    ):
        parse_binance_exports([("empty-only.zip", empty_supported_zip)])


def test_summarize_binance_entries_groups_by_type_and_source():
    entries = [
        BinanceLedgerEntry(
            tx_type="spot_trade_buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity=Decimal("0.1"),
            price_usd=Decimal("60000"),
            total_usd=Decimal("6000"),
            fee=Decimal("0.0001"),
            fee_currency="BTC",
            timestamp=None,
            fingerprint="a",
            raw_data={"source_type": "spot_trade"},
        ),
        BinanceLedgerEntry(
            tx_type="external_deposit",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity=Decimal("1000"),
            price_usd=Decimal("1"),
            total_usd=Decimal("1000"),
            fee=Decimal("0"),
            fee_currency="USDT",
            timestamp=None,
            fingerprint="b",
            raw_data={"source_type": "transaction_history"},
        ),
    ]

    summary = summarize_binance_entries(entries)

    assert summary["count"] == 2
    assert summary["by_type"] == {
        "spot_trade_buy": Decimal("1"),
        "external_deposit": Decimal("1"),
    }
    assert summary["by_source_type"] == {
        "spot_trade": Decimal("1"),
        "transaction_history": Decimal("1"),
    }
    assert summary["gross_accounting_value_usd"] == Decimal("7000")
