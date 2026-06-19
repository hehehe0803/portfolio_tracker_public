# Dashboard Contract

Status: draft contract for Dashboard Contract Spec Worker.
Last updated: 2026-06-18.

This document defines the Portfolio Performance Cockpit dashboard contract shape at the field/group level. It is a planning contract for frontend mockups and later API/shared-contract implementation. It does not implement backend routes, database schema, shared contracts, or UI components.

Product source-of-truth remains `docs/product_north_star.md`. Reconciliation confidence rules remain `docs/architecture/reconciliation_policy.md`.

## Goal

The dashboard MVP must show a chart-first portfolio cockpit without overstating accounting confidence.

It must let these truths coexist:

- Current portfolio value can be trusted before full history is trusted.
- Cash reserve can be trusted or blocked independently from the total value.
- Inception history, lifetime P&L, return percentages, and rolling performance can remain provisional or blocked while current value is usable.
- Material or severe accounting gaps must route the user to a clear accounting review action instead of pretending precision.

## MVP Dashboard Sections

The first screen should be contract-driven and organized around these sections:

1. Current value header
   - Current total portfolio value.
   - As-of timestamp and data freshness.
   - Current-value trust state.
   - Top current-value blocker when one exists.

2. Inception performance chart
   - Primary line: total portfolio value from inception.
   - Companion line: net capital at work.
   - Deposit and withdrawal markers available for hover/drilldown, not noisy default clutter.
   - Chart-level confidence state independent from current-value confidence.

3. Performance summary
   - Default period: rolling 30D.
   - Available periods: rolling 7D, rolling 30D, rolling 90D.
   - Starting value, ending value, external deposits, external withdrawals, and investment gain/loss.
   - Lifetime P&L and return percentage only when confidence allows.

4. Capital context
   - Gross deposits.
   - Gross withdrawals.
   - Net capital at work.
   - First activity date.
   - Average net capital added per month when first activity date is trusted enough.

5. Allocation and cash reserve
   - Asset-type allocation: crypto, stocks/ETFs, commodities, cash, fallback other.
   - Dollars lead percentages.
   - USDT and USDC are cash reserve, not crypto exposure.
   - Cash reserve split between stablecoin reserve, broker cash, and other tracked cash when available.

6. Holding drivers
   - Top 5 gain drivers and top 5 loss drivers for the selected period.
   - Dollars lead percentages.
   - Low-confidence drivers are flagged, demoted, or omitted instead of shown as precise.

7. Source and broker status
   - Status of Binance, XTB, Aster, Hyperliquid, tracked wallets, cash, commodities, and any fallback source.
   - Coverage/freshness summaries that explain whether current value, cash, and history are trusted.

8. Review queue badges and primary action
   - Accounting review count and top accounting task.
   - Investment review/watchlist counts may appear later, but accounting review must remain verbally separate.
   - When a material or blocking issue exists, the primary action should route to the top accounting reconciliation task.

Raw transactions, import rows, parser evidence, and activity logs belong behind drilldowns. They are not MVP dashboard sections.

## Route-Level Contract Assumptions

Future implementation can expose this through a versioned portfolio route, for example:

```text
GET /v1/portfolio/dashboard
```

Route assumptions:

- The route returns one cockpit payload for the default dashboard.
- Default period is `30d`; clients may request `7d`, `30d`, or `90d`.
- The chart range defaults to inception when available.
- All money values are USD unless a nested field explicitly states another currency.
- Every chart point and sensitive metric carries confidence metadata or inherits it from a clearly named group.
- Current value confidence must not be inferred from history confidence.
- History confidence must not be inferred from current value confidence.
- The route may include links or action descriptors for drilldowns and review tasks, but it must not require frontend code to infer accounting decisions from raw logs.
- Schema, route naming, and shared-contract class/interface names are implementation decisions for VNEXT-07A and require the shared-contract gates before landing.

## Trust-State Language

Use scoped trust states. A single global confidence flag is not enough.

Allowed states:

| State | Meaning | Dashboard behavior |
| --- | --- | --- |
| `trusted` | No known material blocker for this scope. | Show normally. |
| `warning` | Unresolved issue exists below the material threshold. | Show value with warning context. |
| `provisional` | Usable for exploration, not final truth. | Show demoted or labeled as provisional. |
| `review_required` | Semantic decision or material gap needs review. | Show the top accounting action. |
| `blocked` | Metric may be wrong or misleading. | Hide/block sensitive value and show blocker. |

Trust language by scope:

- Trusted current value: latest tracked holdings, tracked cash, stablecoin reserve, broker cash, and position existence reconcile to authoritative current evidence.
- Provisional history: historical values are usable for chart exploration but lack complete source coverage, anchors, prices, or cashflow reconciliation for final lifetime claims.
- Blocked/unreconciled value: a missing or conflicting input affects current total value, cash reserve, position existence, lifetime P&L, historical coverage, or rolling period performance.

Sensitive derived stats must be hidden, blocked, or demoted when their scope is `provisional`, `review_required`, or `blocked`:

- Lifetime P&L.
- Return percentage.
- Rolling period performance.
- Inception chart claims.
- Asset-level lifetime contribution/P&L.

Display rule: a trusted current total must never make lifetime P&L or the inception chart look trusted by association.

## Payload Shape

This shape is illustrative and field/group-level only. Runtime implementation should convert it into the repo's shared Python and TypeScript contracts when VNEXT-07A starts.

```json
{
  "as_of": "2026-06-18T12:00:00Z",
  "base_currency": "USD",
  "selected_period": "30d",
  "available_periods": ["7d", "30d", "90d"],
  "confidence": {
    "current_value": {
      "state": "trusted",
      "issues": []
    },
    "cash_reserve": {
      "state": "trusted",
      "issues": []
    },
    "history": {
      "state": "provisional",
      "issues": []
    },
    "lifetime_pnl": {
      "state": "blocked",
      "issues": []
    },
    "rolling_performance": {
      "state": "provisional",
      "issues": []
    }
  },
  "current_value": {
    "amount_usd": "125000.00",
    "as_of": "2026-06-18T12:00:00Z",
    "confidence_state": "trusted",
    "blocked": false
  },
  "capital": {
    "gross_deposits_usd": "90000.00",
    "gross_withdrawals_usd": "10000.00",
    "net_capital_at_work_usd": "80000.00",
    "first_activity_date": "2023-01-15",
    "avg_net_capital_added_per_month_usd": "1904.76",
    "confidence_state": "provisional"
  },
  "pnl": {
    "lifetime_pnl_usd": null,
    "lifetime_return_pct": null,
    "display_state": "blocked",
    "blocked_reason_codes": ["history_coverage_gap"]
  },
  "periods": [
    {
      "period": "30d",
      "starting_value_usd": "118000.00",
      "ending_value_usd": "125000.00",
      "external_deposits_usd": "2000.00",
      "external_withdrawals_usd": "0.00",
      "investment_gain_usd": "5000.00",
      "return_pct": null,
      "confidence_state": "provisional",
      "reason_codes": ["missing_historical_anchor"]
    }
  ],
  "value_series": [
    {
      "date": "2026-06-18",
      "value_usd": "125000.00",
      "net_capital_at_work_usd": "80000.00",
      "confidence_state": "trusted",
      "source": "current_snapshot",
      "markers": []
    }
  ],
  "allocation": {
    "total_usd": "125000.00",
    "confidence_state": "trusted",
    "groups": [
      {
        "asset_type": "cash",
        "label": "Cash reserve",
        "value_usd": "25000.00",
        "percentage": "20.00",
        "percentage_display_state": "trusted",
        "children": [
          {
            "kind": "stablecoin_reserve",
            "value_usd": "15000.00",
            "symbols": ["USDT", "USDC"],
            "confidence_state": "trusted"
          },
          {
            "kind": "broker_cash",
            "value_usd": "10000.00",
            "sources": ["xtb"],
            "confidence_state": "trusted"
          }
        ]
      }
    ]
  },
  "drivers": {
    "period": "30d",
    "confidence_state": "provisional",
    "top_gainers": [
      {
        "symbol": "BTC",
        "name": "Bitcoin",
        "asset_type": "crypto",
        "movement_usd": "3000.00",
        "movement_pct": null,
        "confidence_state": "trusted",
        "detail_href": "/holdings/BTC"
      }
    ],
    "top_losers": []
  },
  "sources": [
    {
      "source": "xtb",
      "label": "XTB",
      "current_value_state": "trusted",
      "cash_state": "trusted",
      "history_state": "provisional",
      "last_import_at": "2026-06-18T10:00:00Z",
      "coverage_start": "2025-09-07",
      "coverage_end": "2026-06-18",
      "open_issue_count": 1
    }
  ],
  "review_queue": {
    "accounting": {
      "open_count": 3,
      "blocking_count": 1,
      "top_action": {
        "task_id": "task_123",
        "label": "Resolve missing XTB history coverage",
        "href": "/review?task=task_123",
        "affected_scopes": ["history", "lifetime_pnl"]
      }
    },
    "investment": {
      "open_count": 0
    }
  },
  "drilldowns": {
    "transactions_href": "/portfolio/transactions",
    "imports_href": "/ops/imports",
    "activity_href": "/ops/activity"
  }
}
```

## Field Group Requirements

### Value Time Series

Required fields:

- `date`.
- `value_usd`.
- `net_capital_at_work_usd`.
- `confidence_state`.
- `source`: exact anchor, reconstructed, current snapshot, or staged/provisional source.
- `markers`: deposits, withdrawals, missing anchors, source gaps, or review events.

Rules:

- Exact broker/account snapshot anchors beat reconstruction.
- Reconstruction must degrade when required transactions or historical prices are missing.
- A point can be trusted, provisional, review-required, or blocked independently from adjacent points.

### Net Capital

Required fields:

- `gross_deposits_usd`.
- `gross_withdrawals_usd`.
- `net_capital_at_work_usd`.
- `first_activity_date`.
- `avg_net_capital_added_per_month_usd`.
- `confidence_state`.

Rules:

- `net_capital_at_work = gross_deposits - gross_withdrawals`.
- Gross deposits remain context, not the default denominator for lifetime P&L.
- Monthly averages are provisional or unavailable when first activity date is missing or low confidence.

### P&L

Required fields:

- `lifetime_pnl_usd`.
- `lifetime_return_pct`.
- `period_investment_gain_usd`.
- `display_state`.
- `blocked_reason_codes`.

Rules:

- `lifetime_pnl = current_portfolio_value - net_capital_at_work` when confidence allows.
- `investment_gain = ending_value - starting_value - deposits + withdrawals`.
- Deposits inside a period must not appear as investment gain.
- Withdrawals inside a period must not appear as investment loss.

### Allocation

Required fields:

- `asset_type`.
- `label`.
- `value_usd`.
- `percentage`.
- `percentage_display_state`.
- `confidence_state`.
- Optional child groups for venue, stablecoin reserve, broker cash, source, tag, or sector.

Rules:

- Use asset types: crypto, stocks/ETFs, commodities, cash, other.
- USDT and USDC are cash reserve.
- Dollars lead percentages.
- Percentages are hidden or marked unavailable when denominator confidence is weak.
- Asset-type totals must reconcile to trusted current value within the documented distribution tolerance before being marked trusted.

### Cash

Required fields:

- `total_cash_reserve_usd`.
- `stablecoin_reserve_usd`.
- `broker_cash_usd`.
- `other_cash_usd`.
- `deployable_cash_usd` when known.
- `confidence_state` for each cash scope.

Rules:

- Cash is tracked portfolio reserve unless withdrawn.
- Broker cash, stablecoin reserve, and other cash can have different trust states.
- If cash affects current value or cash reserve and is unreconciled, derived stats must be blocked or demoted.

### Broker/Source Status

Required fields:

- `source`.
- `label`.
- `current_value_state`.
- `cash_state`.
- `history_state`.
- `last_import_at`.
- `coverage_start`.
- `coverage_end`.
- `open_issue_count`.

Rules:

- Sources include Binance, XTB, Aster, Hyperliquid, tracked wallets, cash, commodities, and fallback other where needed.
- XTB full statements are authoritative for historical reconciliation when coverage/control totals are present.
- XTB daily PDFs and Gmail daily PDFs are provisional fast updates unless reconciled against full statements.

### Review Queue Badges

Required fields:

- `accounting.open_count`.
- `accounting.blocking_count`.
- `accounting.top_action`.
- `investment.open_count` when investment review is present.

Rules:

- Accounting review and investment review are separate products.
- Accounting tasks must describe what happened, why it matters, choices, metric effects, and remaining unresolved evidence.
- Dashboard badges should link to decisions, not raw parser logs.

## Verification Gates Before Implementation

Docs/spec gate for this file:

- `git diff --check -- docs/architecture/dashboard_contract.md`

Future VNEXT-07A API/shared-contract gates:

- API tests for trusted current/provisional history payload.
- API tests for severe current-value blockers hiding or blocking sensitive derived stats.
- API tests for rolling 7D, 30D, and 90D period fields.
- API tests for top 5 gain and top 5 loss drivers.
- Shared Python and TypeScript contracts updated together.
- Frontend shared-contract smoke passes.

Future dashboard UI gates:

- Dashboard tests cover trusted state.
- Dashboard tests cover severe-blocked state.
- Dashboard tests assert ambiguous "all-time P&L" or "total P&L" labels are absent.
- Desktop and mobile browser smoke show chart-first first viewport, no overlap, useful confidence state, and useful top reconciliation action.

Safety gates:

- No schema/migration work without the protected DB runbook and explicit scope.
- No destructive or smoke test may target `portfolio_dev`.
- No private broker statements, exports, credentials, cookies, or account references may be committed.

## Manual Gates Before Implementation

User/coordinator review is required before:

- Promoting this field-level shape into shared Python/TypeScript contracts.
- Choosing final route name, response model names, or schema names.
- Implementing dashboard UI from this contract.
- Marking inception history, lifetime P&L, or rolling performance trusted.
- Adding schema or migration work for durable accounting state.
- Adding XTB browser automation, hidden endpoint capture, cookies, or credential/session storage.
- Changing the accepted confidence state vocabulary or materiality thresholds.

Open implementation decisions for VNEXT-07A:

- Exact route path and query parameter names.
- Exact money serialization convention in shared contracts.
- Whether unavailable blocked values serialize as `null`, an omitted value, or a value object with `display_state = blocked`.
- Exact drilldown/action descriptor shape.
- Exact source identifiers and asset-type enum names in shared contracts.
