# Local-Prod DB Migration Runbook

## Status
Accepted operating policy as of 2026-04-30 after the local `portfolio_dev` database was confirmed to be both the developer database and the current local production database.

## Why this exists

This project is hosted on a local machine, so **dev and prod are currently the same durable database**. The `portfolio_dev` database contains real portfolio data and must be treated as protected state, not disposable test state.

Previous failures showed that a dev/test process can accidentally wipe useful portfolio data when it points destructive setup at `portfolio_dev`. Any migration, destructive test helper, or always-on deployment change must therefore start from the assumption that `portfolio_dev` is local-prod data.

## Local-prod rule

- `portfolio_dev` is protected.
- Automated tests must use explicitly named test/smoke databases such as `portfolio_backend_test` or `portfolio_frontend_auth_smoke`.
- No script may run `drop_all`, `create_all`, `DROP DATABASE`, or destructive fixture setup against `portfolio_dev`.
- Feature work that touches migrations, ORM models, import/sync, or always-on deployment must perform a read-only DB alignment check first.
- Before applying migrations to `portfolio_dev`, create and verify a backup.

## Required pre-migration backup

Preferred helper:

```bash
DATABASE_URL="postgresql://USER@HOST:PORT/portfolio_dev" \
  BACKUP_DIR=backups/local-prod \
  scripts/backup_local_prod_db.sh
```

The helper accepts either `DATABASE_URL` or standard `PG*` variables, writes a custom-format dump, and verifies it immediately with `pg_restore --list`. It does not require or embed any password; use `.pgpass`, `PGPASSWORD`, or your shell secret manager outside the script.

Manual equivalent:

Use a timestamped custom-format dump:

```bash
mkdir -p backups
PGPASSWORD=[REDACTED] pg_dump \
  -h 127.0.0.1 \
  -p 5433 \
  -U portfolio \
  -d portfolio_dev \
  --format=custom \
  --file="backups/portfolio_dev_pre_migration_$(date +%Y%m%d_%H%M%S).dump"
```

Verify the dump is readable:

```bash
pg_restore --list backups/portfolio_dev_pre_migration_YYYYMMDD_HHMMSS.dump >/tmp/portfolio_dev_restore_list.txt
wc -l /tmp/portfolio_dev_restore_list.txt
```

The backup file may contain sensitive local portfolio data and must not be committed.

## Read-only alignment checks

Before running `alembic upgrade head`, capture:

```bash
PGPASSWORD=[REDACTED] psql -h 127.0.0.1 -p 5433 -U portfolio -d portfolio_dev -Atqc "select version_num from alembic_version;"
PGPASSWORD=[REDACTED] psql -h 127.0.0.1 -p 5433 -U portfolio -d portfolio_dev -Atqc "select 'transactions', count(*) from transactions; select 'assets', count(*) from assets; select 'position_snapshots', count(*) from position_snapshots;"
PGPASSWORD=[REDACTED] psql -h 127.0.0.1 -p 5433 -U portfolio -d portfolio_dev -Atqc "select 'hypertables', count(*) from timescaledb_information.hypertables; select 'continuous_aggs', count(*) from timescaledb_information.continuous_aggregates;"
```

Also compare:

- `api/migrations/versions/*.py`
- `api/app/db/models.py`
- tables/columns in live DB
- current app env variables needed by migrations and services

## ELI5: the three Alembic repair choices

Alembic is the database's **sticker chart**. Each migration is a sticker saying “this schema change has been applied.” The live DB stores the latest sticker in `alembic_version`.

### 1. Run missing migrations

Use when: the DB is truly missing the schema changes.

ELI5: “Do the homework pages that have not been done yet.”

Example:

```bash
uv run --extra api alembic -c api/Alembic.ini upgrade head
```

This is the normal path when the live DB is behind and the missing migrations are safe.

### 2. Stamp the DB

Use when: the schema changes already exist, but the sticker chart is wrong.

ELI5: “The homework was already done manually, so just put the sticker on the chart.”

Example:

```bash
uv run --extra api alembic -c api/Alembic.ini stamp sec001_institution_creds
```

Danger: stamping without checking schema can make Alembic believe columns/tables exist when they do not.

### 3. Custom repair migration

Use when: the live DB is in an in-between weird state that normal migration or stamping cannot safely describe.

ELI5: “The homework page is half-erased and half-done, so write a special cleanup page that fixes only what is wrong.”

This is safest when:

- some columns already exist but not all
- old/manual schema edits drifted from migration files
- data needs careful transformation before dropping old columns
- a migration partly failed

## Credential master key: what it is

`INSTITUTION_CREDENTIALS_MASTER_KEY` is the local secret used to encrypt/decrypt broker API credentials stored in the database.

ELI5: it is the **locker key**. The database can hold locked boxes (`api_key_encrypted`, `api_secret_encrypted`), but the app needs the locker key to open them when syncing with Binance.

Important rules:

- Do not commit this key.
- Do not paste it into docs or chat.
- Keep the same key across app restarts; changing it makes previously encrypted credentials unreadable.
- If the key is lost, broker credentials should be re-entered/rotated through the app.
- Migrations that convert existing plaintext credentials may require this key if plaintext credentials are present.

Current local-prod migration note from 2026-04-30: no plaintext institution credentials were present, so the security migration could run without encrypting existing credential values. The app will still require `INSTITUTION_CREDENTIALS_MASTER_KEY` before storing or using encrypted broker credentials.

## 2026-04-30 migration execution record

Pre-check:

- `portfolio_dev` had real data: 454 transactions, 98 assets, 171 position snapshots, 1 import artifact.
- Alembic version before migration: `backend_foundation_tables`.
- Timescale extension existed, but there were 0 hypertables and 0 continuous aggregates.
- `institutions` had 1 row and 0 rows with plaintext API key/secret values.

Backup created and verified:

- `backups/portfolio_dev_pre_migration_20260430_152325.dump`
- `pg_restore --list` succeeded with 176 listed items.

Migration applied:

```bash
uv run --extra api alembic -c api/Alembic.ini upgrade head
```

Post-check:

- Alembic version after migration: `sec001_institution_creds`.
- Data counts preserved: 454 transactions, 98 assets, 171 position snapshots, 1 import artifact.
- Timescale now reports 2 hypertables and 8 continuous aggregates.
- `position_snapshots` and `benchmark_quotes` primary keys are now `(id, captured_at)`.
- `institutions` now uses encrypted credential columns: `api_key_encrypted`, `api_secret_encrypted`, `credentials_updated_at`, `credential_rotation_count`.

## Restore reminder

If a migration corrupts local-prod data, stop the app first and restore into a new database for inspection before overwriting `portfolio_dev`. Prefer proving the restore path into `portfolio_restore_test` before touching the protected DB.

Preferred restore-drill helper:

```bash
RESTORE_DATABASE_URL="postgresql://USER@HOST:PORT/portfolio_restore_test" \
  scripts/restore_drill_local_prod_db.sh backups/local-prod/portfolio_backup_YYYYMMDDTHHMMSSZ.dump
```

Safety rules in the helper:

- It verifies the archive with `pg_restore --list` before restoring.
- It refuses restore targets unless the target database name contains `test` or `smoke`.
- If no `RESTORE_DATABASE_URL` is set, the default PG target database name is `portfolio_restore_test`.
- It does not embed passwords or secrets.

Manual outline:

```bash
createdb -h 127.0.0.1 -p 5433 -U portfolio portfolio_restore_test
pg_restore -h 127.0.0.1 -p 5433 -U portfolio -d portfolio_restore_test backups/portfolio_dev_pre_migration_YYYYMMDD_HHMMSS.dump
```

Only replace `portfolio_dev` after verifying the restored DB contains the expected row counts and schema.
