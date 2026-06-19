# Product North Star

Status: source-of-truth product contract.
Last updated: 2026-06-15.

## Purpose

Portfolio Tracker is a local-first portfolio analytics app. vNext succeeds only when the user can trust the money numbers first, then understand portfolio structure, and only then use higher-level decision support.

This document defines product semantics. It is not an implementation plan. Agent execution must use this document together with `docs/implementation_plan.md` and `docs/verification_matrix.md`.

## Source-Of-Truth Order

If docs conflict, use this order:

1. `AGENTS.md` and `CLAUDE.md` for safety and agent behavior.
2. `docs/current_state.md` for current repo/worktree state and protected-data cautions.
3. `docs/product_north_star.md` for product semantics, formulas, UI rules, and non-goals.
4. `docs/implementation_plan.md` for execution tickets, dependencies, and file boundaries.
5. `docs/verification_matrix.md` for acceptance gates.
6. Runbooks and fixture references for task-specific operational details.

If code contradicts this document, do not silently follow the code. Record the contradiction in the ticket handoff and either update the code to this contract or update this document only with explicit user approval.

## vNext Build Order

Build complete functional layers in this order:

1. Trusted money numbers and reconciliation.
2. Structure and distribution analytics.
3. Dashboard and asset detail UI on trusted contracts.
4. Later decision-support features.

No backend or UI implementation should start from deleted PRD/SRD/checklist material or dated premortems.

## Core Definitions

| Term | Definition |
| --- | --- |
| Tracked portfolio | All assets, cash, and venues the app treats as inside the user's portfolio. |
| External cashflow | Money or asset value entering from outside the tracked portfolio, or leaving for personal/outside use. |
| Internal movement | Transfer between tracked venues, accounts, or wallets. It does not change external capital. |
| Trade/allocation | Buy, sell, convert, or swap that changes asset exposure. |
| Current portfolio value | Trusted current USD value of tracked assets and tracked cash. |
| Gross deposits | Confirmed external deposits into the tracked portfolio. |
| Gross withdrawals | Confirmed external withdrawals out of the tracked portfolio. |
| Net capital at work | `gross_deposits - gross_withdrawals`. |
| Lifetime P&L | `current_portfolio_value - net_capital_at_work`, when confidence allows. |
| First activity date | First tracked deposit, trade, transfer, or broker/account statement anchor. |
| Accounting review | Workflow that resolves trust blockers in portfolio truth. |
| Investment review | Workflow that decides whether to hold, add, trim, exit, research, snooze, or archive an asset. |

Accounting review and investment review are separate products. Do not mix them in one primary queue unless the UI clearly labels which kind of decision is being made.

## Function 1: Trusted Money Numbers

### User Questions

The first vNext function must answer:

- What assets and cash do I have now?
- What are they worth now?
- How much external capital did I deposit?
- How much external capital did I withdraw?
- How much net capital is still at work?
- What is lifetime P&L?
- Since the first activity date, how much net capital have I added on average per month?
- What changed over rolling 7D, 30D, and 90D after separating cashflows from investment gain?
- Can I trust each number?
- What accounting task must I resolve when confidence is low?

### Capital Formulas

Default lifetime P&L:

```text
lifetime_pnl = current_portfolio_value - net_capital_at_work
```

Capital at work:

```text
net_capital_at_work = gross_deposits - gross_withdrawals
```

Capital rhythm:

```text
avg_net_capital_added_per_month = net_capital_at_work / elapsed_months_since_first_activity
avg_gross_deposit_per_month = gross_deposits / elapsed_months_since_first_activity
```

Rules:

- Gross deposits and gross withdrawals remain visible as context.
- Gross deposits alone must not be the default denominator for lifetime P&L.
- If `first_activity_date` is missing or low confidence, monthly averages are provisional or hidden.
- If current portfolio value is unreliable, lifetime P&L and return percentages are blocked.

### Rolling Period Performance

Dashboard default period is rolling 30D.

Required dashboard periods:

- Rolling 7D.
- Rolling 30D.
- Rolling 90D.

Calendar periods such as this month, last month, and YTD are deferred to later analytics/report views.

Period formula:

```text
investment_gain = ending_value - starting_value - deposits + withdrawals
```

Every period contract must expose:

- Starting value.
- Ending value.
- External deposits.
- External withdrawals.
- Investment gain/loss.
- Confidence state.
- Missing anchor or missing price reasons, when applicable.

Deposits inside a period must not appear as investment gain. Withdrawals inside a period must not appear as investment loss.

## Movement Classification

Track three movements separately:

1. External cashflow.
2. Internal movement.
3. Trade/allocation.

Rules:

- XTB stock-account withdrawals default to external withdrawals unless matched evidence says otherwise.
- Crypto withdrawals are never classified by sign alone.
- Binance trading account, Binance wallet, Aster, Hyperliquid, and tracked wallets are inside the crypto portfolio.
- Transfers among tracked crypto venues/accounts/wallets are internal movements when matched.
- Unknown outgoing crypto transfers create accounting reconciliation tasks. They are not automatically personal withdrawals.
- Asset-to-asset trades normalize through USD, USDT, or USDC value at trade time.
- Selling BTC and buying SOL should be represented as BTC out to stable value, then stable value allocated into SOL. Portfolio-level external capital does not increase.

## Sources And Asset Types

Tracked sources for vNext accounting:

- Binance.
- XTB.
- Aster.
- Hyperliquid.
- Tracked wallets where evidence exists.
- Cash.
- Commodities.

Aster and Hyperliquid are tracked crypto sources. Aster has mostly moved back to Binance, but it remains relevant for historical transfer matching. Hyperliquid remains relevant for current holdings and historical transfer matching.

Primary dashboard asset types:

- Crypto.
- Stocks / ETFs.
- Commodities.
- Cash.
- Other only as fallback.

Stablecoin rule:

- USDT and USDC are cash reserve, not crypto exposure.
- Stablecoin reserve is inside the tracked portfolio unless withdrawn.
- Use labels such as cash reserve, deployable cash, stablecoin reserve, and broker cash.
- Do not frame tracked cash as idle personal money.

Venues such as Binance, XTB, Hyperliquid, Aster, and wallets are secondary drilldowns that explain where exposure lives.

## Historical P&L Model

Historical P&L uses a hybrid model:

- Broker/account snapshots are anchors.
- Reconstruction between anchors may use transactions and historical prices only when complete enough.
- Each date and period has confidence metadata.
- Gaps and low-confidence states must be shown instead of pretending precision.

Inputs:

- Broker statements.
- Current and historical portfolio snapshots.
- Cashflow and trade ledgers.
- Historical prices.
- Confidence metadata.

If exact snapshot and reconstructed value both exist for a date, prefer the exact snapshot unless a ticket explicitly says otherwise.

## Reconciliation Workflow

Low-confidence accounting evidence creates manual reconciliation tasks, not raw log pages.

Examples:

```text
We found an outgoing 500 USDT from Binance on May 12.
Possible matches:
1. Hyperliquid deposit May 12, 498 USDT
2. Aster deposit May 13, 500 USDT
3. Personal withdrawal
4. Not sure yet
```

```text
We cannot calculate SOL P&L for May because cost basis is missing.
Choose source:
1. Import missing Binance trade CSV
2. Enter average cost manually
3. Mark as unknown for now
```

Approvals must write durable accounting state, such as:

- Transfer links.
- External-cashflow classifications.
- Import approvals.
- Manually confirmed cost basis.

Activity logs audit decisions. Activity logs are not the only decision state.

## Confidence And Materiality

Headline numbers degrade based on unresolved accounting value:

| State | Rule | Display Behavior |
| --- | --- | --- |
| Trusted | No known material blocker | Show normally. |
| Warning | Unresolved issue exists but is below material threshold | Show value with warning. |
| Provisional | Unresolved value is greater than max(1% of portfolio value, 100 USD) | Show value as provisional or demote prominence. |
| Severe/blocking | Unresolved value is greater than 5% of portfolio value, affects a meaningful current holding, or prevents reliable current total value | Hide or block sensitive derived stats. |

Always severe if the issue changes whether a position exists or materially changes current total value.

Sensitive derived stats include:

- Lifetime P&L.
- Return percentage.
- Period performance.
- Asset-level lifetime contribution/P&L.

When material or severe, the primary action should be the top reconciliation task.

## Function 2: Structure And Distribution Analytics

After money truth is trusted enough, the dashboard should explain:

- How much money is in each asset type.
- How much money is in each asset.
- How much cash reserve is available.
- Which holdings drive rolling 7D, 30D, and 90D moves.
- How asset-type and asset distribution changed over time.
- How current allocation differs from actual capital flow, comparing current allocation against contributed and allocated capital over time.
- Which venue/account holds each exposure when needed.

Rules:

- Dollars appear before percentages.
- Percentages require reliable denominators and confidence flags.
- Asset-type totals must reconcile to trusted current value within documented tolerance.
- USDT and USDC are excluded from crypto exposure and included in cash.
- Weak denominator suppresses or flags percentage display.

Distribution reconciliation tolerance:

```text
allowed_distribution_delta_usd = max(0.01 USD, current_portfolio_value * 0.0001)
```

If asset-type totals differ from trusted current value by more than this tolerance, distribution percentages are provisional or hidden until the mismatch is explained.

## Function 3: Dashboard And Asset Detail

The dashboard is an analytics surface, not a log browser.

The first dashboard screen should prioritize:

- Current total value.
- Rolling 30D investment gain/loss separated from contributions and withdrawals.
- Lifetime P&L and net capital at work when confidence allows.
- Trust/confidence state.
- Asset-type distribution.
- Cash reserve.
- Top holding drivers.
- Top reconciliation action when needed.

Asset detail exists because the user selected an asset. It should first answer:

- Current position and value.
- Current-position P&L.
- Capital allocated into the asset.
- Lifetime contribution/P&L for that asset when confidence allows.
- Recent movement.
- Why the asset drove portfolio movement.
- Trust blockers.

Raw transactions, activity, import rows, and logs should be collapsed behind explicit drilldowns.

Avoid on primary surfaces:

- Ambiguous all-time/total P&L labels.
- Naive return percentages with tiny, partial, or unreliable denominators.
- Benchmark ratios on the first dashboard screen.
- Raw performance summary blocks with unclear methodology.
- Long transaction/activity logs as primary UI.

## Deferred Until Core Trust Exists

Do not dispatch implementation agents for these until Phases 1-3 are accepted:

- Watchlist expansion.
- Alerts and thesis tracking.
- Advanced decision support.
- Advanced risk metrics.
- Benchmark ratio prominence.
- Calendar reports.
- Broader live Binance delta coverage beyond export-first categories.

## Open Decisions

These decisions should be resolved before implementation tickets that depend on them:

- Exact frontend wording for confidence states.

Durable accounting state shape decisions for transfer links,
external-cashflow classifications, import approvals, manual cost basis, and
explicit unknown cost basis are resolved in
`docs/architecture/durable_accounting_state_decision.md`. Schema work should use
that record before VNEXT-01C starts.

If an agent reaches one of these decisions, they should stop and propose a narrow decision update before implementing dependent behavior.
