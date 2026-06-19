# vNext Orchestrator Goal

Status: active execution goal after PR #2 merge.
Last updated: 2026-06-19.

## Goal

Implement the approved vNext sprint sequence in the public repository using
dependency-aware subagent-driven development. Every sprint must use isolated
worktrees, exact write sets, TDD, targeted and broad verification, PR review,
adversarial review, fixes for concrete findings, and merge only after CI and
review are clean.

The active source documents are:

- `docs/superpowers/specs/2026-06-19-vnext-sprint-spec-pack.md`
- `docs/superpowers/plans/2026-06-19-vnext-sprint-plan-pack.md`
- `docs/superpowers/specs/2026-06-19-vnext-sprint-gate-design.md`
- `docs/superpowers/plans/2026-06-19-vnext-sprint-map.md`
- `docs/product_north_star.md`
- `docs/implementation_plan.md`
- `docs/verification_matrix.md`

## Operating Rules

- Use the public repository as the active implementation and CI target.
- Do not merge private Git history into public.
- Do not commit private broker exports, statements, credentials, account
  references, private paths, or local evidence filenames.
- Do not touch `portfolio_dev` without the protected local-production database
  runbook and explicit approval.
- Do not dispatch implementation from stale roadmap/checklist docs.
- If implementation discovers a schema, API, UI, product, privacy, or
  protected-data decision outside the approved sprint section, stop and return
  to the spec gate.
- Activity logs are audit evidence only; semantic accounting decisions must
  write canonical accounting state first.
- No crypto withdrawal may become a personal withdrawal by sign alone.
- No UI may show sensitive derived stats as trusted when backend confidence
  marks them provisional, review-required, or blocked.

## Per-Sprint Process

For each sprint:

1. Confirm the sprint dependencies are merged on `origin/main`.
2. Confirm the sprint spec section is approved and no open decision remains.
3. Create an isolated worktree and branch from current public `main`.
4. Publish a dispatch record with:
   - ticket;
   - worker;
   - branch/worktree;
   - dependencies complete;
   - exact write set;
   - read-only context;
   - blocked files;
   - DB or migration risk;
   - protected DB runbook requirement;
   - verification commands;
   - handoff expected.
5. Write failing tests first.
6. Implement only inside the dispatch write set.
7. Run targeted verification from `docs/verification_matrix.md`.
8. Run `make feature-check` for backend, frontend, migration,
   scheduler/sync, shared-contract, or e2e-sensitive work unless a narrower
   gate is explicitly accepted in the sprint plan.
9. Commit with a scoped imperative message.
10. Open a PR against public `main`.
11. Run adversarial spec-compliance review.
12. Run adversarial code-quality/safety review.
13. Fix every concrete finding, rerun affected tests, and re-request review
    until no high/medium issue remains.
14. Merge only when GitHub CI is green, review is clean, and the PR head SHA is
    the verified SHA.
15. Sync local `main` before starting the next dependent sprint.

## Dependency Order

Stage 1, serialized:

- `VNEXT-01D`: durable reconciliation task schema and transfer matching.

Stage 2, parallel when write sets stay disjoint:

- `VNEXT-02A`: capital truth service.
- `VNEXT-04A`: historical anchors and confidence service.

Stage 3, parallel after `VNEXT-02A` and `VNEXT-04A`:

- `VNEXT-03A`: rolling period performance service.
- `VNEXT-05A`: accounting review API and typed contracts.
- `VNEXT-06A`: asset-type distribution and cash reserve service.

Stage 4, parallel when dependencies are complete:

- `VNEXT-06B`: holding drivers, after `VNEXT-03A`, `VNEXT-04A`, and
  `VNEXT-06A`.
- `VNEXT-05B`: accounting review UI, after `VNEXT-05A`.

Stage 5, serialized:

- `VNEXT-07A`: dashboard and asset detail API/shared contract.

Stage 6, parallel after `VNEXT-07A`:

- `VNEXT-07B`: dashboard first screen UI.
- `VNEXT-07C`: asset detail UI.

## Parallelization Rules

- Never parallelize schema/migration work.
- Never parallelize shared-contract ownership.
- Never parallelize broad edits to the same service, API route, or primary
  frontend route.
- A parallel worker may only edit files listed in its dispatch record.
- If a worker needs a file outside its dispatch record, it must stop and ask
  the orchestrator to update the plan.
- Read-only exploration/review agents may run in parallel at any time.
- Implementation subagents may run in parallel only for dependency-ready
  tickets with exact non-overlapping write sets.

## Review Requirements

Every PR needs two adversarial passes:

- Spec compliance review: compare implementation against the approved sprint
  spec and reject missing requirements or scope creep.
- Code quality/safety review: inspect correctness, data safety, migrations,
  confidence semantics, money math, test coverage, and runtime risks.

Reviewer findings are handled as follows:

- High/medium concrete findings must be fixed before merge.
- Low findings may be fixed or explicitly deferred in the PR.
- Any reviewer-discovered product/schema/API/UI decision returns to the spec
  gate.
- A fix must be re-reviewed by the reviewer or an equivalent adversarial pass.

## Merge Criteria

A sprint PR may merge only when all are true:

- PR branch is based on current public `main` or has been updated.
- Required targeted commands passed in the current implementation session.
- Broad gate passed or a documented approved narrower gate exists.
- GitHub CI is green for the exact head SHA.
- Adversarial review has no unresolved high/medium findings.
- No unrelated user work was reverted.
- Handoff records changed files, verification evidence, skipped gates, and
  remaining risks.

## Stop Conditions

Stop and ask the user before:

- touching protected local-production data;
- adding or changing schema outside the approved sprint;
- changing confidence/materiality thresholds;
- changing public API route/model names outside the approved contract;
- making UI copy that changes accounting or investment decision semantics;
- using private broker evidence in tracked files;
- merging a PR with red CI or unresolved high/medium review findings.
