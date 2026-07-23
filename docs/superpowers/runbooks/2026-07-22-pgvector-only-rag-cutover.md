# pgvector-only RAG cutover runbook

## Scope

Legal, review-case, and fault-ratio precedent retrieval use PostgreSQL/pgvector only.
No deployment step starts or queries a separate search cluster.

## Pre-cutover

1. Take a recoverable database backup and record its identifier.
2. Load/re-embed review-case and fault-ratio precedent source data, then create their HNSW indexes.
3. Validate the legal seed manifest and load the legal pgvector seed.
4. Run and retain the JSON output of:

   ```powershell
   python backend/manage.py verify_pgvector_rag_readiness --format json
   python backend/manage.py smoke_law_ground_search --require-results --format json
   python backend/manage.py smoke_text_ml_case_search --require-pgvector --require-results --format json
   ```

5. Do not continue unless all three readiness domains report `ready` and both smoke commands pass.

## Deployment

1. Stage the Pilot release with `Deploy-Pilot.ps1 -StageForInitialRagBootstrap`.
2. Run `Load-Rag-Seed-Pilot.ps1` after the source-specific pgvector preparation is complete.
3. Promote with `Deploy-Pilot.ps1` only after its readiness and application smoke checks pass.

## Observe

Monitor pgvector unavailable count, no-result rate, evidence count, p50/p95 retrieval latency,
database connection saturation, and HNSW index validity. Investigate any rise before deleting
legacy infrastructure.

## Removal and rollback

- Apply [20260722_remove_es_search_artifacts.sql](../../../storage/migrations/20260722_remove_es_search_artifacts.sql)
  only in the approved maintenance window after backup and readiness evidence are recorded.
- Delete external search resources only through the approved cloud change process; this repository
  change does not perform cloud deletion.
- `Rollback-Pilot.ps1` restores the previous application release. It does not reverse data migration,
  embeddings, or the schema-removal migration.
