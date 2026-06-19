# Actions Budget And Public Readiness Audit

Status: precursor audit.
Created: 2026-06-19.

## Scope

This audit explains why the repository exhausted the private-repository GitHub
Actions minutes quota and defines the minimum scrub plan before making the repo
public to use free standard hosted-runner minutes.

It does not change repository visibility, rewrite history, delete local data,
touch protected `portfolio_dev`, or mutate GitHub settings.

## Findings

### Actions Minutes Root Cause

GitHub Actions minutes were consumed by older CI workflow revisions that allowed
the `verify` job to run for GitHub's default job timeout of 360 minutes.

Context7-backed GitHub Actions docs state:

- standard GitHub-hosted runner usage is free for public repositories;
- private repositories consume included account minutes before billing;
- `jobs.<job_id>.timeout-minutes` defaults to 360 minutes when omitted.

The quota burn is explained by these seven cancelled jobs alone:

| Run | Job | Branch | Started UTC | Completed UTC | Approx minutes |
| --- | --- | --- | --- | --- | ---: |
| `27680190466` | `81865420321` | `codex/major-revamp-planning` | 2026-06-17 09:45:01 | 2026-06-17 15:45:16 | 360.25 |
| `27680223776` | `81865529724` | `main` | 2026-06-17 09:45:35 | 2026-06-17 15:45:53 | 360.30 |
| `27745985843` | `82084267982` | `codex/major-revamp-sprint1` | 2026-06-18 08:11:51 | 2026-06-18 14:12:06 | 360.25 |
| `27747015904` | `82087704351` | `codex/major-revamp-sprint1` | 2026-06-18 08:31:32 | 2026-06-18 14:31:50 | 360.30 |
| `27748275153` | `82091925838` | `codex/major-revamp-sprint1` | 2026-06-18 08:55:13 | 2026-06-18 14:55:32 | 360.32 |
| `27749729952` | `82096879169` | `main` | 2026-06-18 09:22:27 | 2026-06-18 15:22:42 | 360.25 |
| `27750775455` | `82100421981` | `codex/major-revamp-wave2` | 2026-06-18 09:41:38 | 2026-06-18 15:41:58 | 360.33 |

Total from these seven jobs: about 2,522 runner minutes.

Those workflow revisions had these risk factors:

- no job-level `timeout-minutes`;
- monolithic `Run CI checks` step running `make ci`;
- CI service database named `portfolio_dev`, which conflicted with the repo's
  protected-data vocabulary even though it was an ephemeral Actions service DB.

Current `.github/workflows/ci.yml` has already reduced the recurrence risk:

- workflow-level concurrency cancels in-progress runs for the same PR/ref;
- `verify` has `timeout-minutes: 45`;
- expensive checks are split into bounded steps;
- CI uses `portfolio_backend_test` instead of `portfolio_dev`.

The later failing vNext runs did not consume the same kind of minutes: they
completed in seconds because GitHub refused to start jobs after the account hit
the billing/spending limit.

### Remaining Actions Risk

The current workflow is safer, but still expensive for every push and pull
request:

- installs Python dependencies;
- installs frontend dependencies;
- installs system packages;
- installs Playwright browsers;
- runs several backend shards;
- runs shared-contract, lint, typecheck, and Playwright smoke.

For a private repo, this should be protected by policy even after the quota is
reset. For a public repo, the minute cap pressure is lower, but runaway jobs can
still waste time and block feedback.

Recommended guardrails before resuming broad parallel PR traffic:

1. Keep job-level and step-level timeouts mandatory.
2. Add a lightweight docs-only workflow path or path filter so docs-only PRs do
   not install Playwright and run the full backend matrix.
3. Keep concurrency cancellation, but do not rely on it as the only budget
   guard because different branches and push/main runs can still run together.
4. Prefer targeted local verification plus one exact-head full CI run before
   merge for implementation PRs.
5. Keep `portfolio_backend_test` or another explicit `test` database name in CI.

## Public Readiness Findings

Making the current GitHub repository public without additional work is not safe.

Current tracked files do not include `.env`, `.env.*`, PEM files, ignored
private broker directories, or ignored local data payloads. A regex scan of the
current tree outside `data/` found only placeholder or redacted secret examples,
not obvious live API keys.

However, public visibility exposes both the current tree and Git history. Git
history still contains private broker/account artifacts. Redacted examples:

- `docs/xtb_statement_reference/[account-id]_DailyStatement.pdf`
- `docs/xtb_statement_reference/account_[account-id]_en_html_[date-range].mhtml`
- `docs/xtb_statement_reference/account_[account-id]_en_xlsx_[date-range].xlsx`
- `api/tests/fixtures/xtb/account_[account-id]_en_xlsx_[date-range].xlsx`
- `docs/binance_export_baseline_dry_run_2026-05-03.json`
- `docs/binance_export_baseline_dry_run_2026-05-03.md`

The current tree also contained private-identifying XTB account strings and
fixture filenames in tests/docs before this hardening pass.

### Public Conversion Options

Option A: sanitized mirror repository.

- Create a fresh public repo from a sanitized export of the current tree.
- Do not publish old Git history.
- Keep the private repo as the real development repository if historical private
  data or branches must be preserved.
- This is the lowest-risk path for public visibility.

Option B: rewrite this repository's history before making it public.

- Use a history rewrite tool such as `git filter-repo` or BFG to remove private
  broker artifacts and sensitive derived files from all refs.
- Force-push rewritten refs.
- Recreate or retarget open PRs.
- Treat any exposed historical secrets/account identifiers as compromised if
  they were ever pushed to a remote that other users could access.
- This is higher operational risk because it disrupts branches, PRs, and local
  clones.

Option C: keep private and reduce CI cost without public visibility.

- Keep the current private repo.
- Add docs-only/path-filtered CI.
- Add manual full-CI workflow dispatch for expensive gates.
- Use local `make feature-check` and targeted verification for most parallel
  worker iterations.
- This avoids public-data risk but does not get unlimited hosted-runner minutes.

## Required Scrub Plan Before Public Visibility

Do not flip repository visibility until all items below are complete and
reviewed.

1. Current tree scrub:
   - replace real account number strings with synthetic identifiers;
   - rename private fixture references to synthetic names;
   - ensure tests still skip when ignored private fixtures are absent;
   - keep only sanitized synthetic fixtures under tracked paths.
2. History decision:
   - choose sanitized mirror or history rewrite;
   - if history rewrite, remove all historical private broker blobs and derived
     private baseline docs from every ref;
   - verify `git rev-list --all --objects` no longer exposes private paths.
3. Secret scan:
   - run a real secret scanner such as Gitleaks or equivalent on the final
     public candidate, including history;
   - review hits manually because placeholder local credentials are expected in
     examples and Compose test services.
4. Ignored data verification:
   - confirm `.gitignore` still excludes `.env`, `.env.*`, `*.pem`, backups,
     dumps, `.worktrees/`, `.hermes/`, and `data/*` except `data/README.md`;
   - check `git status --ignored=matching` before any public export.
5. Public CI hardening:
   - keep `permissions` minimal in workflow YAML;
   - keep timeouts and concurrency;
   - add docs-only or path-filtered CI before high-volume agent PR traffic.
6. GitHub settings review:
   - confirm no repository secrets, environments, deployment keys, webhooks, or
     Actions variables expose private infrastructure in a public setting;
   - confirm branch protection and required checks after the visibility change.
7. Final evidence bundle:
   - current tree secret scan output;
   - history object/path scan output;
   - ignored data/status output;
   - CI workflow diff and verification output;
   - explicit user approval to make the repo public.

## Immediate Recommendation

Do not make this existing repository public as-is.

The safest next precursor PR is a public-readiness hardening PR that:

- sanitizes current-tree private account strings and fixture names;
- adds a docs-only/path-aware CI fast path or a separate lightweight docs
  workflow;
- documents the chosen public conversion path.

After that, decide between a sanitized public mirror and a full history rewrite.
