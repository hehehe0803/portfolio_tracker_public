#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# Institution credentials are encrypted in the DB and only need the master key at
# runtime. Older local setups may have that key in api/.env because local Python
# runs load api/.env directly; Docker Compose does not. Load it here without
# requiring the operator to duplicate the key into the repo-root .env.
if [[ -z "${INSTITUTION_CREDENTIALS_MASTER_KEY:-}" && -f api/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source api/.env
  set +a
fi

: "${SECRET_KEY:?Set SECRET_KEY in $ROOT_DIR/.env before starting the app profile}"

export POSTGRES_PORT="${POSTGRES_PORT_OVERRIDE:-5433}"
export REDIS_PORT="${REDIS_PORT_OVERRIDE:-6380}"
export DATABASE_URL="${COMPOSE_DATABASE_URL:-postgresql+asyncpg://portfolio:portfolio@timescale:5432/portfolio_dev}"
export REDIS_URL="${COMPOSE_REDIS_URL:-redis://redis:6379/0}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://100.108.242.71:8000}"
export EXTRA_CORS_ORIGINS="${EXTRA_CORS_ORIGINS:-[\"http://localhost:3000\",\"http://100.108.242.71:3000\"]}"

exec docker compose -f infra/docker-compose.yml --profile app up -d "$@"
