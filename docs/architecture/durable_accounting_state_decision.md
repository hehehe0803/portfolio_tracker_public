# Durable Accounting State Decision

Status: approved decision record for VNEXT-01B.
Last updated: 2026-06-18.

This record decides where durable accounting decisions live before VNEXT-01C
schema work starts. It does not change runtime behavior, database models,
migrations, API routes, or frontend code.

Product semantics come from `docs/product_north_star.md`. Zero-wrong
reconciliation rules come from `docs/architecture/reconciliation_policy.md`.
Dashboard confidence consumers should follow
`docs/architecture/dashboard_contract.md`.

## Decision Summary

VNEXT-01C must add canonical accounting state outside activity logs and outside
the existing import-review candidate structures.

Durable accounting decisions use four canonical state shapes:

1. Transfer links.
2. External-cashflow classifications.
3. Import approvals.
4. Cost-basis decisions, including explicit unknown cost basis.

Activity logs may mirror these decisions for audit and UI timelines, but an
activity log row must never be the primary decision state. Review/import code may
continue to stage candidate actions such as `confirm_transfer_link` and
`approve_import`; approval commits must write the canonical state first, then
write audit evidence.

## Canonical Shape Rules

- Every canonical decision has a stable primary id.
- Every canonical decision records `created_at`, `created_by`, `decision_source`,
  `status`, `supersedes_id`, `voided_at`, `voided_by`, and `void_reason`.
- Valid statuses are `active`, `superseded`, and `voided`.
- Canonical decisions are append-first. Corrections create a new active decision
  and mark the previous active decision as `superseded`; destructive updates are
  not the normal path.
- `created_by` may be the local user, an import process, or a system actor, but
  semantic decisions that change money truth must use `decision_source = manual`
  unless deterministic auto-commit rules prove the decision.
- Evidence references are stored as structured references so VNEXT-01C can link
  to existing or future normalized source rows without depending on one importer.
- Amounts are stored as decimals, not floats. USD-equivalent fields are optional
  when unavailable, but confidence/materiality consumers must treat missing
  values explicitly.
- Time values use timezone-aware UTC timestamps. Source-local dates may be stored
  separately when the source reports date-only records.

## Evidence Reference Shape

All four decision shapes use this embedded reference form when they need to point
at raw or staged evidence:

| Field | Required | Meaning |
| --- | --- | --- |
| `source` | yes | Source system such as `binance`, `xtb`, `aster`, `hyperliquid`, `wallet`, `cash`, or `commodities`. |
| `source_account_id` | no | Stable account, wallet, venue, or broker sub-account identifier when available. |
| `fingerprint` | no | Existing source row or parser fingerprint when available. |
| `external_id` | no | Broker/source id, transaction hash, statement row id, order id, or import row id when available. |
| `import_scope_id` | no | File/import/session/snapshot scope that produced the evidence. |
| `occurred_at` | no | Source event timestamp in UTC when known. |
| `source_date` | no | Source date when only a date is available or when statement-date semantics matter. |
| `asset_symbol` | no | Source asset symbol normalized to uppercase when asset-specific. |
| `quantity` | no | Source quantity in source units. |
| `amount_usd` | no | Source or normalized USD-equivalent amount, when known. |
| `raw_ref` | no | Small JSON pointer to private/local evidence, not private payload content. |

VNEXT-01C should prefer real foreign keys where existing normalized rows have
stable ids, but it must keep enough structured reference fields to support
sources that are still staged by fingerprint or import scope.

## Transfer Links

Decision: implement transfer links as a new canonical state table, not as import
review metadata and not as an activity-log-only event.

Purpose: prove that two or more source movements are one internal movement
inside the tracked portfolio. A transfer link must not increase gross deposits
or gross withdrawals.

Recommended table name: `accounting_transfer_links`.

Shape:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable decision id. |
| `link_group_key` | yes | Idempotency key for the approved movement, derived from sorted evidence fingerprints/external ids and normalized asset. |
| `from_evidence` | yes | Evidence reference for the outgoing side. |
| `to_evidence` | yes | One or more evidence references for destination side candidates approved as the internal destination. |
| `asset_symbol` | yes | Asset transferred, normalized uppercase. |
| `from_quantity` | yes | Signed or direction-tagged quantity leaving the source. |
| `to_quantity` | yes | Total quantity arriving at destination evidence. |
| `quantity_delta` | yes | Absolute quantity difference between source and destination after fees/slippage. |
| `fee_quantity` | no | Transfer fee quantity when source evidence proves it. |
| `fee_asset_symbol` | no | Fee asset when different from transferred asset. |
| `amount_usd` | no | USD value at transfer time when available. |
| `from_source` | yes | Source venue/account, for indexed queries. |
| `to_source` | yes | Destination venue/account, for indexed queries. |
| `occurred_at` | yes | Best canonical transfer timestamp. |
| `confidence_state` | yes | `trusted`, `warning`, `provisional`, `review_required`, or `blocked`. |
| `review_task_id` | no | Review task that approved the link, when applicable. |
| `decision_reason` | yes | Short reason code such as `manual_match`, `deterministic_exact_match`, or `statement_control_total`. |
| `notes` | no | User/operator rationale. |
| lifecycle fields | yes | Common canonical lifecycle fields. |

Constraints and behavior:

- There can be only one active transfer link for the same source-side evidence
  unless a later active decision supersedes it.
- There can be only one active transfer link for the same destination evidence
  unless a many-leg transfer explicitly stores all destination evidence in the
  same link.
- Ambiguous candidate matches from import review are staged evidence until an
  active transfer link exists.
- Crypto withdrawals are not personal withdrawals by sign alone. If no active
  transfer link and no active external-cashflow classification exists, the
  movement remains unresolved and should create or keep an accounting task.

## External-Cashflow Classifications

Decision: implement external-cashflow classifications as a new canonical state
table.

Purpose: decide whether a source movement is money or value entering from
outside the tracked portfolio, leaving for outside/personal use, or explicitly
not an external cashflow. These decisions feed gross deposits, gross withdrawals,
net capital at work, lifetime P&L, and period performance.

Recommended table name: `accounting_external_cashflow_classifications`.

Shape:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable decision id. |
| `classification_key` | yes | Idempotency key for source evidence plus classification kind. |
| `evidence` | yes | Evidence reference being classified. |
| `cashflow_type` | yes | `external_deposit`, `external_withdrawal`, or `not_external_cashflow`. |
| `movement_type` | yes | `external_cashflow`, `internal_movement`, or `trade_allocation`; included so capital services do not infer from sign. |
| `source` | yes | Indexed source venue/account. |
| `asset_symbol` | yes | Asset or currency moved. |
| `quantity` | yes | Source quantity. |
| `amount_usd` | no | USD-equivalent amount used for capital truth, if known. |
| `occurred_at` | yes | Canonical event timestamp. |
| `capital_effect_usd` | no | Positive for gross deposit, negative for gross withdrawal, zero for not external. |
| `confidence_state` | yes | Scoped confidence state after this decision. |
| `materiality_usd` | no | Amount used by confidence/materiality gates. |
| `review_task_id` | no | Review task that approved the classification. |
| `decision_reason` | yes | Reason code such as `xtb_default_external_withdrawal`, `manual_personal_withdrawal`, `matched_internal_transfer`, or `deterministic_statement_evidence`. |
| `notes` | no | User/operator rationale. |
| lifecycle fields | yes | Common canonical lifecycle fields. |

Constraints and behavior:

- Only one active classification may exist for the same evidence.
- XTB stock-account withdrawals may default to active external withdrawals only
  when the source policy says no matched evidence is required. If later matched
  evidence proves an internal movement, a new active classification must
  supersede the previous one.
- Unknown outgoing crypto transfers must not become active external withdrawals
  without explicit approval or authoritative evidence.
- `not_external_cashflow` is allowed when the decision is useful for audit and
  blocking duplicate review work, but an active transfer link is still the
  preferred representation for proven internal transfers.

## Import Approvals

Decision: implement import approvals as a new canonical state table that
promotes staged source evidence into trusted accounting input scopes.

Purpose: separate parser/import confidence from canonical accounting trust.
`approve_import` from current import review semantics becomes a staged action
until an active import approval records the approved source, scope, coverage,
and affected accounting scopes.

Recommended table name: `accounting_import_approvals`.

Shape:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable decision id. |
| `approval_key` | yes | Idempotency key for source, import scope, coverage range, and source fingerprint set. |
| `source` | yes | Source system approved. |
| `source_account_id` | no | Account, wallet, venue, or broker sub-account. |
| `import_scope_id` | yes | File/import/session/snapshot scope being approved. |
| `source_fingerprints` | yes | Ordered or sorted source fingerprints included in the approved scope. |
| `coverage_start` | no | First source date/time covered by the approved import. |
| `coverage_end` | no | Last source date/time covered by the approved import. |
| `approved_scope` | yes | `current_value`, `cash_reserve`, `history`, `trades`, `cashflows`, `fees_taxes_dividends`, or a list of these scopes. |
| `control_totals` | no | Structured totals checked before approval, such as positions, broker cash, deposits, withdrawals, trades, fees, taxes, dividends, and row counts. |
| `confidence_state` | yes | Confidence state granted to this approved scope. |
| `review_task_id` | no | Review task that approved the import. |
| `decision_reason` | yes | Reason code such as `identifier_backed_import`, `full_statement_reconciled`, `manual_scope_approval`, or `deterministic_duplicate_import`. |
| `notes` | no | User/operator rationale. |
| lifecycle fields | yes | Common canonical lifecycle fields. |

Constraints and behavior:

- Approval is scoped. Approving a daily XTB PDF for fast current updates does not
  approve full history, broker cash coverage, inception metrics, or lifetime P&L
  unless the approved scope and control totals prove those scopes.
- Re-import of the same source scope should be idempotent when fingerprints and
  control totals match.
- If control totals conflict with parsed rows, do not approve the scope. Stage a
  review task or implementation defect depending on whether the mismatch is
  semantic or mechanical.
- Import approval can make source evidence eligible for capital truth, but it
  does not by itself classify ambiguous withdrawals, link transfers, or decide
  cost basis.

## Manual Cost Basis And Explicit Unknown Cost Basis

Decision: implement manual cost basis and explicit unknown cost basis in a new
canonical cost-basis decision table. Do not extend import-review candidate
structures, transaction rows, or activity logs as the primary store.

Purpose: let the user confirm an asset/account cost basis when evidence is
missing, or explicitly mark cost basis as unknown so sensitive metrics remain
provisional or blocked without repeatedly asking the same unresolved question.

Recommended table name: `accounting_cost_basis_decisions`.

Shape:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable decision id. |
| `basis_key` | yes | Idempotency key for asset, source/account scope, lot/scope, and effective date. |
| `decision_type` | yes | `manual_cost_basis` or `unknown_cost_basis`. |
| `asset_symbol` | yes | Asset symbol normalized uppercase. |
| `source` | no | Source venue/account if the basis is source-specific. |
| `source_account_id` | no | Account or wallet scope if applicable. |
| `basis_scope` | yes | `lot`, `position`, `asset_source`, or `asset_global`. |
| `evidence` | no | Evidence reference for the lot, position, transaction, or import gap. |
| `quantity` | no | Quantity covered by the decision when known. |
| `cost_basis_usd` | no | Total USD cost basis for the covered scope. Required for `manual_cost_basis`. |
| `unit_cost_usd` | no | Unit USD basis when useful for lot/position calculations. |
| `effective_at` | yes | Date/time the basis applies to. |
| `basis_method` | no | `manual_average`, `manual_lot`, `source_statement`, `unknown`, or later approved methods. |
| `confidence_state` | yes | `trusted` for confirmed manual basis, usually `blocked` or `provisional` for unknown basis. |
| `affected_metric_scopes` | yes | Metric scopes affected, such as `asset_lifetime_pnl`, `lifetime_pnl`, `period_performance`, or `asset_detail`. |
| `review_task_id` | no | Review task that approved the decision. |
| `decision_reason` | yes | Reason code such as `manual_average_cost`, `source_gap_accepted_unknown`, or `missing_import_deferred`. |
| `notes` | no | User/operator rationale. |
| lifecycle fields | yes | Common canonical lifecycle fields. |

Constraints and behavior:

- `manual_cost_basis` requires either `cost_basis_usd` or enough quantity/unit
  cost fields to compute it deterministically.
- `unknown_cost_basis` intentionally preserves uncertainty. It may close or
  suppress a repeated review prompt, but it must not mark affected sensitive
  metrics trusted.
- Only one active cost-basis decision may exist for the same basis scope.
- Later imported authoritative evidence may supersede manual or unknown basis
  decisions, but the prior decision remains audit-visible.

## Lifecycle And Audit Semantics

Approval lifecycle:

1. Raw source evidence is imported or discovered.
2. Staged reconciliation evidence and review tasks are generated.
3. A deterministic rule or manual review approves a decision.
4. The canonical accounting state row is inserted or supersedes a prior row.
5. An audit event/activity log is written with the canonical decision id.
6. Confidence/materiality services consume canonical state, not raw activity
   logs, when deciding trusted, warning, provisional, review-required, or
   blocked display states.

Audit event requirements:

- Every canonical insert, supersession, and void must be auditable.
- Audit metadata must include canonical decision id, decision type, previous
  decision id when superseding, actor, timestamp, reason code, and affected
  metric scopes.
- Audit logs can be rebuilt from canonical rows if necessary. The reverse must
  not be required.
- Voiding a decision should create or reopen accounting review when the voided
  decision affected capital truth, current value, cash reserve, position
  existence, lifetime P&L, period performance, or asset-level P&L.

Idempotency requirements:

- Replaying the same approval request must not create duplicate active decisions.
- Re-importing the same source rows must not duplicate active import approvals
  when fingerprints and control totals match.
- Supersession must be explicit; silent overwrite is not acceptable for semantic
  accounting decisions.

## Gates Before VNEXT-01C Schema Work

VNEXT-01C may start only after these gates are satisfied:

1. This record is present and accepted as the active VNEXT-01B decision record.
2. VNEXT-01C dispatch is serialized; no parallel worker edits
   `api/app/db/models.py` or `api/migrations/`.
3. The schema worker reads `docs/local_prod_db_migration_runbook.md` before any
   migration work and does not touch `portfolio_dev` without the required backup
   and approval evidence.
4. The schema worker maps the recommended table names and fields above to actual
   model names before writing migrations.
5. The schema worker defines uniqueness/idempotency constraints for active
   transfer links, active cashflow classifications, import approval keys, and
   active cost-basis decisions.
6. The schema worker defines foreign-key or structured-reference strategy for
   evidence references without requiring private raw broker payloads in version
   control.
7. DB tests are planned for relationships, active-row uniqueness, supersession,
   voiding, and idempotent replay.
8. No API, service, frontend, or runtime behavior is changed until schema tests
   prove the durable state is available.

## Non-Decisions

- VNEXT-01B does not choose endpoint names for accounting-review approvals.
- VNEXT-01B does not implement review queue behavior.
- VNEXT-01B does not define dashboard payload classes.
- VNEXT-01B does not change activity log schema.
- VNEXT-01B does not run migrations, touch `portfolio_dev`, or inspect private
  broker data.
