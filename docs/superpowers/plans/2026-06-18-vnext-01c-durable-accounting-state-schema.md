# VNEXT-01C Durable Accounting State Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add canonical durable accounting-decision tables for transfer links, external-cashflow classifications, import approvals, and cost-basis decisions.

**Architecture:** VNEXT-01C is schema-only. It adds SQLAlchemy ORM models, one Alembic migration, and DB/schema tests. It must not add API routes, services, frontend UI, import approval behavior, broker sync behavior, or runtime dashboard contracts.

**Tech Stack:** Python, SQLAlchemy 2.0 ORM, Alembic, PostgreSQL, pytest, repo DB safety helpers.

**Implementation status:** Completed on branch `codex/vnext-01c-accounting-state`. The remaining protected local-production migration/application step is not part of this PR and still requires the local-prod migration runbook plus explicit approval.

---

## Source Inputs

- `docs/architecture/durable_accounting_state_decision.md`
- `docs/architecture/reconciliation_policy.md`
- `docs/product_north_star.md`
- `docs/implementation_plan.md`
- `docs/verification_matrix.md`
- `docs/local_prod_db_migration_runbook.md`

`portfolio_dev` is protected. This plan does not apply the migration to `portfolio_dev`. Any later protected DB migration requires the runbook backup/alignment gate and explicit approval.

VNEXT-01C implementation approval means approval to change repository schema
files and to run tests against disposable test databases only. It does not
approve read-only or write access to `portfolio_dev`. The local-prod read-only
alignment and backup/apply steps stay a separate manual gate after the PR lands.

## Exact Write Set

- Modify: `api/app/db/models.py`
- Create: `api/migrations/versions/00008_accounting_state.py`
- Modify: `api/tests/db/test_schema_alignment.py`
- Create: `api/tests/db/test_accounting_state_schema.py`
- Modify: `.gitignore` only to whitelist this durable plan file.

Blocked files unless a new approval changes scope:

- `api/app/api/`
- `api/app/services/`
- `shared/`
- `frontend/`
- `worker/`
- `infra/`
- private `data/`

## Schema Design

Use four new ORM models and tables:

- `AccountingTransferLink` -> `accounting_transfer_links`
- `AccountingExternalCashflowClassification` -> `accounting_external_cashflow_classifications`
- `AccountingImportApproval` -> `accounting_import_approvals`
- `AccountingCostBasisDecision` -> `accounting_cost_basis_decisions`

Every table gets canonical lifecycle columns:

- `id BIGSERIAL PRIMARY KEY`
- `created_at TIMESTAMPTZ NOT NULL`
- `created_by VARCHAR(80) NOT NULL`
- `decision_source VARCHAR(30) NOT NULL`
- `status VARCHAR(20) NOT NULL`
- `supersedes_id BIGINT NULL` self-FK with `ON DELETE SET NULL`
- `voided_at TIMESTAMPTZ NULL`
- `voided_by VARCHAR(80) NULL`
- `void_reason TEXT NULL`
- `decision_reason VARCHAR(80) NOT NULL`
- `notes TEXT NULL`

Use structured evidence JSON columns for rich source references, but add scalar idempotency keys for database constraints. JSON-only evidence is not enough for active-row uniqueness.

Allowed status values:

- `active`
- `superseded`
- `voided`

Allowed confidence states:

- `trusted`
- `warning`
- `provisional`
- `review_required`
- `blocked`

PostgreSQL partial unique indexes enforce active-row uniqueness. The current SQLAlchemy 2.0 docs confirm using `Index(..., postgresql_where=...)` for PostgreSQL partial indexes.

Every bounded vocabulary above must be protected by DB check constraints and
covered by live migrated-PostgreSQL tests. Do not rely on future application code
to prevent invalid `status`, `confidence_state`, cashflow, movement, basis, or
decision values.

Cross-field invariants to enforce in DB when simple:

- `status` is one of `active`, `superseded`, or `voided`.
- `decision_source` is one of `manual`, `system`, `import`, or `deterministic`.
- `voided_at` and `voided_by` must both be null unless `status = 'voided'`.
- `confidence_state` is one of `trusted`, `warning`, `provisional`, `review_required`, or `blocked`.
- `cashflow_type = 'external_deposit'` requires `capital_effect_usd IS NULL OR capital_effect_usd >= 0`.
- `cashflow_type = 'external_withdrawal'` requires `capital_effect_usd IS NULL OR capital_effect_usd <= 0`.
- `cashflow_type = 'not_external_cashflow'` requires `capital_effect_usd IS NULL OR capital_effect_usd = 0`.
- `unknown_cost_basis` must not use `confidence_state = 'trusted'`.
- `manual_cost_basis` requires either `cost_basis_usd` or both `quantity` and `unit_cost_usd`.

Some richer semantic checks stay application-level for later tickets, such as
whether `decision_source = manual` is mandatory for a particular money-truth
approval, because VNEXT-01C has no approval API or actor policy layer.

## Table Details

### `accounting_transfer_links`

Purpose: prove source and destination evidence represent an internal transfer, not an external cashflow.

Key columns:

- `link_group_key VARCHAR(128) NOT NULL`
- `from_evidence JSON NOT NULL`
- `to_evidence JSON NOT NULL`
- `from_evidence_key VARCHAR(128) NOT NULL`
- `to_evidence_key VARCHAR(128) NOT NULL`
- `asset_symbol VARCHAR(20) NOT NULL`
- `from_quantity NUMERIC(30, 10) NOT NULL`
- `to_quantity NUMERIC(30, 10) NOT NULL`
- `quantity_delta NUMERIC(30, 10) NOT NULL`
- `fee_quantity NUMERIC(30, 10) NULL`
- `fee_asset_symbol VARCHAR(20) NULL`
- `amount_usd NUMERIC(20, 6) NULL`
- `from_source VARCHAR(50) NOT NULL`
- `to_source VARCHAR(50) NOT NULL`
- `occurred_at TIMESTAMPTZ NOT NULL`
- `confidence_state VARCHAR(30) NOT NULL`
- `review_task_id VARCHAR(100) NULL`

Indexes:

- `ix_accounting_transfer_links_occurred_at`
- `ix_accounting_transfer_links_sources`
- unique partial `uq_accounting_transfer_links_active_group` on `link_group_key` where `status = 'active'`
- unique partial `uq_accounting_transfer_links_active_from_evidence` on `from_evidence_key` where `status = 'active'`
- unique partial `uq_accounting_transfer_links_active_to_evidence` on `to_evidence_key` where `status = 'active'`

Scope note: VNEXT-01C stores the canonical transfer-link row shape but does not
implement many-leg destination overlap prevention. `to_evidence` may carry one
or more evidence references for future compatibility, but the active uniqueness
contract in VNEXT-01C is keyed by `to_evidence_key`. Until a later normalized
transfer-leg table exists, approval code must only use a one-destination
`to_evidence_key` or create a deterministic group key that represents the entire
destination set. Add a test that overlapping many-leg destination arrays are not
claimed as fully prevented by this schema; this is a documented deferred risk,
not a hidden guarantee.

### `accounting_external_cashflow_classifications`

Purpose: decide whether source evidence is an external deposit, external withdrawal, or explicitly not external.

Key columns:

- `classification_key VARCHAR(128) NOT NULL`
- `evidence JSON NOT NULL`
- `evidence_key VARCHAR(128) NOT NULL`
- `cashflow_type VARCHAR(40) NOT NULL`
- `movement_type VARCHAR(40) NOT NULL`
- `source VARCHAR(50) NOT NULL`
- `asset_symbol VARCHAR(20) NOT NULL`
- `quantity NUMERIC(30, 10) NOT NULL`
- `amount_usd NUMERIC(20, 6) NULL`
- `occurred_at TIMESTAMPTZ NOT NULL`
- `capital_effect_usd NUMERIC(20, 6) NULL`
- `confidence_state VARCHAR(30) NOT NULL`
- `materiality_usd NUMERIC(20, 6) NULL`
- `review_task_id VARCHAR(100) NULL`

Allowed cashflow types:

- `external_deposit`
- `external_withdrawal`
- `not_external_cashflow`

Allowed movement types:

- `external_cashflow`
- `internal_movement`
- `trade_allocation`

Indexes:

- `ix_acct_cashflow_occurred_at`
- `ix_acct_cashflow_source`
- unique partial `uq_acct_cashflow_active_key` on `classification_key` where `status = 'active'`
- unique partial `uq_acct_cashflow_active_evidence` on `evidence_key` where `status = 'active'`

Check constraints:

- valid `cashflow_type`;
- valid `movement_type`;
- valid `confidence_state`;
- valid lifecycle status/source;
- capital-effect sign/null rules listed in the global schema design.

### `accounting_import_approvals`

Purpose: approve a source/import scope as eligible accounting input without classifying ambiguous transfers or cost basis.

Key columns:

- `approval_key VARCHAR(160) NOT NULL`
- `source VARCHAR(50) NOT NULL`
- `source_account_id VARCHAR(120) NULL`
- `import_scope_id VARCHAR(160) NOT NULL`
- `source_fingerprints JSON NOT NULL`
- `coverage_start TIMESTAMPTZ NULL`
- `coverage_end TIMESTAMPTZ NULL`
- `approved_scope JSON NOT NULL`
- `control_totals JSON NULL`
- `confidence_state VARCHAR(30) NOT NULL`
- `review_task_id VARCHAR(100) NULL`

Indexes:

- `ix_accounting_import_approvals_source_scope`
- `ix_accounting_import_approvals_coverage`
- unique partial `uq_accounting_import_approvals_active_key` on `approval_key` where `status = 'active'`

Check constraints:

- valid `confidence_state`;
- valid lifecycle status/source;
- `coverage_start IS NULL OR coverage_end IS NULL OR coverage_start <= coverage_end`.

### `accounting_cost_basis_decisions`

Purpose: store manual cost basis and explicit unknown cost-basis decisions as canonical state.

Key columns:

- `basis_key VARCHAR(160) NOT NULL`
- `decision_type VARCHAR(40) NOT NULL`
- `asset_symbol VARCHAR(20) NOT NULL`
- `source VARCHAR(50) NULL`
- `source_account_id VARCHAR(120) NULL`
- `basis_scope VARCHAR(40) NOT NULL`
- `evidence JSON NULL`
- `quantity NUMERIC(30, 10) NULL`
- `cost_basis_usd NUMERIC(20, 6) NULL`
- `unit_cost_usd NUMERIC(20, 6) NULL`
- `effective_at TIMESTAMPTZ NOT NULL`
- `basis_method VARCHAR(40) NULL`
- `confidence_state VARCHAR(30) NOT NULL`
- `affected_metric_scopes JSON NOT NULL`
- `review_task_id VARCHAR(100) NULL`

Allowed decision types:

- `manual_cost_basis`
- `unknown_cost_basis`

Allowed basis scopes:

- `lot`
- `position`
- `asset_source`
- `asset_global`

Add a check constraint that `manual_cost_basis` requires either `cost_basis_usd` or both `quantity` and `unit_cost_usd`.

Indexes:

- `ix_accounting_cost_basis_decisions_asset_effective_at`
- unique partial `uq_accounting_cost_basis_decisions_active_key` on `basis_key` where `status = 'active'`

Check constraints:

- valid `decision_type`;
- valid `basis_scope`;
- valid `confidence_state`;
- valid lifecycle status/source;
- manual cost-basis required-value rule;
- unknown cost basis cannot be `trusted`.

## Preflight: Create Branch Before Editing

**Files:**

- No file changes.

- [ ] **Step 1: Verify synced clean main**

Run:

```bash
git status --short --branch
git pull origin main
```

Expected: clean `main` tracking `origin/main`, already up to date or fast-forwarded.

- [ ] **Step 2: Create the scoped branch**

Run:

```bash
git switch -c codex/vnext-01c-accounting-state
```

Expected: branch created before schema edits start.

- [ ] **Step 3: Confirm protected DB boundary**

Record in the PR notes that VNEXT-01C did not access `portfolio_dev`. If a
future run needs local-prod read-only alignment or migration application, stop
and request a separate approval with the runbook backup/alignment steps.

## Task 1: Add ORM Models And Metadata Tests

**Files:**

- Modify: `api/app/db/models.py`
- Modify: `api/tests/db/test_schema_alignment.py`

- [ ] **Step 1: Add a failing metadata test for accounting tables**

Add the four accounting tables to `EXPECTED_TABLES` and add expected index names to `EXPECTED_INDEXES`.

Update `test_importing_app_db_registers_new_tables` to assert:

```python
assert {
    "accounting_transfer_links",
    "accounting_external_cashflow_classifications",
    "accounting_import_approvals",
    "accounting_cost_basis_decisions",
} <= table_names
```

- [ ] **Step 2: Run the metadata test and verify it fails**

Run:

```bash
uv run pytest api/tests/db/test_schema_alignment.py::test_importing_app_db_registers_new_tables api/tests/db/test_schema_alignment.py::test_metadata_signature_includes_tag_note_and_activity_tables -q
```

Expected: fails because accounting tables are not registered.

- [ ] **Step 3: Add ORM models**

Add the four model classes to `api/app/db/models.py` after `ActivityLog` or near the other accounting/import models. Follow current repo style: `Mapped[...]`, `mapped_column`, `JSON`, `Numeric`, `DateTime(timezone=True)`, `Index`, and `ForeignKey`.

Use SQLAlchemy partial indexes in `__table_args__`, for example:

```python
Index(
    "uq_accounting_import_approvals_active_key",
    "approval_key",
    unique=True,
    postgresql_where=status == "active",
)
```

If direct class-body column references are awkward, define partial unique indexes after class declaration using the table column objects.

- [ ] **Step 4: Update metadata expectations**

Update `expected_unique_constraints` only for non-partial `UniqueConstraint` entries. Partial unique indexes belong in `EXPECTED_INDEXES`, not `expected_unique_constraints`.

Add expected FK entries for self-referential `supersedes_id` on all four new tables:

```python
(("supersedes_id",), "accounting_transfer_links", ("id",), "SET NULL")
```

Repeat for each table.

Also add the expected check-constraint names to a new `EXPECTED_CHECK_CONSTRAINTS`
mapping and update metadata inspection to compare check constraint names for the
four accounting tables.

- [ ] **Step 5: Run metadata tests and verify they pass**

Run:

```bash
uv run pytest api/tests/db/test_schema_alignment.py::test_importing_app_db_registers_new_tables api/tests/db/test_schema_alignment.py::test_metadata_signature_includes_tag_note_and_activity_tables -q
```

Expected: pass.

## Task 2: Add Alembic Migration

**Files:**

- Create: `api/migrations/versions/00008_accounting_state.py`
- Modify: `api/tests/db/test_schema_alignment.py`

- [ ] **Step 1: Add a failing full migration alignment test expectation**

With metadata updated but no migration file yet, run:

```bash
uv run pytest api/tests/db/test_schema_alignment.py::test_core_schema_alignment_after_full_migration_cycle -q
```

Expected: fail because live migrated schema lacks the new accounting tables.

- [ ] **Step 2: Create the migration**

Create `api/migrations/versions/00008_accounting_state.py`:

- `revision = "accounting_state_001"`
- `down_revision = "intel_watchlist_001"`
- `upgrade()` creates the four tables, check constraints, regular indexes, and partial unique indexes.
- `downgrade()` drops indexes first, then tables in reverse order.

Use `sa.JSON()` for structured evidence and scope payloads. Use `sa.Numeric(30, 10)` for quantities and `sa.Numeric(20, 6)` for USD amounts.

Name check constraints explicitly, for example:

- `ck_accounting_transfer_links_status`
- `ck_accounting_transfer_links_decision_source`
- `ck_accounting_transfer_links_confidence_state`
- `ck_accounting_transfer_links_void_lifecycle`
- `ck_acct_cashflow_cashflow_type`
- `ck_acct_cashflow_movement_type`
- `ck_acct_cashflow_capital_effect`
- `ck_accounting_import_approvals_coverage_order`
- `ck_accounting_cost_basis_decisions_decision_type`
- `ck_accounting_cost_basis_decisions_basis_scope`
- `ck_accounting_cost_basis_decisions_manual_value`
- `ck_accounting_cost_basis_decisions_unknown_not_trusted`

- [ ] **Step 3: Run full migration alignment**

Run:

```bash
uv run pytest api/tests/db/test_schema_alignment.py::test_core_schema_alignment_after_full_migration_cycle -q
```

Expected: pass against a disposable database whose generated name contains `test`.

## Task 3: Add Accounting State Constraint Tests

**Files:**

- Create: `api/tests/db/test_accounting_state_schema.py`

- [ ] **Step 1: Write failing tests for active-row uniqueness**

Create tests that use the same disposable database helper pattern as `test_schema_alignment.py`.

Test behavior:

- two active transfer links with the same `link_group_key` fail;
- active plus superseded transfer links with the same `link_group_key` succeed;
- duplicate active cashflow `evidence_key` fails;
- duplicate active import `approval_key` fails;
- duplicate active cost-basis `basis_key` fails.
- invalid lifecycle `status` fails;
- invalid `confidence_state` fails;
- invalid cashflow/movement/basis vocabularies fail;
- `not_external_cashflow` with nonzero capital effect fails;
- external deposit with negative capital effect fails;
- external withdrawal with positive capital effect fails;
- `voided_at` without `status = 'voided'` fails.

- [ ] **Step 2: Run and verify failure if constraints are incomplete**

Run:

```bash
uv run pytest api/tests/db/test_accounting_state_schema.py -q
```

Expected before complete constraints: at least one duplicate-active test fails.

- [ ] **Step 3: Complete migration/model constraints**

Fix any missing partial unique indexes or check constraints in both ORM metadata and the migration.

- [ ] **Step 4: Add cost-basis check test**

Add a test proving:

- `manual_cost_basis` with no `cost_basis_usd` and no `quantity`/`unit_cost_usd` fails;
- `unknown_cost_basis` with no cost fields succeeds.
- `unknown_cost_basis` with `confidence_state = 'trusted'` fails.

- [ ] **Step 5: Add live schema contract tests**

Assert live migrated PostgreSQL has:

- every required column on all four accounting tables;
- expected nullable vs non-nullable columns;
- expected check-constraint names;
- expected partial unique index names and predicates containing `status = 'active'`;
- expected self-FK `supersedes_id` constraints.

Also add a test documenting the deferred many-leg overlap behavior: the schema
does not expose per-destination-leg uniqueness beyond `to_evidence_key`, so
approval services must not assume overlapping arrays are prevented until a later
normalized transfer-leg table exists.

- [ ] **Step 6: Run constraint tests**

Run:

```bash
uv run pytest api/tests/db/test_accounting_state_schema.py -q
```

Expected: pass.

## Task 4: Safety And Broad Verification

**Files:**

- No new files unless tests expose a bug in the exact write set.

- [ ] **Step 1: Check worktree scope**

Run:

```bash
git status --short
git diff --name-only
```

Expected changed files are only:

- `api/app/db/models.py`
- `api/migrations/versions/00008_accounting_state.py`
- `api/tests/db/test_schema_alignment.py`
- `api/tests/db/test_accounting_state_schema.py`
- this plan file if intentionally included in the PR
- `.gitignore` if only whitelisting this plan file

- [ ] **Step 2: Run DB targeted tests**

Run:

```bash
uv run pytest api/tests/db -q
```

Expected: pass or skip only when local PostgreSQL tooling is unavailable. If skipped due to unavailable PostgreSQL, do not merge without an equivalent verified PostgreSQL gate.

- [ ] **Step 3: Run migration smoke against a safe test DB only**

Use existing schema tests as the migration smoke. Do not run `alembic upgrade head` against `portfolio_dev`.

Acceptable command:

```bash
uv run pytest api/tests/db/test_schema_alignment.py::test_core_schema_alignment_after_full_migration_cycle -q
```

- [ ] **Step 4: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 5: Run broad gate**

Run:

```bash
make ci
```

Expected: pass. If it fails because local PostgreSQL/Redis is unavailable, root-cause the failure and either start only required disposable test services or report the manual blocker. Do not point any broad gate at `portfolio_dev`.

- [ ] **Step 6: Run feature gate**

Because VNEXT-01C touches migrations, run:

```bash
make feature-check
```

Expected: pass. If a narrower gate is needed, document the reason and request
explicit user approval before merge.

## Task 5: PR, Adversarial Review, Fixes, And Merge

**Files:**

- No predetermined additional files.

- [ ] **Step 1: Commit implementation**

Use a small scoped commit:

```bash
git add api/app/db/models.py api/migrations/versions/00008_accounting_state.py api/tests/db/test_schema_alignment.py api/tests/db/test_accounting_state_schema.py docs/superpowers/plans/2026-06-18-vnext-01c-durable-accounting-state-schema.md
git commit -m "feat(api): add durable accounting state schema"
```

- [ ] **Step 2: Open PR**

Create a PR to `main` titled:

```text
Add durable accounting state schema
```

PR body must include:

- summary of the four canonical tables;
- explicit protected DB safety note;
- targeted DB test output;
- `git diff --check` output;
- `make ci` output;
- `make feature-check` output;
- note that no API/service/frontend/runtime behavior was changed.
- note that `portfolio_dev` was not accessed.

- [ ] **Step 3: Adversarial review**

Review the PR against:

- wrong committed accounting decisions;
- active-row uniqueness gaps;
- partial-index predicate gaps;
- missing check-constraint coverage;
- JSON-only uniqueness assumptions;
- many-leg transfer overlap assumptions;
- lifecycle/supersession holes;
- check constraints that block valid unknown/provisional states;
- check constraints that allow wrong-money states;
- migration downgrade correctness;
- test DB safety;
- hidden `portfolio_dev` assumptions;
- missing schema alignment coverage;
- CI flakiness.

- [ ] **Step 4: Fix found bugs with tests first**

For each bug:

1. Write or adjust a failing test.
2. Run the targeted test to verify the failure.
3. Fix the implementation.
4. Re-run the targeted test.
5. Re-run `uv run pytest api/tests/db -q`.

- [ ] **Step 5: Merge only after gates pass**

Merge only when:

- all found bugs are fixed;
- targeted DB tests pass;
- `git diff --check` passes;
- `make ci` passes or the user explicitly approves a narrower documented gate;
- `make feature-check` passes or the user explicitly approves a narrower documented gate;
- GitHub CI is passing, or GitHub CI is stuck and the user explicitly approves merge based on local passing `make ci`.

## Non-Goals

- No service methods that write accounting decisions.
- No review API.
- No frontend accounting review UI.
- No dashboard contract implementation.
- No XTB browser automation.
- No migration against `portfolio_dev`.
- No private broker data inspection.
