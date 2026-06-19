# Worker Service

Background job runner responsible for broker sync tasks, alert dispatch, and scheduled portfolio freshness jobs. Integrates with Redis and external providers under the current vNext hot path. Uses RQ for the worker runtime.

## Local Development
- Install dependencies: `uv sync --extra api --extra worker --extra shared --extra binance --extra dev`
- Start worker: `uv run --extra api --extra worker --extra shared --extra binance rq worker`
- Start lightweight scheduler: `uv run --extra api --extra worker --extra shared --extra binance python -m worker.scheduler`
- Smoke-test job path: `uv run pytest api/tests/worker/test_worker_smoke.py api/tests/worker/test_owned_polling_jobs.py -q`
- For `portfolio_dev`, keep the API scheduler disabled and run the separate worker/scheduler pair instead: `API_SCHEDULER_ENABLED=false`, `STARTUP_DB_INIT_ENABLED=false`, `STARTUP_REPAIRS_ENABLED=false`.
- Recommended local-prod cadence: owned polling every 15 minutes (`OWNED_POLLING_CADENCE_SECONDS=900`), scheduler loop every 30 seconds (`SCHEDULER_POLL_INTERVAL_SECONDS=30`), Binance API delta sync disabled by default and hourly only when deliberately enabled (`BINANCE_AUTO_SYNC_ENABLED=true`, `BINANCE_AUTO_SYNC_CADENCE_SECONDS=3600`), watchlist alerts disabled by default and hourly only when wanted (`WATCHLIST_ALERTS_ENABLED=true`, `WATCHLIST_ALERTS_CADENCE_SECONDS=3600`).

## Entrypoints
- `worker.app:get_queue()` builds the default RQ queue from `REDIS_URL`.
- `worker.jobs:ping()` is the minimal smoke-test job.
- `worker.jobs:run_alert_evaluation()` wraps the async alert evaluation service for RQ workers.
- `worker.jobs:run_owned_refresh()` runs the owned-asset portfolio-state refresh path with single-flight locking.
- `worker.jobs:run_binance_auto_sync()` runs optional Binance auto-sync with credential/degraded-state safeguards.
- `worker.scheduler:run_forever()` enqueues due owned-refresh, broker-sync, and optional watchlist-alert jobs. `SCHEDULER_POLL_INTERVAL_SECONDS` controls its polling loop; default is 30 seconds.

## Docker Compose app profile

The full local app profile runs the worker and scheduler as separate services:

```bash
SECRET_KEY=change_this_to_a_32_byte_random_value docker compose -f infra/docker-compose.yml --profile app up -d
```

The scheduler enqueues due Redis/RQ jobs; the worker executes them. The Compose app profile defaults API startup table creation, startup repairs, and the older in-API scheduler to disabled so container startup does not mutate protected `portfolio_dev`; run Alembic/repairs explicitly via the runbooks when needed. With `OWNED_POLLING_ENABLED=true`, the separate scheduler/worker may append new `position_snapshots` as normal freshness data. Set `OWNED_POLLING_ENABLED=false` for a boot-only smoke check.
