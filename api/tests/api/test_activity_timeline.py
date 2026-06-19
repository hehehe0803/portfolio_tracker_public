from __future__ import annotations

from intel_fixtures import *  # noqa: F403


async def test_activity_timeline_filters_user_and_system_events(async_client, seeded_asset):
    await async_client.post("/v1/intelligence/notes", json={"entity_type": "asset", "entity_id": "AAPL", "content": "watch margins"})
    await async_client.put("/v1/intelligence/assets/AAPL/classification", json={"sector": "Technology", "asset_type": "equity", "themes": ["AI"], "thesis_status": "core"})

    all_events = await async_client.get("/v1/intelligence/activity?limit=10")
    assert all_events.status_code == 200
    assert {event["source"] for event in all_events.json()} >= {"note", "classification"}

    asset_events = await async_client.get("/v1/intelligence/activity?entity_type=asset&entity_id=AAPL")
    assert asset_events.status_code == 200
    assert all(event["entity_id"] == "AAPL" for event in asset_events.json())

    note = await async_client.post(
        "/v1/intelligence/notes",
        json={"entity_type": "portfolio", "entity_id": "default", "content": "lowercase portfolio id"},
    )
    assert note.status_code == 200
    portfolio_events = await async_client.get("/v1/intelligence/activity?entity_type=portfolio&entity_id=default")
    assert portfolio_events.status_code == 200
    assert portfolio_events.json()[0]["entity_id"] == "default"
