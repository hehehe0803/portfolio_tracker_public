from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import Transaction as DBTransaction
from app.services.binance_client import BinanceError
from app.services.binance_export_parser import (
    _parse_convert_orders,
    _parse_transaction_history,
    parse_binance_exports,
)
from app.services.binance_sync import (
    API_DELTA_OVERLAP,
    HISTORY_PAGE_LIMIT,
    _build_source_specific_overlap_counts,
    _normalize_c2c_history,
    _normalize_convert_history,
    _normalize_simple_earn_history,
    _source_specific_overlap_key,
    build_delta_records,
)


def _build_zip(member_name: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, content)
    return buffer.getvalue()


def test_simple_earn_api_fingerprints_match_export_baseline_for_overlap_flows() -> None:
    flexible_reward_rows = {
        "rows": [
            {
                "time": int(
                    datetime(2026, 4, 18, 17, 0, tzinfo=UTC).timestamp() * 1000
                ),
                "asset": "BTC",
                "rewards": "0.00000006",
                "type": "BONUS",
            }
        ]
    }
    locked_subscription_rows = {
        "rows": [
            {
                "time": int(
                    datetime(2026, 3, 10, 7, 48, 21, tzinfo=UTC).timestamp() * 1000
                ),
                "asset": "FET",
                "amount": "3024.12030413",
                "lockPeriod": 120,
                "type": "NORMAL",
                "sourceAccount": "SPOT",
            }
        ]
    }
    locked_redemption_rows = {
        "rows": [
            {
                "time": int(datetime(2026, 4, 10, 1, 0, tzinfo=UTC).timestamp() * 1000),
                "asset": "SOL",
                "amount": "1.50000000",
                "redeemTo": "SPOT",
                "status": "SUCCESS",
            }
        ]
    }
    locked_reward_rows = {
        "rows": [
            {
                "time": int(
                    datetime(2026, 4, 9, 17, 0, tzinfo=UTC).timestamp() * 1000
                ),
                "asset": "FET",
                "amount": "0.37284379",
                "lockPeriod": 120,
                "type": "LOCKED_REWARD",
            }
        ]
    }

    api_entries = (
        _normalize_simple_earn_history(flexible_reward_rows, kind="flexible_reward")
        + _normalize_simple_earn_history(
            locked_subscription_rows, kind="locked_subscription"
        )
        + _normalize_simple_earn_history(
            locked_redemption_rows, kind="locked_redemption"
        )
        + _normalize_simple_earn_history(locked_reward_rows, kind="locked_reward")
    )

    export_entries = parse_binance_exports(
        [
            (
                "reward.zip",
                _build_zip(
                    "Binance-Simple-Earn—Flexible-History-202604201020(UTC+7).csv",
                    "Time,Coin,Amount,Type\n"
                    "2026-04-19,BTC,0.00000006,Bonus Tiered APR Rewards\n",
                ),
            ),
            (
                "locked-subscription.zip",
                _build_zip(
                    "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
                    (
                        "Subscription Date,Coin,Total Amount,Lock Period,Type,From\n"
                        '26-03-10 14:48:21,FET,"3,024.12030413",'
                        "120 Days,Normal,SPOT Wallet\n"
                    ),
                ),
            ),
            (
                "locked-redemption.zip",
                _build_zip(
                    "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
                    (
                        "Redemption Date,Coin,Redemption Amount,Redeem to,"
                        "Est. Arrival Time,Status\n"
                        "26-04-10 08:00:00,SOL,1.50000000,SPOT Wallet,"
                        "2026-04-11 08:00:00,Success\n"
                    ),
                ),
            ),
            (
                "locked-reward.zip",
                _build_zip(
                    "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
                    (
                        "Time,Coin,Interest,Lock Period,APR,Type\n"
                        "26-04-10 00:00:00,FET,0.37284379,120 Days,,Locked Rewards\n"
                    ),
                ),
            ),
        ]
    )

    api_fingerprints = {entry.fingerprint for entry in api_entries}
    export_fingerprints = {entry.fingerprint for entry in export_entries}

    assert api_fingerprints == export_fingerprints


def test_convert_api_fingerprints_match_export_baseline_with_ms_timestamp() -> None:
    api_entries = _normalize_convert_history(
        {
            "list": [
                {
                    "quoteId": "60114aedb0244ca583b38a388ff54c40",
                    "orderId": 2107825500537135191,
                    "orderStatus": "SUCCESS",
                    "fromAsset": "GLMR",
                    "fromAmount": "76.108492",
                    "toAsset": "USDT",
                    "toAmount": "4.02374543",
                    "createTime": 1760119184420,
                    "walletType": "SPOT",
                    "side": "SELL",
                }
            ]
        }
    )
    export_entries = _parse_convert_orders(
        [
            {
                "Time": "2025-10-11 00:59:44",
                "Pair": "GLMRUSDT",
                "Sell": "76.10849200 GLMR",
                "Buy": "4.02374543 USDT",
                "Wallet": "SPOT",
                "Status": "Successful",
            }
        ],
        "Binance-Convert-Order-History-202604201025(UTC+7).csv",
    )

    assert {entry.fingerprint for entry in api_entries} == {
        entry.fingerprint for entry in export_entries
    }


def test_c2c_api_fingerprints_match_export_baseline_with_taker_amount() -> None:
    api_entries = _normalize_c2c_history(
        {
            "data": [
                {
                    "orderNumber": "22735222720347865088",
                    "tradeType": "BUY",
                    "asset": "USDT",
                    "fiat": "VND",
                    "amount": "200.20000000",
                    "takerAmount": "200",
                    "totalPrice": "5177172.00000000",
                    "orderStatus": "COMPLETED",
                    "createTime": 1742284760545,
                }
            ]
        }
    )
    export_entries = _parse_transaction_history(
        [
            {
                "Time": "25-03-18 15:01:04",
                "Account": "Funding",
                "Operation": "P2P Trading",
                "Coin": "USDT",
                "Change": "200",
                "Remark": "P2P - 22735222720347865088",
            }
        ],
        "Binance-Transaction-History-202604201017(UTC+7).csv",
    )

    assert {entry.fingerprint for entry in api_entries} == {
        entry.fingerprint for entry in export_entries
    }


def test_source_specific_overlap_key_matches_locked_reward_and_redemption_pairs() -> None:
    locked_reward_api = _normalize_simple_earn_history(
        {
            "rows": [
                {
                    "time": int(
                        datetime(2024, 5, 20, 0, 22, 55, tzinfo=UTC).timestamp() * 1000
                    ),
                    "asset": "GLMR",
                    "amount": "0.03117278",
                    "lockPeriod": 30,
                    "type": "LOCKED_REWARD",
                }
            ]
        },
        kind="locked_reward",
    )[0]
    locked_reward_export = parse_binance_exports(
        [
            (
                "locked-reward.zip",
                _build_zip(
                    "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
                    (
                        "Time,Coin,Interest,Lock Period,APR,Type\n"
                        "2024-05-20 00:00:00,GLMR,0.03117278,30 Days,,Locked Rewards\n"
                    ),
                ),
            )
        ]
    )[0]

    locked_redeem_api = _normalize_simple_earn_history(
        {
            "rows": [
                {
                    "time": int(
                        datetime(2025, 1, 4, 0, 23, 45, tzinfo=UTC).timestamp() * 1000
                    ),
                    "asset": "ADA",
                    "amount": "0.88750574",
                    "lockPeriod": 120,
                    "type": "NEW_TRANSFERRED",
                    "status": "PAID",
                }
            ]
        },
        kind="locked_redemption",
    )[0]
    locked_redeem_export = parse_binance_exports(
        [
            (
                "locked-redemption.zip",
                _build_zip(
                    "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
                    (
                        "Redemption Date,Coin,Redemption Amount,Redeem to,Est. Arrival Time,Status\n"
                        "25-01-04 07:23:45,ADA,0.88750574,SPOT Wallet,25-01-04 07:23:45,Success\n"
                    ),
                ),
            )
        ]
    )[0]

    assert _source_specific_overlap_key(locked_reward_api) == _source_specific_overlap_key(
        locked_reward_export
    )
    assert _source_specific_overlap_key(locked_redeem_api) == _source_specific_overlap_key(
        locked_redeem_export
    )


def test_source_specific_overlap_key_ignores_flexible_rewards_for_now() -> None:
    flexible_reward = _normalize_simple_earn_history(
        {
            "rows": [
                {
                    "time": int(
                        datetime(2025, 9, 18, 4, 29, 46, tzinfo=UTC).timestamp() * 1000
                    ),
                    "asset": "ETH",
                    "rewards": "0.00000054",
                    "type": "BONUS",
                }
            ]
        },
        kind="flexible_reward",
    )[0]

    assert _source_specific_overlap_key(flexible_reward) is None


def test_build_source_specific_overlap_counts_counts_duplicate_locked_rewards() -> None:
    export_rows = parse_binance_exports(
        [
            (
                "locked-reward.zip",
                _build_zip(
                    "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv",
                    (
                        "Time,Coin,Interest,Lock Period,APR,Type\n"
                        "2024-05-20 00:00:00,GLMR,0.03117278,30 Days,,Locked Rewards\n"
                        "2024-05-20 08:00:00,GLMR,0.03117278,30 Days,,Locked Rewards\n"
                    ),
                ),
            )
        ]
    )

    counts = _build_source_specific_overlap_counts(export_rows)
    keys = [_source_specific_overlap_key(row) for row in export_rows]

    assert keys[0] is not None
    assert keys[0] == keys[1]
    assert counts[keys[0]] == 2


def test_overlap_counts_are_meant_for_import_backed_export_rows_only() -> None:
    shared_payload = {
        "source_type": "simple_earn_locked_reward",
        "lock_period": "30 Days",
    }
    export_tx = DBTransaction(
        institution="binance",
        tx_type="earn_reward",
        asset_symbol="GLMR",
        asset_type="crypto",
        quantity=Decimal("0.03117278"),
        price_usd=None,
        total_usd=None,
        fee=Decimal("0"),
        fee_currency="GLMR",
        timestamp=datetime(2024, 5, 20, 0, 0, tzinfo=UTC),
        fingerprint="export-fp",
        raw_data=shared_payload,
        import_id=1,
    )
    api_tx = DBTransaction(
        institution="binance",
        tx_type="earn_reward",
        asset_symbol="GLMR",
        asset_type="crypto",
        quantity=Decimal("0.03117278"),
        price_usd=None,
        total_usd=None,
        fee=Decimal("0"),
        fee_currency="GLMR",
        timestamp=datetime(2024, 5, 19, 17, 22, 55, tzinfo=UTC),
        fingerprint="api-fp",
        raw_data=shared_payload,
        import_id=None,
    )

    export_only_counts = _build_source_specific_overlap_counts([export_tx])
    mixed_counts = _build_source_specific_overlap_counts([export_tx, api_tx])
    export_key = _source_specific_overlap_key(export_tx)

    assert export_key is not None
    assert export_only_counts[export_key] == 1
    assert mixed_counts[export_key] == 2


class _PaginatedClient:
    def __init__(self) -> None:
        self.deposit_calls: list[tuple[datetime | None, int]] = []

    def get_deposit_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        *,
        limit: int = 1000,
        offset: int = 0,
    ):
        self.deposit_calls.append((start_time, offset))
        first_page = [
            {
                "insertTime": int(
                    datetime(2026, 4, 20, 4, 0, tzinfo=UTC).timestamp() * 1000
                ),
                "coin": "USDT",
                "amount": "1",
                "txId": f"dep-{idx}",
                "status": 1,
            }
            for idx in range(1000)
        ]
        second_page = [
            {
                "insertTime": int(
                    datetime(2026, 4, 20, 5, 0, tzinfo=UTC).timestamp() * 1000
                ),
                "coin": "USDT",
                "amount": "2",
                "txId": "dep-final",
                "status": 1,
            }
        ]
        if offset == 0:
            return first_page
        return second_page

    def get_withdraw_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        *,
        limit: int = 1000,
        offset: int = 0,
    ):
        raise BinanceError("withdraw disabled")

    def get_convert_trade_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
    ):
        return {"list": []}

    def get_flexible_subscription_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        current: int = 1,
    ):
        return {"rows": []}

    def get_flexible_redemption_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        current: int = 1,
    ):
        return {"rows": []}

    def get_flexible_rewards_history(
        self,
        rewards_type: str = "BONUS",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
    ):
        return {"rows": []}

    def get_locked_subscription_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        current: int = 1,
    ):
        return {"rows": []}

    def get_locked_redemption_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        current: int = 1,
    ):
        return {"rows": []}

    def get_locked_rewards_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        current: int = 1,
    ):
        return {"rows": []}

    def get_c2c_trade_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = HISTORY_PAGE_LIMIT,
        trade_type: str | None = None,
        page: int = 1,
    ):
        return {"data": []}


def test_build_delta_records_paginates_and_tolerates_endpoint_errors() -> None:
    client = _PaginatedClient()
    start_time = datetime(2026, 4, 20, 4, 0, tzinfo=UTC) - API_DELTA_OVERLAP
    end_time = datetime(2026, 4, 21, 4, 0, tzinfo=UTC)

    records, warnings = build_delta_records(client, start_time, end_time)

    deposits = [record for record in records if record.tx_type == "deposit"]
    assert len(deposits) == 1001
    assert deposits[-1].fingerprint != deposits[0].fingerprint
    assert client.deposit_calls == [
        (start_time, 0),
        (start_time, 1000),
    ]
    assert {record.asset_symbol for record in deposits} == {"USDT"}
    assert {record.quantity for record in deposits} == {Decimal("1"), Decimal("2")}
    assert warnings == ["withdraw_history: withdraw disabled"]
