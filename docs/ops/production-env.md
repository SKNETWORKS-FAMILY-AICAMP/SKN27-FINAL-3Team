# Production Environment Guide

This guide pins the environment variables required before the Django canonical
runtime can be treated as production-shaped.

Use [.env.production.example](../../.env.production.example) as a template only.
Actual values must live in the deployment platform secret store, not in Git.

## 1. Readiness Command

Run the non-network readiness check before a release:

```powershell
python backend\manage.py check_production_readiness --skip-database --format json
```

For local verification with a file copied from `.env.production.example`, load it
explicitly:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
python backend\manage.py check_production_readiness --skip-database --format json
```

Run the database-backed check after PostgreSQL is reachable and migrations plus
legal RAG ETL have been applied:

```powershell
python backend\manage.py check_production_readiness --format json --fail-on-error
```

The first command validates settings only. The second also checks that the
runtime database has worker and RAG tables.

## 2. Blocking Settings

These variables must be production values before release:

```dotenv
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<secret-store-value>
DJANGO_ALLOWED_HOSTS=<production-hosts>
DJANGO_DATABASE_ENGINE=postgres
CORS_ALLOWED_ORIGINS=<frontend-origin>
CSRF_TRUSTED_ORIGINS=<frontend-origin>
GOOGLE_CLIENT_ID=<google-oauth-web-client-id>
GOOGLE_CLIENT_SECRET=<secret-store-value>
GOOGLE_POPUP_REDIRECT_URI=<frontend-origin>
APP_JWT_SECRET=<secret-store-value>
OAUTH_TOKEN_SECRET=<secret-store-value>
```

The readiness command reports `fail` when any required value is missing or still
contains a placeholder.

## 3. Database And Worker

Production uses PostgreSQL with the pgvector image:

```dotenv
POSTGRES_IMAGE=pgvector/pgvector:pg16
POSTGRES_HOST=<postgres-host>
POSTGRES_PORT=5432
POSTGRES_USER=<app-db-user>
POSTGRES_PASSWORD=<secret-store-value>
POSTGRES_DB=law_db
REDIS_URL=<redis-url>
AGENT_WORKER_STALE_AFTER_SECONDS=900
AGENT_WORKER_RETRY_BACKOFF_SECONDS=60
AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS=900
AGENT_WORKER_LOOP_SLEEP_SECONDS=5
```

Use `POSTGRES_HOST=postgres` only from containers that share the
`docker-compose` network. When running `python backend\manage.py ...` directly
from the Windows host against the published Compose database port, set
`POSTGRES_HOST=localhost` in the loaded environment file.

`agent_work_items`, `analysis_jobs`, and `agent_invocations` must exist before a
worker is started. Run migrations first, then start a long-running worker
process:

```powershell
python backend\manage.py process_agent_work_items --loop --limit 10
```

For smoke tests, run one bounded polling loop:

```powershell
python backend\manage.py process_agent_work_items --limit 10 --max-loops 1
```

## 4. Legal RAG

Vector search is optional during staged rollout but required for full RAG:

```dotenv
LEGAL_RAG_VECTOR_ENABLED=1
LEGAL_RAG_QUERY_EMBEDDING_PROVIDER=sentence-transformers
LEGAL_RAG_QUERY_EMBEDDING_MODEL=intfloat/multilingual-e5-large
LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS=1024
LAW_GROUND_SEARCH_ENABLE_NEO4J=0
```

Before enabling it, load ETL output into `law_chunks` and `law_embeddings`.
The runtime falls back to Django `rag_chunks` lexical search when vector search
is disabled or unavailable, and records that fallback in retrieval metadata.
Keep `LAW_GROUND_SEARCH_ENABLE_NEO4J=0` unless the Neo4j hint graph and legal
relation graph have both been loaded and `NEO4J_URI` points to that service.
The legal ingestion pipeline writes `relations/law_extra_relations.jsonl` for
`HAS_PENALTY`, `HAS_APPENDIX`, `HAS_EXCEPTION`, and `RELATED_TO`;
`export_neo4j.py` imports that file when present. Before enabling Neo4j-backed
law expansion, verify the target relation counts:

```cypher
MATCH ()-[r]->()
WHERE type(r) IN ["HAS_PENALTY", "HAS_APPENDIX", "HAS_EXCEPTION", "RELATED_TO"]
RETURN type(r), count(*)
ORDER BY type(r)
```

Create or refresh the pgvector schema from the Django runtime:

```powershell
python backend\manage.py load_legal_rag_pgvector --schema-only --format text
```

Load ETL JSONL artifacts and run a smoke query:

```powershell
python backend\manage.py load_legal_rag_pgvector --replace --format text --smoke-query "어린이보호구역 정차 과태료"
```

The command expects:

- `output/law_ingestion/chunks/law_chunks.jsonl`
- `output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl`

For a local no-pgvector smoke, load the tiny Django fallback fixture and run a
representative query:

```powershell
python backend\manage.py load_legal_rag_smoke_fixture --replace --format text --smoke-query "school zone emergency stopping fine notice"
```

The fixture lives at `storage/rag/legal_rag_smoke_chunks.jsonl` and should keep
`rag_chunks` non-zero even when pgvector ETL artifacts are not available yet.

## 5. Law Ground Search Sync Smoke

`law_ground_search` can run in sync mode through the Supervisor adapter. The
safe smoke verifies that the adapter imports, receives the canonical context,
and returns a normalized envelope even when the legal RAG result set is empty:

```powershell
python backend\manage.py smoke_law_ground_search --format text
```

After the legal RAG data and retrieval path are ready, require at least one
provision:

```powershell
python backend\manage.py smoke_law_ground_search --require-results --format text
```

The readiness report includes `law_ground_search_sync`; it warns while
`LEGAL_RAG_VECTOR_ENABLED=0` because the adapter may only prove connectivity,
not release-quality retrieval.

## 6. Fault Ratio Text ML RAG

`text_ml_case_search` can run in sync mode without Elasticsearch. In that mode
it returns a safe partial/fallback result and records the fallback in
`limitations`. Enable Elasticsearch only after the review-case and
fault-ratio-precedent BM25/Nori indexes are loaded.

```dotenv
TEXT_ML_CASE_SEARCH_SYNC_USE_ES=1
TEXT_ML_CASE_SEARCH_ELASTICSEARCH_HOST=http://elasticsearch:9200
TEXT_ML_CASE_SEARCH_ELASTICSEARCH_USER=elastic
TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD=<secret-store-value>
TEXT_ML_CASE_SEARCH_ELASTICSEARCH_REQUEST_TIMEOUT=120
REVIEW_CASE_ES_BM25_INDEX=review_case_chunks_bm25_nori_v1
FAULT_RATIO_PRECEDENT_ES_BM25_INDEX=precedent_fault_ratio_chunks_bm25_nori_v1
```

The readiness report includes `text_ml_case_search_rag`. With
`TEXT_ML_CASE_SEARCH_SYNC_USE_ES=0` or unset, this check is `warn` because the
runtime stays usable but does not perform ES-backed case retrieval. With
`TEXT_ML_CASE_SEARCH_SYNC_USE_ES=1`, readiness validates the required package,
host, password policy, and index names without pinging Elasticsearch.

Run the safe smoke without requiring Elasticsearch:

```powershell
python backend\manage.py smoke_text_ml_case_search --format text
```

After Elasticsearch is reachable and the two BM25/Nori indexes are loaded, use
the stricter smoke:

```powershell
python backend\manage.py smoke_text_ml_case_search --require-es --format text
```

If `--require-es` fails, the service can still run the non-ES fallback, but the
fault-ratio similar-case quality is not release-ready.

## 7. Optional Warnings

These settings may remain warning-level during a staged rollout:

```dotenv
SUPERVISOR_LLM_ENABLED=0
LEGAL_RAG_VECTOR_ENABLED=0
TEXT_ML_CASE_SEARCH_SYNC_USE_ES=0
OBJECT_STORAGE_PROVIDER=mock_s3
REDIS_URL=
```

For a production release, prefer:

```dotenv
SUPERVISOR_LLM_ENABLED=1
SUPERVISOR_LLM_API_KEY=<secret-store-value>
OBJECT_STORAGE_PROVIDER=s3
OBJECT_STORAGE_BUCKET=<production-bucket>
OBJECT_STORAGE_REGION=<aws-region>
OBJECT_STORAGE_ACCESS_KEY_ID=<secret-store-value-or-empty-when-using-iam-role>
OBJECT_STORAGE_SECRET_ACCESS_KEY=<secret-store-value-or-empty-when-using-iam-role>
REDIS_URL=<redis-url>
FILE_SCAN_PROVIDER=clamav
FILE_SCAN_CLAMAV_HOST=<clamav-host>
FILE_SCAN_CLAMAV_PORT=3310
FILE_SCAN_TIMEOUT_SECONDS=10
FILE_SCAN_EXTERNAL_INLINE_MAX_BYTES=5242880
```

The S3 binary adapter requires the `boto3` package at runtime. When using AWS
standard environment variables or an IAM role, leave the project-specific
access key fields empty and provide `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and `AWS_DEFAULT_REGION` through
the deployment platform as needed.

After enabling Supervisor LLM, run a real planner smoke:

```powershell
python backend\manage.py smoke_supervisor_llm --require-used --require-slot-state --format text
```

Without `--require-used`, the command reports whether the LLM path was
`used`, `fallback`, or `disabled` without printing secrets. `--require-slot-state`
also verifies that `slot_filling_state.v1` is present in ready Agent input
packages.

After Google Cloud OAuth settings are registered, verify code-flow settings:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
python backend\manage.py smoke_google_oauth_code --format text
```

The Vite frontend reads `VITE_` variables from the repository root env files.
For local development, put `VITE_GOOGLE_CLIENT_ID` in the loaded root `.env` or
start Vite with the same mode as the file that contains it:

```powershell
npm --prefix app\web run dev -- --mode production
```

To complete a real exchange smoke, obtain a one-time Google authorization code
from the configured frontend redirect flow, then run:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
python backend\manage.py smoke_google_oauth_code --code "<one-time-code>" --require-exchange --format text
```

Run the file scan smoke before allowing uploaded files into Agent handoff:

```powershell
python backend\manage.py smoke_file_scan --require-clean --format text
python backend\manage.py process_uploaded_file_scans --limit 20 --format text
```

`FILE_SCAN_PROVIDER=local_policy` is acceptable for local development only. A
production release should use `clamav` or an external scan API and keep
`FILE_SCAN_MAX_BYTES`, `FILE_SCAN_TIMEOUT_SECONDS`, and `FILE_SCAN_REJECT_PII`
explicit in the environment. The scanner fails closed: if the configured
provider cannot scan a source file, the uploaded file is rejected instead of
being handed to an Agent.

Run the object storage binary smoke:

```powershell
python backend\manage.py smoke_object_storage --require-binary --format text
```

For local staged rollout, `OBJECT_STORAGE_PROVIDER=mock_s3` writes binary
objects into `OBJECT_STORAGE_LOCAL_ROOT`. For production, use
`OBJECT_STORAGE_PROVIDER=s3` with real bucket credentials and run the same
`--require-binary` smoke against the target storage. A `no_credentials` smoke
failure means the runtime did not receive either project-specific S3
credentials or standard AWS credentials/IAM role credentials.

Before real Agent adapters are connected, verify the demo persona catalog still
drives every pre-agent product flow to the mock-contract boundary:

```powershell
python backend\manage.py smoke_persona_catalog --format text
```

The staged catalog currently covers fine notice objection, accident scene
photo, blackbox video, law-only question, and saved report re-download personas.
This smoke does not prove OCR/RAG/Vision model quality; it proves the
Supervisor-facing persona plan, reporting payload, and report action boundary
remain executable.

## 7. Secret Rules

- Do not commit `.env`, `.env.production`, or copied secret files.
- Commit only `.env.example` and `.env.production.example`.
- Store real Google OAuth, app JWT, OAuth token, database, object storage, LLM,
  and Elasticsearch keys in the deployment secret store.
- After changing secrets, rerun the readiness command and the auth smoke tests.
