from __future__ import annotations

from intel_fixtures import *  # noqa: F403


async def test_notes_crud_and_list(async_client):
    created = await async_client.post("/v1/intelligence/notes", json={"entity_type": "portfolio", "entity_id": "default", "content": "rebalance plan"})
    assert created.status_code == 200
    note_id = created.json()["id"]

    updated = await async_client.patch(f"/v1/intelligence/notes/{note_id}", json={"content": "updated plan"})
    assert updated.status_code == 200
    assert updated.json()["content"] == "updated plan"

    listed = await async_client.get("/v1/intelligence/notes?entity_type=portfolio&entity_id=default")
    assert listed.status_code == 200
    assert [n["content"] for n in listed.json()] == ["updated plan"]

    deleted = await async_client.delete(f"/v1/intelligence/notes/{note_id}")
    assert deleted.status_code == 200
    assert (await async_client.get("/v1/intelligence/notes?entity_type=portfolio&entity_id=default")).json() == []
