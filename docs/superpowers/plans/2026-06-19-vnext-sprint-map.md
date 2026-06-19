# vNext Sprint Map And Approval Gates

Status: active sprint routing map.
Last updated: 2026-06-19.

## Operating Model

Use this map with `docs/superpowers/specs/2026-06-19-vnext-sprint-gate-design.md`.
The public mirror is the active development target. Every sprint marked
`Spec required` must receive a short user-approved spec before implementation.

## Current Inputs

Already approved or landed enough to be used as implementation inputs:

- `VNEXT-00`: docs cleanup and hot-path orientation.
- `VNEXT-01B`: durable accounting state decision record.
- `VNEXT-01C`: durable accounting state schema.
- `docs/architecture/reconciliation_policy.md`.
- `docs/architecture/xtb_source_coverage.md`.
- `docs/architecture/historical_anchors_confidence_plan.md` as planning input
  for `VNEXT-04A`.
- `docs/architecture/dashboard_contract.md` as draft input for later dashboard
  API/UI specs, not as implementation approval.

## Sprint Approval Map

| Sprint | Gate | Reason |
| --- | --- | --- |
| `VNEXT-01D` Transfer Matching And Unknown Outgoing Tasks | Spec required next | Needs explicit durable accounting task decision before implementation; schema changes require hot-path write-set amendment and user approval. |
| `VNEXT-02A` Capital Truth Contract | Spec required | Defines headline money formulas, confidence blocking, and API exposure. |
| `VNEXT-03A` Rolling Period Performance | Spec required | Depends on capital truth and historical anchors; affects dashboard-sensitive metrics. |
| `VNEXT-04A` Historical P&L Anchors And Confidence | Spec required | Planning note exists, but implementation boundaries and data inputs need approval. |
| `VNEXT-05A` Manual Reconciliation Queue With Durable Decisions | Spec required | User decisions, durable approvals, audit order, and API shape must be explicit. |
| `VNEXT-05B` Accounting Review UI | Spec required | User-facing workflow/copy must separate accounting review from investment review. |
| `VNEXT-06A` Asset-Type Distribution And Cash Reserve | Spec required | Cash/stablecoin and weak-denominator display rules affect trust. |
| `VNEXT-06B` Holding Drivers | Spec required | Driver math and low-confidence omission rules need approval. |
| `VNEXT-07A` Dashboard And Asset Detail API Contract | Spec required | Shared contract and API shape must be frozen before UI work. |
| `VNEXT-07B` Dashboard First Screen UI | Spec required | First-screen money labels, confidence display, and review action need user approval. |
| `VNEXT-07C` Asset Detail UI | Spec required | Must separate current-position P&L from lifetime/contribution P&L. |

## Immediate `VNEXT-01D` Spec Questions

The next sprint spec must decide:

- Whether to add a durable `accounting_reconciliation_tasks` table now.
- If not, which existing durable table represents an unresolved outgoing crypto
  task without corrupting external-cashflow semantics.
- Whether matched Binance-to-Aster/Hyperliquid transfers can be committed
  deterministically, or only staged for manual approval.
- How task ids connect to transfer links, external-cashflow classifications,
  import approvals, and later review UI.
- Which API exposure, if any, is in scope for `VNEXT-01D`.

Default recommendation for the spec: evaluate a focused durable task table as a
precursor, because activity logs are audit evidence only and
`not_external_cashflow` is a decision, not an unresolved task. This map is not
approval to add schema inside `VNEXT-01D`; if the spec chooses that path, it
must also amend the hot-path implementation plan, update verification gates, and
receive explicit user approval for the schema write set.

## Parallelization Rules

- No parallel implementation until the sprint spec is approved.
- Schema, shared contracts, broad analytics services, and primary frontend
  routes are serialized.
- Parallel workers are allowed only when the spec names exact non-overlapping
  write sets.
- Read-only exploration agents may run before approval if they do not mutate
  tracked files.

## Required Review Loop

For each sprint:

1. Write the sprint spec.
2. Run an adversarial spec review focused on scope drift, wrong money truth,
   private-data risk, missing tests, and missing user decisions.
3. Fix the spec.
4. Wait for user approval.
5. Write the implementation plan.
6. Confirm the implementation plan does not expand beyond the approved spec.
   If it does, return to spec approval before code work.
7. Implement with TDD where behavior changes.
8. Run targeted verification and the broad gate required by
   `docs/verification_matrix.md`.
9. Run adversarial PR review.
10. Fix all concrete findings before merge.

## Existing Draft Work

`/tmp/portfolio_tracker_public_worktrees/vnext-01d-transfer-matching` contains
uncommitted draft RED tests for `VNEXT-01D`. Keep them as reference material.
After the `VNEXT-01D` spec is approved, the implementation plan must explicitly
adopt, revise, or delete those draft tests.
