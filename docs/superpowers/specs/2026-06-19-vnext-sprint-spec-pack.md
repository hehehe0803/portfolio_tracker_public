# vNext Sprint Spec Pack

Status: draft for adversarial review and user approval.
Last updated: 2026-06-19.

This pack applies the approved sprint gate design to the remaining vNext work.
It is intentionally sanitized for the public repository. It must not include
private account ids, broker exports, statements, local evidence filenames,
secrets, or protected database details.

Each sprint section is independently approvable. Approval of this pack does not
permit implementation that exceeds the scope, write set, or user decisions
listed here.

## Shared Architecture

vNext uses a layered accounting architecture:

1. Source evidence and parser output remain raw or staged evidence.
2. Canonical accounting state records semantic decisions:
   `accounting_transfer_links`,
   `accounting_external_cashflow_classifications`,
   `accounting_import_approvals`, and
   `accounting_cost_basis_decisions`.
3. Accounting reconciliation tasks represent unresolved decisions that need
   manual or later deterministic resolution.
4. Capital, historical anchor, rolling performance, distribution, and driver
   services consume canonical accounting state and scoped confidence.
5. API/shared contracts expose trusted values, blocked values, reasons, and
   actions without requiring UI clients to infer accounting decisions from raw
   logs.
6. Frontend surfaces consume the stable contracts and keep accounting review
   separate from investment review.

The public code already contains the four canonical decision tables from
VNEXT-01C. It does not contain a durable accounting task table. The unresolved
task model is therefore a real schema/product decision and must be approved
before VNEXT-01D implementation.

## Confidence And Materiality Decision

User approval of this pack also approves this single threshold table for vNext
implementation unless amended later:

| Level | Rule | Display effect |
| --- | --- | --- |
| `trusted` | No known material blocker for the scope. | Show normally. |
| `warning` | Issue amount is greater than `max(10 USD, 0.01% of portfolio value)` but does not affect current value, cash reserve, position existence, historical coverage, lifetime P&L, or period performance. | Show value with warning context. |
| `provisional` | Unresolved value is greater than `max(100 USD, 1% of portfolio value)` or source coverage is incomplete but not a hard block for the current scope. | Demote the value and show reason codes. |
| `review_required` | Semantic accounting decision is required before the scope can be trusted. | Route to the top accounting task. |
| `blocked` | Issue affects current value, cash reserve, position existence, historical coverage, lifetime P&L, period performance, asset-level lifetime contribution/P&L, or unresolved value is greater than `5% of portfolio value`. | Hide or block sensitive derived stats. |

Hard-block rules beat numeric thresholds. For example, an unresolved issue that
changes whether a position exists blocks affected current-value and asset-detail
scopes even if its USD amount is small.

## Global Non-Goals

- Do not touch `portfolio_dev`.
- Do not commit private data, broker exports, statements, credentials, cookies,
  account references, or local evidence filenames.
- Do not implement XTB browser automation or hidden endpoint capture in these
  sprints.
- Do not make investment recommendations.
- Do not make dashboard/UI work trust numbers that backend confidence marks as
  provisional, review-required, or blocked.
- Do not revive stale roadmap/checklist docs as implementation authority.

## VNEXT-01D: Transfer Matching And Unknown Outgoing Tasks

### Problem

Crypto withdrawals cannot be classified by sign alone. Matched Binance to Aster
or Hyperliquid transfers should become internal movements; unmatched outgoing
crypto movements should create accounting reconciliation tasks instead of
personal withdrawals.

### User Decision Required

Approve adding a focused durable table named
`accounting_reconciliation_tasks` before transfer matching service work.

Recommended shape:

- `id` stable primary id.
- `task_id` stable string id used by canonical decision `review_task_id`
  fields.
- `task_key` idempotency key.
- `task_type`, initially `unknown_outgoing_transfer`, with room for
  `missing_cost_basis`, `import_approval`, and `source_coverage_gap`.
- `status`: `open`, `resolved`, `superseded`, or `voided`.
- `severity`: `warning`, `provisional`, `review_required`, or `blocked`.
- `source`, `asset_symbol`, `quantity`, `amount_usd`, `occurred_at`.
- `evidence` structured reference, not private payload.
- `candidate_actions` JSON with internal transfer, personal withdrawal,
  import/cost-basis, and unknown choices when applicable.
- `affected_metric_scopes`.
- `resolved_by_decision_type` and `resolved_by_decision_id`.
- lifecycle/audit fields consistent with canonical accounting decisions.

Existing canonical decision tables store `review_task_id` as nullable strings.
VNEXT-01D must make `task_id` the stable string identifier for that field and
must test both directions: task resolution points to the canonical decision, and
the canonical decision points back to the resolving task.

Without this table, there is no approved durable state for unresolved tasks.
Using activity logs alone or writing `not_external_cashflow` as a placeholder is
not acceptable because it would confuse audit evidence with unresolved state.

### Scope

- Add durable accounting task schema, model, migration, and DB tests.
- Add focused transfer-matching service behavior that:
  - stages candidate matches from source evidence;
  - writes active transfer links only when the proof standard below is met;
  - writes open reconciliation tasks for unmatched outgoing crypto;
  - preserves explicit personal withdrawal as a later decision path.
- No public API is required in this sprint except test helpers or service seams.

### Writes

- `api/app/db/models.py`
- `api/migrations/versions/`
- `api/tests/db/`
- `api/app/services/accounting_reconciliation.py`
- `api/tests/reconciliation/test_accounting_reconciliation.py`

Blocked: frontend, shared contracts, broad dashboard API shape, private data,
`portfolio_dev`.

### Verifiable Subtasks

- RED DB test for `accounting_reconciliation_tasks` lifecycle, uniqueness, and
  structured evidence.
- Migration/model implementation for the task table.
- RED reconciliation tests for Binance-to-Aster match, Binance-to-Hyperliquid
  match, unmatched outgoing crypto task, and XTB default external withdrawal.
- RED tests for ambiguous exact-amount/date-only candidates and fee/slippage
  candidates that must create review tasks rather than active links.
- Service implementation that writes transfer links or tasks idempotently.
- Audit evidence after canonical state writes, if audit logging is in scope for
  the service operation.

### Acceptance

- Unknown outgoing crypto writes an open durable task.
- Matched internal movement writes an active transfer link only when exact
  source/destination identifiers or authoritative control-total proof make the
  link deterministic; amount/date-only or multi-candidate matches create review
  tasks instead.
- Active internal transfer links do not increase external capital.
- XTB withdrawal default external behavior remains covered.
- No frontend or shared-contract work lands.
- Protected DB runbook is read; no protected DB migration is run without a
  separate explicit approval.

## VNEXT-02A: Capital Truth Contract

### Problem

The app needs one canonical money contract for deposits, withdrawals, net
capital, capital rhythm, lifetime P&L, and confidence. Gross deposits must not
be treated as the default lifetime P&L denominator.

### Scope

- Add a focused capital truth service.
- Compute outputs from current value, canonical external-cashflow
  classifications, transfer links, import approvals, cost-basis decisions, and
  unresolved task/materiality state.
- Treat trusted current value as requiring latest holdings, broker cash,
  stablecoin reserve, and position existence to reconcile to authoritative
  current evidence or accepted import approvals.
- XTB daily PDFs and Gmail-discovered daily PDFs remain provisional fast-update
  evidence unless reconciled against full statements or equivalent control
  totals.
- Default to backend service only. API/shared-contract exposure is deferred to
  VNEXT-07A unless the user explicitly amends this sprint spec.

### Writes

- `api/app/services/accounting_capital.py` or equivalent focused module.
- `api/tests/analytics/test_accounting_capital.py`

Blocked: frontend layout, portfolio API, shared contracts, migrations unless a
missing approved field is found, private data, protected DB.

### Verifiable Subtasks

- RED tests for net capital with deposits and withdrawals.
- RED tests proving lifetime P&L uses current value minus net capital at work.
- RED tests for first activity date and monthly averages.
- RED tests proving severe unresolved issues block or hide sensitive stats.
- RED tests proving unreconciled broker cash, stablecoin reserve, or position
  existence prevents trusted current value and blocks sensitive derived stats.
- RED threshold-boundary tests for `warning`, `provisional`, `review_required`,
  and `blocked`.
- Service implementation with Decimal math and scoped confidence.
- API/shared-contract exposure requires a spec amendment or VNEXT-07A.

### Acceptance

- `net_capital_at_work = gross_deposits - gross_withdrawals`.
- `lifetime_pnl = current_portfolio_value - net_capital_at_work` when allowed.
- Gross deposits and gross withdrawals remain visible context.
- Material unresolved tasks degrade or block sensitive metrics.
- Current value cannot be trusted from current holdings alone when cash reserve
  or position-existence coverage is unresolved.

## VNEXT-04A: Historical P&L Anchors And Confidence

### Problem

Rolling performance, lifetime P&L, inception history, and asset-level lifetime
metrics need date anchors and scoped confidence. A trusted current value must
not imply trusted history.

### Scope

- Add a focused historical value/confidence service.
- Extend portfolio state access only for anchor queries and metadata needed by
  the service.
- Add historical price lookup seams that can fail with reason codes instead of
  silently using live/current prices.
- Keep source coverage and control-total support synthetic/testable unless
  separately approved for private evidence.

### Writes

- `api/app/services/accounting_history.py` or equivalent focused module.
- `api/app/services/portfolio_state.py` for small anchor-query helpers.
- `api/app/services/pricing.py` only for historical lookup seams.
- `api/tests/pricing/test_accounting_history_anchors.py`
- `api/tests/analytics/test_accounting_history.py`

Blocked: schema/migrations unless a later approved plan adds source coverage
state, public API contracts, frontend UI, protected DB.

### Verifiable Subtasks

- RED tests for exact snapshot preferred over reconstruction.
- RED tests for current value trusted while history/lifetime remains blocked or
  provisional.
- RED tests for missing historical price and missing coverage reason codes.
- RED tests for confidence propagation to sensitive metric visibility.
- Service implementation returning anchor source, value, confidence state, and
  reason codes.

### Acceptance

- Exact anchors beat reconstruction on the same date.
- Reconstruction only trusts complete ledgers, prices, coverage, and accounting
  decisions.
- Missing anchors/prices/cashflow classifications produce explicit confidence
  effects.

## VNEXT-03A: Rolling Period Performance

### Problem

The dashboard needs rolling 7D, 30D, and 90D performance where deposits do not
look like investment gain and withdrawals do not look like investment loss.

### Scope

- Add a rolling performance service that consumes VNEXT-02A capital truth and
  VNEXT-04A historical boundary anchors.
- Default to backend service only. API/shared-contract exposure is deferred to
  VNEXT-07A unless the user explicitly amends this sprint spec.
- Default dashboard period is 30D, with 7D and 90D available.

### Writes

- `api/app/services/accounting_performance.py` or equivalent focused module.
- `api/tests/analytics/test_accounting_performance.py`
- `api/tests/pricing/test_accounting_performance_boundaries.py`

Blocked: frontend implementation, portfolio API, shared contracts, and any
calendar-period report views.

### Verifiable Subtasks

- RED tests for deposit inside period not counted as gain.
- RED tests for withdrawal inside period not counted as loss.
- RED tests for missing start/end anchor provisional state.
- RED tests for unresolved cashflow inside period blocking trusted performance.
- Service implementation returning start/end values, deposits, withdrawals,
  investment gain, confidence, and reason codes.

### Acceptance

- Formula is `ending_value - starting_value - deposits + withdrawals`.
- 7D, 30D, and 90D are available.
- Low-confidence boundaries degrade the period instead of pretending precision.

## VNEXT-05A: Manual Reconciliation Queue With Durable Decisions

### Problem

Low-confidence evidence needs a user workflow that resolves accounting truth.
Approvals must write canonical accounting state before activity/audit logs.

### Scope

- Add accounting-review service operations around durable tasks and canonical
  decisions.
- Add API endpoints under a new accounting-review route or a clearly separated
  section of `api/app/api/v1/review.py`.
- If a new route file is used, route registration is in scope.
- Accounting-review request/response shapes are shared-contract surfaces
  because VNEXT-05B consumes them from frontend code.
- Resolve choices for internal transfer, personal withdrawal, import approval,
  manual cost basis, explicit unknown cost basis, and unknown/deferred.
- Frontend is out of scope.

### Writes

- `api/app/services/accounting_review.py` or equivalent focused module.
- `api/app/api/v1/review.py` or a new `api/app/api/v1/accounting_review.py`.
- `api/app/main.py` only if a new route file is added.
- `shared/python/contracts.py` and `shared/typescript/contracts.ts` for
  accounting-review request/response models.
- `api/tests/review/test_accounting_review_semantics.py`
- `api/tests/api/test_accounting_review.py`
- `api/tests/reconciliation/test_accounting_reconciliation.py`

Blocked: frontend UI, investment-review semantics, schema beyond the approved
task table and existing canonical decision tables.

### Verifiable Subtasks

- RED tests for listing open accounting tasks.
- RED tests for internal transfer approval writing transfer link first.
- RED tests for personal withdrawal approval writing cashflow classification.
- RED tests for import approval and manual/unknown cost-basis decisions.
- RED tests proving audit/activity log is written after canonical state.
- API implementation with idempotent decision requests.
- Shared-contract smoke proving frontend decision payloads cannot drift from
  backend accounting semantics.

### Acceptance

- API tasks are verbally and structurally accounting review, not investment
  review.
- Every approval writes canonical accounting state.
- Durable task status updates reference the resolved canonical decision.
- Python and TypeScript accounting-review contracts stay synchronized.

## VNEXT-05B: Accounting Review UI

### Problem

The user needs a clear accounting review workflow that resolves durable
accounting tasks without mixing them with investment review.

### Scope

- Build a dedicated accounting review route or a clearly partitioned accounting
  mode in the existing review route.
- Show what happened, why it matters, candidate choices, affected metrics, and
  remaining uncertainty.
- Submit decisions to VNEXT-05A APIs.
- Avoid recommendation language.

### Writes

- `frontend/app/review/page.tsx` or a new route such as
  `frontend/app/accounting-review/page.tsx`.
- focused components under `frontend/components/accounting-review/`.
- `frontend/lib/api.ts` if API bindings live there.
- `frontend/__tests__/accounting-review.test.tsx`.

Blocked: backend schema/API changes beyond consuming VNEXT-05A, dashboard UI,
investment recommendation copy.

### Verifiable Subtasks

- RED UI tests for accounting task list.
- RED UI tests for internal transfer and personal withdrawal choice submission.
- RED UI tests for import/cost-basis/unknown paths.
- RED UI tests for loading, empty, error, blocked, and resolved states.
- Browser/mobile smoke for no layout overlap and clear accounting/investment
  language separation.

### Acceptance

- Accounting tasks are separate from investment review.
- Choice submission calls durable approval APIs.
- Confidence/materiality effect is visible before confirmation.

## VNEXT-06A: Asset-Type Distribution And Cash Reserve

### Problem

After money truth exists, the app needs distribution analytics that classify
USDT/USDC as cash reserve, lead with dollars, and suppress weak percentages.

### Scope

- Add distribution service using trusted current value and confidence.
- Group into crypto, stocks/ETFs, commodities, cash, and other.
- Split cash reserve into stablecoin, broker cash, and other tracked cash when
  data supports it.
- Default to backend service only. API/shared-contract exposure is deferred to
  VNEXT-07A unless the user explicitly amends this sprint spec.

### Writes

- `api/app/services/accounting_distribution.py` or equivalent focused module.
- `api/tests/analytics/test_accounting_distribution.py`.

Blocked: frontend UI, portfolio API, shared contracts, and source automation.

### Verifiable Subtasks

- RED tests for USDT/USDC included in cash and excluded from crypto.
- RED tests for distribution totals reconciling to trusted current value within
  tolerance.
- RED tests for weak denominator suppressing/flagging percentages.
- Service implementation with Decimal math and confidence output.

### Acceptance

- Dollars lead percentages.
- Distribution trusted state requires reconciliation to current value.
- Cash reserve confidence is scoped.

## VNEXT-06B: Holding Drivers

### Problem

The dashboard needs explainable 7D, 30D, and 90D holding drivers without showing
low-confidence movement as precise.

### Scope

- Add driver service that consumes rolling periods, historical anchors,
  holdings, and confidence.
- Return positive drivers, negative drivers, no-data state, and reason codes.
- Default to backend service only. API/shared-contract exposure is deferred to
  VNEXT-07A unless the user explicitly amends this sprint spec.

### Writes

- `api/app/services/accounting_drivers.py` or equivalent focused module.
- `api/tests/analytics/test_accounting_drivers.py`.

Blocked: frontend UI, portfolio API, shared contracts, and broad analytics
refactors.

### Verifiable Subtasks

- RED tests for top positive driver.
- RED tests for top negative driver.
- RED tests for low-confidence driver flagged or omitted.
- RED tests for no-data state.
- Service implementation returning dollars first and optional percentages only
  when denominators are trusted.

### Acceptance

- Driver calculations respect period confidence.
- Low-confidence drivers are not shown as precise.
- No-data state is explicit.

## VNEXT-07A: Dashboard And Asset Detail API Contract

### Problem

Dashboard and asset detail UI need a stable API/shared contract that exposes
trusted values, blocked values, confidence, review actions, distribution, cash
reserve, and drivers.

### Scope

- Add a dashboard route and asset detail route under versioned portfolio API.
- Update shared Python and TypeScript contracts together.
- Include current total value, selected 30D period, available 7D/30D/90D
  periods, capital context, P&L display state, allocation, cash reserve,
  drivers, sources, review queue action, and drilldown links.
- Include source coverage/control-total confidence for current value, broker
  cash, stablecoin reserve, and position existence.
- Include asset detail current-position fields separately from lifetime or
  contribution fields.

### User Decision Required

Approve final route and model naming. Recommendation:

- `GET /v1/portfolio/dashboard`
- `GET /v1/portfolio/assets/{symbol}`
- money values serialized as decimal strings;
- blocked unavailable values serialized as `null` plus display/confidence state.

### Writes

- `api/app/api/v1/portfolio.py`
- `shared/python/contracts.py`
- `shared/typescript/contracts.ts`
- `api/tests/api/test_dashboard_contract.py`
- `api/tests/api/test_asset_detail_contract.py`
- `frontend/types/shared-contract-smoke.ts` or current shared-contract smoke
  target.

Blocked: frontend page rewrites, schema/migrations, private data.

### Verifiable Subtasks

- RED API tests for trusted current/provisional history dashboard payload.
- RED API tests for severe blockers hiding sensitive values.
- RED API tests proving XTB daily-PDF-only current evidence remains provisional
  and unresolved broker-cash/stablecoin/position-existence gaps block sensitive
  stats.
- RED API tests for asset detail separating current-position and lifetime
  fields.
- Shared contract updates in Python and TypeScript.
- Shared contract smoke proving frontend-consumable shape.

### Acceptance

- UI does not need raw logs to infer accounting state.
- Severe blockers hide or block sensitive derived stats.
- Current-value confidence is scoped separately from history, broker cash,
  stablecoin reserve, position existence, lifetime P&L, and rolling
  performance.
- Shared contracts stay synchronized.

## VNEXT-07B: Dashboard First Screen UI

### Problem

The first dashboard screen must become a trusted portfolio cockpit instead of a
log-heavy surface with ambiguous P&L labels.

### Scope

- Consume VNEXT-07A dashboard contract.
- Prioritize current value, rolling 30D investment gain/loss, contributions and
  withdrawals, lifetime P&L/net capital when allowed, trust state, distribution,
  cash reserve, drivers, and top accounting action.
- Collapse raw transactions, import rows, parser evidence, and activity logs
  behind drilldowns.

### Writes

- `frontend/app/page.tsx`
- `frontend/components/dashboard/`
- `frontend/__tests__/dashboard.test.tsx`
- dashboard fixtures/snapshots only when intentional.

Blocked: backend contract changes beyond using VNEXT-07A, asset-detail route,
investment recommendations.

### Verifiable Subtasks

- RED tests for trusted dashboard state.
- RED tests for severe-blocked state.
- RED tests asserting ambiguous all-time/total P&L labels are absent.
- Component implementation with stable responsive layout.
- Browser/mobile smoke for first viewport, no overlap, confidence visibility,
  and visible accounting action when material.

### Acceptance

- Chart-first first screen uses trusted contract.
- Sensitive values follow confidence state.
- Raw logs are not primary UI.

## VNEXT-07C: Asset Detail UI

### Problem

Asset detail must answer why the user selected an asset while separating current
position P&L from lifetime or contribution P&L.

### Scope

- Consume VNEXT-07A asset detail contract.
- Show current position/value, current-position P&L, capital allocated,
  lifetime/contribution P&L when allowed, recent movement, driver explanation,
  and trust blockers.
- Collapse raw logs behind drilldowns.

### Writes

- `frontend/app/holdings/[symbol]/page.tsx`
- asset-detail components if split out.
- `frontend/__tests__/asset-detail.test.tsx`.

Blocked: dashboard first-screen layout, backend contract changes beyond using
VNEXT-07A, investment recommendation copy.

### Verifiable Subtasks

- RED tests for current-position P&L label and value.
- RED tests for lifetime/contribution P&L separate display state.
- RED tests for trust blocker display.
- Component implementation with responsive route.
- Browser/mobile smoke for no overlap and clear trust blocker display.

### Acceptance

- Current-position P&L is never labeled as lifetime or contribution P&L.
- Sensitive asset-level lifetime/contribution values are hidden or blocked
  when confidence requires.
- Raw activity is drilldown-only.

## Parallelization Summary

After user approval, safe parallelization is:

- `VNEXT-01D` must start serialized because it adds task schema.
- After `VNEXT-01D`, `VNEXT-02A` and `VNEXT-04A` can run in parallel if their
  write sets remain disjoint.
- After both `VNEXT-02A` and `VNEXT-04A`, `VNEXT-03A`, `VNEXT-05A`, and
  `VNEXT-06A` can run in parallel because API/shared-contract writes are
  deferred to VNEXT-07A unless a sprint spec is amended.
- After `VNEXT-03A`, `VNEXT-04A`, and `VNEXT-06A`, `VNEXT-06B` can run.
- After `VNEXT-05A`, `VNEXT-05B` can run.
- `VNEXT-07A` is serialized shared-contract/API work.
- After `VNEXT-07A`, `VNEXT-07B` and `VNEXT-07C` can run in parallel because
  their frontend write sets are separate.

## Manual Gates

The user must approve before:

- Adding `accounting_reconciliation_tasks`.
- Choosing route/model names for VNEXT-07A.
- Starting frontend workflow work that changes review or money-truth copy.
- Running any protected local-production DB operation.
- Starting implementation of any sprint section whose open decision remains
  unresolved.
