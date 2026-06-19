# vNext Sprint Gate Design

Status: approved planning protocol.
Last updated: 2026-06-19.

## Goal

Prevent vNext agents from fixing product, schema, API, or UI scope during
implementation. Every vNext sprint that has not already received explicit user
feedback must pass through a short spec, adversarial review, and user approval
before code work starts.

## Why This Exists

The public mirror solved the GitHub Actions quota problem by moving future code
and CI work to a sanitized public repository. It did not change product truth,
private-data safety, or the need for scoped sprint approval.

`VNEXT-01D` exposed the failure mode this protocol is meant to prevent: the
roadmap says unknown outgoing crypto transfers create accounting tasks, but the
current durable accounting schema has decision tables and no durable task table.
That is a product/schema decision, not an implementation detail.

## Scope Gate

Before implementing any unapproved sprint, the coordinator must write a sprint
spec that answers:

- What user-visible or accounting-truth problem the sprint solves.
- What it explicitly does not change.
- Whether it changes schema, shared contracts, public API shape, UI flows,
  imports/sync behavior, or protected local-prod data.
- Exact write set and blocked files.
- Required test evidence and broad gates.
- Whether parallel agents may work, and the non-overlapping write sets if so.
- What manual/user decisions remain after the sprint.

The sprint is not implementation-ready until:

1. The spec is written in `docs/superpowers/specs/`.
2. A reviewer or review pass challenges scope, contracts, private-data safety,
   and missing user decisions.
3. Review findings are fixed or explicitly rejected with reasoning.
4. The user explicitly approves the spec.
5. An implementation plan is written in `docs/superpowers/plans/`.

The implementation plan must stay inside the approved spec. If plan writing
uncovers a new schema, API, UI, product, privacy, or protected-data decision,
stop and return to the sprint spec gate before implementation.

## Approval Rules

- Each unreviewed sprint requires its own user-approved spec.
- Batch approval is not assumed.
- A previously approved architecture note is input evidence, not approval to
  implement every dependent sprint.
- Schema/migration work is serialized and must read
  `docs/local_prod_db_migration_runbook.md`.
- Shared-contract work is serialized.
- UI work that materially affects accounting or investment decisions requires
  user-approved copy and workflow semantics.

## Public And Private Repo Rules

- The public repository is the active code and CI target.
- The private repository remains legacy/private-data state.
- Normal Git history must not be merged from private into public.
- Private-only context may inform specs, but implementation branches and PRs
  must be created against the public repository unless explicitly stated.
- Public specs and plans must be sanitized. Do not include private account
  identifiers, raw broker/export content, secrets, local evidence filenames, or
  private data paths. If private evidence matters, summarize the decision in
  source-neutral terms and keep the sensitive evidence in ignored local data or
  private-only handoff material.
- Private broker exports and `portfolio_dev` are not required for normal sprint
  implementation. Protected DB work requires a separate explicit approval gate.

## Draft Evidence Rule

Exploratory tests, notes, or branches created before spec approval may be kept
as draft evidence. They must not be treated as approved design. After spec
approval, the implementation plan must either adopt, revise, or delete that
draft work intentionally.

For the current `VNEXT-01D` branch, the uncommitted RED tests in
`/tmp/portfolio_tracker_public_worktrees/vnext-01d-transfer-matching` are draft
evidence only.

## Completion Rule

A sprint is complete only when its approved spec, implementation plan, PR, test
evidence, adversarial review, fixes, and merge evidence all agree. Passing tests
alone do not prove completion if the spec requirements are broader.
