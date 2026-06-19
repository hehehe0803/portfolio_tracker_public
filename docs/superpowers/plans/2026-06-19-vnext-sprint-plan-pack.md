# vNext Sprint Implementation Plan Pack

Status: draft implementation sketch for adversarial review and user approval.
Last updated: 2026-06-19.

This plan implements
`docs/superpowers/specs/2026-06-19-vnext-sprint-spec-pack.md`. It is not
permission to implement code until the relevant sprint spec is approved by the
user. If implementation discovers a schema, API, UI, product, privacy, or
protected-data decision outside the approved sprint section, stop and return to
the spec gate.

This file is non-dispatchable until the relevant sprint spec section is
approved. No dispatch record may cite this plan as implementation authority
while its matching spec section remains draft.

## Coordinator Protocol

For each sprint:

1. Confirm dependencies and user approval for that sprint section.
2. Publish a dispatch record with exact write set and blocked files.
3. Create a dedicated public-repo worktree/branch.
4. Write failing tests first.
5. Implement only inside the dispatch record.
6. Run targeted verification from `docs/verification_matrix.md`.
7. Run the broad gate required by changed areas.
8. Run adversarial PR review.
9. Fix concrete findings.
10. Merge only after verification, review, and CI agree.

All implementation branches target the public repository unless the user says
otherwise.

## Execution Order

1. `VNEXT-01D` task schema precursor and transfer matching.
2. Parallel lane A: `VNEXT-02A` capital truth.
3. Parallel lane B: `VNEXT-04A` historical anchors.
4. Parallel group after lanes A/B: `VNEXT-03A`, `VNEXT-05A`, `VNEXT-06A`.
5. `VNEXT-06B` after `VNEXT-03A`, `VNEXT-04A`, and `VNEXT-06A`.
6. `VNEXT-05B` after `VNEXT-05A`.
7. `VNEXT-07A` serialized API/shared contract.
8. Parallel frontend group: `VNEXT-07B` dashboard and `VNEXT-07C` asset detail.

## VNEXT-01D Plan

### Architecture

Split the sprint into two commits or two PRs if CI/runtime risk is high:

- `VNEXT-01D-0`: durable accounting task schema.
- `VNEXT-01D-1`: transfer matching service and reconciliation tests.

`accounting_reconciliation_tasks` is the durable unresolved-work queue.
Transfer matching reads staged movement evidence and writes one of:

- active `accounting_transfer_links` for proof-backed internal matches;
- open `accounting_reconciliation_tasks` for unmatched outgoing crypto;
- active external-cashflow classification only for source-policy defaults such
  as XTB external withdrawals or later explicit approvals.

Deterministic transfer links require exact source/destination identifiers or
authoritative control-total proof. Amount/date-only matches, fee/slippage
candidates, and multi-candidate matches create review tasks.

### Steps

1. Read `docs/local_prod_db_migration_runbook.md`.
2. Add RED DB tests for task table fields, lifecycle, idempotent active
   `task_id`, `task_key`, canonical decision back-reference, lifecycle, and
   resolution pointers.
3. Add model and migration for `accounting_reconciliation_tasks`.
4. Run `uv run pytest api/tests/db -q`.
5. Add RED reconciliation tests for matched Binance-to-Aster,
   matched Binance-to-Hyperliquid, unmatched outgoing crypto task, and XTB
   default withdrawal, ambiguous exact-amount/date-only candidate, and
   fee/slippage candidate.
6. Add `api/app/services/accounting_reconciliation.py` or equivalent.
7. Implement idempotent task creation and deterministic transfer-link writes.
8. Run `uv run pytest api/tests/reconciliation api/tests/db -q`.
9. Run `make feature-check` unless a narrower gate is explicitly accepted.

### Dispatch Shape

Exact write set:

- `api/app/db/models.py`
- `api/migrations/versions/`
- `api/tests/db/`
- `api/app/services/accounting_reconciliation.py`
- `api/tests/reconciliation/test_accounting_reconciliation.py`

Blocked:

- frontend
- shared contracts
- dashboard API
- private data and `portfolio_dev`

## VNEXT-02A Plan

### Architecture

Create a focused capital service that consumes canonical cashflow
classifications, transfer links, unresolved task materiality, cost-basis
decisions, source coverage, current-value control totals, and current value.
Keep Decimal math in the service. API exposure is deferred to VNEXT-07A unless
the user amends this sprint spec.

### Steps

1. Add RED analytics tests for deposits, withdrawals, net capital, first
   activity date, monthly averages, lifetime P&L, and blocked confidence.
2. Implement `api/app/services/accounting_capital.py`.
3. Do not add API/shared-contract exposure unless the user amends this sprint
   spec; VNEXT-07A owns the default API contract.
4. Run targeted analytics tests.
5. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/services/accounting_capital.py`
- `api/tests/analytics/test_accounting_capital.py`

Blocked:

- frontend
- portfolio API
- shared contracts
- migrations
- protected DB

## VNEXT-04A Plan

### Architecture

Create a historical value/confidence service that selects exact anchors before
reconstruction. Add narrow access helpers to `portfolio_state.py` and historical
price lookup seams only where needed. Return reason codes for missing prices,
coverage gaps, anchor conflicts, and current-value-trusted/history-untrusted
states.

### Steps

1. Add RED tests for exact anchor precedence and current-value/history split.
2. Add RED tests for missing price, missing transaction/source coverage, and
   anchor conflict.
3. Add historical value dataclasses/service.
4. Add portfolio-state anchor queries and historical price lookup seam.
5. Run `uv run pytest api/tests/pricing api/tests/analytics -q`.
6. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/services/accounting_history.py`
- `api/app/services/portfolio_state.py`
- `api/app/services/pricing.py`
- `api/tests/pricing/test_accounting_history_anchors.py`
- `api/tests/analytics/test_accounting_history.py`

Blocked:

- migrations
- frontend
- API/shared contracts unless separately approved

## VNEXT-03A Plan

### Architecture

Create a rolling performance service that depends on `accounting_capital` and
`accounting_history`. It should produce period objects with start/end boundary
confidence, deposits, withdrawals, investment gain, and reason codes.

### Steps

1. Add RED tests for 7D, 30D, and 90D output.
2. Add RED tests for deposit not gain and withdrawal not loss.
3. Add RED tests for missing anchor and unresolved cashflow degradation.
4. Implement `api/app/services/accounting_performance.py`.
5. Do not expose through API/shared contracts unless the user amends this sprint
   spec; VNEXT-07A owns the default API contract.
6. Run targeted analytics/pricing tests.
7. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/services/accounting_performance.py`
- `api/tests/analytics/test_accounting_performance.py`
- `api/tests/pricing/test_accounting_performance_boundaries.py`

Blocked:

- frontend
- portfolio API
- shared contracts
- calendar report views
- migrations

## VNEXT-05A Plan

### Architecture

Accounting review API is a durable decision workflow. It lists open
`accounting_reconciliation_tasks`, applies user decisions, writes canonical
state first, then writes audit/activity evidence, then resolves the task.

### Steps

1. Add RED API/service tests for task list and each decision type.
2. Add API request/response models for accounting task decision submission.
3. Implement `api/app/services/accounting_review.py`.
4. Implement a new accounting-review route or separated endpoints in review API.
5. Verify idempotent replay and audit-after-canonical ordering.
6. Run `uv run pytest api/tests/review/test_accounting_review_semantics.py api/tests/api/test_accounting_review.py api/tests/reconciliation/test_accounting_reconciliation.py api/tests/shared/test_contract_shapes.py -q`.
7. Run frontend shared-contract smoke for accounting-review request/response
   shapes.
8. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/services/accounting_review.py`
- `api/app/api/v1/review.py` or `api/app/api/v1/accounting_review.py`
- `api/app/main.py` only if a new route file is added
- `shared/python/contracts.py`
- `shared/typescript/contracts.ts`
- `api/tests/review/test_accounting_review_semantics.py`
- `api/tests/api/test_accounting_review.py`
- `api/tests/reconciliation/test_accounting_reconciliation.py`

Blocked:

- frontend
- investment review behavior changes
- schema beyond approved task table

## VNEXT-05B Plan

### Architecture

Build accounting review UI on top of VNEXT-05A. The page presents evidence,
choices, affected metrics, and unresolved evidence. It must not sound like an
investment recommendation and must not combine accounting tasks with watchlist
or hold/add/trim decisions.

### Steps

1. Add API binding tests/mocks for accounting task list and decision submit.
2. Add RED UI tests for list, choice submission, loading, empty, error,
   blocked, and resolved states.
3. Implement route and focused components.
4. Run frontend lint, typecheck, and targeted tests.
5. Run shared-contract smoke against the VNEXT-05A accounting-review contract.
6. Run browser/mobile smoke with screenshots or trace notes.
7. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `frontend/app/review/page.tsx` or new accounting-review route
- `frontend/components/accounting-review/`
- `frontend/lib/api.ts`
- `frontend/__tests__/accounting-review.test.tsx`

Blocked:

- backend API/schema changes
- dashboard page
- asset detail page

## VNEXT-06A Plan

### Architecture

Create a distribution service that consumes trusted current value and current
holdings. It should classify stablecoins as cash reserve, group asset types,
calculate totals with Decimal math, and control percentage display using scoped
confidence.

### Steps

1. Add RED tests for USDT/USDC cash classification.
2. Add RED tests for distribution reconciliation tolerance.
3. Add RED tests for weak-denominator percentage suppression.
4. Implement `api/app/services/accounting_distribution.py`.
5. Do not expose through API/shared contracts unless the user amends this sprint
   spec; VNEXT-07A owns the default API contract.
6. Run targeted analytics tests.
7. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/services/accounting_distribution.py`
- `api/tests/analytics/test_accounting_distribution.py`

Blocked:

- frontend
- portfolio API
- shared contracts
- migrations
- source automation

## VNEXT-06B Plan

### Architecture

Create a holding driver service that consumes rolling periods, historical
anchors, current/period holdings, and confidence. It returns top gainers,
losers, omitted low-confidence drivers, and no-data states.

### Steps

1. Add RED tests for positive and negative drivers.
2. Add RED tests for low-confidence flag/omit behavior.
3. Add RED tests for no-data state.
4. Implement `api/app/services/accounting_drivers.py`.
5. Do not expose through API/shared contracts unless the user amends this sprint
   spec; VNEXT-07A owns the default API contract.
6. Run targeted analytics tests.
7. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/services/accounting_drivers.py`
- `api/tests/analytics/test_accounting_drivers.py`

Blocked:

- frontend
- portfolio API
- shared contracts
- broad analytics refactor
- migrations

## VNEXT-07A Plan

### Architecture

Serialize API/shared-contract work. The portfolio API composes existing backend
services into dashboard and asset detail payloads. Shared Python and TypeScript
contracts define the public shape. UI work waits for this contract to land.

Recommended contract choices pending user approval:

- `GET /v1/portfolio/dashboard`
- `GET /v1/portfolio/assets/{symbol}`
- money values as decimal strings
- blocked values as `null` plus confidence/display state and reason codes

### Steps

1. Add RED API tests for trusted dashboard, provisional history, severe blocker,
   period fields, allocation/cash, drivers, and top accounting action.
2. Add RED API tests for asset detail current-position versus lifetime fields.
3. Update shared Python and TypeScript contracts together.
4. Implement route composition in `api/app/api/v1/portfolio.py`.
5. Run `uv run pytest api/tests/api -q`.
6. Run frontend shared-contract smoke.
7. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `api/app/api/v1/portfolio.py`
- `shared/python/contracts.py`
- `shared/typescript/contracts.ts`
- `api/tests/api/test_dashboard_contract.py`
- `api/tests/api/test_asset_detail_contract.py`
- frontend shared-contract smoke target

Blocked:

- frontend UI rewrites
- migrations
- protected DB

## VNEXT-07B Plan

### Architecture

Replace the first dashboard screen with contract-driven components. Keep chart
and money truth above raw logs. Use the dashboard payload display states
directly; do not recompute accounting confidence in React.

### Steps

1. Add/update dashboard fixtures for trusted and severe-blocked payloads.
2. Add RED tests for trusted state, blocked state, and absence of ambiguous P&L
   labels.
3. Implement contract API consumption and dashboard components.
4. Run frontend lint, typecheck, and targeted dashboard tests.
5. Run desktop/mobile browser smoke for first viewport and no overlap.
6. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `frontend/app/page.tsx`
- `frontend/components/dashboard/`
- `frontend/__tests__/dashboard.test.tsx`
- dashboard fixtures/snapshots

Blocked:

- API contract changes beyond VNEXT-07A
- asset detail route
- backend services

## VNEXT-07C Plan

### Architecture

Rebuild asset detail on the VNEXT-07A asset payload. Keep current-position
value/P&L primary and lifetime/contribution values explicitly separate and
confidence-controlled.

### Steps

1. Add asset-detail fixtures for trusted and blocked lifetime/contribution
   states.
2. Add RED tests for current-position P&L labels and calculations.
3. Add RED tests for lifetime/contribution display state and trust blockers.
4. Implement route/components.
5. Run frontend lint, typecheck, targeted tests, and mobile/browser smoke.
6. Run `make feature-check`.

### Dispatch Shape

Exact write set:

- `frontend/app/holdings/[symbol]/page.tsx`
- asset-detail components if split out
- `frontend/__tests__/asset-detail.test.tsx`

Blocked:

- dashboard page
- backend/API contract changes
- investment recommendation copy

## Parallel Dispatch Matrix

| Stage | Parallelizable | Serialization reason |
| --- | --- | --- |
| 1 | None | `VNEXT-01D` starts with schema. |
| 2 | `VNEXT-02A` and `VNEXT-04A` | Disjoint capital/history services after task schema. |
| 3 | `VNEXT-03A`, `VNEXT-05A`, `VNEXT-06A` | API/shared-contract writes are deferred to VNEXT-07A unless a sprint spec is amended. |
| 4 | `VNEXT-06B` and `VNEXT-05B` can overlap | Backend driver service and frontend review route are disjoint after dependencies. |
| 5 | None | `VNEXT-07A` serializes API/shared contracts. |
| 6 | `VNEXT-07B` and `VNEXT-07C` | Dashboard and asset-detail frontend write sets are separate. |

## Review Checklist

Use this checklist for spec/plan review and every implementation PR:

- Does any task infer personal withdrawal from crypto sign alone?
- Does any workflow write activity logs before canonical accounting state?
- Does any API expose one global confidence state instead of scoped states?
- Does any dashboard/UI label imply lifetime/all-time P&L when confidence is
  blocked or when the value is only current-position P&L?
- Does any service use floats for money?
- Does any test depend on private data or `portfolio_dev`?
- Does any parallel worker overlap migrations, shared contracts, or primary
  frontend routes?
- Does any route or UI copy mix accounting review with investment review?
