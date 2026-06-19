# vNext Verification Matrix

Status: source-of-truth acceptance contract.
Last updated: 2026-06-15.

Use this matrix to decide whether vNext work is complete. A ticket is not complete until its relevant gates pass and any skipped gate is explicitly justified.

## Permanent Gates

| Gate | Applies To | Required Evidence |
| --- | --- | --- |
| Diff hygiene | All work | `git diff --check` or a narrower equivalent for docs-only work |
| Worktree scope | All work | `git status --short` before and after; unrelated dirty files called out and not reverted |
| Docs-only scope | Docs work | `git diff --name-only -- README.md AGENTS.md docs` plus status note for unrelated dirty files |
| Planning artifact scope | Docs/superpowers planning work | `git diff --check -- .gitignore README.md AGENTS.md docs`; `git diff --name-only -- .gitignore README.md AGENTS.md docs`; `git status --short` proves new planning artifacts are tracked or intentionally ignored |
| Protected DB safety | Schema/migration/sync/destructive/Compose work | `docs/local_prod_db_migration_runbook.md` read; backup evidence when schema touches protected data; no destructive helper pointed at `portfolio_dev` |
| Test/smoke DB safety | Tests and smoke seeders | Database names contain `test` or `smoke`; reset helpers call `app.db.safety.assert_safe_destructive_database_url(...)` |
| Shared contract safety | API/frontend contract work | Python and TypeScript contracts updated together; frontend shared-contract smoke passes |
| Feature branch broad gate | Backend/frontend/migrations/scheduler/e2e-sensitive UI | `make feature-check` unless a narrower documented gate is explicitly accepted |

## Completion Language Rule

An agent may not claim a ticket is complete unless:

- Required tests have been run in the same turn/session.
- Output was read and exit code checked.
- Any skipped gate is named with the reason.
- Remaining risks are stated.

## Ticket Matrix

| Ticket | Required Behavior | Required Tests | Required Commands |
| --- | --- | --- | --- |
| VNEXT-00 | Hot path exists; stale orientation removed; broker fixture/data preserved; `portfolio_dev` untouched | Docs reference search has no stale hot-path targets | `git diff --check -- README.md AGENTS.md docs`; `find docs -maxdepth 3 -type f \( -name '*.md' -o -name '*.html' \) \| sort` |
| VNEXT-01A | Source/movement taxonomy exists without durable writes | Classification tests for Binance, XTB, Aster, Hyperliquid, tracked wallet, cash, commodities, USDT/USDC cash rule, crypto withdrawal not sign-only | Targeted pytest for taxonomy tests; `uv run pytest api/tests/analytics api/tests/reconciliation -q` if shared analytics touched |
| VNEXT-01B | Durable accounting state decisions are resolved before schema work | Product/plan/matrix route to the durable accounting state record with concrete durable shapes and no runtime changes | `git diff --check -- docs/product_north_star.md docs/implementation_plan.md docs/verification_matrix.md docs/architecture/durable_accounting_state_decision.md` |
| VNEXT-01C | Durable accounting state exists for transfer links, external-cashflow classifications, import approvals, manual cost basis/unknown decisions | DB model/migration tests for constraints and relationships | `uv run pytest api/tests/db -q`; migration smoke against safe test DB only |
| VNEXT-01D | Durable task schema exists; transfer matching creates internal movements; unknown outgoing creates tasks | Task table lifecycle/idempotency/resolution references; Binance-to-Aster/Hyperliquid match; ambiguous candidates create tasks; unmatched outgoing task; XTB default external withdrawal; internal transfer does not increase external capital | `uv run pytest api/tests/db api/tests/reconciliation -q`; schema work must read `docs/local_prod_db_migration_runbook.md`; migration smoke against safe test DB only |
| VNEXT-02A | Capital truth contract computes net capital, lifetime P&L, capital rhythm, confidence | Net capital with deposits/withdrawals; lifetime P&L does not use gross deposits; missing/uncertain capital marks stats provisional/blocked; severe issue hides/blocks sensitive stats | `uv run pytest api/tests/analytics api/tests/api/test_portfolio_summary.py -q` or exact new test paths |
| VNEXT-03A | Rolling 7D/30D/90D separates cashflows from investment gain | Deposit not gain; withdrawal not loss; missing anchor/low-confidence provisional; dashboard default 30D available | Targeted analytics/API tests for period contract |
| VNEXT-04A | Historical anchors and confidence are reliable | Exact snapshot preferred; reconstruction degrades on missing transaction/price; confidence affects visibility | `uv run pytest api/tests/pricing api/tests/analytics -q` or exact new test paths |
| VNEXT-05A | Reconciliation queue writes durable decisions and typed accounting-review contracts | Unknown outgoing task; internal transfer approval; personal withdrawal approval; import approval; manual cost basis/unknown; audit log after durable state; accounting-review Python/TypeScript contract smoke | `uv run pytest api/tests/review/test_accounting_review_semantics.py api/tests/api/test_accounting_review.py api/tests/reconciliation/test_accounting_reconciliation.py api/tests/shared/test_contract_shapes.py -q`; frontend shared-contract smoke for accounting-review request/response shapes |
| VNEXT-05B | Accounting review UI lets user resolve durable accounting tasks | Task list; choice submission; blocked/loading/error states; accounting review separated from investment review language | Frontend targeted tests; mobile/browser smoke evidence |
| VNEXT-06A | Asset-type distribution and cash reserve follow confidence rules | USDT/USDC cash; totals reconcile to trusted current value; weak denominator suppresses/flags percentages | Targeted analytics/API tests |
| VNEXT-06B | Holding drivers explain rolling movement with confidence | Positive driver; negative driver; low-confidence driver flagged/omitted; no-data state | Targeted analytics/API tests |
| VNEXT-07A | Dashboard and asset detail API contract is stable | API tests for trusted/severe states; shared Python/TypeScript contract smoke | `uv run pytest api/tests/api -q`; `(cd frontend && npm run typecheck:shared-contracts)` |
| VNEXT-07B | Dashboard first screen uses trusted contract and avoids ambiguous labels | Dashboard tests for trusted state, severe-blocked state, no ambiguous all-time/total P&L labels | `npm --workspace frontend run lint`; `npm --workspace frontend run typecheck`; targeted dashboard tests |
| VNEXT-07C | Asset detail separates current-position P&L from lifetime/contribution P&L | Asset detail tests for labels/calculations; mobile route smoke where relevant | Frontend targeted tests; mobile/browser smoke evidence |

## Detailed Acceptance Gates

### VNEXT-00: Docs Cleanup

Required behavior:

- Hot-path docs exist and are linked from orientation docs.
- Stale PRD/SRD/checklist/project-brain surfaces are not normal orientation.
- Broker fixture/data directories are preserved unless explicitly classified.
- `portfolio_dev` is untouched.

Required evidence:

- Docs diff hygiene passes.
- Stale hot-path reference search returns no actionable references.
- Remaining docs list is limited to hot path, runbooks, current superpowers artifacts, and explicitly kept references.

### VNEXT-01A: Source And Movement Taxonomy

Required behavior:

- External cashflows, internal movements, and trades/allocation are separate types.
- Binance, XTB, Aster, Hyperliquid, tracked wallets, cash, and commodities are represented where current data supports them.
- Crypto withdrawals are not classified by sign alone.
- USDT and USDC are cash reserve, not crypto exposure.

Required test examples:

- Binance external deposit.
- XTB withdrawal defaults external.
- Binance-to-Hyperliquid candidate is not external by sign alone.
- USDT/USDC classification returns cash.

### VNEXT-01B: Durable Accounting State Decision Record

Required behavior:

- Durable transfer link shape is explicitly decided.
- External-cashflow classification shape is explicitly decided.
- Import approval shape is explicitly decided.
- Manual cost basis and explicit unknown cost-basis storage are explicitly decided.
- Runtime code and migrations are not changed in this ticket.

Required evidence:

- Updated product/plan/matrix docs that route to
  `docs/architecture/durable_accounting_state_decision.md`.
- Open decisions removed or narrowed with a follow-up ticket.

### VNEXT-01C: Durable Accounting State

Required behavior:

- Durable state exists outside activity logs.
- Transfer links identify source and destination evidence.
- External-cashflow classifications are durable and auditable.
- Manual cost-basis or unknown decisions are durable and auditable.

Required evidence:

- Migration and model tests.
- Protected DB runbook evidence if a protected migration is run.

### VNEXT-01D: Transfer Matching

Required behavior:

- Durable accounting reconciliation tasks exist for unresolved outgoing crypto
  and later manual accounting work.
- Matched transfers among tracked venues/accounts/wallets do not increase external capital.
- Unknown outgoing crypto transfers create reconciliation tasks.
- Personal withdrawal remains an explicit decision path.

Required tests:

- Task table lifecycle, idempotency, structured evidence, and resolution
  references.
- Binance-to-Aster internal transfer match.
- Binance-to-Hyperliquid internal transfer match.
- Ambiguous exact-amount/date-only or fee/slippage candidates create review
  tasks rather than active transfer links.
- Unknown outgoing transfer creates task.
- Explicit personal withdrawal classification affects external withdrawals.

### VNEXT-02A: Capital Truth Contract

Required behavior:

- `net_capital_at_work = gross_deposits - gross_withdrawals`.
- `lifetime_pnl = current_portfolio_value - net_capital_at_work`.
- `avg_net_capital_added_per_month` uses elapsed months since `first_activity_date`.
- Gross deposits and withdrawals remain visible as context.
- Materiality and confidence flags degrade headline metrics.

Required tests:

- Net capital with deposit and withdrawal.
- Lifetime P&L does not use gross deposits as default denominator.
- Missing first activity date hides/provisionalizes monthly average.
- Severe issue hides or blocks lifetime P&L, return percentage, and period performance.

### VNEXT-03A: Rolling Period Performance

Required behavior:

- Dashboard default is rolling 30D.
- Rolling 7D and 90D are available.
- Period investment gain excludes deposits and withdrawals.
- Contributions, withdrawals, ending value, and investment gain/loss are separate outputs.

Formula under test:

```text
investment_gain = ending_value - starting_value - deposits + withdrawals
```

Required tests:

- Deposit inside period does not appear as investment gain.
- Withdrawal inside period does not appear as investment loss.
- Missing anchor marks period provisional.

### VNEXT-04A: Historical P&L Anchors And Confidence

Required behavior:

- Broker/account snapshots act as anchors.
- Reconstruction between anchors uses transactions and historical prices only when complete enough.
- Each date/period has confidence metadata.
- Gaps and low-confidence states are shown instead of pretending precision.

Required tests:

- Exact snapshot anchor preferred over reconstructed value.
- Reconstruction fails/degrades when required transactions/prices are missing.
- Confidence state changes derived metric visibility.

### VNEXT-05A: Manual Reconciliation Queue

Required behavior:

- Low-confidence transfers and missing cost basis create accounting tasks.
- Suggested choices can resolve as internal transfer, personal withdrawal, import missing data, manual cost basis, or unknown.
- Approvals write durable accounting state.
- Activity logs audit decisions but are not the only state.

Required tests:

- Unknown outgoing transfer creates task.
- Approving internal transfer writes transfer link and updates capital truth inputs.
- Approving personal withdrawal writes external-cashflow classification.
- Import approval persists durable import state.
- Activity log row is created after durable state.

### VNEXT-05B: Accounting Review UI

Required behavior:

- Accounting review tasks are visually and verbally separate from investment review tasks.
- Suggested choices are shown when backend provides them.
- Decisions submit to durable approval APIs.
- Confidence/materiality impact is visible.
- UI avoids recommendation language.

Required tests and smoke:

- Task list renders.
- Internal transfer choice submission.
- Personal withdrawal choice submission.
- Import missing data or manual cost basis choice submission.
- Blocked/loading/error states.
- Manual mobile/browser smoke verifies no overlap.

### VNEXT-06A: Structure And Distribution Analytics

Required behavior:

- Asset-type distribution uses crypto, stocks/ETFs, commodities, cash, and fallback other.
- USDT and USDC classify as cash.
- Cash is labeled as reserve/deployable cash, stablecoin reserve, or broker cash.
- Dollars appear before percentages.
- Percentages are hidden, downgraded, or marked unavailable when denominators are unreliable.
- Asset-type totals reconcile to trusted current value within `max(0.01 USD, current_portfolio_value * 0.0001)`.

Required tests:

- USDT/USDC excluded from crypto exposure and included in cash.
- Asset-type totals reconcile to trusted current value within documented tolerance.
- Weak denominator suppresses or flags percentage display.

### VNEXT-06B: Holding Drivers

Required behavior:

- Holding drivers are shown for rolling 7D, 30D, and 90D movement.
- Dollars lead percentages.
- Confidence state controls whether driver values are trusted, provisional, or hidden.

Required tests:

- Top positive driver.
- Top negative driver.
- Low-confidence driver is flagged or omitted.
- No-data state is explicit.

### VNEXT-07A: Dashboard And Asset Detail API Contract

Required behavior:

- First dashboard contract exposes current total value, 30D investment gain/loss, contributions/withdrawals split, lifetime P&L/net capital when allowed, confidence state, asset-type distribution, cash reserve, holding drivers, and top reconciliation action.
- Asset detail contract exposes current position/value, current-position P&L, capital allocated, lifetime contribution/P&L when allowed, recent movement, driver explanation, and trust blockers.

Required tests:

- Trusted dashboard contract.
- Severe accounting issue blocks/hides sensitive derived stats.
- Asset detail separates current-position and lifetime/contribution values.
- Shared contract smoke passes.

### VNEXT-07B: Dashboard UI

Required behavior:

- Primary screen uses trusted dashboard contract.
- Raw transactions/activity/import logs are collapsed behind drilldowns.
- Ambiguous all-time/total P&L labels are absent.
- Top reconciliation action is visible when material/severe.

Required tests and smoke:

- Dashboard test asserts no ambiguous all-time/total P&L labels.
- Dashboard test asserts severe accounting issues block/hide sensitive derived stats.
- Manual mobile/browser smoke verifies first-viewport truth, no overlap, and useful confidence/reconciliation action state.

### VNEXT-07C: Asset Detail UI

Required behavior:

- Current position/value and current-position P&L are primary.
- Lifetime/contribution P&L is separate and hidden/blocked when confidence requires.
- Trust blockers are visible.
- Raw logs are collapsed behind drilldowns.

Required tests and smoke:

- Asset detail test separates current-position P&L from lifetime/contribution P&L.
- Manual mobile/browser smoke verifies layout and trust-blocker display.
