# Repository Guidelines

## Project Structure

Implementation lives in three services:

- `frontend/` — Next.js UI.
- `api/` — FastAPI backend and Alembic config.
- `worker/` — scheduled jobs and queue consumers.

Shared contracts and utilities belong in `shared/`. Infrastructure manifests and runtime scripts belong in `infra/` and `scripts/`. Long-form product, safety, and reference material belongs in `docs/`. Private broker exports, statements, and account reference files belong in ignored `data/`.

## Agent Orientation

Before making changes, read the hot path in this order:

1. [`README.md`](README.md)
2. [`docs/current_state.md`](docs/current_state.md)
3. [`docs/product_north_star.md`](docs/product_north_star.md)
4. [`docs/roadmap.md`](docs/roadmap.md)
5. [`docs/implementation_plan.md`](docs/implementation_plan.md)
6. [`docs/verification_matrix.md`](docs/verification_matrix.md)
7. Relevant runbook or fixture reference for the task

Claude Code users should also load [`CLAUDE.md`](CLAUDE.md) when available for local behavioral conventions.

The old project-brain docs are no longer part of normal orientation. Do not add new backend or UI work from stale checklists, dated premortems, or old roadmap walls.

## Current Safety Rules

- `portfolio_dev` is protected local-production data, not disposable dev/test state.
- Do not run migrations, schema repair, broker sync experiments, destructive tests, smoke seeders, or Compose always-on changes against `portfolio_dev` without following [`docs/local_prod_db_migration_runbook.md`](docs/local_prod_db_migration_runbook.md).
- Destructive tests and smoke scripts must use explicit localhost database names containing `test` or `smoke`.
- Private broker export/data directories belong under ignored `data/`; do not move them back into `docs/` or service fixtures unless sanitized and explicitly approved for version control.
- Unrelated dirty worktree changes must not be reverted.

## vNext Scope Guardrails

The vNext order is:

1. Trusted money numbers.
2. Structure and distribution analytics.
3. Dashboard and asset detail UI on trusted contracts.
4. Later decision-support features.

No backend or UI implementation should begin until the current docs hot path is clean enough to guide agents.

## Build, Test, And Development Commands

```bash
docker compose -f infra/docker-compose.yml up -d
cd api && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
make ci
make feature-check
```

`make feature-check` is the preferred broad feature gate before push for backend, frontend, migration, scheduler/sync, or e2e-sensitive work.

## Runtime And Tooling

Any command that streams logs, opens an interactive CLI, or is expected to hang until interrupted must run inside a named tmux session, for example:

```bash
tmux new-session -As api_server 'cd api && uv run uvicorn app.main:app --reload'
```

When monitoring long-running work, prefer:

```bash
tmux capture-pane -p -t <session> | tail -n 200
```

## Coding Style

- Frontend: Prettier and ESLint defaults, 2-space indentation, camelCase functions, PascalCase React components.
- Backend: `uvx ruff format`, `uvx ruff check`, `uvx pyright`, snake_case modules.
- Shared contracts: keep schema names stable and version REST routes under `/v1/`.

## Testing Guidelines

- Frontend tests live near the UI and under `frontend/__tests__/`; Playwright smoke tests live under `frontend/e2e/`.
- Backend tests live under `api/tests/` and use `uv run pytest`.
- Broker adapters should use synthetic tracked fixtures for normal tests. Private regression fixtures may live under `data/` and tests that depend on them must skip clearly when absent.
- Critical coverage areas: ingestion, reconciliation, DB safety, sync, pricing, alerts, accounting truth, and dashboard trust states.

## External Documentation Lookup

Use `ctx7` for current library/framework/SDK/API/CLI/cloud documentation whenever coding against external technology. Resolve first with:

```bash
npx ctx7@latest library <name> "<user's question>"
```

Then fetch docs with:

```bash
npx ctx7@latest docs <libraryId> "<user's question>"
```

Do not use Context7 for pure docs cleanup, refactoring, business-logic debugging, or general programming concepts.

## Commit And PR Guidelines

Keep commits small, imperative, and scoped. PRs need a concise summary, verification output, screenshots or traces for UI/API changes, and explicit notes for schema, infrastructure, secrets, or runbook changes.
