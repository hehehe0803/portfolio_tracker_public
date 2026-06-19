#!/usr/bin/env bash
set -euo pipefail

verify_static() {
  echo "== Verifying toolchain consistency =="
  rg -n "python 3\.13" .tool-versions
  rg -n "nodejs 24" .tool-versions

  rg -n "\[project\]" pyproject.toml
  rg -n "rq" pyproject.toml
  ! rg -n "arq" pyproject.toml

  rg -n "\"node\": \">=24" package.json
  rg -n "\"node\": \">=24" frontend/package.json

  ! rg -n "poetry" docs README.md api/README.md

  echo "== Verifying architecture decisions =="
  rg -n "GraphQL.*Phase 2|GraphQL deferred" docs/automation-guide.md api/README.md
  rg -n "CSR-first|CSR" docs/automation-guide.md

  echo "== Verifying deployment model =="
  rg -n "local.*deploy|Docker Compose|self-hosted" docs/automation-guide.md README.md
  ! rg -n "Railway" docs README.md AGENTS.md

  echo "== Verifying worker runtime =="
  rg -n "RQ" docs/implementation_plan.md worker/README.md docs/automation-guide.md
  ! rg -n "Arq" docs/implementation_plan.md worker/README.md
}

run_backend_tests() {
  echo "== Running tests =="
  uv run --extra dev --extra api --extra shared --extra binance --extra worker pytest api/tests "$@"
}

verify_shared_contracts() {
  echo "== Verifying frontend shared-contract smoke =="
  (cd frontend && npm run typecheck:shared-contracts)
}

run_all() {
  verify_static
  run_backend_tests
  verify_shared_contracts
  echo "== All checks passed =="
}

case "${1:-all}" in
  all)
    run_all
    ;;
  static)
    verify_static
    ;;
  tests)
    shift
    run_backend_tests "$@"
    ;;
  shared-contracts)
    verify_shared_contracts
    ;;
  *)
    echo "Usage: $0 [all|static|tests|shared-contracts]" >&2
    exit 2
    ;;
esac
