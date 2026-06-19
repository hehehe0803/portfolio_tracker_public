# Local app Docker Compose runbook

This runbook covers the `backlog-compose-001` app profile for running the full portfolio tracker locally: TimescaleDB, Redis, MinIO, FastAPI API, Next.js frontend, RQ worker, and lightweight scheduler.

## Safety rules

- `portfolio_dev` is protected local-production data.
- Do not run destructive test provisioning against `portfolio_dev`.
- Compose app startup does not run Alembic migrations and does not drop/recreate tables.
- The app profile defaults `STARTUP_DB_INIT_ENABLED=false`, `STARTUP_REPAIRS_ENABLED=false`, and `API_SCHEDULER_ENABLED=false`, so API container startup does not run SQLAlchemy table creation, legacy startup repairs, or the older in-API scheduler against protected `portfolio_dev`.
- With `OWNED_POLLING_ENABLED=true`, the separate scheduler/worker can append new `position_snapshots` and refresh Timescale continuous aggregates as normal freshness data. This is expected and not a reset.
- `BINANCE_AUTO_SYNC_ENABLED=false` is the safer default. Enable it only after encrypted Binance credentials are configured, `INSTITUTION_CREDENTIALS_MASTER_KEY` is present in the API/worker/scheduler container runtime env, decrypt-only verification passes, and the operator accepts API delta-sync coverage limits.
- Take a `pg_dump --format=custom` backup before migrations or schema-heavy changes. See `docs/local_prod_db_migration_runbook.md`.

## Start data services only

This preserves the previous infra-only workflow:

```bash
docker compose -f infra/docker-compose.yml up -d
```

This starts only:

- `timescale`
- `redis`
- `minio`

Note: the Compose Redis host port defaults to `6380` to avoid conflicts with an existing local Redis on `6379`. Services inside Compose still use the internal Redis URL `redis://redis:6379/0`.

## Start full app profile safely

Use this when the app should stay available from the browser/phone and the worker/scheduler should keep portfolio freshness alive. Set the real protected DB connection string in your shell or gitignored env file; do not paste real secrets into docs or chat.

```bash
export DATABASE_URL="$PORTFOLIO_DEV_DATABASE_URL"
export SECRET_KEY=change_this_to_a_32_byte_random_value
export STARTUP_DB_INIT_ENABLED=false
export STARTUP_REPAIRS_ENABLED=false
export API_SCHEDULER_ENABLED=false
export OWNED_POLLING_ENABLED=true
export OWNED_POLLING_CADENCE_SECONDS=900
export BINANCE_AUTO_SYNC_ENABLED=false
export BINANCE_AUTO_SYNC_CADENCE_SECONDS=3600
export INSTITUTION_CREDENTIALS_MASTER_KEY=use_the_existing_gitignored_master_key
export WATCHLIST_ALERTS_ENABLED=false
export WATCHLIST_ALERTS_CADENCE_SECONDS=3600
export SCHEDULER_POLL_INTERVAL_SECONDS=30
export REDIS_URL=redis://redis:6379/0
export NEXT_PUBLIC_API_URL=http://100.108.242.71:8000
export EXTRA_CORS_ORIGINS='["http://localhost:3000","http://100.108.242.71:3000"]'
docker compose -f infra/docker-compose.yml --profile app up -d --build
```

This adds:

- `api` on `${API_PORT:-8000}`
- `frontend` on `${FRONTEND_PORT:-3000}`
- `worker`
- `scheduler`

If local ports are already in use, override only the host ports:

```bash
SECRET_KEY=change_this_to_a_32_byte_random_value \
API_PORT=8010 FRONTEND_PORT=3010 REDIS_PORT=6380 \
NEXT_PUBLIC_API_URL=http://localhost:8010 \
docker compose -f infra/docker-compose.yml --profile app up -d --build
```

For Tailscale/phone access, set `NEXT_PUBLIC_API_URL` to the reachable API origin before building the frontend image, for example:

```bash
SECRET_KEY=change_this_to_a_32_byte_random_value \
NEXT_PUBLIC_API_URL=http://100.108.242.71:8000 \
docker compose -f infra/docker-compose.yml --profile app up -d --build frontend
```

## Worker/scheduler responsibilities and cadence

The API scheduler is intentionally disabled for UAT/local-prod (`API_SCHEDULER_ENABLED=false`). The separate `scheduler` container should enqueue jobs into Redis/RQ, and the separate `worker` container should execute them. This keeps periodic mutation paths observable and stoppable without restarting the API.

Recommended local-prod cadence:

- Owned portfolio polling: enabled, every 15 minutes (`OWNED_POLLING_ENABLED=true`, `OWNED_POLLING_CADENCE_SECONDS=900`). This updates current prices, appends/upserts `position_snapshots`, and refreshes aggregates. It should not reset `transactions`, `assets`, or `import_artifacts`.
- Binance API delta sync: disabled by default; if enabled, run hourly (`BINANCE_AUTO_SYNC_ENABLED=true`, `BINANCE_AUTO_SYNC_CADENCE_SECONDS=3600`). Current API delta coverage is deposits, withdrawals, convert, Simple Earn, and C2C/P2P; full historical truth still depends on export imports for spot trades/internal transfers/dividends/dust.
- Watchlist target alerts: disabled by default for local-prod (`WATCHLIST_ALERTS_ENABLED=false`) and safe to enable hourly (`WATCHLIST_ALERTS_CADENCE_SECONDS=3600`) when the user wants Telegram target pings. Missing provider prices must not trigger alerts, and duplicate alerts are suppressed by stored `watchlist_target_alerts` rows.
- Scheduler loop: check due jobs every 30 seconds (`SCHEDULER_POLL_INTERVAL_SECONDS=30`). Catch-up is bounded by app settings so a long outage cannot enqueue an unbounded backlog.

To pause all periodic portfolio mutations while leaving the UI/API up:

```bash
docker compose -f infra/docker-compose.yml --profile app stop worker scheduler
```

To resume:

```bash
docker compose -f infra/docker-compose.yml --profile app up -d worker scheduler
```

To disable owned polling on the next app-profile recreate:

```bash
OWNED_POLLING_ENABLED=false docker compose -f infra/docker-compose.yml --profile app up -d --force-recreate scheduler worker
```

To enable hourly Binance auto-sync on the next app-profile recreate, first verify encrypted credentials in the app and then run:

```bash
BINANCE_AUTO_SYNC_ENABLED=true BINANCE_AUTO_SYNC_CADENCE_SECONDS=3600 \
docker compose -f infra/docker-compose.yml --profile app up -d --force-recreate scheduler worker
```

Important: `api/.env` is loaded by local Python processes, but Docker Compose containers only receive variables explicitly passed in `infra/docker-compose.yml` or exported by `scripts/start_local_app_compose.sh`. Encrypted Binance credentials in the DB are unusable inside containers unless `INSTITUTION_CREDENTIALS_MASTER_KEY` reaches `api`, `worker`, and `scheduler`. Do not solve this by baking `.env` files into Docker images.

No-secret decrypt-only probe after app container recreate:

```bash
docker exec -i portfolio-api uv run --extra api --extra binance python - <<'PY'
import asyncio
from sqlalchemy import select
from app.db.session import async_session_factory
from app.db.models import Institution

async def main():
    async with async_session_factory() as db:
        inst = (await db.execute(select(Institution).where(Institution.name == "binance"))).scalar_one_or_none()
        result = {
            "institution_row_present": bool(inst),
            "has_encrypted_key": bool(inst and inst.api_key_encrypted),
            "has_encrypted_secret": bool(inst and inst.api_secret_encrypted),
            "decrypt_ok": False,
            "key_present": False,
            "secret_present": False,
        }
        if inst:
            creds = inst.get_api_credentials()
            result.update(
                decrypt_ok=True,
                key_present=bool(creds.get("api_key")),
                secret_present=bool(creds.get("api_secret")),
            )
        print(result)

asyncio.run(main())
PY
```

To enable hourly watchlist target alert evaluation on the next app-profile recreate:

```bash
WATCHLIST_ALERTS_ENABLED=true WATCHLIST_ALERTS_CADENCE_SECONDS=3600 \
docker compose -f infra/docker-compose.yml --profile app up -d --force-recreate scheduler worker
```

## Health and status checks

```bash
curl -fsS http://127.0.0.1:${API_PORT:-8000}/health
curl -fsS http://127.0.0.1:${API_PORT:-8000}/readiness
curl -fsSI http://127.0.0.1:${FRONTEND_PORT:-3000}/login
```

Worker/scheduler status:

```bash
docker compose -f infra/docker-compose.yml --profile app ps
docker compose -f infra/docker-compose.yml --profile app logs --tail=100 worker scheduler
```

Authenticated API users can also check freshness through `/v1/sync/freshness`.

For protected DB evidence, query row counts before and after a smoke window. `position_snapshots` may increase; `transactions`, `assets`, and `import_artifacts` must not reset.

```bash
psql "$PORTFOLIO_DEV_PSQL_URL" -Atqc "
select 'transactions', count(*) from transactions;
select 'assets', count(*) from assets;
select 'position_snapshots', count(*) from position_snapshots;
select 'import_artifacts', count(*) from import_artifacts;
select source, status, created_at, left(message, 120)
from activity_logs
where source in ('owned_polling.refresh', 'sync.binance_auto', 'watchlist_alert')
order by created_at desc
limit 10;
"
```

## Stop app services without deleting data

```bash
docker compose -f infra/docker-compose.yml --profile app stop frontend api worker scheduler
```

Do not use `docker compose down -v` unless you intentionally want to delete local data volumes.

## Verification commands

```bash
make compose-check
SECRET_KEY=change_this_to_a_32_byte_random_value docker compose -f infra/docker-compose.yml --profile app config --quiet
SECRET_KEY=change_this_to_a_32_byte_random_value docker compose -f infra/docker-compose.yml --profile app up -d --build
curl -fsS http://127.0.0.1:${API_PORT:-8000}/health
curl -fsS http://127.0.0.1:${API_PORT:-8000}/readiness
curl -fsSI http://127.0.0.1:${FRONTEND_PORT:-3000}/login
make feature-check
```
