#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${AUTH_SMOKE_DB_NAME:-portfolio_frontend_auth_smoke}"
PGHOST="${AUTH_SMOKE_PGHOST:-127.0.0.1}"
PGPORT="${AUTH_SMOKE_PGPORT:-5433}"
PGUSER="${AUTH_SMOKE_PGUSER:-portfolio}"
PGPASSWORD="${AUTH_SMOKE_PGPASSWORD:-portfolio}"
AUTH_SMOKE_DATABASE_URL="postgresql+asyncpg://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${DB_NAME}"
API_PORT="${AUTH_SMOKE_API_PORT:-8001}"
FRONTEND_PORT="${PORT:-3000}"
FRONTEND_ORIGIN="${PLAYWRIGHT_BASE_URL:-http://localhost:${FRONTEND_PORT}}"

export DATABASE_URL="$AUTH_SMOKE_DATABASE_URL"
export AUTH_SMOKE_DATABASE_URL
export REDIS_URL="${AUTH_SMOKE_REDIS_URL:-redis://127.0.0.1:6379/0}"
export EXTRA_CORS_ORIGINS="${EXTRA_CORS_ORIGINS:-[\"${FRONTEND_ORIGIN}\",\"http://localhost:${FRONTEND_PORT}\",\"http://127.0.0.1:${FRONTEND_PORT}\"]}"
# The auth-smoke suite performs several legitimate UI logins against one
# disposable backend in quick succession. Keep production defaults in app code,
# but relax the smoke backend limit so additional e2e specs do not trip 429s.
export RATE_LIMIT_AUTH_REQUESTS="${AUTH_SMOKE_RATE_LIMIT_AUTH_REQUESTS:-25}"
export ENVIRONMENT="development"
export DEBUG="false"
export PYTHONPATH="${PYTHONPATH:-}:../api"

uv run --extra api --extra shared python ../api/scripts/provision_test_database.py --database-url "$AUTH_SMOKE_DATABASE_URL" --recreate
uv run --extra api --extra shared --extra worker --extra binance python e2e/seed-auth-smoke-backend.py
exec uv run --extra api --extra shared --extra worker --extra binance uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port "$API_PORT"
