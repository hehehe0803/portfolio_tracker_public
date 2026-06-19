#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups/local-prod}"
DATABASE_URL_VALUE="${DATABASE_URL:-}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump is required" >&2
  exit 1
fi
if ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_restore is required" >&2
  exit 1
fi

TARGET="${BACKUP_DIR}/portfolio_backup_${TIMESTAMP}.dump"

if [[ -n "$DATABASE_URL_VALUE" ]]; then
  echo "Backing up database from DATABASE_URL to ${TARGET}"
  pg_dump --format=custom --file="$TARGET" "$DATABASE_URL_VALUE"
else
  echo "Backing up database from PG* environment to ${TARGET}"
  : "${PGDATABASE:?Set DATABASE_URL or PGDATABASE before running backup}"
  pg_dump --format=custom --file="$TARGET"
fi

pg_restore --list "$TARGET" >/dev/null
chmod 0600 "$TARGET"
echo "Backup verified with pg_restore --list: ${TARGET}"
