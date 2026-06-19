# Reconciliation MVP And XTB Truth Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first revamp implementation slice: trusted current value can progress independently while XTB/history/inception metrics remain provisional until coverage reconciliation proves them.

**Architecture:** Add evidence/coverage policy first, then implement XTB cash-ledger correctness and confidence-aware dashboard input contracts. Use staged evidence and deterministic reconciliation rules; avoid semantic auto-repair unless backed by authoritative control totals or explicit user approval.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, existing XTB parsers/import services, Python analytics services, shared Python/TypeScript contracts, Next.js frontend consumers later.

---

## Safety Gates

- Do not touch `portfolio_dev` unless `docs/local_prod_db_migration_runbook.md` is read and user approval is explicit.
- Destructive tests must use localhost database names containing `test` or `smoke`.
- No credentials, cookies, PDFs, statements, or private broker data may be committed.
- XTB automation is discovery-only in this plan; no browser login implementation is included here.
- Any schema/migration decision must stop for user review before code implementation.

## File Structure

Expected files for this sprint:

- Create: `docs/architecture/reconciliation_policy.md`
  - Defines zero-wrong-decision policy, staged evidence, control totals, confidence states, and thresholds.
- Create: `docs/architecture/xtb_source_coverage.md`
  - Coverage matrix for XTB XLSX/HTML/MHTML, daily PDFs, Gmail PDFs, manual exports, future browser automation, and potential hidden endpoint.
- Create: `api/app/services/xtb_cash_ledger.py`
  - Focused XTB cash ledger computation from XTB transactions.
- Modify: `api/app/services/analytics.py`
  - Only if needed to consume cash-ledger results; keep edits narrow.
- Modify: `api/app/api/v1/portfolio.py`
  - Only if exposing confidence split in current endpoints during this sprint.
- Modify: `shared/python/contracts.py`
  - Only if API response contracts change.
- Modify: `shared/typescript/contracts.ts`
  - Only if API response contracts change.
- Test: `api/tests/xtb/test_xtb_cash_ledger.py`
- Test: `api/tests/api/test_portfolio_summary.py` or new targeted API contract tests if API shape changes.

If an implementation worker needs files outside this list, stop and update the dispatch record.

## Dispatch Records

Before assigning a worker, publish a record:

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

No two active workers may edit the same exact files. Schema/shared-contract changes are serialized.

## Task 1: Reconciliation Policy Doc

**Files:**

- Create: `docs/architecture/reconciliation_policy.md`

- [ ] **Step 1: Draft policy skeleton**

Include sections:

```markdown
# Reconciliation Policy

Status: proposed.

## Goal
## Zero-Wrong-Decision Rule
## False Positive / False Negative Definitions
## Staged Evidence Versus Canonical Accounting
## Deterministic Auto-Commit Rules
## Manual Review Rules
## Control Totals
## Confidence States
## Thresholds
## Dashboard Display Rules
## Protected Data Safety
```

- [ ] **Step 2: Encode zero-wrong-decision rules**

Required content:

- False positive: incorrect committed classification or repair.
- False negative: marking data trusted while a blocker remains.
- Auto-commit only exact deterministic mechanics.
- Semantic decisions require control-total proof or user approval.
- Historical/inception metrics can be provisional while current value is trusted.

- [ ] **Step 3: Encode thresholds**

Use:

```text
cash_statement_tolerance = broker currency precision
distribution_tolerance = max(0.01 USD, current_portfolio_value * 0.0001)
material_warning = unresolved amount > 10 USD or > 0.01% portfolio value
hard_block = issue affects current value, cash reserve, lifetime P&L, position existence, or historical coverage
```

- [ ] **Step 4: Verify docs diff**

Run:

```bash
git diff --check -- docs/architecture/reconciliation_policy.md
```

Expected: no output, exit 0.

- [ ] **Step 5: Handoff**

Commit only if the coordinator requests commits during planning execution.

## Task 2: XTB Source Coverage Matrix

**Files:**

- Create: `docs/architecture/xtb_source_coverage.md`

- [ ] **Step 1: Inventory implemented XTB source paths**

Read-only context:

- `api/app/api/v1/imports.py`
- `api/app/services/xtb_ingest.py`
- `api/app/services/xtb_parser.py`
- `api/app/services/xtb_gmail_ingest.py`
- `api/tests/xtb/`

Document existing support:

- XLSX full statement import.
- HTML/MHTML full statement import.
- Daily PDF executed trade parser.
- Gmail daily PDF discovery/previews.
- Import preview/confirm.

- [ ] **Step 2: Build coverage matrix**

Required columns:

```markdown
| Source | Current support | Trades | Dividends | Deposits/withdrawals | Fees/taxes/swaps | Cash balance | Positions | Corporate actions | Date coverage | Confidence | Notes |
```

Rows:

- XTB XLSX statement.
- XTB HTML/MHTML statement.
- XTB daily PDF.
- Gmail daily PDF.
- Future browser-downloaded full statement.
- Future captured export endpoint.
- Manual private regression fixture.

- [ ] **Step 3: Identify authoritative source**

State that full statements are authoritative baseline for historical reconciliation. Daily PDFs and Gmail PDFs are provisional fast updates unless reconciled against a full statement.

- [ ] **Step 4: Verify docs diff**

Run:

```bash
git diff --check -- docs/architecture/xtb_source_coverage.md
```

Expected: no output, exit 0.

## Task 3: XTB Cash Ledger Tests

**Files:**

- Create: `api/tests/xtb/test_xtb_cash_ledger.py`
- Create later: `api/app/services/xtb_cash_ledger.py`

- [ ] **Step 1: Write failing test for stock buy consuming USD cash**

Test shape:

```python
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.xtb_cash_ledger import calculate_xtb_cash_ledger


def _tx(tx_type, symbol, quantity, price=None, total=None, timestamp=None):
    return SimpleNamespace(
        institution="xtb",
        tx_type=tx_type,
        asset_symbol=symbol,
        quantity=Decimal(str(quantity)),
        price_usd=Decimal(str(price)) if price is not None else None,
        total_usd=Decimal(str(total)) if total is not None else None,
        fee=Decimal("0"),
        fee_currency="USD",
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=UTC),
        raw_data={},
    )


def test_xtb_stock_buy_consumes_usd_cash():
    ledger = calculate_xtb_cash_ledger([
        _tx("deposit", "USD", "1000", total="1000"),
        _tx("buy", "AAPL.US", "2", price="100", total="200"),
    ])

    assert ledger.cash_balance_usd == Decimal("800")
```

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run pytest api/tests/xtb/test_xtb_cash_ledger.py::test_xtb_stock_buy_consumes_usd_cash -q
```

Expected: fail because module/function does not exist.

- [ ] **Step 3: Add tests for sell, dividend, fee, withdrawal**

Required behaviors:

- Sell increases USD cash by proceeds minus fees.
- Dividend increases USD cash.
- Fee/commission/stamp duty decreases USD cash.
- Withdrawal decreases USD cash.

- [ ] **Step 4: Add test for unknown/missing amount**

Required behavior: missing reliable USD value creates a ledger issue and prevents trusted cash balance.

- [ ] **Step 5: Do not implement until tests are reviewed by coordinator**

Coordinator checks that tests reflect user’s zero-wrong strategy.

## Task 4: XTB Cash Ledger Implementation

**Files:**

- Create: `api/app/services/xtb_cash_ledger.py`
- Test: `api/tests/xtb/test_xtb_cash_ledger.py`

- [ ] **Step 1: Implement dataclasses**

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class XtbCashLedgerIssue:
    code: str
    message: str
    transaction_id: int | None = None
    asset_symbol: str | None = None


@dataclass(frozen=True)
class XtbCashLedger:
    cash_balance_usd: Decimal
    trusted: bool
    issues: tuple[XtbCashLedgerIssue, ...] = field(default_factory=tuple)
```

- [ ] **Step 2: Implement value helper**

Rules:

- Prefer `total_usd` when present.
- Else use `quantity * price_usd` for buys/sells.
- Else use USD/stable cash quantity only for cash rows.
- Else emit issue.

- [ ] **Step 3: Implement ledger transitions**

Rules:

- `deposit`, `external_deposit`: add cash.
- `withdrawal`, `external_withdrawal`: subtract cash.
- `buy`, `open`, `open_position`: subtract trade value and USD fees.
- `sell`, `close`, `close_position`: add proceeds minus USD fees.
- `dividend`: add cash.
- `fee`, `commission`, `stamp_duty`, `swap`: subtract value.
- Non-XTB rows ignored or rejected by issue, depending on function contract.

- [ ] **Step 4: Run targeted tests**

Run:

```bash
uv run pytest api/tests/xtb/test_xtb_cash_ledger.py -q
```

Expected: pass.

- [ ] **Step 5: Run broader XTB tests**

Run:

```bash
uv run pytest api/tests/xtb -q
```

Expected: pass or skip private fixtures clearly.

## Task 5: Portfolio Confidence Split Contract Decision

**Files:**

- Modify docs only unless coordinator approves runtime contract implementation:
  - `docs/architecture/reconciliation_policy.md`
  - This plan, if needed.

- [ ] **Step 1: Decide minimal confidence fields**

Proposed API shape:

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

- [ ] **Step 2: Stop for user review if shared contracts must change**

Do not edit `shared/python/contracts.py` or `shared/typescript/contracts.ts` until this shape is approved.

- [ ] **Step 3: Record the decision**

Update `docs/architecture/reconciliation_policy.md` with final field names.

## Task 6: Optional API Integration Spike

Only run this task if coordinator approves adding runtime behavior in this sprint.

**Files:**

- Modify: `api/app/api/v1/portfolio.py`
- Modify: `shared/python/contracts.py`
- Modify: `shared/typescript/contracts.ts`
- Test: `api/tests/api/test_portfolio_summary.py`

- [ ] **Step 1: Write API test for trusted current/provisional history**

Expected behavior:

- Current total can be trusted.
- History/inception/lifetime P&L can be provisional or blocked.
- Response exposes distinct confidence states.

- [ ] **Step 2: Run failing API test**

Run exact test path.

- [ ] **Step 3: Implement minimal response shape**

Keep implementation narrow. Do not redesign dashboard UI here.

- [ ] **Step 4: Run API and shared contract checks**

Run:

```bash
uv run pytest api/tests/api/test_portfolio_summary.py -q
(cd frontend && npm run typecheck:shared-contracts)
```

Expected: pass.

## Task 7: Final Verification

- [ ] **Step 1: Check status**

Run:

```bash
git status --short --branch
```

Expected: only planned files changed.

- [ ] **Step 2: Diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output, exit 0.

- [ ] **Step 3: Required tests**

Minimum if only docs/tests/service changed:

```bash
uv run pytest api/tests/xtb/test_xtb_cash_ledger.py -q
uv run pytest api/tests/xtb -q
```

If API/shared contracts changed:

```bash
uv run pytest api/tests/api/test_portfolio_summary.py -q
(cd frontend && npm run typecheck:shared-contracts)
```

- [ ] **Step 4: Handoff summary**

Include:

- Changed files.
- Verification output.
- Whether `portfolio_dev` was untouched.
- Any skipped gates and reason.
- Remaining user decisions.

## Review Gates

User review required before:

- Implementing schema/migrations.
- Persisting new durable accounting state shape.
- Adding XTB browser automation or endpoint capture.
- Storing cookies/session state.
- Marking inception/history trusted.
- Implementing dashboard UI on these contracts.

Coordinator review required before:

- Editing shared contracts.
- Broad edits to `analytics.py`.
- Any hidden endpoint/curl implementation.
- Dispatching parallel workers with overlapping write sets.
