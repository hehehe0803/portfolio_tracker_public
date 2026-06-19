# vNext Implementation Plan

Status: source-of-truth dispatch plan.
Last updated: 2026-06-15.

This plan turns `docs/product_north_star.md` into parallel-safe implementation tickets. It replaces the old v3 TODO wall.

## Dispatch Rules

- Do not start backend or UI implementation from stale docs, deleted PRD/SRD files, old checklists, or dated premortems.
- Do not touch `portfolio_dev` without `docs/local_prod_db_migration_runbook.md`.
- Destructive tests and smoke seeders must use localhost database names containing `test` or `smoke`.
- Preserve broker fixture/data directories unless explicitly classified otherwise.
- Use `docs/verification_matrix.md` before marking any ticket complete.
- A ticket is ready for implementation only when dependencies are complete, write sets do not conflict, and open decisions for that ticket are resolved.
- Parallel agents may work only on tickets with disjoint write sets and no unresolved contract dependency.
- Shared contract tickets land before dependent API, analytics, or UI tickets.
- Before dispatching a parallel agent, the coordinator must publish a dispatch record using the format below.

## Current Dirty Worktree Caution

`docs/current_state.md` records unrelated dirty frontend, infra, script, and fixture/reference work. Implementation agents must inspect `git status --short` before editing and must not revert unrelated changes.

## Dispatch Record And Write Locks

Before any parallel worker starts, the coordinator must publish a dispatch record in the active coordination thread, issue, or PR description. The dispatch record is the write-lock source for that run.

Required format:

```text
ticket:
worker:
branch/worktree:
dependencies_complete:
exact_write_set:
read_only_context:
blocked_files:
db_or_migration_risk:
protected_db_runbook_required:
verification_commands:
handoff_expected:
```

Rules:

- `exact_write_set` must list concrete files or directories before work starts.
- Broad buckets such as "analytics services" are not enough for dispatch; they are planning hints only.
- No two active workers may claim overlapping write sets.
- Schema/migration tickets are serialized.
- Shared contract changes are serialized.
- If a worker discovers it must edit outside the dispatch record, it must stop and ask the coordinator to update the record.
- A final handoff must repeat the actual changed files and verification results.

## File Ownership Map

Likely files for vNext work:

| Area | Primary Files | Notes |
| --- | --- | --- |
| DB models/migrations | `api/app/db/models.py`, `api/migrations/`, `api/tests/db/` | Requires protected DB runbook if migration touches protected data. |
| Accounting domain services | `api/app/services/analytics.py`, new `api/app/services/accounting_*.py`, `api/tests/analytics/`, `api/tests/reconciliation/` | Prefer focused new modules over growing `analytics.py` if behavior is substantial. |
| Import/reconciliation services | `api/app/services/import_review.py`, `api/app/api/v1/review.py`, `api/tests/review/`, `api/tests/api/test_review_queue.py` | Existing review API is investment/accounting-adjacent; do not assume activity logs are durable state. |
| Portfolio state and pricing | `api/app/services/portfolio_state.py`, `api/app/services/pricing.py`, `api/tests/pricing/` | Current value and anchors depend on these surfaces. |
| API routes/contracts | `api/app/api/v1/portfolio.py`, `api/app/api/v1/review.py`, `shared/python/contracts.py`, `shared/typescript/contracts.ts`, `api/tests/api/`, `frontend/types/shared-contract-smoke.ts` | Shared contracts must be updated before UI consumers. |
| Frontend dashboard | `frontend/app/page.tsx`, `frontend/components/dashboard/`, `frontend/__tests__/dashboard.test.tsx` | Avoid log-heavy primary UI. |
| Frontend asset detail | `frontend/app/holdings/[symbol]/page.tsx`, `frontend/__tests__/mobile-routes.test.tsx` | Must distinguish current-position P&L from lifetime/contribution P&L. |

Agents should confirm exact files before editing. If a ticket needs new files, name the responsibility in the PR/commit message.

## Dependency Graph

```text
VNEXT-00 -> VNEXT-01A
VNEXT-01A -> VNEXT-01B
VNEXT-01A -> VNEXT-04A
VNEXT-01B -> VNEXT-01C
VNEXT-01A + VNEXT-01C -> VNEXT-01D
VNEXT-01A + VNEXT-01C + VNEXT-01D -> VNEXT-02A
VNEXT-02A + VNEXT-04A -> VNEXT-03A
VNEXT-01B + VNEXT-01C + VNEXT-01D + VNEXT-02A -> VNEXT-05A
VNEXT-05A -> VNEXT-05B
VNEXT-02A + VNEXT-04A -> VNEXT-06A
VNEXT-03A + VNEXT-04A + VNEXT-06A -> VNEXT-06B
VNEXT-02A + VNEXT-03A + VNEXT-05A + VNEXT-05B + VNEXT-06A + VNEXT-06B -> VNEXT-07A
VNEXT-07A -> VNEXT-07B
VNEXT-07A -> VNEXT-07C
```

Potential parallel groups:

- After VNEXT-01A lands, VNEXT-01B decision work and VNEXT-04A anchor investigation can proceed in parallel if their dispatch records do not overlap.
- After VNEXT-02A and VNEXT-04A land, VNEXT-03A, VNEXT-05A, and VNEXT-06A can proceed in parallel if their dispatch records do not overlap.
- After VNEXT-07A lands, VNEXT-07B and VNEXT-07C can proceed in parallel if their dispatch records do not overlap.

Do not parallelize migrations, shared contract changes, or broad edits to `api/app/services/analytics.py`.

## VNEXT-00: Docs Cleanup And Worktree Classification

Status: complete. Merged by PR #4 on 2026-06-15 as merge commit `43013c6f644e404c4be7e6709e8e3e1c37d75a83`.

Goal: make the current hot path clean enough for future agents.

Acceptance:

- Remaining docs are hot path, safety/runtime references, current superpowers artifacts, and explicitly kept reference/data material.
- No hot-path orientation references to deleted stale docs, old checklist graveyards, or dated premortems.
- `git diff --check -- README.md AGENTS.md docs` passes.
- `portfolio_dev` was not touched.

## VNEXT-01A: Source And Movement Taxonomy

Goal: create the canonical source and movement taxonomy used by all money-truth calculations.

Depends on:

- VNEXT-00.

Allowed write set:

- New focused accounting taxonomy module under `api/app/services/`.
- Tests under `api/tests/analytics/` or `api/tests/reconciliation/`.
- Shared contracts only if the API must expose taxonomy values.

Do not edit:

- Frontend UI.
- Migrations unless VNEXT-01B is also in scope.
- `portfolio_dev`.

Required behavior:

- Movement types: external cashflow, internal movement, trade/allocation.
- Sources: Binance, XTB, Aster, Hyperliquid, tracked wallets, cash, commodities.
- USDT/USDC are cash reserve for exposure classification.
- XTB withdrawals default external unless matched evidence exists.
- Crypto withdrawals are not classified by sign alone.

Acceptance:

- Tests prove each source/movement classification.
- Tests prove USDT/USDC are cash, not crypto exposure.
- No durable state write is required in this ticket.

## VNEXT-01B: Durable Accounting State Decision Record

Status: decision record added in `docs/architecture/durable_accounting_state_decision.md`.

Goal: resolve where durable accounting decisions live before any schema implementation starts.

Depends on:

- VNEXT-01A.

Allowed write set:

- `docs/product_north_star.md`.
- `docs/implementation_plan.md`.
- `docs/verification_matrix.md`.
- Optional short architecture note under `docs/architecture/` if needed.

Do not edit:

- `api/app/db/models.py`.
- Alembic migrations.
- Runtime code.

Required decision:

- Exact durable shape for transfer links.
- Exact durable shape for external-cashflow classifications.
- Exact durable shape for import approvals.
- Whether manual cost basis and explicit unknown cost basis use a new accounting table or extend existing import-review/transaction models.

Acceptance:

- Open decisions in `docs/product_north_star.md` are resolved or narrowed.
- VNEXT-01C has enough detail to implement schema without inventing product semantics.
- No runtime behavior changes.
- VNEXT-01C uses `docs/architecture/durable_accounting_state_decision.md` as the active schema input.

## VNEXT-01C: Durable Accounting State Schema

Goal: implement the durable accounting state resolved by VNEXT-01B.

Depends on:

- VNEXT-01B.
- `docs/architecture/durable_accounting_state_decision.md`.

Allowed write set:

- `api/app/db/models.py`.
- Alembic migration files.
- `api/tests/db/`.

Safety:

- Read `docs/local_prod_db_migration_runbook.md` before schema work.
- Do not run migrations against `portfolio_dev` without backup/restore-drill evidence.
- Tests must use safe test DB names.

Required durable state:

- Transfer links.
- External-cashflow classifications.
- Import approvals.
- Manual cost basis or explicit unknown cost-basis decisions.

Acceptance:

- Migration creates durable tables/columns with stable names.
- DB tests prove relationships and constraints.
- Activity logs remain audit evidence, not primary decision state.

## VNEXT-01D: Transfer Matching And Unknown Outgoing Tasks

Goal: identify internal transfers and create accounting tasks for unresolved outgoing crypto transfers.

Depends on:

- VNEXT-01A.
- VNEXT-01C.

Allowed write set:

- Accounting/reconciliation services under `api/app/services/`.
- Reconciliation tests under `api/tests/reconciliation/`.
- API tests only if task creation is exposed immediately.

Required behavior:

- Binance-to-Aster and Binance-to-Hyperliquid matches become internal movements when evidence matches.
- Unknown outgoing crypto transfer creates a reconciliation task.
- Matched internal movement does not increase external capital.
- Personal withdrawal decision remains possible but must be explicit or evidence-backed.

Acceptance:

- Tests cover matched transfer, unmatched outgoing transfer, and XTB default external withdrawal.
- Durable task state is written for unknown outgoing transfer.

## VNEXT-02A: Capital Truth Contract

Goal: implement the canonical capital truth contract.

Depends on:

- VNEXT-01A.
- VNEXT-01C.
- VNEXT-01D for unresolved-transfer inputs.

Allowed write set:

- Accounting/capital service under `api/app/services/`.
- `api/app/api/v1/portfolio.py` only if exposing the contract.
- Shared contracts when API shape changes.
- Tests under `api/tests/analytics/` and `api/tests/api/`.

Required outputs:

- `first_activity_date`.
- `gross_deposits`.
- `gross_withdrawals`.
- `net_capital_at_work`.
- `avg_net_capital_added_per_month`.
- `avg_gross_deposit_per_month`.
- `lifetime_pnl`.
- Confidence/materiality state.

Acceptance:

- Lifetime P&L uses current value minus net capital at work.
- Gross deposits are context, not the default P&L denominator.
- Severe uncertainty blocks or hides sensitive derived stats.

## VNEXT-03A: Rolling Period Performance

Goal: expose rolling 7D, 30D, and 90D performance with cashflows separated from investment gain.

Depends on:

- VNEXT-02A.
- VNEXT-04A.

Allowed write set:

- Analytics/accounting services.
- Portfolio API route if exposing periods.
- Shared contracts if API shape changes.
- Tests under `api/tests/analytics/`, `api/tests/pricing/`, and `api/tests/api/`.

Required formula:

```text
investment_gain = ending_value - starting_value - deposits + withdrawals
```

Acceptance:

- Deposit inside a period is not investment gain.
- Withdrawal inside a period is not investment loss.
- Missing anchor or low-confidence date marks period provisional.
- Dashboard default can consume rolling 30D.

## VNEXT-04A: Historical P&L Anchors And Confidence

Goal: provide reliable anchor selection and confidence metadata for historical values.

Depends on:

- VNEXT-01A.
- Existing portfolio state/pricing foundations.

Allowed write set:

- `api/app/services/portfolio_state.py`.
- Focused historical value/confidence service under `api/app/services/`.
- Tests under `api/tests/pricing/` and `api/tests/analytics/`.

Required behavior:

- Exact broker/account snapshot anchor is preferred over reconstruction.
- Reconstruction fails or degrades when required transactions/prices are missing.
- Confidence state affects derived metric visibility.

Acceptance:

- Tests cover exact anchor, reconstructed value, missing price/transaction gap, and confidence degradation.

## VNEXT-05A: Manual Reconciliation Queue With Durable Decisions

Goal: turn low-confidence accounting evidence into durable user decisions.

Depends on:

- VNEXT-01B.
- VNEXT-01C.
- VNEXT-01D.
- VNEXT-02A for capital-truth effects.

Allowed write set:

- Reconciliation services.
- `api/app/api/v1/review.py` or a new accounting-review route.
- API tests under `api/tests/api/` and `api/tests/review/`.
- Frontend is out of scope unless explicitly split into a separate UI ticket.

Required behavior:

- Suggested choices can resolve as internal transfer, personal withdrawal, import missing data, manual cost basis, or unknown.
- Approval writes durable accounting state before audit/activity log.
- Decisions update capital truth inputs where applicable.

Acceptance:

- Tests prove unknown outgoing transfer task, internal transfer approval, personal withdrawal approval, import approval, manual cost-basis/unknown decision, and audit log after durable state.

## VNEXT-05B: Accounting Review UI

Goal: provide a user-facing accounting review workflow for the durable decisions from VNEXT-05A.

Depends on:

- VNEXT-05A.

Allowed write set:

- `frontend/app/review/page.tsx` or a new accounting-review route.
- New review components under `frontend/components/` if split out.
- Frontend tests under `frontend/__tests__/`.
- API bindings in `frontend/lib/api.ts` if needed.

Required behavior:

- Shows accounting tasks separately from investment review tasks.
- Presents suggested choices for internal transfer, personal withdrawal, import missing data, manual cost basis, or unknown when the backend provides them.
- Submits decisions to the durable approval API.
- Shows confidence/materiality impact and avoids implying a recommendation.

Acceptance:

- Frontend tests cover task list, choice submission, blocked/loading/error states, and separation from investment review language.
- Manual mobile/browser smoke verifies the review workflow is usable without layout overlap.

## VNEXT-06A: Asset-Type Distribution And Cash Reserve

Goal: explain current portfolio distribution by asset type and cash reserve.

Depends on:

- VNEXT-02A.
- VNEXT-04A for confidence.

Allowed write set:

- Analytics/accounting services.
- Portfolio API/shared contracts if exposed.
- Tests under `api/tests/analytics/` and `api/tests/api/`.

Required behavior:

- Asset types: crypto, stocks/ETFs, commodities, cash, fallback other.
- USDT/USDC are cash.
- Dollars lead percentages.
- Weak denominator suppresses or flags percentages.

Acceptance:

- Asset-type totals reconcile to trusted current value within documented tolerance.
- USDT/USDC excluded from crypto exposure and included in cash.
- Confidence state flows into percentage display eligibility.

## VNEXT-06B: Holding Drivers

Goal: identify holdings that drive rolling 7D, 30D, and 90D movement.

Depends on:

- VNEXT-03A.
- VNEXT-04A.
- VNEXT-06A.

Allowed write set:

- Analytics services.
- Portfolio API/shared contracts if exposed.
- Tests under `api/tests/analytics/` and `api/tests/api/`.

Required behavior:

- Holding drivers explain movement in dollars first.
- Driver calculations respect confidence state.
- Low-confidence drivers are flagged or omitted rather than shown as precise.

Acceptance:

- Tests cover positive driver, negative driver, low-confidence driver, and no-data state.

## VNEXT-07A: Dashboard And Asset Detail API Contract

Goal: expose one stable contract for dashboard and asset detail UI.

Depends on:

- VNEXT-02A.
- VNEXT-03A.
- VNEXT-05A.
- VNEXT-05B for dashboard links/actions that enter the accounting review workflow.
- VNEXT-06A.
- VNEXT-06B.

Allowed write set:

- `api/app/api/v1/portfolio.py`.
- Shared Python/TypeScript contracts.
- API tests and shared contract smoke tests.

Required behavior:

- Dashboard contract includes current total value, rolling 30D investment gain/loss, contributions/withdrawals split, lifetime P&L/net capital when allowed, confidence state, asset-type distribution, cash reserve, holding drivers, and top reconciliation action.
- Asset detail contract includes current position/value, current-position P&L, capital allocated, lifetime contribution/P&L when allowed, recent movement, driver explanation, and trust blockers.

Acceptance:

- API tests prove severe accounting issues block/hide sensitive derived stats.
- Shared-contract smoke tests prove frontend-consumable TypeScript shape.

## VNEXT-07B: Dashboard First Screen UI

Goal: rebuild the dashboard first screen on the trusted dashboard contract.

Depends on:

- VNEXT-07A.

Allowed write set:

- `frontend/app/page.tsx`.
- `frontend/components/dashboard/`.
- `frontend/__tests__/dashboard.test.tsx`.
- Snapshots only when intentional and reviewed.

Required behavior:

- First screen prioritizes current total value, rolling 30D investment gain/loss, contributions/withdrawals, lifetime P&L/net capital when allowed, confidence state, asset-type distribution, cash reserve, holding drivers, and top reconciliation action.
- Raw transactions/activity/import logs are collapsed behind drilldowns.
- Ambiguous all-time/total P&L labels are absent.

Acceptance:

- Dashboard tests cover trusted state, severe-blocked state, and no ambiguous all-time/total P&L labels.
- Manual mobile/browser smoke includes first-viewport truth, no overlap, and useful confidence/reconciliation action state.

## VNEXT-07C: Asset Detail UI

Goal: rebuild asset detail on the trusted asset detail contract.

Depends on:

- VNEXT-07A.

Allowed write set:

- `frontend/app/holdings/[symbol]/page.tsx`.
- Asset-detail components if split out.
- Frontend tests under `frontend/__tests__/`.

Required behavior:

- Shows current position/value and current-position P&L separately from lifetime/contribution P&L.
- Shows capital allocated, recent movement, driver explanation, and trust blockers.
- Collapses raw transactions/activity/import logs behind drilldowns.

Acceptance:

- Tests prove current-position P&L is not labeled or calculated as lifetime/contribution P&L.
- Mobile/browser smoke verifies no overlap and useful trust-blocker display.

## Deferred Until Core Trust Exists

Do not dispatch these until VNEXT-01 through VNEXT-07 are accepted:

- Watchlist expansion.
- Alerts and thesis tracking.
- Advanced decision support.
- Advanced risk metrics.
- Benchmark ratio prominence.
- Calendar reports.
- Broader live Binance delta coverage beyond export-first categories.

## Dispatch Checklist

Before starting a ticket:

- [ ] Read `README.md`, `AGENTS.md`, `docs/current_state.md`, `docs/product_north_star.md`, this plan, and `docs/verification_matrix.md`.
- [ ] Confirm dependencies are complete.
- [ ] Confirm write set does not overlap with active agents.
- [ ] Confirm whether schema work requires the protected DB runbook.
- [ ] Write failing tests first.
- [ ] Run the ticket-specific verification command.
- [ ] Run broader gates required by `docs/verification_matrix.md`.
- [ ] Record skipped gates with a reason.
