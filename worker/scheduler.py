from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from app.config import Settings, settings
from app.services.scheduler_jobs import enqueue_due_jobs as enqueue_scheduler_jobs
from worker.app import get_queue, get_redis_connection


def enqueue_due_jobs(
    *,
    queue=None,
    redis_connection=None,
    now: datetime | None = None,
    settings: Settings = settings,
) -> dict[str, int]:
    redis_connection = redis_connection or get_redis_connection()
    queue = queue or get_queue(connection=redis_connection)
    return enqueue_scheduler_jobs(
        queue=queue,
        redis_connection=redis_connection,
        now=now or datetime.now(UTC),
        app_settings=settings,
    )


def run_forever(poll_interval_seconds: int | None = None) -> None:
    if poll_interval_seconds is None:
        poll_interval_seconds = int(os.getenv("SCHEDULER_POLL_INTERVAL_SECONDS", "30"))
    while True:
        enqueue_due_jobs()
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    run_forever()
