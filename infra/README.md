# Infrastructure

Docker Compose manifests and environment configuration that provision the portfolio tracker stack (TimescaleDB, Redis, MinIO).

## Local Stack
- `docker-compose.yml` boots TimescaleDB, Redis, and MinIO using the credentials from `.env`.
- Run `docker compose -f infra/docker-compose.yml up -d` after copying `.env.example` to `.env`.
- Data persists in named volumes (`timescale-data`, `redis-data`, `minio-data`); remove with `docker compose down -v` when resetting the environment.
- MinIO console is exposed on `http://localhost:9001` for inspecting uploaded statements.

## Deployment
All services run locally on the dev machine. No cloud hosting in scope for MVP.
