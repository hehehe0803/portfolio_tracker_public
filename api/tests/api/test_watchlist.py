from __future__ import annotations

from unittest.mock import AsyncMock

from intel_fixtures import *  # noqa: F403


async def test_watchlist_crud_query_and_promote(
    async_client, seeded_asset, monkeypatch
):
    monkeypatch.setattr(
        "app.services.pricing.get_prices_bulk", AsyncMock(return_value={"MSFT": None})
    )
    created = await async_client.post(
        "/v1/watchlist",
        json={
            "symbol": "msft",
            "name": "Microsoft",
            "market": "NASDAQ",
            "asset_type": "equity",
            "priority": "high",
            "status": "researching",
            "target_entry_min": 250,
            "target_entry_max": 300,
            "thesis": "AI platform",
            "catalyst": "pullback",
            "next_review_date": "2026-05-15",
        },
    )
    assert created.status_code == 200
    item_id = created.json()["id"]
    assert created.json()["symbol"] == "MSFT"

    listed = await async_client.get("/v1/watchlist?status=researching")
    assert [item["symbol"] for item in listed.json()] == ["MSFT"]
    assert listed.json()[0]["current_price_usd"] is None
    assert listed.json()[0]["freshness"]["source"] == "not_priced"

    updated = await async_client.patch(
        f"/v1/watchlist/{item_id}",
        json={
            "symbol": "msft",
            "priority": "medium",
            "status": "ready",
            "asset_type": "equity",
            "target_entry_max": 280,
        },
    )
    assert updated.json()["status"] == "ready"
    assert updated.json()["name"] == "Microsoft"
    assert updated.json()["market"] == "NASDAQ"
    assert updated.json()["target_entry_min"] == 250.0
    assert updated.json()["thesis"] == "AI platform"
    assert updated.json()["catalyst"] == "pullback"

    promoted = await async_client.post(f"/v1/watchlist/{item_id}/promote/AAPL")
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "promoted"


async def test_watchlist_list_includes_price_freshness_metadata(
    async_client, monkeypatch
):
    await async_client.post(
        "/v1/watchlist",
        json={
            "symbol": "NVDA",
            "target_entry_max": 900,
            "priority": "high",
            "status": "ready",
        },
    )
    monkeypatch.setattr(
        "app.services.pricing.get_prices_bulk", AsyncMock(return_value={"NVDA": 850.0})
    )

    listed = await async_client.get("/v1/watchlist?status=ready")

    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["symbol"] == "NVDA"
    assert row["current_price_usd"] == 850.0
    assert row["freshness"]["source"] == "live_price_provider"
    assert row["freshness"]["as_of"] is not None
    assert row["freshness"]["degraded"] is False


async def test_watchlist_rejects_invalid_target_range(async_client):
    response = await async_client.post(
        "/v1/watchlist",
        json={"symbol": "TSLA", "target_entry_min": 300, "target_entry_max": 200},
    )
    assert response.status_code == 400


async def test_watchlist_rejects_symbols_that_cannot_be_priced_safely(async_client):
    created = await async_client.post(
        "/v1/watchlist",
        json={"symbol": "bad ticker", "target_entry_max": 10},
    )
    assert created.status_code == 400
    assert created.json()["detail"] == "Unsupported watchlist symbol"

    valid = await async_client.post(
        "/v1/watchlist",
        json={"symbol": "NVDA.US", "target_entry_max": 900},
    )
    assert valid.status_code == 200

    patched = await async_client.patch(
        f"/v1/watchlist/{valid.json()['id']}", json={"symbol": "NVDA/USD"}
    )
    assert patched.status_code == 400
    assert patched.json()["detail"] == "Unsupported watchlist symbol"


async def test_watchlist_missing_provider_price_is_stale_and_does_not_alert(
    async_client, monkeypatch
):
    await async_client.post(
        "/v1/watchlist",
        json={
            "symbol": "FUTURE.US",
            "target_entry_max": 50,
            "priority": "high",
            "status": "ready",
        },
    )
    monkeypatch.setattr(
        "app.services.pricing.get_prices_bulk",
        AsyncMock(return_value={"FUTURE.US": None}),
    )
    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.telegram.send_message", send_message)

    listed = await async_client.get("/v1/watchlist?status=ready")
    row = listed.json()[0]
    assert row["current_price_usd"] is None
    assert row["freshness"] == {
        "source": "not_priced",
        "as_of": row["freshness"]["as_of"],
        "stale": True,
        "degraded": True,
        "fallback": False,
        "warnings": ["FUTURE.US has no watchlist price metadata"],
    }
    assert row["freshness"]["as_of"] is not None

    evaluated = await async_client.post("/v1/watchlist/alerts/evaluate")
    assert evaluated.status_code == 200
    assert evaluated.json()["triggered"] == []
    send_message.assert_not_awaited()


async def test_watchlist_target_alert_evaluator(async_client, monkeypatch):
    created = await async_client.post(
        "/v1/watchlist",
        json={
            "symbol": "NVDA",
            "target_entry_max": 900,
            "priority": "high",
            "status": "ready",
        },
    )
    monkeypatch.setattr(
        "app.services.pricing.get_prices_bulk", AsyncMock(return_value={"NVDA": 850.0})
    )
    send_message = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.telegram.send_message", send_message)

    evaluated = await async_client.post("/v1/watchlist/alerts/evaluate")
    assert evaluated.status_code == 200
    assert evaluated.json()["triggered"][0]["symbol"] == "NVDA"
    send_message.assert_awaited_once()

    events = await async_client.get("/v1/watchlist/alerts/events")
    assert events.status_code == 200
    assert events.json()[0]["watchlist_item_id"] == created.json()["id"]
    assert events.json()[0]["telegram_delivered"] is True
    assert events.json()[0]["delivered_at"] is not None

    evaluated_again = await async_client.post("/v1/watchlist/alerts/evaluate")
    assert evaluated_again.status_code == 200
    assert evaluated_again.json()["triggered"] == []
    send_message.assert_awaited_once()
