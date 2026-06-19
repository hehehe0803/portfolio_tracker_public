from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import create_application


@pytest.fixture
def app() -> FastAPI:
    probe_state = {"calls": 0}

    async def readiness_probe() -> None:
        probe_state["calls"] += 1

    application = create_application(
        run_startup_db_init=False,
        run_startup_repairs=False,
        run_scheduler=False,
        readiness_check=readiness_probe,
    )
    application.state.readiness_probe_state = probe_state
    return application


@pytest_asyncio.fixture
async def async_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
