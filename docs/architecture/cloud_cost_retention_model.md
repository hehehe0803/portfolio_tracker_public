# Cloud Cost And Retention Model

Status: planning model v2.
Last updated: 2026-06-18.
Worker: cloud-cost-retention.

## Scope

This document estimates the storage and retention shape for a local-first
Portfolio Tracker deployment. It does not change runtime files, deployment
configuration, secrets, database schema, migrations, or protected local data.

The model is intentionally conservative because no protected database queries
were run. Use it to decide what can stay local, what can be hosted on a free or
hobby tier, and what needs explicit approval before any deployment work starts.

Current documentation lookup:

- Context7 was used for Supabase current documentation because this model
  discusses free hosted Postgres and object storage tradeoffs.
- Context7 result selected `/supabase/supabase` with high source reputation.
- The fetched docs reported a Supabase free-plan example with 500 MB database
  storage, 1 GB file storage, and 5 GB bandwidth, and noted that database
  backups do not restore Storage objects because the database stores object
  metadata only.
- Other provider-specific quotas and prices are not treated as current facts in
  this document. Verify live provider pages before deployment.

## Product Constraints That Drive Cost

Portfolio Tracker is single-user and local-first. The first deployment target
must preserve the product order:

1. Trusted money numbers and reconciliation.
2. Structure and distribution analytics.
3. Dashboard and asset detail UI on trusted contracts.
4. Later decision support.

Cost modeling should therefore optimize for accounting truth and auditability,
not for retaining every high-frequency intermediate forever.

Hard constraints:

- `portfolio_dev` is protected local-production data.
- Private broker exports, statements, credentials, cookies, legal PDFs, and
  account reference files must stay local unless explicitly approved.
- Cloud deployment must not silently upload raw broker evidence.
- Background polling at 15-minute cadence is expensive mainly because it creates
  time-series rows, indexes, backups, and retention obligations.

## Sizing Assumptions

These are planning assumptions, not measured facts.

| Class | Planning unit | Conservative storage range | Notes |
| --- | ---: | ---: | --- |
| Broker export file | one raw CSV/XLSX/PDF/archive | 50 KB to 10 MB | PDFs and full statements can dominate storage quickly. |
| Raw import artifact in DB | raw bytes plus metadata | `file_bytes * 1.1` to `file_bytes * 1.5` | DB storage also affects backups and restores. |
| Parsed transaction row | one normalized transaction | 1 KB to 3 KB | Includes row overhead, indexes, source metadata, and audit fields. |
| Position snapshot row | one holding at one timestamp | 0.5 KB to 1.5 KB | Higher if JSON/debug fields or wide indexes are added. |
| Benchmark/price snapshot row | one symbol at one timestamp | 0.4 KB to 1.2 KB | Similar retention risk to position snapshots. |
| Daily aggregate row | one asset/source/type/day | 0.5 KB to 2 KB | Cheap enough for long retention. |
| Activity/log row | one app audit/status event | 1 KB to 3 KB | Keep decision audit longer than noisy scheduler status. |
| CI/browser artifact | one trace, screenshot, or report | 1 MB to 100 MB | Should stay in CI/object artifact retention, not app DB. |

Storage formulas:

```text
snapshots_per_day = 24 * 60 / polling_interval_minutes
position_snapshot_rows = holdings_count * snapshots_per_day * retained_days
benchmark_rows = benchmark_symbol_count * snapshots_per_day * retained_days
transaction_storage_bytes = parsed_transaction_count * transaction_row_bytes
raw_import_storage_bytes = sum(raw_file_bytes) * raw_import_overhead_factor
daily_aggregate_rows = aggregate_keys_per_day * retained_days
log_rows = events_per_day * retained_days
```

For 15-minute polling:

```text
snapshots_per_day = 96
```

## Volume Scenarios

### Broker Files And Raw Imports

Raw broker evidence is high-sensitivity and should default to local ignored
storage under `data/`.

| Scenario | Files/year | Average file size | Raw bytes/year | 3-year raw bytes | Hosted posture |
| --- | ---: | ---: | ---: | ---: | --- |
| Minimal manual imports | 24 | 0.5 MB | 12 MB | 36 MB | Cloud storage possible but not worth privacy risk. |
| Normal single-user | 120 | 2 MB | 240 MB | 720 MB | Keep local; derived rows can be hosted if approved. |
| Heavy evidence retention | 500 | 5 MB | 2.5 GB | 7.5 GB | Not a free DB fit; object storage only after approval. |
| PDF-heavy statements | 1,000 | 10 MB | 10 GB | 30 GB | Local or paid storage with explicit privacy decision. |

Raw import rule:

```text
hosted_raw_imports_allowed = explicit_user_approval
  and encryption/backups/retention_runbook_exists
  and provider_quota_reviewed_currently
```

### Parsed Transactions

Parsed transactions are much smaller than raw files and are usually the better
cloud candidate, provided private-data approval exists.

| Scenario | Parsed transactions/year | Planning bytes/row | Storage/year | 5-year storage |
| --- | ---: | ---: | ---: | ---: |
| Small | 5,000 | 2 KB | 10 MB | 50 MB |
| Medium | 25,000 | 2 KB | 50 MB | 250 MB |
| Large | 100,000 | 2 KB | 200 MB | 1 GB |

Parsed transactions should be retained long term because they support capital
truth, reconciliation, cost basis, and auditability.

### Position Snapshots At 15-Minute Cadence

Position snapshots are the main free-tier risk.

| Scenario | Holdings | Rows/day | Rows/year | 1 KB row estimate/year | 3-year raw estimate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Small | 25 | 2,400 | 876,000 | 876 MB | 2.6 GB |
| Medium | 75 | 7,200 | 2,628,000 | 2.6 GB | 7.9 GB |
| Large | 150 | 14,400 | 5,256,000 | 5.3 GB | 15.8 GB |

Even the small scenario can exceed a 500 MB free database once indexes, bloat,
transactions, logs, and aggregates are included. Full-fidelity 15-minute history
should therefore be local-only or retained in a bounded recent cloud window.

### Benchmark And Price Snapshots

Benchmark snapshots grow linearly with tracked symbols.

| Scenario | Symbols | Rows/day | Rows/year | 0.8 KB row estimate/year |
| --- | ---: | ---: | ---: | ---: |
| Small | 5 | 480 | 175,200 | 140 MB |
| Medium | 10 | 960 | 350,400 | 280 MB |
| Large | 20 | 1,920 | 700,800 | 561 MB |

Free cloud retention should avoid indefinite 15-minute benchmark history. Daily
close/open/high/low aggregates usually answer dashboard questions with far less
storage.

### Daily Aggregates

Daily aggregates are cheap and useful for the dashboard contract.

Assume aggregate keys per day:

```text
aggregate_keys_per_day =
  1 portfolio total
  + asset_type_count
  + tracked_asset_count
  + source_count
  + selected driver/period summaries
```

| Scenario | Aggregate keys/day | Rows/year | 2 KB row estimate/year | 10-year estimate |
| --- | ---: | ---: | ---: | ---: |
| Small | 50 | 18,250 | 37 MB | 365 MB |
| Medium | 120 | 43,800 | 88 MB | 876 MB |
| Large | 250 | 91,250 | 183 MB | 1.8 GB |

Daily aggregates are the best hosted history primitive for a zero-cost
dashboard. They preserve portfolio story, rolling periods, allocation over time,
and confidence states without retaining every intraday poll.

### Logs, Activity, And Artifacts

Separate audit records from operational noise.

| Stream | Example events | Retention purpose | Cost posture |
| --- | --- | --- | --- |
| Accounting decision audit | transfer link approval, external-cashflow classification, import approval, cost-basis override | Durable accounting truth | Keep long term in DB. |
| Import audit | file parsed, parser confidence, rows accepted/rejected | Reproducibility and support | Keep summary long term; raw evidence local by default. |
| Scheduler status | due job checked, refresh succeeded, queue heartbeat | Operations | Keep short window, then aggregate. |
| App debug logs | request traces, stack traces, verbose worker logs | Debugging | Do not persist indefinitely in app DB. |
| CI/browser artifacts | screenshots, traces, reports | Verification evidence | Retain in CI/artifact storage, not portfolio DB. |

Planning formula:

```text
log_rows_per_year = events_per_day * 365
log_storage_per_year = log_rows_per_year * log_row_bytes
```

| Scenario | Events/day | Rows/year | 2 KB row estimate/year |
| --- | ---: | ---: | ---: |
| Quiet | 100 | 36,500 | 73 MB |
| Normal | 500 | 182,500 | 365 MB |
| Noisy | 2,000 | 730,000 | 1.5 GB |

Noisy scheduler and debug logs can become larger than parsed transactions. They
need short retention and daily summaries before cloud deployment.

## Retention Tiers

| Tier | Data | Local retention | Free/hobby cloud retention | Reason |
| --- | --- | --- | --- | --- |
| Tier 0: secrets and credentials | API keys, broker credentials, cookies, session files | Local secret store only | Never upload by default | Highest sensitivity; deployment requires separate secret review. |
| Tier 1: raw broker evidence | CSV/XLSX/PDF exports, statements, screenshots, account references | Keep local under ignored `data/` until user deletes | None by default | Private, bulky, and not needed for dashboard rendering. |
| Tier 2: durable accounting decisions | transfer links, cashflow classifications, import approvals, manual/unknown cost basis | Indefinite | Indefinite if cloud DB is approved | Required for trust and auditability. |
| Tier 3: parsed normalized transactions | trades, deposits, withdrawals, fees, transfers | Indefinite | Indefinite if cloud DB is approved and storage fits | Small enough and core to money truth. |
| Tier 4: recent intraday snapshots | position and quote snapshots at 15-minute cadence | 90 to 365 days, configurable | 7 to 30 days on free tier | Useful for freshness and recent movement; expensive long term. |
| Tier 5: daily aggregates | portfolio, asset, asset-type, source, cash, driver summaries | Indefinite | 5 to 10 years if storage fits | Best long-history primitive. |
| Tier 6: operational logs | scheduler heartbeat, worker status, API debug logs | 7 to 30 days raw, 1 year summary | 3 to 14 days raw, 90 days summary | Useful for ops, not accounting truth. |
| Tier 7: verification artifacts | screenshots, Playwright traces, CI reports | Per-run or local artifact folder | CI retention only | Keep out of app DB/object store unless explicitly curated. |

Recommended first cloud policy:

```text
raw broker evidence: local only
parsed transactions: cloud only after private-data approval
durable accounting decisions: cloud only after private-data approval
15-minute snapshots: retain 14 days cloud, full local optional
daily aggregates: retain 10 years cloud
operational logs: retain 7 days cloud, 90 days aggregate
CI/browser artifacts: external CI retention, not app storage
```

## Local Storage Versus Free Cloud Storage

| Decision axis | Local DB/files | Free cloud DB | Free cloud object storage |
| --- | --- | --- | --- |
| Privacy | Best default; data stays on machine. | Requires explicit approval for private financial rows. | Requires explicit approval for raw private files. |
| Cost predictability | Zero provider bill, local disk cost only. | Quota-bound; time-series rows can exceed free limits. | Quota-bound; raw statements can exceed free limits. |
| Remote access | Requires LAN, VPN, tunnel, or remote desktop. | Enables hosted dashboard/API if auth and secrets are solved. | Enables hosted import evidence only if API permissions are solved. |
| Backup/restore | User controls backups; must run drills. | Provider backups may be limited on free tiers; verify current terms. | Database backups may not include objects; object lifecycle must be separate. |
| Best use | Protected prod, raw broker files, full intraday history. | Sanitized preview, derived dashboard data, small approved private dataset. | Approved raw evidence archive, sanitized fixtures, large non-DB artifacts. |
| Worst use | Sharing public demos from private local data. | Indefinite 15-minute snapshots for many holdings. | Unreviewed upload of broker statements or secrets-adjacent evidence. |

Supabase-specific planning note from Context7 docs:

- Supabase can provide hosted Postgres plus file storage in one platform.
- The fetched docs report a free-plan example with small DB and file-storage
  quotas.
- Supabase database backups do not restore Storage objects; object retention and
  restore need their own policy.

Do not infer that any free cloud tier is safe for private production data just
because it is technically large enough.

## Zero-Cost And Hobby Deployment Tradeoffs

| Option | Monthly cost target | Data posture | Works well for | Fails when |
| --- | ---: | --- | --- | --- |
| Local-only | 0 USD | All private data local. | Maximum privacy, full fidelity, protected `portfolio_dev`. | User needs remote access or hosted mobile review. |
| Frontend preview only | 0 USD if host quotas fit | Mock, sanitized, or local-tunnel data only. | UI review, screenshots, mobile layout smoke. | Real private dashboard needs API/DB/secrets. |
| Free DB with derived data only | 0 USD if quotas fit | Daily aggregates and maybe parsed rows after approval. | Read-only dashboard, low-cost history. | Needs full raw evidence, full intraday retention, or reliable backups. |
| Free DB plus object storage | 0 USD until quotas hit | Raw files only after explicit approval. | Small approved import archive. | Broker statements grow, restore policy is weak, or privacy is unresolved. |
| Full hosted hobby app | 0 USD not guaranteed | API, DB, worker, scheduler, and storage hosted. | Always-accessible personal app after runbooks exist. | Workers need always-on compute, storage grows, backups matter. |

Free/hobby deployment should start as a discovery and preview track, not a
`portfolio_dev` migration.

## Decision Table

| Data/product need | Recommended storage | Retention | Manual approval before cloud? | Rationale |
| --- | --- | --- | --- | --- |
| Current dashboard with trusted total value | Local DB first; cloud derived payload later | Current plus latest aggregate | Yes, if private values leave machine | Supports dashboard without raw evidence upload. |
| Inception chart | Daily aggregates in DB | 5 to 10 years | Yes for cloud | Small and aligned with dashboard contract. |
| Rolling 7D/30D/90D performance | Daily aggregates plus recent intraday if needed | 10 years daily; 14 to 30 days intraday cloud | Yes for cloud | Cashflow-separated performance does not need full intraday forever. |
| Reconciliation decisions | Relational DB | Indefinite | Yes for cloud | Durable accounting state must survive raw log pruning. |
| Parsed transactions | Relational DB | Indefinite | Yes for cloud | Core accounting evidence, smaller than raw imports. |
| Raw broker exports/statements | Local ignored files by default | User-controlled | Yes, explicit and separate | High-sensitivity and bulky. |
| Import previews and parser evidence | DB summaries; raw local | Summary indefinite; raw local | Yes for raw cloud | Auditability without cloud file bloat. |
| 15-minute position snapshots | Local full history; cloud recent window only | 90-365 days local; 7-30 days cloud | Yes for cloud | Biggest free-tier storage risk. |
| 15-minute quote snapshots | Local recent/full as needed; cloud daily aggregates | 90-365 days local; 7-30 days cloud | Yes for cloud | Similar row-growth risk. |
| Worker/scheduler logs | Log sink or DB summary | 7-30 days raw; 90 days summary | No for local, yes for hosted logs | Operational noise should not crowd accounting data. |
| CI/browser artifacts | CI artifact store or local evidence folder | Short CI retention | No app-cloud upload by default | Verification evidence is not portfolio state. |

## Manual Decisions Before Deployment

These must be answered before any cloud deployment or hosted-data migration:

1. Is the first hosted goal a frontend preview, read-only dashboard, private
   remote app, or public sanitized demo?
2. May private financial rows leave the local machine?
3. May raw broker files, PDFs, screenshots, or account references leave the
   local machine?
4. Which provider is approved for database hosting, and what are the current
   free/hobby limits, backup terms, pause/sleep behavior, and restore terms?
5. Which provider is approved for object storage, and how are object retention,
   deletion, encryption, and restore tested?
6. What cloud retention policy is accepted for 15-minute snapshots: none,
   7 days, 14 days, 30 days, or longer paid retention?
7. Is a hosted deployment allowed to be read-only at first?
8. Are workers and scheduler staying local, or does hosted operation require an
   always-on worker platform?
9. What is the manual restore test before trusting hosted data?
10. What alert or budget threshold stops sync/import jobs before quota overage?

Default answers until explicitly changed:

```text
hosted_raw_broker_files = false
hosted_private_financial_rows = false
cloud_intraday_retention_days = 0
hosted_dashboard_mode = sanitized_preview_or_local_tunnel_only
workers_and_scheduler = local_only
```

## Verification Model For Future Agents

Before selecting a cloud DB, run a read-only sizing ticket after user approval
for protected-data metadata access:

```sql
select
  relname,
  n_live_tup as estimated_rows,
  pg_size_pretty(pg_total_relation_size(relid)) as total_size
from pg_stat_user_tables
order by pg_total_relation_size(relid) desc;
```

Then measure high-growth tables:

```sql
select count(*) from position_snapshots;
select count(*) from benchmark_quotes;
select count(*) from transactions;
select count(*) from import_artifacts;
select count(*) from activity_logs;
```

If raw artifacts are stored in the DB, estimate their byte size:

```sql
select
  count(*) as artifacts,
  pg_size_pretty(sum(octet_length(file_data))::bigint) as raw_file_bytes
from import_artifacts;
```

Do not run these against `portfolio_dev` unless the dispatch explicitly allows
read-only protected metadata access. They are non-mutating SQL statements, but
the data is still private.

## Recommended V2 Policy

For the next revamp wave, keep the app local-first and model cloud as a preview
or derived-data surface:

1. Keep raw broker evidence local under ignored `data/`.
2. Keep full 15-minute snapshot history local unless the user accepts paid or
   bounded retention.
3. Store daily aggregates as the long-lived hosted history primitive.
4. Store durable accounting decisions and parsed transactions in cloud only
   after explicit private-data approval.
5. Retain only 7 to 30 days of 15-minute cloud snapshots if remote recent
   movement is required.
6. Prune or summarize worker/scheduler logs before they compete with accounting
   data.
7. Verify current provider limits with Context7 or official provider docs before
   deployment, because free-tier quotas and backup terms change.
