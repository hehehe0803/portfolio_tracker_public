SHELL := /bin/bash

.PHONY: ci test lint typecheck verify provision-test-db e2e feature-check compose-check

verify:
	scripts/verify_all.sh

provision-test-db:
	uv run --extra api --extra shared python api/scripts/provision_test_database.py --database-url "$${TEST_DATABASE_URL:-postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_backend_test}" --recreate

lint:
	npm --workspace frontend run lint

typecheck:
	npm --workspace frontend run typecheck

test:
	uv run --extra dev --extra api --extra shared --extra binance --extra worker pytest api/tests -q

e2e:
	npm --workspace frontend run test:auth-smoke

compose-check:
	bash scripts/verify_compose_app_profile.sh

feature-check: provision-test-db ci e2e

ci: verify lint typecheck
