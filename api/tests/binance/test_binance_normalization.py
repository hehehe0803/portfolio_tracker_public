from datetime import datetime, timezone

from app.models.binance import (
    AccountType,
    AssetBalance,
    BinanceAccountSummary,
    StakingPosition,
)
from app.services.binance_sync import build_snapshot_records


def test_binance_normalization_matches_snapshot():
    captured_at = datetime(2026, 3, 24, 12, 0, tzinfo=timezone.utc)
    summary = BinanceAccountSummary(
        spot_balances=[
            AssetBalance(asset="BTC", free=1.0, locked=0.1, account_type=AccountType.SPOT),
            AssetBalance(asset="USDT", free=500.0, locked=0.0, account_type=AccountType.SPOT),
        ],
        funding_balances=[
            AssetBalance(asset="ETH", free=2.5, locked=0.0, account_type=AccountType.FUNDING),
        ],
        earn_balances=[
            AssetBalance(asset="USDT", free=25.0, locked=0.0, account_type=AccountType.EARN),
        ],
        staking_positions=[
            StakingPosition(
                position_id="eth_staking",
                asset="ETH",
                amount=0.75,
                apy=None,
                start_date=None,
                status="active",
                account_type=AccountType.EARN,
            )
        ],
    )

    records = build_snapshot_records(summary, captured_at)

    assert [(record.asset_symbol, str(record.quantity), record.tx_type) for record in records] == [
        ("BTC", "1.1", "balance_snapshot_spot"),
        ("USDT", "500.0", "balance_snapshot_spot"),
        ("ETH", "2.5", "balance_snapshot_funding"),
        ("USDT", "25.0", "balance_snapshot_earn"),
        ("ETH", "0.75", "staking_position"),
    ]


