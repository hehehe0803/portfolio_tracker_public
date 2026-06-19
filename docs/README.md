# Docs Index

Backlink: [`../AGENTS.md`](../AGENTS.md)

This directory contains the current vNext hot path, safety runbooks, architecture references, and reviewed visual references. It is no longer a broad status document.

## Hot Path

Read these before implementation work:

1. [`current_state.md`](current_state.md)
2. [`product_north_star.md`](product_north_star.md)
3. [`roadmap.md`](roadmap.md)
4. [`implementation_plan.md`](implementation_plan.md)
5. [`verification_matrix.md`](verification_matrix.md)

Current superpowers artifact:

- [`superpowers/specs/current-vnext-design.md`](superpowers/specs/current-vnext-design.md)

## Safety And Runtime

- [`local_prod_db_migration_runbook.md`](local_prod_db_migration_runbook.md) — required before migrations, schema-heavy work, protected sync experiments, or any operation that could affect `portfolio_dev`.
- [`local_app_compose_runbook.md`](local_app_compose_runbook.md) — local app Compose profile, scheduler/worker notes, and protected-data cautions.
- [`automation-guide.md`](automation-guide.md) — CI/CD automation reference.
- [`worktree-codex.md`](worktree-codex.md) — worktree helper reference.

## Architecture And Policy References

- [`architecture/system-context.md`](architecture/system-context.md)
- [`architecture/container-view.md`](architecture/container-view.md)
- [`architecture/actions_budget_public_readiness.md`](architecture/actions_budget_public_readiness.md)
- [`binance_accounting_policy.md`](binance_accounting_policy.md)

These are references for implementation detail. If they contradict the hot path, update or replace them before relying on them.

## Local Broker Data

Raw broker exports, account statements, legal PDFs, and derived private-account snapshots belong under ignored local `../data/`, not under `docs/`:

- `../data/binance_data/`
- `../data/xtb_statement_reference/`
- `../data/aster_data/`
- `../data/hyperliquid_data/`
- `../data/xtb/`

See [`../data/README.md`](../data/README.md).

Frontend visual references:

- `frontend_reference/`
