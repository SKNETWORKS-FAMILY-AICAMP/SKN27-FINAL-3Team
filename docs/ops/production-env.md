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
VITE_GOOGLE_CLIENT_ID=<same-google-oauth-web-client-id>
GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT=20
GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS=<comma-separated-controlled-proxy-cidrs-or-empty>
APP_JWT_SECRET=<secret-store-value>
OAUTH_TOKEN_SECRET=<secret-store-value>
```

The readiness command reports `fail` when any required value is missing or still
contains a placeholder.

For the exact Google Cloud Console, local, staging, replay, and evidence-capture
sequence, follow [google-oauth-live-e2e.md](google-oauth-live-e2e.md). The popup
redirect value is an origin, not a callback path, and the frontend and backend
must use the same Google Web client ID.

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
AGENT_WORKER_HEARTBEAT_SECONDS=30
AGENT_WORKER_RETRY_BACKOFF_SECONDS=60
AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS=900
ANALYSIS_JOB_RESERVATION_STALE_AFTER_SECONDS=300
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

Legal retrieval is pgvector-only. Production must not start with vector search disabled:

```dotenv
LEGAL_RAG_VECTOR_ENABLED=1
LEGAL_RAG_QUERY_EMBEDDING_PROVIDER=sentence-transformers
LEGAL_RAG_QUERY_EMBEDDING_MODEL=intfloat/multilingual-e5-large
LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS=1024
LAW_GROUND_SEARCH_ENABLE_NEO4J=0
```

Load ETL output into `law_chunks` and `law_embeddings` before serving traffic.
If pgvector is unavailable or has no result, the runtime returns a safe
unavailable/empty result; it does not fall back to Django table search.
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

Verify all production RAG domains before promotion:

```powershell
python backend\manage.py verify_pgvector_rag_readiness --format json
```

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

The readiness report includes `law_ground_search_sync`; a disabled or
unavailable pgvector domain is a release blocker for retrieval quality.

## 6. Fault Ratio Text ML RAG

`text_ml_case_search` retrieves review-case and fault-ratio precedent evidence
through their source-specific PostgreSQL/pgvector retrievers. An unavailable
source is reported as a safe partial result; there is no alternate search
backend.

```dotenv
TEXT_ML_CASE_SEARCH_PGVECTOR_TOP_K=5
TEXT_ML_CASE_SEARCH_V2_REVIEW_CASE_QUOTA=5
TEXT_ML_CASE_SEARCH_V2_FAULT_RATIO_PRECEDENT_QUOTA=5
TEXT_ML_CASE_SEARCH_V2_FINAL_TOP_K=10
```

The readiness report includes `text_ml_case_search_rag` and validates the
three pgvector domains, their embedding counts, and HNSW indexes.

Run the safe smoke:

```powershell
python backend\manage.py smoke_text_ml_case_search --format text
```

Require pgvector evidence for the release gate:

```powershell
python backend\manage.py smoke_text_ml_case_search --require-pgvector --format text
```

If `--require-pgvector` fails, do not promote the release. Repair the source
data, embeddings, or HNSW index and rerun the readiness command.

## 7. Optional Warnings

These settings may remain warning-level during a staged rollout:

```dotenv
SUPERVISOR_LLM_ENABLED=0
OBJECT_STORAGE_PROVIDER=mock_s3
REDIS_URL=
```

For a production release, prefer:

```dotenv
SUPERVISOR_LLM_ENABLED=1
SUPERVISOR_LLM_API_KEY=<secret-store-value>
OBJECT_STORAGE_PROVIDER=s3
OBJECT_STORAGE_BUCKET=<production-bucket>
OBJECT_STORAGE_QUARANTINE_BUCKET=<production-quarantine-bucket>
OBJECT_STORAGE_REGION=<aws-region>
OBJECT_STORAGE_ACCESS_KEY_ID=<secret-store-value-or-empty-when-using-iam-role>
OBJECT_STORAGE_SECRET_ACCESS_KEY=<secret-store-value-or-empty-when-using-iam-role>
REDIS_URL=<redis-url>
FILE_UPLOAD_MAX_BYTES=20971520
FILE_SCAN_PROVIDER=clamav
FILE_SCAN_CLAMAV_HOST=<clamav-host>
FILE_SCAN_CLAMAV_PORT=3310
FILE_SCAN_TIMEOUT_SECONDS=10
FILE_SCAN_EXTERNAL_INLINE_MAX_BYTES=5242880
FILE_SCAN_CLAIM_STALE_AFTER_SECONDS=300
FILE_SCAN_RETRY_BACKOFF_SECONDS=60
FILE_RETENTION_PURGE_LIMIT=100
FILE_MAX_ATTACHMENTS_PER_REQUEST=20
REPORT_STAGING_CLEANUP_LIMIT=100
```

`OBJECT_STORAGE_QUARANTINE_BUCKET` must be different from `OBJECT_STORAGE_BUCKET`.
Keep the quarantine bucket private, encrypt it with SSE-KMS, leave versioning
disabled, and permanently expire objects after 7 days. This avoids a delete
marker retaining a noncurrent raw version beyond the seven-day boundary. Do not
apply that short retention policy to the clean object bucket. The API writes
unscanned bytes only to quarantine. The file scan worker reads one in-process
snapshot, scans that exact byte sequence, and writes only that verified
snapshot to the clean bucket while holding the database claim fence. It never
re-reads the mutable quarantine key for promotion.

The Terraform quarantine bucket is a new, never-versioned resource. If an
environment previously created a versioned bucket with the same purpose, do
not reuse it: replace it with a fresh bucket and separately purge all old
versions under the approved data-deletion runbook.

`FILE_UPLOAD_MAX_BYTES` is enforced before multipart parsing when the request
declares an oversized `Content-Length`, and again by a bounded streaming upload
handler when the length is absent or inaccurate. Configure the edge proxy with
the same request-body limit as an additional outer guard.

Metadata-only registrations remain `pending/awaiting_upload` and are not picked
up by the scanner. Scanner or storage outages leave binary uploads in a
retryable `uploaded/error` state; they never become clean or rejected solely
because the scanner is unavailable. `FILE_SCAN_CLAIM_STALE_AFTER_SECONDS`
controls stale-worker recovery and `FILE_SCAN_RETRY_BACKOFF_SECONDS` prevents a
tight retry loop.

`FILE_MAX_ATTACHMENTS_PER_REQUEST` fails closed before any attachment lookup
when a request exceeds the configured count. Requests within the limit use one
batched query, preventing attachment IDs from amplifying database work.
Queued Agent work re-runs the same gate immediately before execution. Canonical
object reads then re-check `ready/clean`, deletion, retention, and storage URI
under the upload row lock, so a concurrent retention purge cannot race a stale
queued attachment into an adapter.

The continuously running scanner task also enforces upload retention before
each scan poll. It deletes both quarantine and clean objects whose
`retention_expires_at` deadline has passed, then scrubs the database row to a
non-sensitive tombstone. `FILE_RETENTION_PURGE_LIMIT` bounds each poll. A
storage deletion failure leaves the row fenced and retryable; it can never be
handed to an Agent while cleanup is pending. The scanner task role therefore
has `DeleteObject` only on the two `canonical/uploads/*` prefixes; the API role
does not gain clean-upload delete access.

The clean object bucket is versioned. For clean uploads, a plain
`DeleteObject` would leave the bytes behind as a noncurrent version, so the
retention purge lists the exact key's Versions and DeleteMarkers, deletes every
version with `DeleteObjectVersion`, and re-runs `ListBucketVersions`. Only an
empty recheck can complete the tombstone. The scanner role's version-list
permission is bucket-level but constrained by `s3:prefix` to
`canonical/uploads/*`. Report staging uses the same permanent-delete procedure
under `staging/canonical/reports/*`; final report version history is unchanged.
As a defense-in-depth fallback for a runtime or IAM outage, the object bucket
lifecycle expires only the `staging/` prefix (including noncurrent versions)
after one day. It does not apply to clean uploads or final reports.
The Agent worker retries any report whose staging delete is incomplete;
`REPORT_STAGING_CLEANUP_LIMIT` bounds that work per poll, and a report is not
marked `finalized` until the versioned staging key is permanently absent.

For a dry-run or an explicit one-off cleanup, use:

```powershell
python backend\manage.py purge_expired_uploads --dry-run --format json
python backend\manage.py purge_expired_uploads --limit 100 --fail-on-error --format text
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

For the persisted non-DL analysis-to-Reporting boundary, run the separate strict
paid-call-gated smoke described in
[`non-dl-analysis-reporting-smoke.md`](non-dl-analysis-reporting-smoke.md). It
excludes Vision/DL and verifies the real fine-notice, law-ground, text/case-search,
and appeal-decision adapters, persisted analysis rows, Supervisor handoff
provenance, Reporting consumption, final report/display rows, and safe terminal
retry behavior. The command requires an operator-reviewed clean S3 acceptance
fixture under `canonical/acceptance/`; see the runbook for the exact invocation.

Without `--require-used`, the command reports whether the LLM path was
`used`, `fallback`, or `disabled` without printing secrets. `--require-slot-state`
also verifies that `slot_filling_state.v1` is present in ready Agent input
packages.

After Google Cloud OAuth settings are registered, verify code-flow settings:

Set `GOOGLE_OAUTH_CODE_EXCHANGE_DAILY_LIMIT` (default `20`). Keep
`GOOGLE_OAUTH_TRUSTED_PROXY_CIDRS` empty for direct access; behind a reverse
proxy, list only the proxy CIDRs controlled by this deployment. The application
then stores only an HMAC-derived rate-limit subject, never the raw client IP.
Google 429/5xx and network failures return 503; do not retry the same one-time
code automatically. Start a fresh Google login to obtain a new code.

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
python backend\manage.py smoke_google_oauth_code --prompt-code --require-exchange --format text
```

To prove that the provider rejects reuse of that same one-time code, use a fresh
code and run both exchanges in one sanitized command:

```powershell
$env:DJANGO_ENV_FILE=".env.production"
python backend\manage.py smoke_google_oauth_code --prompt-code --require-exchange --verify-replay-rejection --format json
```

`--prompt-code` uses a hidden terminal prompt so the one-time code is not stored
in the process argument list or shell history. Non-interactive automation may use
the short-lived `GOOGLE_OAUTH_SMOKE_CODE` environment variable instead; clear it
immediately after the command exits.

Run the file scan smoke before allowing uploaded files into Agent handoff:

```powershell
# Run as a one-off task with the API task role (quarantine Put only).
python backend\manage.py smoke_file_scan --phase upload --attachment-id att_release_scan --format text

# Run as a one-off task with the scanner task role (quarantine Get + clean promotion).
python backend\manage.py smoke_file_scan --phase scan --attachment-id att_release_scan --require-clean --format text
```

For a local single-role environment only, `--phase end-to-end --require-clean`
combines both phases. Production must keep them split so the smoke verifies the
same least-privilege boundary used by the deployed API and scanner tasks.

`FILE_SCAN_PROVIDER=local_policy` is acceptable for local development only. A
production release should use `clamav` or an external scan API and keep
`FILE_SCAN_MAX_BYTES`, `FILE_SCAN_TIMEOUT_SECONDS`, and `FILE_SCAN_REJECT_PII`
explicit in the environment. The scanner fails closed: if the configured
provider cannot scan a source file, the upload remains in a retryable error
state instead of being handed to an Agent.

Run the object storage binary smoke:

```powershell
python backend\manage.py smoke_object_storage --require-binary --format text
```

Run this command with the API task role. It validates report staging and final
report writes only; it deliberately skips direct writes to clean upload keys.
Clean upload promotion is covered by the split file-scan smoke above and is
authorized only for the scanner task role.

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
- Store real Google OAuth, app JWT, OAuth token, database, object storage, and
  LLM keys in the deployment secret store.
- After changing secrets, rerun the readiness command and the auth smoke tests.
