from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from intel_fixtures import *  # noqa: F403

from app.db.models import ActivityLog, Asset, Note, PositionSnapshot, WatchlistItem


AS_OF = "2026-05-18T12:00:00+00:00"
AS_OF_DT = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)


async def test_review_queue_collects_missing_review_inputs_watchlist_due_stale_notes_and_broker_events(
    async_client, intel_session_factory
):
    async with intel_session_factory() as session:
        aapl = Asset(symbol="AAPL", asset_type="equity", thesis_status="none")
        tsla = Asset(symbol="TSLA", asset_type="equity", thesis_status="core")
        session.add_all([aapl, tsla])
        await session.flush()
        session.add_all(
            [
                PositionSnapshot(
                    asset_id=aapl.id,
                    captured_at=AS_OF_DT - timedelta(hours=1),
                    quantity=Decimal("10"),
                    avg_buy_price_usd=Decimal("100"),
                    total_cost_usd=Decimal("1000"),
                    current_price_usd=Decimal("175"),
                    current_value_usd=Decimal("1750"),
                    unrealized_pnl_usd=Decimal("750"),
                    unrealized_pnl_pct=Decimal("0.75"),
                ),
                PositionSnapshot(
                    asset_id=tsla.id,
                    captured_at=AS_OF_DT - timedelta(hours=1),
                    quantity=Decimal("5"),
                    avg_buy_price_usd=Decimal("300"),
                    total_cost_usd=Decimal("1500"),
                    current_price_usd=Decimal("210"),
                    current_value_usd=Decimal("1050"),
                    unrealized_pnl_usd=Decimal("-450"),
                    unrealized_pnl_pct=Decimal("-0.30"),
                ),
                WatchlistItem(
                    symbol="MSFT",
                    priority="high",
                    status="researching",
                    thesis="AI platform",
                    next_review_date=date(2026, 5, 1),
                ),
                Note(
                    entity_type="asset",
                    entity_id="TSLA",
                    content="Old concern that needs a decision",
                    user_id=1,
                    created_at=AS_OF_DT - timedelta(days=120),
                ),
                ActivityLog(
                    source="sync.binance",
                    status="success",
                    message="Binance sync imported fresh state",
                    created_at=AS_OF_DT - timedelta(days=1),
                    event_metadata={"institution": "binance"},
                ),
            ]
        )
        await session.commit()

    response = await async_client.get(
        "/v1/review/queue", params={"as_of": AS_OF, "stale_note_days": 90}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of"] == AS_OF
    reasons_by_key = {item["key"]: item["reasons"] for item in payload["items"]}
    assert "asset:AAPL" in reasons_by_key
    assert "missing_thesis" in reasons_by_key["asset:AAPL"]
    assert "missing_review_date" in reasons_by_key["asset:AAPL"]
    assert "major_unrealized_pnl_move" in reasons_by_key["asset:AAPL"]
    assert "watchlist:MSFT" in reasons_by_key
    assert reasons_by_key["watchlist:MSFT"] == ["watchlist_review_due"]
    assert "asset:TSLA" in reasons_by_key
    assert "stale_note" in reasons_by_key["asset:TSLA"]
    assert "major_unrealized_pnl_move" in reasons_by_key["asset:TSLA"]
    assert "event:sync.binance" in reasons_by_key
    assert payload["allowed_decisions"] == [
        "hold",
        "add",
        "trim",
        "exit",
        "research",
        "snooze",
        "archive",
    ]


async def test_review_decision_records_auditable_next_review_and_removes_snoozed_asset_from_queue(
    async_client, intel_session_factory
):
    async with intel_session_factory() as session:
        asset = Asset(symbol="AAPL", asset_type="equity", thesis_status="core")
        session.add(asset)
        await session.flush()
        session.add(
            PositionSnapshot(
                asset_id=asset.id,
                captured_at=AS_OF_DT - timedelta(hours=1),
                quantity=Decimal("10"),
                avg_buy_price_usd=Decimal("100"),
                total_cost_usd=Decimal("1000"),
                current_price_usd=Decimal("120"),
                current_value_usd=Decimal("1200"),
                unrealized_pnl_usd=Decimal("200"),
                unrealized_pnl_pct=Decimal("0.20"),
            )
        )
        await session.commit()

    decision = await async_client.post(
        "/v1/review/decisions",
        json={
            "entity_type": "asset",
            "entity_id": "AAPL",
            "decision": "hold",
            "rationale": "Thesis intact; review after next earnings.",
            "next_review_date": "2026-06-30",
        },
    )

    assert decision.status_code == 200
    assert decision.json()["decision"] == "hold"
    assert decision.json()["entity_id"] == "AAPL"
    assert decision.json()["next_review_date"] == "2026-06-30"

    queue = await async_client.get("/v1/review/queue", params={"as_of": AS_OF})
    keys = [item["key"] for item in queue.json()["items"]]
    assert "asset:AAPL" not in keys

    activity = await async_client.get(
        "/v1/intelligence/activity?entity_type=asset&entity_id=AAPL"
    )
    assert activity.json()[0]["source"] == "review_decision"
    assert activity.json()[0]["status"] == "hold"
    assert activity.json()[0]["metadata"]["next_review_date"] == "2026-06-30"


async def test_review_decision_rejects_unsupported_actions(async_client):
    response = await async_client.post(
        "/v1/review/decisions",
        json={"entity_type": "asset", "entity_id": "AAPL", "decision": "pray"},
    )

    assert response.status_code == 400
