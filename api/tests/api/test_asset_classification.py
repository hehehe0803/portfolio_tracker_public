from __future__ import annotations

from intel_fixtures import *  # noqa: F403


async def test_asset_classification_persists_sector_type_themes_and_status(async_client, seeded_asset):
    response = await async_client.put("/v1/intelligence/assets/AAPL/classification", json={"sector": "Technology", "asset_type": "equity", "themes": ["AI", "Quality"], "thesis_status": "core"})
    assert response.status_code == 200
    assert response.json()["sector"] == "Technology"
    assert set(response.json()["themes"]) == {"AI", "Quality"}

    fetched = await async_client.get("/v1/intelligence/assets/AAPL/classification")
    assert fetched.json()["thesis_status"] == "core"


async def test_asset_classification_rejects_unknown_type(async_client, seeded_asset):
    response = await async_client.put("/v1/intelligence/assets/AAPL/classification", json={"asset_type": "moonbag", "themes": [], "thesis_status": "core"})
    assert response.status_code == 400
