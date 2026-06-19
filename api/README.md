# API Service

FastAPI application that exposes REST endpoints, handles broker ingestion, and enforces the current hot-path security and accounting rules. GraphQL is deferred to Phase 2.

## Local Development
- Install dependencies: `uv sync --extra api --extra dev`
- Run API locally from `api/`: `cd api && uv run uvicorn app.main:app --reload`

Detailed setup and tooling will follow in infra-env-002.
