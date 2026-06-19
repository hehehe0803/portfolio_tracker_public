# Reconciliation Policy

Status: approved for Sprint 1 planning on 2026-06-18.

Review outcome:

- Approved: zero-wrong reconciliation policy.
- Approved: current value may become trusted before full historical reconciliation.
- Approved: XTB full statements are authoritative; XTB daily PDFs and Gmail are provisional fast updates unless reconciled.

This policy defines how reconciliation work turns imported broker/source evidence into trusted portfolio accounting. It is a guardrail for implementation, review UI, dashboard contracts, and later automation. Product semantics still come from `docs/product_north_star.md`; this file makes the reconciliation rules concrete enough for Sprint 1A workers.

## Goal

The goal is to let current portfolio value become trusted as soon as authoritative current evidence supports it, while keeping history, inception chart metrics, lifetime P&L, return percentages, and other sensitive derived values provisional or blocked until coverage reconciliation proves them.

Reconciliation must separate three layers:

- Raw source evidence: files, PDFs, parsed rows, Gmail attachments, API rows, downloaded statements, and parser diagnostics.
- Staged reconciliation evidence: normalized candidates, detected gaps, candidate matches, coverage checks, and proposed decisions.
- Canonical accounting state: durable transfer links, external-cashflow classifications, import approvals, manual cost-basis decisions, explicit unknown decisions, and confidence states used by analytics and dashboards.

Raw logs and staged evidence explain decisions. They are not enough to mark accounting truth trusted.

## Zero-Wrong-Decision Rule

The app must prefer no committed decision over a wrong committed decision.

Rules:

- Do not auto-commit semantic accounting decisions unless they are proven by authoritative control totals or explicitly approved by the user.
- Auto-detect before auto-decide. Candidate matches, gaps, and repairs may be staged without becoming canonical accounting state.
- Automation may stage high-confidence proposals, but the proposal must remain reversible and auditable until committed.
- Historical and inception metrics may stay provisional even when current value is trusted.
- Current value may be trusted independently only when latest holdings, broker cash, stablecoin reserve, and position existence reconcile to authoritative current evidence.
- Do not classify crypto withdrawals as personal withdrawals by sign alone.
- Do not silently assume missing XTB cash activity.
- Do not mark historical or inception metrics trusted until source coverage checks pass for the relevant date range.

## False Positive / False Negative Definitions

A false positive is an incorrect committed classification, repair, or trust upgrade. Examples:

- Auto-classifying an unmatched Binance USDT withdrawal as a personal withdrawal when it was actually a Hyperliquid deposit.
- Committing an XTB cash repair that hides a missing dividend, fee, tax, swap, or cash operation.
- Linking two transfers only because amounts are similar when dates, venues, identifiers, or control totals do not prove the match.

A false negative is marking data trusted or complete while a real blocker remains. Examples:

- Showing lifetime P&L as trusted when historical deposits, withdrawals, or broker cash coverage has not reconciled.
- Marking an inception chart trusted while a statement date range is missing.
- Showing current cash reserve as trusted when XTB stock buys, sells, dividends, fees, taxes, swaps, or withdrawals have not reconciled to broker cash.

The policy prioritizes avoiding false positives and false negatives in canonical accounting. It is acceptable to have staged uncertainty and review tasks.

## Staged Evidence Versus Canonical Accounting

Staged evidence is useful but not authoritative. It may include:

- Parsed XTB daily PDF rows.
- Gmail-discovered XTB daily PDF previews.
- Candidate transfer matches between Binance, Aster, Hyperliquid, tracked wallets, or other tracked venues.
- Parser warnings and confidence scores.
- Proposed duplicate cleanup, timestamp normalization, and row normalization.
- Coverage checks comparing imported rows to broker/source totals.

Canonical accounting state must be durable and audit-friendly. It includes:

- Transfer links between source and destination evidence.
- External-cashflow classifications for deposits and withdrawals.
- Import approvals that promote staged source evidence into trusted accounting inputs.
- Manual cost-basis decisions.
- Explicit unknown or unresolved decisions that intentionally keep a metric provisional or blocked.
- Confidence state and materiality metadata used by analytics and dashboard display rules.

Activity logs record what happened. They must not be the only record of an accounting decision.

## Deterministic Auto-Commit Rules

Auto-commit is allowed only for exact deterministic mechanics where the committed result cannot change accounting meaning.

Allowed auto-commit examples:

- Exact duplicate fingerprints for identical source rows from the same source and import scope.
- Lossless timestamp normalization into the app's canonical timezone/date representation.
- Exact statement-row parsing where the source row maps directly to a single normalized event and source totals still reconcile.
- Mechanical currency precision rounding that matches broker precision and preserves totals.
- Idempotent re-import recognition for the same source file, statement range, and row fingerprints.

Auto-commit is not allowed for:

- Personal withdrawal versus internal transfer classification.
- Missing XTB cash activity repair.
- Cost basis selection.
- Dividend, fee, tax, swap, commission, corporate action, or cash-operation inference unless proven by authoritative source totals.
- Hidden endpoint or automation output that has not been staged and reconciled against full statements.
- Any decision that changes gross deposits, gross withdrawals, net capital at work, current value, cash reserve, position existence, lifetime P&L, or period performance.

## Manual Review Rules

Manual review is required when a decision changes accounting semantics, confidence, or dashboard-visible money truth without deterministic proof.

Review tasks must show:

- What happened.
- Why it matters.
- Candidate choices.
- The accounting effect of each choice.
- Which metrics will become trusted, provisional, warning, or blocked after confirmation.
- Which evidence remains unresolved.

Required manual review paths:

- Unknown outgoing crypto transfers.
- Personal withdrawal classifications that are not proven by source evidence.
- Internal transfer links that lack exact deterministic source/destination proof.
- Missing cost basis.
- Explicit unknown cost basis.
- Import approvals where staged evidence affects canonical accounting.
- XTB cash differences involving buys, sells, dividends, fees, taxes, swaps, commissions, corporate actions, deposits, withdrawals, or broker cash balance.

Approvals must write durable accounting state before writing audit log rows.

## Control Totals

Control totals are the source-level checks required to prevent false negatives. They must be used where the source provides them.

Required control totals:

- Position quantities by statement date.
- Broker cash balance by statement date and currency.
- Deposits and withdrawals.
- Trades.
- Dividends and other cash operations.
- Fees, taxes, swaps, commissions, and corporate actions.
- Import coverage by date range.

XTB source authority:

- XTB full statements are the authoritative baseline for historical reconciliation when they include the relevant positions, cash balances, trades, dividends, cash operations, fees, taxes, swaps, commissions, corporate actions, and date range coverage.
- XTB daily PDFs and Gmail-discovered daily PDFs are provisional fast-update evidence unless reconciled against full statements or another authoritative control total.
- Daily PDFs may stage executed trades and near-real-time review tasks, but they must not by themselves mark broker cash, full history, inception metrics, or lifetime P&L trusted.

When control totals conflict with parsed rows, do not silently repair canonical accounting. Stage the difference, record the affected scope, and create a review task or implementation defect depending on whether the mismatch is semantic or mechanical.

## Confidence States

Confidence states must be scoped. A portfolio can have trusted current value while history or lifetime P&L remains provisional.

Recommended fields for dashboard and API contracts:

```json
{
  "confidence": {
    "current_value": {"state": "trusted", "issues": []},
    "cash_reserve": {"state": "trusted", "issues": []},
    "history": {"state": "provisional", "issues": []},
    "lifetime_pnl": {"state": "blocked", "issues": []}
  }
}
```

Allowed states:

| State | Meaning | Typical action |
| --- | --- | --- |
| `trusted` | No known material blocker for this scope. | Show normally. |
| `warning` | An unresolved issue exists below the material threshold. | Show value with warning context. |
| `provisional` | Value is usable for exploration, but not final truth. | Demote prominence and show why. |
| `review_required` | A semantic decision or material gap needs user or agent review. | Route to top accounting task. |
| `blocked` | A sensitive metric may be wrong. | Hide or block the metric and show the blocker. |

Scopes that should be tracked independently:

- Current value.
- Cash reserve.
- Broker cash.
- Stablecoin reserve.
- Position existence.
- History/inception coverage.
- Lifetime P&L.
- Rolling period performance.
- Asset-level lifetime contribution or P&L.

## Thresholds

Use these thresholds unless a later approved product contract changes them:

```text
cash_statement_tolerance = broker currency precision
distribution_tolerance = max(0.01 USD, current_portfolio_value * 0.0001)
material_warning = unresolved amount > 10 USD or > 0.01% portfolio value
hard_block = issue affects current value, cash reserve, lifetime P&L, position existence, or historical coverage
```

Additional rules:

- Cash and statement reconciliation must match exact broker currency precision.
- Portfolio distribution totals must reconcile to trusted current value within `distribution_tolerance`.
- An unresolved issue that changes whether a position exists is always a hard block for affected current-value and asset-detail scopes.
- An unresolved issue that changes current total value or cash reserve is always a hard block for sensitive derived stats.
- Missing first activity date or missing historical coverage makes capital rhythm, inception chart, lifetime P&L, and historical return provisional or blocked.
- Low-value unresolved issues may remain warnings only when they do not affect current value, cash reserve, position existence, lifetime P&L, or historical coverage.

## Dashboard Display Rules

Dashboard surfaces must make confidence visible without turning raw logs into the product center.

Rules:

- Current total value may be prominent when `confidence.current_value.state` is `trusted`.
- Cash reserve may be prominent only when stablecoin reserve and broker cash scopes are trusted or clearly partitioned by confidence.
- Lifetime P&L, return percentage, period performance, inception chart, and asset-level lifetime contribution/P&L are sensitive derived stats.
- Sensitive derived stats must be hidden, blocked, or visually demoted when their confidence scope is `provisional`, `review_required`, or `blocked`.
- A trusted current value must not imply trusted history. Label these states separately.
- Rolling 30D remains the dashboard default period, but missing anchors or low-confidence dates make period metrics provisional.
- Deposits inside a period must not display as investment gain. Withdrawals inside a period must not display as investment loss.
- When a material or blocking issue exists, the primary action should be the top accounting reconciliation task.
- Raw transactions, parser evidence, import rows, and activity logs belong behind drilldowns.
- UI copy must avoid recommendation language for accounting tasks. It should explain evidence, choices, and consequences.

## Protected Data Safety

Reconciliation work must not put private data or protected local-production data at risk.

Rules:

- `portfolio_dev` is protected local-production data. Do not run migrations, schema repair, broker sync experiments, destructive tests, smoke seeders, or Compose always-on changes against it without following `docs/local_prod_db_migration_runbook.md` and receiving explicit approval when required.
- Destructive tests and smoke scripts must use localhost database names containing `test` or `smoke`.
- No credentials, cookies, PDFs, statements, broker exports, account references, or private snapshots may be committed.
- Private broker data belongs under ignored `data/` or another ignored local secret/data location.
- XTB browser automation and hidden endpoint discovery must stage downloads and previews before canonical commits.
- Daily PDFs, Gmail attachments, full statements, and automation artifacts must be treated as private local evidence unless sanitized and explicitly approved for version control.
- If a worker needs files outside its dispatch write set or read-only context, it must stop and ask the coordinator to update the dispatch record.
