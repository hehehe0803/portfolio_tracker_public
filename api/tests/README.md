# API Test Suite

This directory contains deterministic, fixture-driven tests for ingestion, normalization, reconciliation, and valuation.

## How To Run
- All tests: `uv run pytest api/tests`
- Live-only tests (optional later): `uv run pytest -m live api/tests`

## Database Safety (read before running destructive fixtures)
- Never run schema-reset helpers against `portfolio_dev`.
- Any fixture or smoke script that uses `drop_all()` / `create_all()` must target a localhost database whose name explicitly contains `test` or `smoke`.
- Use `TEST_DATABASE_URL` for destructive auth/API fixtures and verify it does not point at `portfolio_dev`, `postgres`, `template0`, or `template1`.
- Use `SCHEMA_TEST_DATABASE_URL` when schema-alignment tests need a safe base URL before they create a disposable database.
- Current guarded smoke DB default: `portfolio_frontend_auth_smoke` via `frontend/e2e/start-auth-smoke-backend.sh`.
- Reusable guard: `from app.db.safety import assert_safe_destructive_database_url`.

## Fixtures Layout
- `api/tests/fixtures/expected/` expected normalized outputs and totals
- `api/tests/fixtures/prices/` pinned price snapshots
- `api/tests/fixtures/binance/` raw Binance API fixtures
