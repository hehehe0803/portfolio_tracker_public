#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:-${BACKUP_FILE:-}}"
RESTORE_DATABASE_URL_VALUE="${RESTORE_DATABASE_URL:-${DATABASE_URL:-}}"
DEFAULT_DB="${RESTORE_DB_NAME:-portfolio_restore_test}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 /path/to/backup.dump" >&2
  echo "Set RESTORE_DATABASE_URL or PG* env for the restore target. Default PGDATABASE is ${DEFAULT_DB}." >&2
  exit 2
fi
if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 2
fi
if ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_restore is required" >&2
  exit 1
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required" >&2
  exit 1
fi

db_name_from_url() {
  python - "$1" <<'PY'
import sys
from urllib.parse import urlparse
url = sys.argv[1]
parsed = urlparse(url)
print((parsed.path or '').rsplit('/', 1)[-1])
PY
}

validate_restore_target() {
  local target_url="$1"
  PYTHONPATH="${PYTHONPATH:-}:api" uv run --extra api python - "$target_url" <<'PY'
import sys
from app.db.safety import assert_safe_destructive_database_url
assert_safe_destructive_database_url(sys.argv[1], context="restore drill")
PY
}

if [[ -n "$RESTORE_DATABASE_URL_VALUE" ]]; then
  RESTORE_DB_NAME_DETECTED="$(db_name_from_url "$RESTORE_DATABASE_URL_VALUE")"
  validate_restore_target "$RESTORE_DATABASE_URL_VALUE"
else
  export PGDATABASE="${PGDATABASE:-$DEFAULT_DB}"
  RESTORE_DB_NAME_DETECTED="$PGDATABASE"
  validate_restore_target "postgresql://${PGHOST:-localhost}:${PGPORT:-5432}/${RESTORE_DB_NAME_DETECTED}"
fi

if [[ ! "$RESTORE_DB_NAME_DETECTED" =~ (test|smoke) ]]; then
  echo "Refusing restore: target database name must contain 'test' or 'smoke' (detected '${RESTORE_DB_NAME_DETECTED}')." >&2
  echo "Use RESTORE_DATABASE_URL pointing at a disposable database such as ${DEFAULT_DB}." >&2
  exit 3
fi

pg_restore --list "$BACKUP_FILE" >/dev/null
echo "Backup archive verified: $BACKUP_FILE"

if [[ -n "$RESTORE_DATABASE_URL_VALUE" ]]; then
  echo "Restoring into DATABASE_URL target database '${RESTORE_DB_NAME_DETECTED}'"
  pg_restore --clean --if-exists --no-owner --dbname="$RESTORE_DATABASE_URL_VALUE" "$BACKUP_FILE"
  psql "$RESTORE_DATABASE_URL_VALUE" -v ON_ERROR_STOP=1 -c "select current_database() as restored_database;"
else
  echo "Restoring into PG* target database '${RESTORE_DB_NAME_DETECTED}'"
  pg_restore --clean --if-exists --no-owner --dbname="$PGDATABASE" "$BACKUP_FILE"
  psql -v ON_ERROR_STOP=1 -c "select current_database() as restored_database;"
fi

echo "Restore drill completed safely against '${RESTORE_DB_NAME_DETECTED}'."
