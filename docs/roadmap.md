# vNext Roadmap

Status: source-of-truth phase roadmap.
Last updated: 2026-06-15.

This roadmap defines phase order. Product semantics live in `docs/product_north_star.md`, implementation tickets live in `docs/implementation_plan.md`, and acceptance gates live in `docs/verification_matrix.md`.

## Phase 0: Clean Docs And Classify State

Goal: make the repo orientation surface current before backend or UI implementation starts.

Deliverables:

- Inventory tracked, untracked, ignored, and filesystem docs/data.
- Preserve broker fixture/data directories unless explicitly classified otherwise.
- Create the hot path: `docs/current_state.md`, `docs/product_north_star.md`, `docs/roadmap.md`, `docs/implementation_plan.md`, and `docs/verification_matrix.md`.
- Trim top-level orientation docs to point at the hot path.
- Salvage useful decisions from stale docs, then delete stale docs with a deletion ledger.
- Verify the remaining docs surface is limited to hot path, safety/runtime references, architecture/policy references, current superpowers specs, and reviewed visual references.

## Phase 1: Trusted Money Numbers

Goal: make capital truth trustworthy before product expansion.

Build:

- Accounting source model for Binance, XTB, Aster, Hyperliquid, tracked wallets, cash, and commodities.
- Transfer classification for external cashflows, internal movements, and trades/allocation.
- Capital truth contract with gross deposits, gross withdrawals, net capital at work, lifetime P&L, first activity date, and capital rhythm.
- 7D, 30D, and 90D rolling period performance with investment gain separated from deposits and withdrawals.
- Historical P&L anchors, reconstruction confidence, and confidence degradation rules.
- Manual reconciliation queue with durable accounting decisions.

Exit criteria:

- Unknown outgoing crypto transfers create reconciliation tasks instead of being treated as withdrawals.
- Lifetime P&L defaults to current portfolio value minus net capital at work.
- Material unresolved issues degrade or block derived stats.
- Approvals create durable accounting state, not only activity logs.

## Phase 2: Structure And Distribution Analytics

Goal: explain how money is distributed and what drives movement after money truth is reliable.

Build:

- Asset-type distribution for crypto, stocks/ETFs, commodities, cash, and fallback other.
- Asset-level allocation and current value.
- Cash reserve/deployable cash views, including stablecoin and broker cash.
- Holding drivers for 7D, 30D, and 90D movement.
- Distribution-over-time analytics based on trusted historical anchors.
- Allocation compared against contributed and allocated capital over time.
- Venue/account drilldowns where they explain exposure.

Exit criteria:

- Dollars lead percentages.
- USDT and USDC classify as cash.
- Percentages are hidden, downgraded, or marked unavailable when denominators are unreliable.

## Phase 3: Dashboard And Asset Detail

Goal: rebuild user-facing portfolio surfaces on trusted contracts.

Build:

- First dashboard screen with current total value, 30D rolling investment gain/loss, lifetime P&L and net capital when confidence allows, trust state, asset-type distribution, cash reserve, top holding drivers, and top reconciliation action.
- Asset detail with current position/value, current-position P&L, capital allocated, lifetime contribution/P&L when confidence allows, recent movement, driver explanation, and trust blockers.
- Collapsed drilldowns for raw transactions, activity, import rows, and logs.
- Manual mobile/browser smoke evidence for dashboard and asset detail.

Exit criteria:

- No ambiguous all-time/total P&L labels on the first screen.
- Log-heavy UI is not the primary product.
- Severe accounting issues block or hide sensitive derived stats.

## Later Or Deferred

Defer until Phases 1-3 are trusted:

- Watchlist expansion.
- Alerts and thesis tracking.
- Advanced decision support.
- Advanced risk metrics.
- Benchmark ratios on the first dashboard screen.
- Calendar report views such as this month, last month, and YTD.
- Broader live Binance delta coverage beyond export-first categories.
