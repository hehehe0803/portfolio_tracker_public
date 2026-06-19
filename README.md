# Portfolio Tracker Monorepo

Local-first portfolio analytics app for a single-user portfolio command center. The repo is organized for separate frontend, API, worker, shared-contract, and infrastructure ownership.

## Start Here

Before implementation work, read:

1. `docs/current_state.md` — current repo state, dirty-worktree cautions, protected-data posture.
2. `docs/product_north_star.md` — product semantics, capital formulas, transfer rules, UI direction.
3. `docs/roadmap.md` — vNext phase order.
4. `docs/implementation_plan.md` — concrete vNext execution sequence.
5. `docs/verification_matrix.md` — required verification gates.
6. Relevant runbooks or fixture references for the task.

No backend or UI implementation should start from the old docs surface.

## Directory Layout

- `frontend/` — Next.js dashboard, portfolio, review, and asset-detail UI.
- `api/` — FastAPI backend, Alembic config, app services, and tests.
- `worker/` — scheduled jobs and queue consumers.
- `shared/` — cross-language schemas, DTOs, and utilities.
- `infra/` — Docker Compose manifests and local runtime configuration.
- `docs/` — current product/roadmap/verification docs, runbooks, and architecture references.
- `data/` — ignored local broker exports, statements, and private account reference material.

## Service Ownership

| Path | Primary Focus |
| --- | --- |
| `frontend/` | Portfolio dashboard, asset detail, review/action UX, client integrations |
| `api/` | Data ingestion, normalization, accounting truth, security, REST APIs |
| `worker/` | Broker sync, freshness polling, alert evaluation, scheduled work |
| `shared/` | Canonical contracts and shared utilities |
| `infra/` | Local Compose runtime and operational scripts |

## Local Setup

- Install toolchains with `asdf install` from `.tool-versions`.
- Install Python dependencies with `uv sync --extra api --extra worker --extra shared --extra dev`.
- Install frontend workspaces with `npm run bootstrap`.
- Copy `.env.example` to `.env` and fill local-only credentials.

Common commands:

```bash
docker compose -f infra/docker-compose.yml up -d
cd api && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
make ci
make feature-check
```

Run Alembic from the repo root only when schema work is explicitly in scope:

```bash
uv run --extra api alembic -c api/Alembic.ini upgrade head
```

## Protected Database Safety

`portfolio_dev` is protected local-production data. Do not run migrations, schema repair, sync scheduler experiments, destructive tests, smoke seeders, or Compose always-on changes against it without first reading `docs/local_prod_db_migration_runbook.md` and creating/verifying a backup when schema changes are involved.

Use only localhost database names that explicitly contain `test` or `smoke` for destructive test helpers. Scripts that reset schema must call `app.db.safety.assert_safe_destructive_database_url(...)` before touching the database.

## Docs And Fixtures

- Hot path: `docs/current_state.md`, `docs/product_north_star.md`, `docs/roadmap.md`, `docs/implementation_plan.md`, `docs/verification_matrix.md`.
- Safety/runtime runbooks: `docs/local_prod_db_migration_runbook.md`, `docs/local_app_compose_runbook.md`.
- Broker export/reference directories are local data, not strategy docs: `data/binance_data/`, `data/xtb_statement_reference/`, `data/aster_data/`, `data/hyperliquid_data/`, and `data/xtb/`.
- Frontend visual references live in `docs/frontend_reference/`.
