# Current State

Status: synthesis.
Last updated: 2026-06-15.

## What This Repo Is

Portfolio Tracker is a local-first personal portfolio analytics app. It should become useful only by making money numbers trustworthy first, then explaining portfolio structure and movement.

No backend or UI implementation agent should start from the old docs surface. Start from this file, `docs/product_north_star.md`, `docs/roadmap.md`, `docs/implementation_plan.md`, and `docs/verification_matrix.md`.

## Current Repo Snapshot

Measured during the vNext docs and data cleanup on 2026-06-15:

- `origin/main` contains the merged vNext docs-orientation cleanup.
- Follow-up cleanup lives on `codex/vnext-spec-dispatch-cleanup` until merged.
- Raw broker exports, statements, legal PDFs, and derived private-account snapshots are local data under ignored `data/`, not agent-facing docs.
- `docs/` should stay limited to the hot path, safety/runtime runbooks, architecture/policy references, and reviewed visual references.

## Protected Data

`portfolio_dev` is protected local-production data. Do not run migrations, schema repair, broker sync experiments, destructive tests, smoke seeders, or Compose always-on changes against it without following `docs/local_prod_db_migration_runbook.md`.

For destructive tests or smoke flows, use only localhost database names that explicitly contain `test` or `smoke`. If a helper can reset schema, it must call `app.db.safety.assert_safe_destructive_database_url(...)` before touching the database.

This docs cleanup did not require database access and must not touch `portfolio_dev`.

## Implemented Foundation

The repo already has substantial backend, frontend, worker, shared-contract, and Compose foundations:

- FastAPI backend under `api/`.
- Next.js frontend under `frontend/`.
- Worker and scheduler foundations under `worker/`.
- Shared contracts under `shared/`.
- Local Compose profile for API, frontend, worker, and scheduler.
- Portfolio assets, snapshots, benchmark quote storage, pending-order storage, performance summary APIs, notes/tags/themes/watchlist surfaces, and sync/freshness endpoints.
- Binance export parsing and pricing support for many current crypto assets.
- XTB daily PDF parsing, XTB Gmail/PDF preview ingestion, Aster/Hyperliquid CSV parsing, Hyperliquid ledger/deposit parsing, and import-review confidence semantics as targeted accounting-truth ingestion foundations.

These foundations are not proof that money truth is trusted in daily use. Existing ingestion/parser work reduces accounting warning debt, but the product still needs durable accounting decisions, confidence-aware money contracts, and user-visible reconciliation workflow.

## Current Product Direction

vNext should stop expanding by half-built surfaces. Build complete functions in this order:

1. Trusted money numbers and reconciliation.
2. Structure and distribution analytics.
3. Dashboard and asset detail UI on top of trusted contracts.
4. Later decision-support surfaces only after the first layers are trustworthy.

Aster and Hyperliquid are in-scope tracked crypto sources for accounting and transfer reconciliation. They are not just spike evidence, but they also are not complete standalone product surfaces yet.

USDT and USDC are cash reserves inside the tracked portfolio, not crypto exposure.

## Known Risks

- Current-position P&L, lifetime P&L, contribution P&L, and performance P&L can still be confused if labels and contracts are not made explicit.
- Crypto withdrawals cannot be classified by sign alone; unknown outgoing transfers should create reconciliation tasks.
- Parsed evidence that only writes activity logs does not resolve accounting uncertainty. Approvals must create durable accounting state such as transfer links, external-cashflow classifications, import approvals, or confirmed cost basis.
- Mobile/dashboard polish is secondary until money numbers and confidence states are clear enough to trust.
