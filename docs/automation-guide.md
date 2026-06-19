# Automation Guide

This guide documents the local and CI verification flow for the current repository state.

## Baseline Decisions
- Runtime LTS: Python 3.13.x, Node 24.x.
- Python tooling: `uv` with `pyproject.toml` (PEP 621).
- Worker runtime: RQ (Redis Queue).
- API shape: REST for MVP; GraphQL deferred to Phase 2.
- Frontend rendering: CSR-first for authenticated dashboard; SSR optional for auth/public entry points.
- Deployment: local self-hosted via Docker Compose (TimescaleDB, Redis, MinIO). No cloud hosting.

## Verification Checklist
- Tooling consistency: `.tool-versions`, `pyproject.toml`, and `package.json` engines align with LTS.
- Worker runtime: RQ referenced consistently in docs and dependencies.
- GraphQL deferral: only referenced as Phase 2, not required for MVP tasks.
- Frontend: CSR-first direction is documented and reflected in UX tasks.
- Deployment: all references point to local Docker Compose, no cloud hosting.

## Local Reproduction
- Sync Python deps: `uv sync --extra api --extra worker --extra shared --extra dev --extra binance`
- Install frontend deps: `npm install`
- Export `INSTITUTION_CREDENTIALS_MASTER_KEY` before using `/v1/settings/binance-keys` or running migrations against existing institution rows. Example: `export INSTITUTION_CREDENTIALS_MASTER_KEY=replace-with-32-byte-random-secret`.
- Run the repo baseline: `scripts/verify_all.sh`
- Run the aggregate CI target: `make ci`

## Institution Credential Rotation Runbook
1. Generate and load the current `INSTITUTION_CREDENTIALS_MASTER_KEY` into the API environment before startup.
2. Use `POST /v1/settings/binance-keys` for first-time credential entry; credentials are stored encrypted in `institutions.api_*_encrypted`.
3. Use `POST /v1/settings/binance-keys/rotate` for any planned or emergency key change. Include a short `reason` so the resulting `activity_logs` row explains why the rotation happened.
4. Confirm the API can still sync successfully after rotation (for local verification: `uv run pytest api/tests/security/test_institution_credentials.py -q`).
5. Keep the previous Binance key disabled only after the rotated key has been verified, then remove any stale plaintext values from operator shells/history.
6. If migrating an existing database with plaintext institution credentials, set `INSTITUTION_CREDENTIALS_MASTER_KEY` before running Alembic so the migration can re-encrypt stored values in place.

## CI Pipeline
- Workflow file: `.github/workflows/ci.yml`
- Python environment: `uv` + Python 3.13
- Frontend environment: Node 24 from `.tool-versions`
- Ubuntu runner system packages: `ripgrep` installed via `apt` before verification scripts run
- Commands executed:
  - `make ci`
  - `make ci` runs `scripts/verify_all.sh`, frontend lint, and frontend type-check

## Notes
- `scripts/verify_all.sh` is the source-of-truth repo baseline for toolchain consistency and backend tests.
- Frontend lint uses the ESLint CLI rather than `next lint`, which is deprecated in current Next.js.
