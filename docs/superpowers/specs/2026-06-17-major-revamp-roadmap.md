# Portfolio Tracker Major Revamp Roadmap

Status: proposed execution roadmap.
Last updated: 2026-06-17.

This roadmap refines the hot-path vNext docs after product/UX discovery. It does not replace `docs/product_north_star.md`, `docs/roadmap.md`, `docs/implementation_plan.md`, or `docs/verification_matrix.md`; it is the working multi-sprint orchestration map for the next major revamp phase.

## Goal

Build a chart-first portfolio performance cockpit backed by trustworthy current value, staged/provisional historical truth, and clear downstream workflows for reconciliation, asset explanation, watchlist/checkpoints, and operations.

Implementation must not start until the user approves the sprint plan. No implementation code is in this document.

## Product Diagnosis

The backend has useful trusted-contract foundations, but the user-facing product is not yet coherent enough. The dashboard currently under-emphasizes the values the user cares about: total portfolio, inception chart, rolling/inception gain/loss, lifetime P&L/net capital, holding drivers, cash reserve, and clear data confidence. Existing review/import surfaces expose implementation details more than guided decisions.

The revamp should stop treating reconciliation as the app identity. Reconciliation is a supporting phase that cleans data so the dashboard can become useful. The final product shape is:

- Portfolio performance cockpit.
- Data cleanup and reconciliation workflow.
- Asset detail and driver explanation workflow.
- Investment decision desk for watchlist, entry/exit checkpoints, thesis, alerts, and reviews.
- Operations surface for imports, automation, scheduler/runtime, security, migrations, and verification.

## UX Direction

### Information Architecture

Primary app areas:

1. **Portfolio**: total value, inception chart, net capital, investment P&L, rolling performance, allocation, cash reserve, top drivers, confidence.
2. **Assets**: asset detail, driver explanation, current position, current-position P&L, lifetime/contribution P&L when trusted, evidence drilldowns.
3. **Watchlist**: entry/exit/review checkpoints, thesis tracking, target prices, later alerts.
4. **Ops**: imports, XTB refresh, automation status, scheduler health, data quality, migrations/runbooks, secrets/security posture.

The navigation may later use a compact single-button expansion pattern, but that is a design-system/polish item requiring accessibility and reduced-motion handling.

### Dashboard Model

Chosen model: **Chart-first Portfolio Performance Cockpit**.

The first screen should answer:

- What is my total portfolio worth?
- How has it changed from inception?
- How much is net capital at work?
- What is true investment P&L/gain-loss, separate from deposits and withdrawals?
- What changed recently?
- What drove the change?
- Can I trust current value, cash reserve, history, and P&L?
- What workflow should I open next?

Default chart:

- Primary line: total portfolio value from inception.
- Companion line: net capital at work.
- Investment P&L/gain-loss shown in headline/stat context.
- Deposits and withdrawals shown as hover/drilldown markers, not noisy default clutter.

MVP confidence split:

- Current portfolio value can become trusted before full history is reconciled.
- Inception chart, lifetime P&L, net capital, and historical return may stay provisional until full historical coverage is reconciled.
- Dashboard must visibly separate current value confidence, historical confidence, cash reserve confidence, and P&L/return confidence.

### Mockup Direction Ledger

UI/UX decisions should use mockups when the decision is visual or flow-spatial. Planning that is mostly backend, orchestration, or policy does not require mockups unless a diagram would clarify the decision.

Validated dashboard direction from the planning mockups:

- **Chart-first wins.** The first screen should feel like "my portfolio story from inception" rather than a dense operations table.
- **Desktop and mobile are both first-class.** Each dashboard UI sprint needs desktop and mobile acceptance evidence, including no-overlap checks and screenshots/smoke.
- **Primary hierarchy:** total portfolio value, all-time investment P&L, inception chart, net capital line, rolling stats, cash reserve, top drivers, and confidence.
- **Below-chart hierarchy:** stats first, then calls to action, then top gain/loss drivers and filters.
- **Driver display:** use top 5 gain and top 5 loss, not a single top driver.
- **Calls to action:** include actions such as add checkpoint, review watchlist, inspect movement, and refresh XTB data. Exact presentation is undecided: box cards, action rail, command bar, or contextual floating actions need a later mockup pass.
- **Filters:** filter UX is intentionally deferred. Later mockups should decide whether filters apply to the chart, drivers, asset table, or all of them. Candidate filters include type, sector, tags, venue, and conviction.
- **Navigation concept:** a compact single-button nav that expands into Portfolio, Assets, Watchlist, and Ops is promising but belongs in the UI/theme/design-system lane. It requires accessibility, keyboard behavior, and reduced-motion behavior.
- **Visual style:** dense, calm, operational finance tool. Avoid marketing-page composition, hero-page framing, decorative cards, and raw log surfaces as the product center.

Deferred UI decisions that must not be forgotten:

1. CTA presentation pattern.
2. Filter placement and scope.
3. Expandable nav animation.
4. Theme, typography, spacing, chart treatment, icons, and motion.
5. Reference scouting from high-quality finance/product interfaces.

### Progressive Disclosure

Raw logs, import rows, transactions, and parser evidence are supporting evidence. They belong behind explicit drilldowns. Primary surfaces should show decisions, explanations, and effects.

### Decision Design

Review flows must answer:

- What happened?
- Why does it matter?
- What are my choices?
- What changes if I choose each option?
- What happens after I confirm?
- What remains unresolved?

Auto-repair is allowed only when deterministic and provable. Ambiguous or semantic decisions must be staged for user review or agent-guided manual resolution.

## Reconciliation Strategy

The user prefers **zero wrong committed decisions** over aggressive automation.

Definitions:

- **False positive**: the app auto-classifies or repairs something incorrectly.
- **False negative**: the app marks data trusted/complete while a real blocker remains.

Strict zero false negatives require authoritative control totals, not just row parsing. The plan must therefore add coverage reconciliation against broker/source totals.

Rules:

- Staged evidence first; canonical accounting state later.
- Auto-detect before auto-decide.
- Auto-commit only deterministic mechanical corrections such as exact duplicate fingerprints, timestamp normalization, and exact statement-row parsing.
- Do not auto-classify crypto withdrawals as personal withdrawals.
- Do not silently assume missing XTB cash activity.
- Do not mark historical/inception metrics trusted until coverage checks pass.
- All proposals must be reversible/auditable.

Control totals required where available:

- Position quantities by statement date.
- Broker cash balance by statement date.
- Deposits and withdrawals.
- Trades.
- Dividends and other cash operations.
- Fees, taxes, swaps, commissions, corporate actions.
- Import coverage by date range.

## Truth States

Recommended confidence states:

- **Trusted current**: latest holdings/current value reconcile to authoritative source or a deterministic current snapshot.
- **Trusted history**: historical positions, cash, cashflows, dividends, trades, and control totals reconcile over the relevant period.
- **Provisional**: usable for exploration, but not for final lifetime P&L, inception return, or trusted chart claims.
- **Review required**: a semantic decision or material gap remains.
- **Blocked**: current total value, cash reserve, position existence, or sensitive derived stats may be wrong.

Suggested thresholds:

- Cash and statement reconciliation: exact to broker currency precision.
- Portfolio distribution reconciliation: `max(0.01 USD, current_portfolio_value * 0.0001)`.
- Material warning: unresolved amount greater than 10 USD or 0.01% of portfolio value.
- Hard block: any unresolved issue affecting current value, cash reserve, lifetime P&L, position existence, or historical coverage.

## XTB Source Strategy

Current `main` already contains:

- Manual XTB upload for `.xlsx`, `.html`, `.mhtml`, `.mht`.
- XTB daily PDF parsing for executed trades.
- Gmail attachment discovery for encrypted XTB daily PDFs.
- Import preview/confirm flow.

Known issue:

- XTB broker cash can be overstated when stock buys do not consume USD cash. This fix is not confirmed merged to `main` and must be treated as required work.

Automation candidates:

1. **Manual/full statement export**: safest source of truth and baseline for historical reconciliation.
2. **Browser automation**: use Playwright/browser tooling to download full statements through the authenticated XTB UI; supports manual MFA gate and visual debugging.
3. **Captured export endpoint**: inspect the browser network flow and, if stable, call a hidden statement/export endpoint with local session cookies/tokens.
4. **Gmail daily PDFs**: useful for near-real-time trade updates, but not authoritative alone because dividends, cash operations, corporate actions, or full cash ledger data may be missing.

Recommended approach:

- Use full statements as authoritative source.
- Use email/PDF automation only as provisional fast updates.
- Discover browser automation first, then endpoint capture.
- Store credentials, cookies, and downloaded statements only in ignored local data/secret storage.
- Import automation must still create staged previews before canonical commits.

## Sprint Roadmap

### Sprint 0: Revamp Planning And Coordination

**User problem:** The revamp needs an executable plan that multiple agents can run without drifting into stale docs or overlapping writes.

**Scope:**

- Capture product diagnosis, UX direction, reconciliation policy, XTB strategy, and sprint lanes.
- Define dispatch rules, dependencies, write-lock risks, acceptance, and review gates.
- Produce the first implementation plan for the next sprint only.

**Non-goals:**

- No runtime code.
- No migrations.
- No protected DB access.

**Dependencies:** Current hot-path docs and user decisions from 2026-06-17 planning.

**Likely write set:**

- `docs/superpowers/specs/2026-06-17-major-revamp-roadmap.md`
- `docs/superpowers/plans/2026-06-17-reconciliation-mvp-plan.md`

**Parallelization/write-lock risks:** Docs-only. Do not edit hot-path docs unless user asks to promote this roadmap.

**Acceptance criteria:**

- Roadmap includes all requested lanes.
- First sprint plan has exact file/module ownership, dependencies, acceptance, verification, and review gates.
- No implementation code.

**Verification commands:**

- `git diff --check -- docs/superpowers/specs/2026-06-17-major-revamp-roadmap.md docs/superpowers/plans/2026-06-17-reconciliation-mvp-plan.md`
- `git status --short --branch`

**Manual review checklist:**

- User confirms sprint order.
- User confirms zero-wrong reconciliation policy.
- User confirms provisional inception/history for MVP.

**Needs user review before implementation:** Yes.

### Sprint 1: Reconciliation MVP And XTB Truth Split

**User problem:** The app needs trusted current value and honest provisional history before a chart-first dashboard can be credible.

**Scope:**

- Inventory source coverage.
- Define staged evidence vs canonical accounting state.
- Fix XTB cash-consumption behavior.
- Define confidence split for current value, cash reserve, history, and P&L.
- Produce trusted/provisional dashboard input contracts.

**Non-goals:**

- No full visual dashboard rebuild.
- No watchlist/checkpoint implementation.
- No hidden XTB endpoint automation commit.
- No protected DB migration without runbook approval.

**Dependencies:**

- Sprint 0 approval.
- Current taxonomy/import foundations.
- Protected DB migration runbook if schema work enters scope.

**Likely owned files/modules:**

- `api/app/services/xtb_ingest.py`
- `api/app/services/xtb_parser.py`
- `api/app/services/analytics.py`
- New focused service under `api/app/services/` for XTB cash ledger or reconciliation coverage.
- `api/app/api/v1/portfolio.py` only after contract shape is defined.
- `shared/python/contracts.py`
- `shared/typescript/contracts.ts`
- `api/tests/xtb/`
- `api/tests/analytics/`
- `api/tests/api/`
- `docs/architecture/` or `docs/superpowers/specs/` for reconciliation policy if needed.

**Parallelization/write-lock risks:**

- XTB source inventory can run in parallel with UI/theme research.
- XTB cash ledger implementation must not overlap broad edits to `analytics.py`.
- Shared contract changes are serialized.
- Schema/migration work is serialized.

**Acceptance criteria:**

- XTB source coverage matrix exists.
- XTB stock buys consume USD cash in tests.
- XTB sells/dividends/fees/cash operations update broker cash correctly in tests.
- Current value can be trusted independently from provisional history.
- Inception/history metrics carry explicit confidence.
- No semantic auto-repair happens without approval or deterministic proof.

**Verification commands:**

- `uv run pytest api/tests/xtb -q`
- Targeted analytics/API tests for new contracts.
- `(cd frontend && npm run typecheck:shared-contracts)` if shared contracts change.
- `git diff --check`

**Manual review checklist:**

- Review XTB source coverage matrix.
- Review confidence labels and threshold policy.
- Review any proposed schema/contract shape before implementation.

**Needs user review before implementation:** Yes, for sprint plan. Also yes for any schema or hidden-endpoint automation decision.

### Sprint 2: XTB Automation Discovery

**User problem:** Manual XTB refresh is friction, but automated email-only trade confirmations may miss dividends and cash operations.

**Scope:**

- Explore browser automation for full statement export.
- Explore captured export endpoint/curl path only after browser flow is understood.
- Define credential/session/cookie storage policy.
- Produce automation runbook and prototype evidence.
- Compare full statement export vs daily PDF/Gmail coverage.

**Non-goals:**

- No trusted canonical import without preview/staging.
- No credentials in repo.
- No brittle hidden API hardcoding without runbook.

**Dependencies:**

- Sprint 1 coverage definitions.
- Browser automation tooling and manual user approval for any login/MFA interaction.

**Likely owned files/modules:**

- New script under `scripts/` or `infra/` only after design approval.
- `docs/` runbook for XTB automation.
- Tests/mocks for downloaded fixture handling.

**Parallelization/write-lock risks:**

- Can run parallel to UI/theme scouting.
- Must not overlap import commit semantics work.

**Acceptance criteria:**

- Documented comparison of manual export, browser automation, endpoint capture, and Gmail PDFs.
- Proof of whether full statement includes trades, dividends, cash operations, fees, positions, and balances.
- Runbook for safe local operation.
- Clear fallback when automation fails.

**Verification commands:**

- Runbook-specific dry run only against ignored local data.
- No protected DB writes.
- `git diff --check -- docs scripts infra`

**Manual review checklist:**

- User approves automation approach.
- User approves credential/session handling.
- User approves any manual MFA gate.

**Needs user review before implementation:** Yes.

### Sprint 3: Dashboard MVP Contracts

**User problem:** The chart-first dashboard needs stable data contracts that allow trusted current value and provisional history without lying.

**Scope:**

- Dashboard contract for current value, inception series, net capital line, investment P&L, confidence states, cash reserve, top gain/loss drivers, and data gaps.
- Asset-type distribution and cash reserve contract if not already landed.
- Provisional/blocked handling for lifetime P&L and historical chart.

**Non-goals:**

- No final dashboard theme polish.
- No watchlist/checkpoint flow.
- No complex filters unless metadata exists.

**Dependencies:**

- Sprint 1 confidence split.
- Shared contract serialization after API shape settles.

**Likely owned files/modules:**

- `api/app/api/v1/portfolio.py`
- Focused analytics services under `api/app/services/`
- `shared/python/contracts.py`
- `shared/typescript/contracts.ts`
- `api/tests/api/`
- `api/tests/analytics/`
- `frontend/types/shared-contract-smoke.ts`

**Parallelization/write-lock risks:**

- Shared contracts serialized.
- API route changes must not overlap with Sprint 1 contract edits.

**Acceptance criteria:**

- Current trusted and history provisional states are both represented.
- Severe current-value blockers hide/block sensitive stats.
- Inception chart can render provisional data with explicit confidence.
- Top 5 gain and top 5 loss drivers can be represented.

**Verification commands:**

- `uv run pytest api/tests/api api/tests/analytics -q`
- `(cd frontend && npm run typecheck:shared-contracts)`
- `git diff --check`

**Manual review checklist:**

- User reviews displayed confidence semantics.
- User reviews which fields are MVP vs later.

**Needs user review before implementation:** Yes.

### Sprint 4: Chart-First Dashboard UI MVP

**User problem:** The first screen must feel like a portfolio performance cockpit, not a log browser.

**Scope:**

- Chart-first desktop and mobile dashboard.
- Total value, inception chart, net capital line, investment P&L, rolling 30D stat, cash reserve, confidence labels.
- Below-chart zone with CTAs and top gain/loss drivers.
- Raw evidence collapsed.

**Non-goals:**

- No final CTA/filter treatment until separate mockup approval.
- No full theme overhaul.
- No expandable nav implementation unless design-system lane approves it.

**Dependencies:**

- Sprint 3 dashboard contract.
- UI mockup approval for first-screen layout.

**Likely owned files/modules:**

- `frontend/app/page.tsx`
- `frontend/components/dashboard/`
- `frontend/lib/api.ts`
- `frontend/__tests__/dashboard.test.tsx`
- `frontend/e2e/` if smoke coverage exists.

**Parallelization/write-lock risks:**

- Must not overlap frontend design-system refactor in same files.
- CTA/filter components should wait for design decision.

**Acceptance criteria:**

- Desktop and mobile first viewport show chart-first hierarchy.
- No ambiguous "total/all-time P&L" labels.
- Current vs historical confidence is visible.
- Top 5 gain/loss driver section exists or has clear MVP placeholder from contract.
- Raw logs are not primary.

**Verification commands:**

- `npm --workspace frontend run lint`
- `npm --workspace frontend run typecheck`
- Targeted dashboard tests.
- Browser/mobile screenshots or Playwright smoke.

**Manual review checklist:**

- User reviews desktop and mobile screenshots.
- User reviews confidence wording.
- User reviews CTA/filter placeholders before later polish.

**Needs user review before implementation:** Yes.

### Sprint 5: Review Workflow UX

**User problem:** When data cleanup needs human input, the review screen must guide decisions rather than show raw queues.

**Scope:**

- Accounting cleanup workflow.
- Show event, why it matters, choices, effect, confirm outcome, and remaining unresolved items.
- Separate accounting cleanup from investment review.

**Non-goals:**

- No investment decision desk.
- No social/news/recommendation features.

**Dependencies:**

- Sprint 1 policy.
- Durable decision state from existing or new schema.
- UI mockup for review flow.

**Likely owned files/modules:**

- `api/app/api/v1/review.py`
- `api/app/services/import_review.py`
- Reconciliation services under `api/app/services/`
- `frontend/app/review/page.tsx`
- `frontend/lib/api.ts`
- `frontend/__tests__/review-page.test.tsx`

**Parallelization/write-lock risks:**

- Backend durable state serialized with schema.
- Frontend review page must not overlap investment review UI work.

**Acceptance criteria:**

- No user prompt is required for deterministic facts.
- Ambiguous/material cases show effect on cash, chart, P&L, and confidence.
- Decisions write durable state before audit logs.
- Review screen has loading, error, no-data, blocked, and success states.

**Verification commands:**

- `uv run pytest api/tests/review api/tests/reconciliation api/tests/api/test_review_queue.py -q`
- Frontend targeted review tests.
- Desktop/mobile browser smoke.

**Manual review checklist:**

- User reviews wording and decision choices.
- User reviews whether any actions should remain agent-guided/manual.

**Needs user review before implementation:** Yes.

### Sprint 6: Asset Detail And Driver Explanation

**User problem:** Clicking a holding or driver should explain why it matters and how it affected the portfolio.

**Scope:**

- Asset detail navigation from dashboard.
- Current position/value.
- Current-position P&L separate from lifetime/contribution P&L.
- Recent movement and driver explanation.
- Trust blockers and evidence drilldowns.

**Non-goals:**

- No watchlist/checkpoint authoring yet.
- No benchmark-heavy analysis on first version.

**Dependencies:**

- Sprint 3 dashboard/asset contract.
- Sprint 4 dashboard entry points.

**Likely owned files/modules:**

- `frontend/app/holdings/[symbol]/page.tsx`
- Asset-detail components under `frontend/components/`
- `api/app/api/v1/portfolio.py`
- Shared contracts if asset detail shape changes.
- Frontend asset/mobile tests.

**Parallelization/write-lock risks:**

- Can run after dashboard contract lands.
- Must avoid overlapping shared contract edits.

**Acceptance criteria:**

- Asset detail distinguishes current-position P&L from lifetime/contribution P&L.
- Driver explanation connects to selected period.
- Trust blockers are visible and actionable.
- Raw rows are drilldowns.

**Verification commands:**

- Frontend targeted asset tests.
- Shared contract smoke if contracts change.
- Desktop/mobile smoke.

**Manual review checklist:**

- User reviews asset detail UX mockup before implementation.

**Needs user review before implementation:** Yes.

### Sprint 7: Watchlist And Checkpoints

**User problem:** The app should support future investment decisions such as entry, trim, exit, review, and thesis checkpoints.

**Scope:**

- Define checkpoint model.
- Watchlist/checkpoint workflow.
- Link from dashboard CTAs and asset detail.
- Basic states for active, triggered, snoozed, archived.

**Non-goals:**

- No alerts infrastructure unless prerequisite exists.
- No advanced risk/thesis system in MVP.

**Dependencies:**

- Sprint 6 asset detail.
- Metadata/tag model decision.
- UI mockup for checkpoint workflow.

**Likely owned files/modules:**

- Existing notes/tags/watchlist surfaces.
- New API/service/model files only after schema decision.
- `frontend/app/watchlist/` or existing route.
- Frontend tests.

**Parallelization/write-lock risks:**

- Schema serialized.
- Watchlist frontend must not overlap dashboard CTA implementation until CTA route is fixed.

**Acceptance criteria:**

- User can define a checkpoint with asset, trigger, reason, and action.
- Checkpoints are visible from watchlist and relevant asset detail.
- No investment advice language.

**Verification commands:**

- API tests if backend changes.
- Frontend targeted tests.
- Browser/mobile smoke.

**Manual review checklist:**

- User reviews checkpoint vocabulary and workflow.

**Needs user review before implementation:** Yes.

### Sprint 8: UI Theme And Frontend Stack Foundation

**User problem:** Without explicit UI vision and frontend stack choices, implementation can become clanky.

**Scope:**

- Audit current frontend stack, charting package, styling approach, icons, component boundaries, responsive patterns, animation support, accessibility, and screenshot tooling.
- Define UI design principles: dense, calm, operational, finance-oriented, chart-first, mobile/desktop first-class.
- Scout high-quality finance/product interfaces and extract concrete patterns.
- Decide whether to keep, replace, or add chart/UI packages.

**Non-goals:**

- No broad visual refactor until data contracts are stable.
- No marketing-page redesign.

**Dependencies:**

- Can start after Sprint 0.
- Use current frontend only; external docs require `ctx7` per `AGENTS.md` if package/API questions arise.

**Likely owned files/modules:**

- Docs/design notes first.
- Potential later changes to `frontend/components/`, `frontend/app/globals.css`, package config, and test tooling only after approval.

**Parallelization/write-lock risks:**

- Research/docs can run parallel to backend reconciliation.
- Runtime frontend package changes serialized with dashboard UI implementation.

**Acceptance criteria:**

- Frontend stack audit exists.
- Reference scouting output lists reusable patterns, not screenshots for their own sake.
- Recommended charting/theming/animation approach is approved before implementation.

**Verification commands:**

- Docs diff hygiene for research outputs.
- Frontend lint/typecheck only if code changes later.

**Manual review checklist:**

- User reviews taste references and UI direction.
- User approves any package changes.

**Needs user review before implementation:** Yes.

### Sprint 9: Ops, Runtime, Security, And CI Readiness

**User problem:** The app should be reliable locally after restart and safe for automation, secrets, migrations, and fresh-session agent work.

**Scope:**

- Docker/local app always-on after machine restart.
- Worker/scheduler reliability and observability.
- Security/auth/secrets hardening.
- Database migration/runbook readiness.
- CI/verification/fresh-session readiness.

**Non-goals:**

- No destructive tests or migrations against `portfolio_dev` without runbook approval.

**Dependencies:**

- Runtime decisions from automation and scheduler work.
- Protected DB runbook for schema/migration work.

**Likely owned files/modules:**

- `infra/`
- `worker/`
- `scripts/`
- `.env.example`
- Docs runbooks.
- CI config if present.

**Parallelization/write-lock risks:**

- Infra/runtime changes can conflict with active dev servers and protected DB.
- Schema/migration serialized.

**Acceptance criteria:**

- Local runtime has clear startup/restart runbook.
- Worker/scheduler has observable health/failure states.
- Secrets are documented without being committed.
- Fresh-session verification is reproducible without private data.

**Verification commands:**

- `make feature-check` where applicable.
- Runtime-specific smoke in safe test/smoke DB.
- `git diff --check`.

**Manual review checklist:**

- User approves any always-on local runtime behavior.
- User approves any protected DB operation.

**Needs user review before implementation:** Yes.

## Parallelization Map

Can run after Sprint 0 approval:

- Sprint 1 source coverage discovery.
- Sprint 8 UI/theme research.
- Parts of Sprint 9 docs/runbook audit.

Must be serialized:

- Schema/migration changes.
- Shared contract changes.
- Broad edits to `api/app/services/analytics.py`.
- Dashboard UI edits touching the same files.
- Any protected DB operation.

Recommended first execution order:

1. Sprint 1: Reconciliation MVP and XTB truth split.
2. Sprint 8: UI theme/frontend stack foundation in parallel as research only.
3. Sprint 2: XTB automation discovery once source coverage is clear.

Then:

4. Sprint 3 dashboard contracts.
5. Sprint 4 dashboard UI MVP.
6. Sprint 5 review workflow if unresolved decisions remain.
7. Sprint 6 asset detail.
8. Sprint 7 watchlist/checkpoints.
9. Sprint 9 ops/security/CI as ongoing hardening lanes.

## Open Questions For User

1. Which XTB automation path should be explored first after source coverage: browser automation, endpoint capture, or both sequentially?
2. Should dashboard MVP show provisional inception chart as the default chart, or should it default to trusted current/rolling history until enough inception data is reconciled?
3. What is the preferred wording for provisional history: "history reconciling", "provisional history", "incomplete history", or another phrase?
4. Which UI references should be scouted first: Robinhood-like broker apps, professional portfolio analytics tools, or high-taste SaaS dashboards?
5. For watchlist/checkpoints, should first MVP support only manual checkpoint creation, or also auto-suggest checkpoints from current holdings?
