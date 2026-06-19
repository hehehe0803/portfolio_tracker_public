# CLAUDE.md — portfolio_tracker agent contract

These rules apply to every Claude Code task in this repo unless the user explicitly overrides them. Keep this file short; detailed runbooks live in `docs/` and `AGENTS.md`.

## Critical repo safety

- `portfolio_dev` is protected local-production data, not a disposable dev DB.
- Never run destructive helpers (`drop_all`, `create_all`, seed resets, smoke resets) against `portfolio_dev` or any non-test DB.
- Destructive DB targets must be localhost and named with `test` or `smoke`; call `app.db.safety.assert_safe_destructive_database_url(...)` before schema reset code.
- Before migrations, schema-heavy work, sync jobs, or Compose app-profile changes, read `docs/local_prod_db_migration_runbook.md`; create and verify a backup when schema changes touch protected data.
- Private broker exports, account statements, legal PDFs, and derived private-account snapshots belong under ignored `data/`, not `docs/` or tracked test fixtures.
- `make feature-check` is the normal pre-push gate for feature branches touching backend, frontend flows, migrations, scheduler/sync behavior, Compose app services, or e2e-sensitive UI copy.

## Operating rules

1. **Think before coding.** State assumptions before non-trivial changes. If ambiguity changes the implementation or data-safety posture, ask instead of guessing.
2. **Simplicity first.** Make the smallest correct change. No speculative abstractions, extra features, or framework swaps.
3. **Surgical changes.** Touch only files/lines required by the task. Do not reformat, rename, or refactor adjacent code unless it is necessary for the requested change.
4. **Goal-driven execution.** Define success criteria and verify against them. Do not declare success from intuition.
5. **Use code for deterministic work.** Do not ask an LLM to decide retries, routing, status-code handling, pure transforms, auth gates, or DB safety. If code/state already answers, code answers.
6. **Budget discipline.** Target <=4,000 tokens per task step and <=30,000 per session. If context is getting large or repeated, summarize state, list verified facts, and restart/compact instead of drifting.
7. **Surface conflicts.** If existing patterns contradict, pick the more recent, tested, or locally dominant pattern; explain why and flag the other for cleanup. Do not blend conflicting patterns.
8. **Read before writing.** Before adding code, inspect the target file exports, immediate caller, and obvious shared utilities/models/tests. Avoid duplicate functions and import-order shadowing.
9. **Tests verify intent.** Tests must encode the business reason, not just a shallow return value. A test that would still pass with hardcoded/constant behavior is not enough.
10. **Checkpoint multi-step work.** After each significant step, summarize what changed, what was verified, and what remains. If you cannot describe the state, stop and restate before continuing.
11. **Convention beats novelty.** Match existing naming, API shapes, DTOs, SQLAlchemy/Alembic patterns, frontend component style, and e2e selector style even if you prefer another approach.
12. **Fail loud.** Surface skipped tests, skipped records, unverifiable claims, partial migrations/imports, and uncertainty. “Completed” is false if anything relevant was skipped silently.

## Required orientation

For most tasks, read in this order before editing:

1. `AGENTS.md`
2. `README.md`
3. `docs/current_state.md`
4. `docs/product_north_star.md`
5. `docs/roadmap.md`
6. `docs/implementation_plan.md`
7. `docs/verification_matrix.md`
8. The relevant runbook or fixture reference for the task
9. The target file, caller, shared utilities/models, and nearby tests

Do not start from deleted PRD/SRD files, old checklist graveyards, project-brain docs, or dated premortems.

## Verification notes

- Prefer targeted tests during development, then the repo gate appropriate to the touched area.
- Do not kill existing local app services or protected data services unless the user explicitly asks; use alternate ports for smoke runs when needed.
- Never print secrets, broker credentials, database passwords, JWTs, or master keys in logs, docs, commits, or chat.
