from datetime import UTC, datetime

import pytest
from app.models.binance import AccountType, TransactionType
from app.services.binance_client import BinanceClient, BinanceError


@pytest.fixture
def client() -> BinanceClient:
    return BinanceClient(api_key="key", api_secret="secret")


def test_get_spot_balances_filters_zero_balances(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        client,
        "_call",
        lambda method_name, *args, **kwargs: {
            "balances": [
                {"asset": "BTC", "free": "1.2", "locked": "0.3"},
                {"asset": "USDT", "free": "0", "locked": "0"},
            ]
        },
    )

    balances = client.get_spot_balances()

    assert len(balances) == 1
    assert balances[0].asset == "BTC"
    assert balances[0].free == 1.2
    assert balances[0].locked == 0.3
    assert balances[0].account_type is AccountType.SPOT


def test_get_funding_balances_returns_empty_on_api_error(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    def raise_error(method_name, *args, **kwargs):
        raise BinanceError("funding disabled")

    monkeypatch.setattr(client, "_call", raise_error)

    assert client.get_funding_balances() == []


def test_get_flexible_products_maps_rows(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    def fake_call(method_name, *args, **kwargs):
        if method_name == "get_flexible_product_position":
            return {
                "rows": [
                    {"asset": "USDT", "totalAmount": "50.5"},
                    {"asset": "BTC", "freeAmount": "0.25"},
                ]
            }
        if method_name == "get_locked_product_position":
            return {"rows": []}
        raise AssertionError(f"unexpected method {method_name}")

    monkeypatch.setattr(client, "_call", fake_call)

    balances = client.get_flexible_products()

    assert [(b.asset, b.free, b.account_type) for b in balances] == [
        ("USDT", 50.5, AccountType.EARN),
        ("BTC", 0.25, AccountType.EARN),
    ]


def test_get_flexible_products_includes_locked_earn_current_positions(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    calls: list[str] = []

    def fake_call(method_name, *args, **kwargs):
        calls.append(method_name)
        if method_name == "get_flexible_product_position":
            return {"rows": [{"asset": "ETH", "totalAmount": "0.73696728"}]}
        if method_name == "get_locked_product_position":
            return {
                "rows": [
                    {"asset": "FET", "amount": "3024.12030413"},
                    {"asset": "ZERO", "amount": "0"},
                ]
            }
        raise AssertionError(f"unexpected method {method_name}")

    monkeypatch.setattr(client, "_call", fake_call)

    balances = client.get_flexible_products()

    assert calls == ["get_flexible_product_position", "get_locked_product_position"]
    assert [
        (balance.asset, balance.free, balance.account_type) for balance in balances
    ] == [
        ("ETH", 0.73696728, AccountType.EARN),
        ("FET", 3024.12030413, AccountType.EARN),
    ]


def test_get_staking_positions_maps_eth_account(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        client,
        "_call",
        lambda method_name, *args, **kwargs: {"holdingInETH": "1.75"},
    )

    positions = client.get_staking_positions()

    assert len(positions) == 1
    assert positions[0].asset == "ETH"
    assert positions[0].amount == 1.75
    assert positions[0].account_type is AccountType.EARN


def test_get_universal_transfers_maps_rows(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        client,
        "_call",
        lambda method_name, *args, **kwargs: {
            "rows": [
                {
                    "tranId": 42,
                    "asset": "BTC",
                    "amount": "0.1",
                    "timestamp": 1703001600000,
                    "status": "SUCCESS",
                }
            ]
        },
    )

    transfers = client.get_universal_transfers()

    assert len(transfers) == 1
    assert transfers[0].id == "42"
    assert transfers[0].asset == "BTC"
    assert transfers[0].amount == 0.1
    assert transfers[0].from_account is AccountType.FUNDING
    assert transfers[0].to_account is AccountType.SPOT
    assert transfers[0].status == "success"


def test_get_my_trades_maps_transactions(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        client,
        "_call",
        lambda method_name, *args, **kwargs: [
            {
                "id": 7,
                "qty": "0.5",
                "time": 1703001600000,
                "commission": "0.001",
                "commissionAsset": "BNB",
            }
        ],
    )

    transactions = client.get_my_trades("BTCUSDT")

    assert len(transactions) == 1
    assert transactions[0].id == "7"
    assert transactions[0].type is TransactionType.SPOT_TRADE
    assert transactions[0].asset == "BTC"
    assert transactions[0].amount == 0.5
    assert transactions[0].fee == 0.001
    assert transactions[0].fee_asset == "BNB"


def test_get_open_orders_prefers_base_asset_and_supports_non_usdt_quotes(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        client,
        "_call",
        lambda method_name, *args, **kwargs: [
            {
                "orderId": 10,
                "symbol": "SOLEUR",
                "baseAsset": "SOL",
                "quoteAsset": "EUR",
                "type": "LIMIT",
                "status": "NEW",
                "side": "BUY",
                "origQty": "12.5",
                "price": "145.40",
                "time": 1703001600000,
            },
            {
                "orderId": 11,
                "symbol": "ETHBTC",
                "quoteAsset": "BTC",
                "type": "STOP_LOSS_LIMIT",
                "status": "PENDING_NEW",
                "side": "SELL",
                "origQty": "1.25",
                "price": "0.075",
                "stopPrice": "0.074",
                "updateTime": 1703005200000,
            },
            {
                "orderId": 12,
                "symbol": "UNKNWNPAIR",
                "type": "LIMIT",
                "status": "NEW",
                "side": "BUY",
                "origQty": "3",
                "price": "1.0",
            },
        ],
    )

    orders = client.get_open_orders()

    actual = [(order.order_id, order.symbol, order.market_symbol) for order in orders]
    assert actual == [
        ("10", "SOL", "SOLEUR"),
        ("11", "ETH", "ETHBTC"),
        ("12", "", "UNKNWNPAIR"),
    ]
    assert orders[0].limit_price == 145.4
    assert orders[1].stop_price == 0.074
    assert orders[0].placed_at == datetime.fromtimestamp(1703001600, tz=UTC)
    assert orders[1].placed_at == datetime.fromtimestamp(1703005200, tz=UTC)


def test_get_account_summary_aggregates_balance_collections(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        client,
        "get_spot_balances",
        lambda: [],
    )
    monkeypatch.setattr(
        client,
        "get_funding_balances",
        lambda: [],
    )
    monkeypatch.setattr(
        client,
        "get_flexible_products",
        lambda: [],
    )
    monkeypatch.setattr(
        client,
        "get_staking_positions",
        lambda: [],
    )

    summary = client.get_account_summary()

    assert summary.total_balance == {}


def test_validate_connection_returns_false_on_binance_error(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    def raise_error(method_name, *args, **kwargs):
        raise BinanceError("boom")

    monkeypatch.setattr(client, "_call", raise_error)

    assert client.validate_connection() is False


def test_history_endpoint_wrappers_forward_time_windows_and_limits(
    client: BinanceClient, monkeypatch: pytest.MonkeyPatch
):
    captured: list[tuple[str, dict]] = []

    def fake_call(method_name, *args, **kwargs):
        captured.append((method_name, kwargs))
        return []

    monkeypatch.setattr(client, "_call", fake_call)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)

    client.get_deposit_history(start, end, limit=1000, offset=2000)
    client.get_withdraw_history(start, end, limit=1000, offset=1000)
    client.get_asset_dividend_history(start, end, limit=200)
    client.get_dust_log(start, end)
    client.get_convert_trade_history(start, end, limit=50)
    client.get_c2c_trade_history(start, end, limit=20, trade_type="BUY")
    client.get_flexible_subscription_records(start, end, limit=40)
    client.get_flexible_redemption_records(start, end, limit=40)
    client.get_flexible_rewards_history("REALTIME", start, end, limit=40)
    client.get_locked_subscription_records(start, end, limit=40)
    client.get_locked_redemption_records(start, end, limit=40)
    client.get_locked_rewards_history(start, end, limit=40)

    assert [name for name, _ in captured] == [
        "deposit_history",
        "withdraw_history",
        "asset_dividend_record",
        "dust_log",
        "get_convert_trade_history",
        "c2c_trade_history",
        "get_flexible_subscription_record",
        "get_flexible_redemption_record",
        "get_flexible_rewards_history",
        "get_locked_subscription_record",
        "get_locked_redemption_record",
        "get_locked_rewards_history",
    ]
    assert captured[0][1] == {
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": 1000,
        "offset": 2000,
    }
    assert captured[1][1] == {
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": 1000,
        "offset": 1000,
    }
    assert captured[2][1]["limit"] == 200
    assert captured[5][1]["tradeType"] == "BUY"
    assert captured[5][1]["page"] == 1
    assert captured[5][1]["rows"] == 20
    assert captured[6][1]["current"] == 1
    assert captured[6][1]["size"] == 40
    assert captured[8][1]["type"] == "REALTIME"
    assert captured[9][1]["current"] == 1
    assert captured[9][1]["size"] == 40
