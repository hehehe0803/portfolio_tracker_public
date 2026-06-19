from datetime import UTC, datetime
from decimal import Decimal

from app.models.binance import (
    AccountType,
    AssetBalance,
    BinanceAccountSummary,
    StakingPosition,
)
from app.services.binance_sync import build_snapshot_records, summarize_snapshot_totals


def test_binance_reconciliation_totals():
    summary = BinanceAccountSummary(
        spot_balances=[
            AssetBalance(
                asset="BTC", free=1.0, locked=0.25, account_type=AccountType.SPOT
            ),
            AssetBalance(
                asset="LDBTC", free=0.99, locked=0.0, account_type=AccountType.SPOT
            ),
            AssetBalance(
                asset="USDT", free=250.0, locked=0.0, account_type=AccountType.SPOT
            ),
        ],
        funding_balances=[
            AssetBalance(
                asset="BTC", free=0.4, locked=0.0, account_type=AccountType.FUNDING
            ),
        ],
        earn_balances=[
            AssetBalance(
                asset="BTC", free=1.0, locked=0.0, account_type=AccountType.EARN
            ),
            AssetBalance(
                asset="ETH", free=3.0, locked=0.0, account_type=AccountType.EARN
            ),
        ],
        staking_positions=[
            StakingPosition(
                position_id="eth_staking",
                asset="ETH",
                amount=0.5,
                apy=None,
                start_date=None,
                status="active",
                account_type=AccountType.EARN,
            )
        ],
    )

    records = build_snapshot_records(summary, datetime(2026, 3, 24, 12, 0, tzinfo=UTC))
    totals = summarize_snapshot_totals(records)

    assert totals == {
        "BTC": Decimal("2.65"),
        "ETH": Decimal("3.0"),
        "USDT": Decimal("250.0"),
    }
