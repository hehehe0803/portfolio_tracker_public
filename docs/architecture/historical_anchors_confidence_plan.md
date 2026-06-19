# Historical Anchors And Confidence Plan

Status: planning contract for VNEXT-04A.
Last updated: 2026-06-18.

This document defines the historical value anchor and confidence behavior needed before rolling period performance, inception charts, lifetime P&L, and asset-level lifetime contribution can be trusted. It is a planning artifact only. It does not implement runtime code, shared contracts, migrations, or UI.

Product semantics remain in `docs/product_north_star.md`. Reconciliation safety and scoped confidence rules remain in `docs/architecture/reconciliation_policy.md`. Dashboard field-group expectations remain in `docs/architecture/dashboard_contract.md`.

## Goal

VNEXT-04A should create a historical value/confidence layer that answers:

- Which value is authoritative for a date.
- Whether a value is an exact anchor or reconstructed.
- Why a date, period, or derived metric is trusted, warning, provisional, review-required, or blocked.
- Which follow-up reconciliation task or source gap must be resolved before a sensitive metric can be shown as trusted.

The layer must allow current portfolio value to be trusted independently from historical/inception metrics. A trusted latest snapshot must not make lifetime P&L, return percentage, rolling performance, or inception chart claims look trusted by association.

## Anchor Precedence

Use this precedence when multiple value sources exist for the same date or period boundary.

1. Exact authoritative broker/account snapshot anchor.
   - Full broker/account statements are the preferred source when the relevant statement range, positions, cash balances, trades, deposits, withdrawals, dividends, fees, taxes, swaps, commissions, corporate actions, and control totals reconcile.
   - XTB full XLSX/HTML/MHTML statements are authoritative historical baselines only after statement coverage and control totals reconcile.
   - A broker/account snapshot can anchor a whole source, account, asset, cash scope, or portfolio aggregate only for the scopes it actually proves.

2. Exact current portfolio snapshot.
   - `PositionSnapshot` rows and refreshed current holdings can anchor current value, current position existence, and current allocation.
   - They do not prove historical coverage, first activity date, net capital, lifetime P&L, or inception chart confidence by themselves.

3. Reconstructed value between accepted anchors.
   - Reconstruction may use canonical transactions, durable accounting decisions, and historical prices when inputs are complete enough.
   - Reconstruction is subordinate to an exact snapshot on the same date.
   - Reconstruction inherits the lowest confidence of required transactions, movement classifications, source coverage, price inputs, and boundary anchors.

4. Provisional fast-update evidence.
   - XTB daily PDFs and Gmail-discovered daily PDFs can stage recent trade evidence and review tasks.
   - They must not mark broker cash, full history, inception history, lifetime P&L, or historical return trusted unless reconciled against full statements or another authoritative control total.

5. No value.
   - If neither an exact anchor nor complete reconstruction exists, the date is a gap.
   - Gaps must produce reason codes and confidence effects instead of interpolated precision.

Tie-break rules:

- If exact snapshot and reconstructed value both exist for a date, use the exact snapshot unless a later ticket explicitly changes the product contract.
- If two exact anchors conflict, do not average or silently choose the newer one. Mark the affected scope `review_required` or `blocked`, record both source references, and create or surface the reconciliation task.
- If an anchor proves positions but not cash, mark position scope separately from cash reserve, broker cash, current total, and derived P&L.
- If an anchor is source-level rather than portfolio-level, aggregate confidence must account for all sources needed by the requested metric.

## Reconstruction Rules

Reconstruction is allowed only when the service can explain all inputs needed for the requested date or period boundary.

Required inputs:

- A start boundary: exact anchor, accepted opening position/cash state, or clearly scoped zero state before first activity.
- A complete canonical transaction ledger for the reconstructed interval.
- Durable movement semantics from the accounting taxonomy and reconciliation decisions: external cashflow, internal movement, or trade/allocation.
- Historical USD prices for every asset quantity that must be valued on the reconstructed date.
- FX conversion evidence when the source value is not USD.
- Stable-value handling for USD, USDT, USDC, BUSD, FDUSD, and DAI at 1 USD unless a later policy explicitly models depeg or source-specific exceptions.
- Cash and broker-cash events, including deposits, withdrawals, dividends, fees, taxes, swaps, commissions, and cash operations when those affect the scope.
- Source coverage metadata sufficient to prove the interval is not missing statement dates or source rows.

Failure and degradation rules:

- Missing historical price for a non-cash asset prevents a trusted reconstructed value for any scope that includes that asset.
- Missing cash operation coverage prevents trusted broker cash and any aggregate depending on broker cash.
- Missing first activity date prevents trusted capital rhythm and inception chart start.
- Unclassified crypto withdrawal prevents trusted external capital, lifetime P&L, and any rolling period that crosses the unresolved event.
- Missing or low-confidence transfer classification keeps the affected amount out of trusted capital totals until resolved.
- Transaction-ledger reconstruction must not overwrite or hide an exact anchor mismatch. A mismatch is evidence of a gap or defect.
- Reconstructed dates should carry `source = reconstructed` and reason codes that explain both the positive basis and any unresolved limitations.

Recommended reason code families:

- `exact_anchor_preferred`
- `reconstructed_from_complete_ledger`
- `missing_historical_price`
- `missing_transaction_coverage`
- `missing_cash_control_total`
- `statement_coverage_gap`
- `unclassified_transfer`
- `anchor_conflict`
- `fast_update_provisional`
- `first_activity_date_untrusted`
- `current_value_trusted_history_untrusted`

## Confidence State Degradation

Confidence must be scoped. Do not expose one global confidence flag for the portfolio.

Required scopes:

- `current_value`
- `cash_reserve`
- `broker_cash`
- `stablecoin_reserve`
- `position_existence`
- `history`
- `lifetime_pnl`
- `rolling_performance`
- `asset_lifetime_contribution`

Use these states:

| State | Meaning | Historical-anchor behavior |
| --- | --- | --- |
| `trusted` | No known material blocker for the scope. | Exact authoritative anchor or complete reconstruction from trusted inputs. |
| `warning` | Unresolved issue exists below material threshold and does not change the sensitive metric. | Show value with warning reason codes. |
| `provisional` | Value is useful for exploration but not final truth. | Show demoted value; never use as proof for lifetime or return claims. |
| `review_required` | Semantic decision or material gap needs user or agent review. | Surface the accounting task and affected scopes. |
| `blocked` | Metric may be materially wrong or misleading. | Hide or block sensitive derived value. |

Degradation rules:

- A point or period inherits the weakest state among required anchors, transactions, prices, source coverage, and accounting decisions.
- A missing price for an asset with non-zero value makes the affected point at least `provisional`; if it affects current total, position existence, lifetime P&L, or period performance, mark the sensitive metric `blocked`.
- An anchor conflict is `review_required` for source-specific history and `blocked` for derived metrics that depend on the conflicted value.
- Unresolved amount thresholds should follow `docs/product_north_star.md` for headline materiality and `docs/architecture/reconciliation_policy.md` for scoped reconciliation hard blocks.
- Issues that affect whether a current position exists, current total value, cash reserve, lifetime P&L, position history, or source coverage are hard blockers for the relevant sensitive metrics even if the dollar amount is small.
- Low-value unresolved issues may remain `warning` only when they do not affect current value, cash reserve, position existence, lifetime P&L, historical coverage, or rolling period performance.

## Metric Visibility Effects

Historical anchor confidence directly controls which dashboard and API metrics can be shown.

Current value:

- Show prominently when `current_value` is `trusted`.
- Do not infer trusted history from trusted current value.
- If position existence is blocked, current total and allocation percentages must be blocked or partitioned by trusted/untrusted scope.

Inception chart:

- Chart points with trusted anchors or complete reconstruction can be shown normally.
- Provisional points can be shown only with demoted styling and reason codes.
- Blocked points should appear as gaps or blocked intervals, not precise values.
- Net capital line requires trusted external cashflow classification for the covered interval.

Rolling 7D, 30D, and 90D performance:

- Starting value and ending value must each have anchor confidence.
- Period investment gain uses `ending_value - starting_value - deposits + withdrawals`.
- Missing start or end anchor makes the period at least `provisional`.
- Unclassified cashflow inside the period blocks trusted investment gain.
- Deposits inside a period must not display as investment gain. Withdrawals inside a period must not display as investment loss.

Lifetime P&L and return percentage:

- Show only when current value, net capital, first activity date where needed, and historical/source coverage are trusted enough.
- Block when historical coverage, unresolved transfers, cash control totals, or anchor conflicts could materially change net capital or current value.
- Gross deposits remain context; they are not the default lifetime P&L denominator.

Asset-level lifetime contribution and P&L:

- Block or demote when cost basis, source coverage, price history, or transfer provenance is missing.
- A trusted current position value is not enough to trust asset-level lifetime contribution.

Allocation and cash reserve:

- Dollars may be shown before percentages when current value is trusted.
- Percentages are hidden or marked unavailable when denominator confidence is weak.
- Stablecoin reserve and broker cash must carry separate confidence states before combining into total cash reserve.

Review action:

- When any material or blocking historical issue exists, the top accounting reconciliation task should be the primary action for the affected dashboard scope.
- Raw transactions, parser rows, import evidence, and activity logs stay behind drilldowns.

## Test Cases

Future VNEXT-04A implementation should add focused tests under `api/tests/pricing/` and `api/tests/analytics/`.

Anchor precedence tests:

- Exact broker/account snapshot is selected over reconstructed value for the same date.
- Current snapshot can make current value trusted while history and lifetime P&L remain provisional or blocked.
- Daily XTB PDF evidence creates a provisional fast-update anchor but does not trust broker cash, history, or lifetime P&L.
- Conflicting exact anchors produce `review_required` or `blocked` instead of silent selection.

Reconstruction tests:

- Complete transaction ledger plus historical prices reconstructs a dated value and marks `source = reconstructed`.
- Missing historical price degrades the date and blocks affected rolling period performance.
- Missing transaction/source coverage creates `statement_coverage_gap` or `missing_transaction_coverage`.
- Stable-value symbols price at 1 USD for reconstruction.
- Internal transfer crossing venues preserves portfolio value and does not change external capital.
- Unclassified outgoing crypto transfer blocks trusted net capital and lifetime P&L.

Metric visibility tests:

- Missing first activity date hides or provisionalizes capital rhythm.
- Missing starting anchor marks rolling 30D performance provisional.
- Deposit inside a period is not investment gain.
- Withdrawal inside a period is not investment loss.
- Severe current-value or position-existence issue blocks lifetime P&L, return percentage, period performance, and asset-level lifetime contribution.
- Low-value non-sensitive issue surfaces as warning without blocking current value.

Integration-shape tests:

- Historical value point exposes date, value, net capital at work when available, confidence state, source, and reason codes.
- Period boundary exposes starting value confidence and ending value confidence separately.
- Aggregate portfolio confidence is the weakest required source scope, not a global latest status.

## Implementation Follow-Ups

Suggested follow-up tickets for the code implementation:

1. Add a focused historical value/confidence service under `api/app/services/`.
   - Define internal dataclasses for anchor candidates, selected historical value points, period boundaries, and scoped confidence issues.
   - Keep this separate from `portfolio_state.py` unless a small helper is clearly reusable there.

2. Extend portfolio state access with anchor queries.
   - Query exact `PositionSnapshot` rows by date/range.
   - Return source/type metadata for current snapshot anchors versus historical broker/account anchors.
   - Preserve existing snapshot refresh behavior.

3. Add historical price access seams.
   - Current `pricing.py` is live/current-price oriented.
   - Historical reconstruction needs explicit historical price lookup or a staged interface that can fail with `missing_historical_price` instead of calling live quotes for past dates.

4. Add source coverage inputs.
   - Represent statement coverage ranges, control-total reconciliation, and daily-PDF provisional status before trusting full history.
   - XTB full statements need first-class coverage/control-total metadata before they can fully anchor history and broker cash.

5. Connect durable accounting decisions.
   - Use transfer links, external-cashflow classifications, import approvals, manual cost basis, and explicit unknown decisions as reconstruction inputs once VNEXT-01C/VNEXT-05A provide them.
   - Until then, expose unresolved movement and missing-cost-basis reason codes.

6. Feed downstream period/dashboard contracts.
   - VNEXT-03A should consume selected start/end anchors and confidence states.
   - VNEXT-07A should expose scoped confidence and reason codes through shared contracts.

7. Keep protected data out of tests.
   - Use synthetic fixtures for normal tests.
   - Optional private XTB regression fixtures must remain under ignored `data/` and skip clearly when absent.
   - Do not run migrations, schema repair, broker sync experiments, destructive tests, or smoke seeders against `portfolio_dev`.
