from pathlib import Path


def test_ci_workflow_bounds_long_running_pr_checks():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "concurrency:" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "classify-changes:" in workflow
    assert "docs-only:" in workflow
    assert "timeout-minutes: 45" in workflow
    assert "timeout-minutes: 12" in workflow
    assert "timeout-minutes: 8" in workflow
    assert "timeout-minutes: 5" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "Run CI checks" not in workflow
    assert "make ci" not in workflow
    assert "Run static verification checks" in workflow
    assert "Run backend tests (app, analytics, broker parsers)" in workflow
    assert "Run backend tests (db)" in workflow
    assert "Run backend tests (pricing state)" in workflow
    assert "Run backend tests (pricing time series)" in workflow
    assert "Run backend tests (pricing providers)" in workflow
    assert "Run backend tests (reconciliation, review)" in workflow
    assert "Run backend tests (security, worker, XTB)" in workflow
    assert "Run frontend shared-contract smoke" in workflow
    assert "Run frontend lint" in workflow
    assert "Run frontend typecheck" in workflow
    assert "faulthandler_timeout=120" in workflow


def test_ci_workflow_uses_docs_only_fast_path_for_documentation_changes():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "docs_only:" in workflow
    assert "needs: classify-changes" in workflow
    assert "if: needs.classify-changes.outputs.docs_only == 'true'" in workflow
    assert "if: needs.classify-changes.outputs.docs_only != 'true'" in workflow
    assert "Run docs-only verification" in workflow
    assert "git diff --check" in workflow
    assert "docs/*|README.md|AGENTS.md|CLAUDE.md|data/README.md" in workflow


def test_ci_workflow_uses_disposable_test_database_names():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "portfolio_dev" not in workflow
    assert "POSTGRES_DB: portfolio_backend_test" in workflow
    assert (
        "DATABASE_URL: postgresql+asyncpg://portfolio:portfolio@127.0.0.1:5433/portfolio_backend_test"
        in workflow
    )
    assert "pg_isready -U portfolio -d portfolio_backend_test" in workflow


def test_auth_smoke_backend_allows_playwright_frontend_origin():
    script = Path("frontend/e2e/start-auth-smoke-backend.sh").read_text()

    assert "PLAYWRIGHT_BASE_URL" in script
    assert "EXTRA_CORS_ORIGINS" in script
    assert "http://localhost:${FRONTEND_PORT}" in script
    assert "http://127.0.0.1:${FRONTEND_PORT}" in script
