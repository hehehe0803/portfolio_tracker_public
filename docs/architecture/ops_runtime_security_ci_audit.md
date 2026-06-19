# Ops Runtime Security CI Audit

Status: audit-only.
Last updated: 2026-06-18.
Worker: sprint-9a-ops-audit.

## Scope

This audit covers Sprint 9A ops/runtime/security/CI readiness from read-only
context. It did not run Docker Compose, runtime services, CI, migrations,
schema repair, destructive tests, or protected DB operations.

Read context:

- `README.md`, `AGENTS.md`, and the current hot-path docs.
- `docs/superpowers/specs/2026-06-17-major-revamp-roadmap.md`.
- `docs/superpowers/plans/2026-06-17-reconciliation-mvp-plan.md`.
- `docs/local_prod_db_migration_runbook.md`.
- `docs/local_app_compose_runbook.md`.
- `infra/`, `worker/`, `scripts/`, `Makefile`, `.env.example`, and `.github/`.

## Overall Readiness

Result: `DONE_WITH_CONCERNS`.

The repo has a coherent local app profile and safety posture for a protected
local-production database. The main readiness gaps are operational evidence and
observability, not missing safety intent:

- Local restart behavior is documented but was not live-verified in this audit.
- Worker/scheduler containers have healthchecks, but those checks do not prove
  that scheduled jobs are being enqueued and completed successfully over time.
- Compose/runbook defaults intentionally allow owned polling against
  `portfolio_dev`; boot-only smoke checks must explicitly disable it.
- CI covers backend, frontend, shared-contract, and Playwright smoke paths, but
  the Compose app-profile structural check is not wired into the GitHub Actions
  workflow.
- Fresh-session readiness still depends on tests skipping cleanly when ignored
  private data under `data/` is absent.

## Deployment Primer For This App

This section is intentionally educational. The app is currently local-first, but
deployment may be worthwhile if the hosted cost and maintenance burden can stay
near zero.

Vocabulary:

- Frontend hosting: serves the Next.js UI, static assets, and any Next.js
  server/serverless routes.
- Backend API hosting: runs the FastAPI service. This repo currently has a
  separate API, so frontend hosting alone is not the full app.
- Database hosting: runs Postgres/Timescale-compatible storage for portfolio
  data. This is the most sensitive hosted component because it contains private
  financial records.
- Worker/scheduler hosting: runs background jobs such as sync, freshness,
  imports, alerts, or future automation. These jobs are not the same as serving
  a web page.
- Object/file storage: stores imports, statements, previews, and private broker
  evidence if hosted. This must be handled carefully or kept local.
- Secrets management: stores API keys, DB URLs, encryption keys, and broker
  credentials outside the repo.

Current hosted-platform facts checked on 2026-06-18:

- Vercel Hobby is advertised as free for personal projects and has first-class
  Next.js deployment, CI/CD, environment variables, CDN, and serverless compute.
  It is a strong candidate for the frontend.
- Vercel is not a drop-in replacement for this repo's long-running FastAPI,
  RQ worker, scheduler, local Compose stack, or XTB browser automation.
- Neon has a $0 Free plan for serverless Postgres with small storage/compute
  quotas and scale-to-zero behavior. It is a plausible hosted Postgres candidate
  for a hobby deployment if the database stays small.
- Current official pricing references:
  - Vercel pricing: `https://vercel.com/pricing`
  - Neon pricing: `https://neon.com/pricing`
- Current notable free-tier limits from those pages:
  - Vercel Hobby: free forever; includes CDN, CI/CD, WAF, DDoS mitigation, and
    limited serverless compute such as 4 active CPU hours and 1M function
    invocations per month.
  - Neon Free: $0; includes 100 CU-hours monthly per project, 0.5 GB storage per
    project, and compute that scales to zero after inactivity.
- Free hosted tiers are quota-bound. They are useful for demos, preview apps,
  and low-traffic personal use, but they are not the same as production
  guarantees, reliable always-on workers, long retention, or deep backups.

Recommended deployment framing:

- Treat Vercel as a frontend/preview deployment candidate first.
- Treat hosted Postgres such as Neon or Supabase as a separate database decision
  that requires privacy, backup, restore, extension, and cost review.
- Keep `portfolio_dev` local until there is a deliberate hosted-data migration
  plan. Do not casually upload private broker data to a free database.
- Keep XTB browser automation local unless a later runbook proves credentials,
  MFA, session storage, downloads, and private statements can be handled safely.
- Keep background workers local or on a platform designed for scheduled workers
  until their required reliability and cost are understood.

Likely deployment options:

| Option | Monthly cost target | What it gives | Tradeoffs |
| --- | --- | --- | --- |
| Local-only | 0 USD | Maximum privacy and full control of FastAPI, worker, scheduler, DB, and local files. | No remote access, no hosted preview, restart/backup burden stays local. |
| Vercel frontend only | 0 USD if Hobby quotas fit | Easy UI preview and sharing; good for dashboard review screenshots and mobile testing. | Still needs local or separate API/DB; private data should not be exposed accidentally. |
| Vercel frontend + free hosted Postgres | 0 USD if quotas fit | Remote app can read/write a small hosted DB. | Requires data privacy decision, migrations, backups, secrets, API hosting shape, and quota monitoring. |
| Full hosted split | Usually not guaranteed 0 USD | Frontend, API, DB, workers, storage, and scheduler all hosted. | More reliable remote access, but more DevOps surface and likely paid components for always-on workers/backups. |

Decision questions before deployment work:

- Is the goal private personal remote access, public demo, mobile review from
  outside the LAN, or CI preview only?
- Can private financial data leave the local machine?
- Is read-only dashboard access enough for a first hosted version?
- Can imports/XTB automation remain local while the hosted UI only displays
  sanitized or manually synced data?
- What is acceptable if a free database sleeps, pauses, hits quotas, or loses
  long restore history?
- Is zero monthly cost more important than always-on reliability?

Recommendation:

- Start with a deployment discovery ticket, not direct deployment.
- First target should be a Vercel frontend preview that uses mock/sanitized data
  or a local API tunnel only for manual testing.
- Second target, only after approval, should compare hosted Postgres options for
  private-data risk, free quota, backup/restore story, Timescale compatibility,
  and migration workflow.
- Do not migrate `portfolio_dev` or broker evidence to hosted infrastructure as
  part of a UI/ops audit.

## Cloud Data Volume And Cost Sizing

Before choosing a hosted database, estimate data volume from the app's actual
write paths. Cost risk is not mainly the number of pages in the UI; it is the
number of time-series rows, retained raw import files, indexes, and future
reconciliation evidence.

Primary database growth drivers in the current schema:

| Data class | Current table | Growth pattern | Cost risk |
| --- | --- | --- | --- |
| Current/history holdings snapshots | `position_snapshots` | `tracked_holdings * snapshots_per_day * retained_days` | Highest if 15-minute polling is retained indefinitely. |
| Benchmark/market quote snapshots | `benchmark_quotes` | `tracked_symbols * snapshots_per_day * retained_days` | Medium; can grow quickly with many symbols. |
| Broker/import transactions | `transactions` | Import volume plus later broker sync deltas | Usually manageable unless raw sync duplicates leak in. |
| Uploaded statements/previews | `import_artifacts` | Number and size of uploaded statements/PDFs plus preview JSON | High privacy risk and potentially high storage if raw files are hosted. |
| Activity/audit logs | `activity_logs` | Scheduler, imports, reviews, sync, decisions | Medium over long retention; useful but should be summarized/pruned. |
| Notes/watchlist/alerts | `notes`, `note_versions`, `watchlist_items`, `alert_events` | Human workflow volume | Usually low for single-user hobby scale. |
| Future reconciliation decisions | future accounting tables | Transfer links, classifications, approvals, unresolved decisions | Likely moderate but important for auditability. |

Current local-prod cadence from the runbook:

- Owned portfolio polling defaults to every 15 minutes.
- That is 96 snapshot opportunities per day.
- Each owned refresh can write one `position_snapshots` row per current holding,
  plus benchmark quote rows for tracked benchmark symbols.

Sizing formulas:

```text
snapshots_per_day = 24 * 60 / polling_interval_minutes
position_snapshot_rows_per_year = holdings_count * snapshots_per_day * 365
benchmark_quote_rows_per_year = benchmark_symbol_count * snapshots_per_day * 365
```

Rough scenarios at 15-minute polling:

| Scenario | Holdings | Benchmark symbols | Position rows/year | Benchmark rows/year | Storage implication |
| --- | ---: | ---: | ---: | ---: | --- |
| Small | 25 | 5 | 876,000 | 175,200 | May fit small free DB only if rows/indexes stay lean and raw files are not stored. |
| Medium | 75 | 10 | 2,628,000 | 350,400 | Likely pressures a 0.5 GB free database after indexes, JSON, and retention. |
| Large | 150 | 20 | 5,256,000 | 700,800 | Not a good fit for free-tier retention without downsampling/pruning. |

Why this matters:

- A numeric row with timestamps and indexes is not just the visible numeric
  payload. Postgres row overhead, indexes, JSON columns, and bloat can multiply
  storage. A safe rough planning range is several hundred bytes to over 1 KB per
  time-series row after indexes, depending on schema and vacuum behavior.
- Raw `import_artifacts.file_data` can dominate storage if statements, PDFs, or
  broker exports are uploaded to a hosted DB. For privacy and cost, hosted
  deployments should avoid storing private raw broker files unless explicitly
  approved.
- Free-tier storage such as Neon Free's 0.5 GB per project can be enough for a
  sanitized preview or small retained dataset, but not for indefinite 15-minute
  full-history retention.

Tradeoff options:

| Strategy | Benefit | Cost/limitation |
| --- | --- | --- |
| Keep full 15-minute snapshots local only | Best fidelity and privacy. | Hosted dashboard cannot show full intraday history without local API/tunnel. |
| Host only daily/monthly aggregates | Much smaller DB; enough for portfolio story and inception chart. | Loses raw intraday drilldown in hosted app. |
| Retain intraday for recent window only | Good recent UX with bounded storage. | Requires retention job and clear historical downsampling policy. |
| Store raw imports in local ignored `data/` only | Protects private broker documents and avoids DB bloat. | Hosted app needs sanitized derived data or manual sync. |
| Use object storage for raw files | Keeps DB smaller. | Still has privacy/secrets/cost concerns; not zero-maintenance. |
| Use paid DB/storage when history grows | Less engineering constraint. | Violates zero-cost goal unless explicitly accepted. |

Recommended sizing task before any hosted DB decision:

1. Count current local rows and relation sizes with read-only SQL:

   ```sql
   select
     relname,
     n_live_tup as estimated_rows,
     pg_size_pretty(pg_total_relation_size(relid)) as total_size
   from pg_stat_user_tables
   order by pg_total_relation_size(relid) desc;
   ```

2. Separately count the highest-growth tables:

   ```sql
   select count(*) from position_snapshots;
   select count(*) from benchmark_quotes;
   select count(*) from transactions;
   select count(*) from import_artifacts;
   select count(*) from activity_logs;
   ```

3. Measure raw import storage:

   ```sql
   select
     count(*) as artifacts,
     pg_size_pretty(sum(octet_length(file_data))::bigint) as raw_file_bytes
   from import_artifacts;
   ```

4. Project storage under three policies:

   - local-only full fidelity;
   - hosted daily/monthly aggregates only;
   - hosted recent intraday window plus downsampled history.

5. Compare each projection against current free-tier limits, backup needs, and
   privacy requirements before selecting Vercel/hosted Postgres or staying
   local-first.

Do not run these queries against `portfolio_dev` in an implementation ticket
unless the task is explicitly read-only and the user approved using local-prod
metadata for sizing. The queries above should not mutate data, but the access
decision still matters because the database contains private portfolio records.

## Local Runtime After Restart

Current posture:

- `infra/docker-compose.yml` defines data services plus an `app` profile for
  `api`, `frontend`, `worker`, and `scheduler`.
- App-profile services use `restart: unless-stopped`.
- Data persists in named volumes for TimescaleDB, Redis, and MinIO.
- API, frontend, worker, scheduler, Redis, TimescaleDB, and MinIO have
  healthchecks in the Compose file.
- API startup defaults are safety-oriented: `STARTUP_DB_INIT_ENABLED=false`,
  `STARTUP_REPAIRS_ENABLED=false`, and `API_SCHEDULER_ENABLED=false`.
- `docs/local_app_compose_runbook.md` documents data-services-only startup,
  full app startup, pause/resume for worker and scheduler, health checks, and
  protected DB row-count evidence.
- `scripts/start_local_app_compose.sh` loads root `.env`, falls back to
  `api/.env` for `INSTITUTION_CREDENTIALS_MASTER_KEY`, requires `SECRET_KEY`,
  and starts the app profile.

Readiness gaps:

- There is no checked-in host boot integration such as a user systemd service,
  cron entry, or launchd equivalent. `restart: unless-stopped` helps after the
  Docker daemon starts, but the audited files do not prove Docker itself or the
  Compose project will be started after machine reboot.
- No live restart evidence was collected. Required future evidence should
  include `docker compose ... ps`, API `/health`, API `/readiness`, frontend
  `/login`, worker/scheduler logs, and protected DB row counts before and after
  a smoke window.
- The app profile defaults `OWNED_POLLING_ENABLED=true`. This is acceptable for
  local-prod freshness, but a boot-only smoke against `portfolio_dev` must set
  `OWNED_POLLING_ENABLED=false` or stop `worker scheduler` to avoid periodic
  portfolio mutations during smoke validation.
- `infra/README.md` still describes a generic local stack and `down -v` reset
  path. The safer local-prod details live in `docs/local_app_compose_runbook.md`;
  future ops edits should keep the runbook as the source of truth.

## Worker And Scheduler Health

Current posture:

- `worker/README.md` identifies RQ as the worker runtime and documents worker,
  scheduler, smoke-test, and local-prod cadence commands.
- The API scheduler is intentionally disabled for local-prod; the separate
  scheduler enqueues due jobs and the separate RQ worker executes them.
- Compose healthchecks verify Redis/RQ connectivity for the worker and Redis
  connectivity for the scheduler.
- `worker.jobs` wraps alert evaluation, owned refresh, and Binance auto-sync
  job entrypoints.
- `worker.scheduler.run_forever()` polls every
  `SCHEDULER_POLL_INTERVAL_SECONDS`, defaulting to 30 seconds.
- The runbook documents logs, `docker compose ... ps`, and authenticated
  `/v1/sync/freshness` as operational checks.

Readiness gaps:

- Scheduler health currently proves Redis is reachable, not that the scheduler
  loop is making progress, jobs are due-enqueued, or the last enqueue attempt
  succeeded.
- Worker health currently proves RQ can report queue information, not that a
  recent job completed successfully or that failed jobs are below an acceptable
  threshold.
- `worker.scheduler.run_forever()` has no visible exception boundary, backoff,
  or heartbeat in the audited file. A thrown exception should cause container
  restart, but the audited docs do not define how operators distinguish crash
  loops from healthy idleness.
- No explicit failed-job queue, dead-letter policy, last-success timestamp, or
  activity-log status contract is documented in the audited worker/runtime
  surfaces.
- Binance auto-sync is correctly disabled by default, but readiness to enable
  it depends on encrypted credentials, `INSTITUTION_CREDENTIALS_MASTER_KEY`,
  decrypt-only verification, and acceptance of delta-sync coverage limits.

## Secrets, Auth, And Credential Posture

Current posture:

- App-profile API, worker, and scheduler commands fail fast when `SECRET_KEY` is
  missing.
- `INSTITUTION_CREDENTIALS_MASTER_KEY` is passed through Compose to API, worker,
  and scheduler.
- The local app runbook documents that encrypted Binance credentials are
  unusable in containers unless the master key reaches the runtime environment.
- `scripts/start_local_app_compose.sh` avoids baking `.env` into images and can
  load the existing local `api/.env` master key into the Compose environment.
- `.env.example` leaves broker/API provider tokens empty and documents master
  key generation.
- The migration runbook documents the institution credential master key and
  warns not to commit or paste it.

Readiness gaps:

- `.env.example` contains local default database and MinIO credentials and a
  placeholder `SECRET_KEY`. That is acceptable for local scaffolding but must
  not be treated as production-strength runtime configuration.
- `DEBUG=true` in `.env.example` is convenient locally, but app-profile Compose
  defaults `DEBUG=false`; operators should keep runtime `.env` aligned with the
  intended mode.
- The audited files do not define key rotation or recovery steps beyond the
  migration runbook note that lost keys require broker credentials to be
  re-entered or rotated through the app.
- No auth/session hardening review was possible inside this dispatch record
  because API/frontend auth implementation files were outside the read-only
  context.

## Migration And Runbook Readiness

Current posture:

- `portfolio_dev` is clearly documented as protected local-production data.
- Schema/migration/destructive/sync/always-on work must use
  `docs/local_prod_db_migration_runbook.md`.
- The migration runbook requires read-only alignment checks and backup evidence
  before applying migrations to `portfolio_dev`.
- `scripts/backup_local_prod_db.sh` creates a custom-format dump, verifies it
  with `pg_restore --list`, and chmods the dump to `0600`.
- `scripts/restore_drill_local_prod_db.sh` verifies archives and refuses restore
  targets unless the target database name contains `test` or `smoke`; it also
  calls `app.db.safety.assert_safe_destructive_database_url(...)`.
- `scripts/binance_export_baseline_dry_run.py` defaults to a disposable
  `portfolio_binance_baseline_test` database and calls the destructive database
  safety helper before recreating the database.

Readiness gaps:

- Protected migration readiness is procedural, not continuously proven. A
  future schema ticket still needs fresh backup, restore-drill, alignment, and
  post-check evidence before touching `portfolio_dev`.
- The backup helper is intentionally a backup tool and does not itself verify
  that the source is `portfolio_dev`; operators must point it at the intended
  protected source.
- The restore helper is safer because it enforces test/smoke naming, but the
  audited workflow still needs an operator-owned decision before replacing or
  repairing `portfolio_dev`.
- Runtime smoke checks that append freshness data are not migrations, but they
  can mutate `position_snapshots` and aggregate state. The local app runbook
  correctly calls this out; future dispatches should classify those checks as
  protected-runtime operations.

## CI And Fresh-Session Readiness

Current posture:

- `Makefile` exposes `ci`, `feature-check`, `compose-check`, and test targets.
- `make feature-check` provisions `portfolio_backend_test`, runs `make ci`, and
  runs frontend auth smoke.
- GitHub Actions sets up TimescaleDB and Redis, installs Python and frontend
  dependencies, provisions the backend test database, runs `make ci`, and runs
  Playwright smoke tests.
- `scripts/verify_compose_app_profile.sh` structurally checks the Compose app
  profile: app services are profile-gated, restart policies and healthchecks
  exist, app services fail fast without `SECRET_KEY`, the master key reaches
  API/worker/scheduler, and API mutation-at-startup defaults are false.
- Hot-path docs and memory guidance agree that private broker exports belong in
  ignored `data/` and tests depending on those files must skip when absent.

Readiness gaps:

- GitHub Actions does not run `make compose-check`, so Compose app-profile drift
  can bypass CI unless a developer runs it locally.
- CI's ephemeral service database is named `portfolio_dev` while destructive
  test guidance says test/smoke databases should contain `test` or `smoke`.
  The workflow also provisions `portfolio_backend_test`, so normal destructive
  tests should use the safe test URL. The gap is naming ambiguity: code that
  accidentally uses `DATABASE_URL` in CI could mutate the ephemeral
  `portfolio_dev` service database and still mask a local-prod safety issue.
- `scripts/verify_all.sh` still checks architecture text in
  `docs/automation-guide.md`. That may be intentional, but it is outside the
  current hot path and should not become an accidental stale-doc dependency.
- This audit did not run a clean-checkout/no-private-data simulation. Future
  merge-readiness should prove private fixture-dependent tests skip cleanly when
  ignored `data/` is absent.

## Private Data And Protected DB Safety

Current posture:

- Orientation docs consistently classify private broker exports, statements,
  legal PDFs, and account reference files as ignored local data under `data/`.
- `AGENTS.md` and current-state docs prohibit moving private broker material
  back into `docs/` or tracked fixtures without sanitization and explicit
  approval.
- The local app runbook documents row-count checks where `position_snapshots`
  may increase during owned polling, but `transactions`, `assets`, and
  `import_artifacts` must not reset.
- The runbooks warn against `docker compose down -v` unless intentionally
  deleting local data volumes.

Readiness gaps:

- No private-data scan or clean-checkout test was run in this audit.
- No protected DB row counts were captured because protected DB access and
  runtime smoke were out of scope.
- Future runtime validation needs an explicit smoke database or explicit user
  approval before any check that may mutate `portfolio_dev`.

## Recommended Follow-Up Work

1. Add `make compose-check` to GitHub Actions or to `make ci` if the required
   Docker Compose dependency is acceptable in CI.
2. Add a scheduler heartbeat or last-enqueue status that proves the scheduler
   loop is alive, not just Redis-reachable.
3. Add worker observability for last success, last failure, failed job count,
   and stale queue age.
4. Create a boot/restart evidence checklist that can be run in a safe smoke DB,
   with a separate explicitly approved `portfolio_dev` local-prod smoke path.
5. Keep Binance auto-sync disabled until credential decrypt-only verification
   and source coverage limitations are accepted for the current runtime.
6. Re-run fresh-session readiness without ignored `data/` before merging any
   backend/import/test changes that could depend on private broker fixtures.
7. Create a deployment discovery doc comparing Vercel frontend-only, Vercel plus
   hosted Postgres, and local-only operation.
8. Teach/record the chosen DevOps posture in a short runbook aimed at future
   agents: what runs where, what data may leave the machine, how backups work,
   and which operations are forbidden without approval.
9. Add a cloud data-volume sizing task before hosted DB work. It should measure
   current row counts/relation sizes read-only, model snapshot growth under the
   current 15-minute cadence, and compare local-only, aggregate-hosted, and
   recent-intraday-hosted retention policies.

## Gates Skipped In This Audit

- Docker Compose startup/restart smoke: skipped by dispatch instruction.
- Worker/scheduler live logs and RQ queue inspection: skipped by dispatch
  instruction.
- API/frontend runtime health checks: skipped by dispatch instruction.
- CI, `make ci`, `make feature-check`, and Playwright: skipped because this was
  audit/docs-only.
- Migration, backup, restore drill, schema checks, and protected DB row counts:
  skipped because protected DB and migration operations were blocked.
- Auth implementation review: skipped because API/frontend auth files were
  outside the dispatch record.
