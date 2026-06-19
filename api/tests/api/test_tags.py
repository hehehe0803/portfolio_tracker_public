from __future__ import annotations

from intel_fixtures import *  # noqa: F403


async def test_tags_crud_and_asset_assignment(async_client, seeded_asset):
    created = await async_client.post("/v1/intelligence/tags", json={"name": "Quality", "color": "#22c55e", "icon": "star"})
    assert created.status_code == 200
    tag_id = created.json()["id"]

    assert (await async_client.get("/v1/intelligence/tags")).json()[0]["name"] == "Quality"
    patched = await async_client.patch(f"/v1/intelligence/tags/{tag_id}", json={"name": "Compounder", "color": "#10b981"})
    assert patched.json()["name"] == "Compounder"

    assigned = await async_client.post(f"/v1/intelligence/assets/AAPL/tags/{tag_id}")
    assert assigned.status_code == 200
    classification = await async_client.get("/v1/intelligence/assets/AAPL/classification")
    assert classification.json()["tags"][0]["name"] == "Compounder"

    removed = await async_client.delete(f"/v1/intelligence/assets/AAPL/tags/{tag_id}")
    assert removed.status_code == 200
