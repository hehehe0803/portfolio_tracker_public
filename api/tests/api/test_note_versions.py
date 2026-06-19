from __future__ import annotations

from intel_fixtures import *  # noqa: F403


async def test_note_versions_preserve_create_update_delete_history(async_client):
    created = await async_client.post("/v1/intelligence/notes", json={"entity_type": "asset", "entity_id": "aapl", "content": "v1"})
    note_id = created.json()["id"]
    await async_client.patch(f"/v1/intelligence/notes/{note_id}", json={"content": "v2"})
    await async_client.delete(f"/v1/intelligence/notes/{note_id}")

    versions = await async_client.get(f"/v1/intelligence/notes/{note_id}/versions")
    assert versions.status_code == 200
    assert [(v["version"], v["operation"], v["content"]) for v in versions.json()] == [(1, "create", "v1"), (2, "update", "v2"), (3, "delete", "v2")]
