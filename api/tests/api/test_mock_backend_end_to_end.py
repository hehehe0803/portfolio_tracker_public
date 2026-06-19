from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from intel_fixtures import *  # noqa: F403

from app.db.models import (
    ActivityLog,
    Asset,
    BenchmarkQuote,
    Note,
    PositionSnapshot,
    Transaction,
    WatchlistItem,
)

AS_OF = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)


async def test_mock_backend_trust_restoration_surfaces_work_together(
    async_client,
    intel_session_factory,
    monkeypatch,
):
    """Exercise the main backend product surfaces with deterministic mock data.

    This covers the post-trust-restoration path without touching portfolio_dev:
    portfolio value/freshness, latest persisted state, transaction feed,
    performance summary, review queue, watchlist freshness, and decision audit log.
    """

    async def fake_prices(symbols):
        prices = {
            "AAPL": 180.0,
            "BTC": 70000.0,
            "WBETH": 2400.0,
            "SPY": 500.0,
            "XAU": 2500.0,
            "MSFT": 420.0,
        }
        return {symbol: prices.get(symbol) for symbol in symbols}

    monkeypatch.setattr("app.services.pricing.get_prices_bulk", fake_prices)
    monkeypatch.setattr("app.api.v1.watchlist.pricing.get_prices_bulk", fake_prices)

    async with intel_session_factory() as session:
        aapl = Asset(symbol="AAPL", asset_type="equity", thesis_status="none")
        btc = Asset(symbol="BTC", asset_type="crypto", thesis_status="core")
        wbeth = Asset(symbol="WBETH", asset_type="crypto", thesis_status="core")
        missing = Asset(symbol="MISSING", asset_type="crypto", thesis_status="none")
        session.add_all([aapl, btc, wbeth, missing])
        await session.flush()

        session.add_all(
            [
                Transaction(
                    institution="xtb",
                    tx_type="buy",
                    asset_symbol="AAPL",
                    asset_type="equity",
                    quantity=Decimal("10"),
                    price_usd=Decimal("100"),
                    total_usd=Decimal("1000"),
                    fee=Decimal("0"),
                    fee_currency="USD",
                    timestamp=AS_OF - timedelta(days=60),
                    fingerprint="mock-aapl-buy",
                    raw_data={"source_type": "mock_trade"},
                ),
                Transaction(
                    institution="binance",
                    tx_type="external_deposit",
                    asset_symbol="BTC",
                    asset_type="crypto",
                    quantity=Decimal("0.10"),
                    price_usd=Decimal("50000"),
                    total_usd=Decimal("5000"),
                    fee=Decimal("0"),
                    fee_currency="USD",
                    timestamp=AS_OF - timedelta(days=30),
                    fingerprint="mock-btc-deposit",
                    raw_data={"source_type": "deposit_history"},
                ),
                Transaction(
                    institution="binance",
                    tx_type="staking_subscribe",
                    asset_symbol="WBETH",
                    asset_type="crypto",
                    quantity=Decimal("1.0"),
                    price_usd=Decimal("2200"),
                    total_usd=Decimal("2200"),
                    fee=Decimal("0"),
                    fee_currency="USD",
                    timestamp=AS_OF - timedelta(days=20),
                    fingerprint="mock-wbeth-stake",
                    raw_data={"source_type": "eth_staking_wrap"},
                ),
                Transaction(
                    institution="binance",
                    tx_type="buy",
                    asset_symbol="MISSING",
                    asset_type="crypto",
                    quantity=Decimal("42"),
                    price_usd=Decimal("1"),
                    total_usd=Decimal("42"),
                    fee=Decimal("0"),
                    fee_currency="USD",
                    timestamp=AS_OF - timedelta(days=10),
                    fingerprint="mock-missing-buy",
                    raw_data={"source_type": "mock_trade_without_price"},
                ),
            ]
        )
        session.add_all(
            [
                PositionSnapshot(
                    asset_id=aapl.id,
                    captured_at=AS_OF,
                    quantity=Decimal("10"),
                    avg_buy_price_usd=Decimal("100"),
                    total_cost_usd=Decimal("1000"),
                    current_price_usd=Decimal("180"),
                    current_value_usd=Decimal("1800"),
                    unrealized_pnl_usd=Decimal("800"),
                    unrealized_pnl_pct=Decimal("0.80"),
                ),
                PositionSnapshot(
                    asset_id=btc.id,
                    captured_at=AS_OF,
                    quantity=Decimal("0.10"),
                    avg_buy_price_usd=Decimal("50000"),
                    total_cost_usd=Decimal("5000"),
                    current_price_usd=Decimal("70000"),
                    current_value_usd=Decimal("7000"),
                    unrealized_pnl_usd=Decimal("2000"),
                    unrealized_pnl_pct=Decimal("0.40"),
                ),
                PositionSnapshot(
                    asset_id=missing.id,
                    captured_at=AS_OF,
                    quantity=Decimal("42"),
                    avg_buy_price_usd=Decimal("1"),
                    total_cost_usd=Decimal("42"),
                    current_price_usd=None,
                    current_value_usd=None,
                    unrealized_pnl_usd=None,
                    unrealized_pnl_pct=None,
                ),
                BenchmarkQuote(symbol="SPY", captured_at=AS_OF, price_usd=Decimal("500")),
                WatchlistItem(
                    symbol="MSFT",
                    name="Microsoft",
                    asset_type="equity",
                    priority="high",
                    status="researching",
                    target_entry_min=Decimal("350"),
                    target_entry_max=Decimal("390"),
                    thesis="Cloud and AI compounder",
                    next_review_date=date(2026, 5, 1),
                ),
                Note(
                    entity_type="asset",
                    entity_id="AAPL",
                    content="Mock stale note should enter weekly review.",
                    user_id=1,
                    created_at=AS_OF - timedelta(days=120),
                ),
                ActivityLog(
                    source="sync.binance",
                    status="success",
                    message="Mock broker sync event",
                    created_at=AS_OF - timedelta(hours=12),
                    event_metadata={"institution": "binance"},
                ),
            ]
        )
        await session.commit()

    summary = (await async_client.get("/v1/portfolio/summary")).json()
    assert summary["holding_count"] == 4
    holdings = {holding["symbol"]: holding for holding in summary["holdings"]}
    assert holdings["AAPL"]["current_value_usd"] == 1800.0
    assert holdings["BTC"]["freshness"]["source"] == "live_price_provider"
    assert holdings["MISSING"]["freshness"]["source"] == "missing_price"
    assert "MISSING has no current price metadata" in summary["freshness"]["warnings"]

    snapshots = (await async_client.get("/v1/portfolio/snapshots/latest")).json()
    assert snapshots["captured_at"] == AS_OF.isoformat()
    assert len(snapshots["snapshots"]) == 3
    assert snapshots["freshness"]["source"] == "persisted_position_snapshot"

    benchmarks = (await async_client.get("/v1/portfolio/benchmarks/latest")).json()
    assert benchmarks["quotes"][0]["symbol"] == "SPY"
    assert benchmarks["quotes"][0]["freshness"]["source"] == "persisted_benchmark_quote"

    transactions = (await async_client.get("/v1/portfolio/transactions?limit=10")).json()
    assert [tx["asset"] for tx in transactions[:3]] == ["MISSING", "WBETH", "BTC"]

    performance = (await async_client.get("/v1/portfolio/performance-summary")).json()
    assert performance["combined"]["current_value_usd"] > 0
    assert performance["combined"]["gross_deposits_usd"] >= 5000

    watchlist = (await async_client.get("/v1/watchlist")).json()
    assert watchlist[0]["symbol"] == "MSFT"
    assert watchlist[0]["current_price_usd"] == 420.0
    assert watchlist[0]["freshness"]["source"] == "live_price_provider"

    queue = (
        await async_client.get(
            "/v1/review/queue",
            params={"as_of": AS_OF.isoformat(), "stale_note_days": 90},
        )
    ).json()
    queue_keys = {item["key"] for item in queue["items"]}
    assert {"asset:AAPL", "watchlist:MSFT", "event:sync.binance"} <= queue_keys

    decision = await async_client.post(
        "/v1/review/decisions",
        json={
            "entity_type": "asset",
            "entity_id": "AAPL",
            "decision": "research",
            "rationale": "Mock QA asks for thesis refresh.",
            "next_review_date": "2026-06-15",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["decision"] == "research"

    activity = (
        await async_client.get(
            "/v1/intelligence/activity?entity_type=asset&entity_id=AAPL"
        )
    ).json()
    assert activity[0]["source"] == "review_decision"
    assert activity[0]["metadata"]["rationale"] == "Mock QA asks for thesis refresh."
