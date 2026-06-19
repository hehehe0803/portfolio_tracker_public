# Portfolio Tracker vNext Design

Status: approved design index.
Last updated: 2026-06-15.

This document records the approved design direction and points to the source-of-truth hot path. It intentionally avoids duplicating the full product and execution contract so it does not drift.

## Source Documents

- Product semantics, formulas, labels, confidence rules, and non-goals: `docs/product_north_star.md`.
- High-level phase order: `docs/roadmap.md`.
- Parallel-agent implementation tickets, dependencies, and write boundaries: `docs/implementation_plan.md`.
- Acceptance gates and required tests: `docs/verification_matrix.md`.
- Safety and current repo state: `docs/current_state.md`, `AGENTS.md`, and `CLAUDE.md`.

## Approved Direction

vNext builds in this order:

1. Trusted money numbers and reconciliation.
2. Structure and distribution analytics.
3. Dashboard and asset detail UI on trusted contracts.
4. Later decision-support features.

The central design decision is that money truth comes before more surfaces. The app must first make current value, external capital, net capital at work, lifetime P&L, rolling period gain, and unresolved reconciliation blockers trustworthy enough to display.

## Parallel Execution Principle

Agents can execute in parallel only when:

- Their tickets in `docs/implementation_plan.md` have disjoint write sets.
- Shared contract dependencies have already landed.
- Schema/migration work is serialized.
- Broad edits to shared analytics services are serialized.
- Each ticket has matching verification gates in `docs/verification_matrix.md`.

No implementation agent should dispatch directly from this design index. Dispatch from `docs/implementation_plan.md`.

## Non-Goals Until Core Trust Exists

Do not expand these until the trusted money, distribution, dashboard, and asset-detail layers are accepted:

- Watchlist expansion.
- Alerts and thesis tracking.
- Advanced decision support.
- Advanced risk metrics.
- Benchmark ratio prominence.
- Calendar report views.
- Broader live Binance delta coverage beyond export-first categories.
