# Phase 0 Compose override

`docker-compose.phase-00.yml` is applied with the repository's base `docker-compose.yml` only by `scripts/refactoring/run_phase_00_compose_gate.sh`.

It does not replace any production command, healthcheck, database, cache, scanner, or worker implementation. It mounts the test-only probe into `backend`, isolates container names with `COMPOSE_PROJECT_NAME`, disables external providers, and makes the backend use the existing ClamAV service. The gate starts only PostgreSQL, Redis, ClamAV, Neo4j, backend, agent-worker, and file-scan-worker; it does not start frontend or optional profiles.

The evidence directory is `tmp/phase-00-compose-evidence/`. It is CI output, is not a production runtime path, and must contain only safe identifiers and status values.
