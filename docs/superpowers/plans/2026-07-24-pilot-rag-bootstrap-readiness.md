# Pilot RAG Bootstrap Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load and verify the required legal and review-case pgvector corpora in the existing pilot `law_db` before the first public release can be promoted.

**Architecture:** The maintenance role applies the review-case schema and its empty HNSW index to the existing `law_db`, then grants the runtime app role access. A manifest-bound Django management command performs idempotent review-case source loading, explicitly approved OpenAI embedding, and readiness verification during the private RAG stage. The existing legal loader remains transactional and public promotion remains tied to the exact verified manifest SHA-256.

**Tech Stack:** Django management commands, psycopg2/pgvector, OpenAI embeddings, PostgreSQL 16, PowerShell 7.2, AWS SSM/S3/ECR/RDS, Docker Compose, pytest

## Global Constraints

- Use the existing Seoul-region Single-AZ RDS instance and existing `law_db`; do not add another RDS instance or database.
- Required shared embedding space is `openai` / `text-embedding-3-large` / 1024 dimensions.
- The approved seed manifest SHA-256 is `279e78cf70db05156c316ddfbddff2eb4c08ea8c199fcb1df1f0f40600eeed6c`.
- Paid embedding calls must fail closed unless both the outer PowerShell switch and inner management-command flag are present.
- Never print OpenAI keys, database passwords, OAuth codes, full source documents, or signed URLs.
- The first public promotion must remain impossible until legal and review-case readiness and retrieval smoke checks pass.
- Fault-ratio precedent readiness remains optional for the first pilot release; its manifest artifact must still contain real source data.
- Implement the 2nd-phase CloudFront work only after this plan; do not mix it into this branch’s runtime changes.

---

### Task 1: Lock the shared-database schema and runtime contract

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `test/test_pgvector_rag_readiness.py`
- Modify: `storage/schemas/review_case_db_schema.sql`
- Modify: `deploy/aws-pilot/runtime.env.example`

**Interfaces:**
- Consumes: existing `REVIEW_CASE_DB` environment lookup in `etl.fault_cases.src.review_case.db_loading.db_config.PostgresSettings`
- Produces: `REVIEW_CASE_DB=law_db` runtime contract and maintenance-created `idx_review_case_chunk_embeddings_cosine_hnsw`

- [ ] **Step 1: Write failing contract tests**

Add assertions that the runtime example pins review-case storage to `law_db` and the schema contains an active, not commented, partial HNSW definition:

```python
def test_pilot_runtime_uses_shared_law_database_for_review_case_pgvector() -> None:
    runtime = _read_deploy("runtime.env.example")
    assert "REVIEW_CASE_DB=law_db" in runtime


def test_review_case_schema_creates_canonical_hnsw_during_maintenance() -> None:
    schema = (ROOT / "storage/schemas/review_case_db_schema.sql").read_text(
        encoding="utf-8"
    )
    statement = (
        "CREATE INDEX IF NOT EXISTS "
        "idx_review_case_chunk_embeddings_cosine_hnsw"
    )
    assert statement in schema
    assert schema.index(statement) < schema.index(
        "ON review_case_chunk_embeddings", schema.index(statement)
    )
    assert "vector_cosine_ops" in schema[schema.index(statement) :]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_pgvector_rag_readiness.py -q
```

Expected: FAIL because `REVIEW_CASE_DB=law_db` and the active HNSW statement are absent.

- [ ] **Step 3: Implement the minimal schema/runtime contract**

Add this runtime value:

```dotenv
REVIEW_CASE_DB=law_db
```

Replace the commented HNSW example with:

```sql
CREATE INDEX IF NOT EXISTS idx_review_case_chunk_embeddings_cosine_hnsw
ON review_case_chunk_embeddings
USING hnsw (embedding_vector vector_cosine_ops)
WHERE embedding_provider = 'openai'
  AND embedding_model = 'text-embedding-3-large'
  AND embedding_version = 'openai_text_embedding_3_large_1024_chunk_text_v1'
  AND embedding_dim = 1024
  AND embedding_vector IS NOT NULL;
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add test/test_aws_pilot_infrastructure.py test/test_pgvector_rag_readiness.py storage/schemas/review_case_db_schema.sql deploy/aws-pilot/runtime.env.example
git commit -m "fix: define shared review case pgvector schema"
```

---

### Task 2: Add a manifest-bound review-case source loader

**Files:**
- Create: `app/services/review_case_seed_service.py`
- Create: `test/test_review_case_seed_service.py`

**Interfaces:**
- Consumes: `RagSeedBundle.artifacts["review_case_chunks"].path`, `SETTINGS.review_case_db`, `review_case_documents`, `review_case_chunks`
- Produces:
  - `ReviewCaseSeedRow`
  - `read_review_case_seed_rows(path: Path) -> list[ReviewCaseSeedRow]`
  - `replace_and_upsert_review_case_rows(rows: Sequence[ReviewCaseSeedRow]) -> dict[str, int]`

- [ ] **Step 1: Write failing row-validation tests**

Cover a real complete row, missing identifiers, short text, duplicate `chunk_id`, and two chunks sharing one document:

```python
def test_read_review_case_seed_rows_normalizes_real_manifest_rows(tmp_path: Path) -> None:
    path = tmp_path / "review.jsonl"
    path.write_text(
        json.dumps(
            {
                "review_case_id": "review_case_2018_051544",
                "chunk_id": "review_case_2018_051544_case_overview",
                "review_no": "2018-051544",
                "chunk_type": "case_overview",
                "chunk_text": "교차로 사고 심의사례의 과실비율 판단 근거를 설명하는 충분한 길이의 본문",
                "source_ref": "review_case:2018-051544",
                "parse_status": "valid",
                "quality_flags": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rows = read_review_case_seed_rows(path)

    assert rows[0].review_case_id == "review_case_2018_051544"
    assert rows[0].review_no == "2018-051544"
    assert rows[0].search_text == rows[0].chunk_text
```

```python
@pytest.mark.parametrize("missing", ["review_case_id", "chunk_id", "chunk_text"])
def test_read_review_case_seed_rows_rejects_missing_required_fields(
    tmp_path: Path,
    missing: str,
) -> None:
    row = {
        "review_case_id": "review_case_2018_051544",
        "chunk_id": "review_case_2018_051544_case_overview",
        "review_no": "2018-051544",
        "chunk_type": "case_overview",
        "chunk_text": "교차로 사고 심의사례의 과실비율 판단 근거를 설명하는 충분한 길이의 본문",
    }
    row.pop(missing)
    path = tmp_path / "review.jsonl"
    path.write_text(
        json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ReviewCaseSeedError, match=missing):
        read_review_case_seed_rows(path)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest test/test_review_case_seed_service.py -q
```

Expected: collection FAIL because the service does not exist.

- [ ] **Step 3: Implement immutable row parsing**

Use a frozen dataclass and reject malformed/duplicate rows before any database connection:

```python
@dataclass(frozen=True)
class ReviewCaseSeedRow:
    review_case_id: str
    review_no: str
    chunk_id: str
    chunk_type: str
    chunk_text: str
    search_text: str
    sequence_no: int
    source_ref: str
    source_type: str
    source_reliability_score: int
    parse_status: str
    quality_flags: list[str]
    raw_json: dict[str, Any]
```

`read_review_case_seed_rows` must open UTF-8-sig JSONL, require at least 20 non-whitespace characters, require non-negative `sequence_no`, reject duplicate chunk IDs, and return no rows for no file only by raising `ReviewCaseSeedError`.

- [ ] **Step 4: Write failing database behavior tests**

Patch only `get_connection` with a recording DB-API test double. Assert the real service generates document and chunk upserts inside one transaction, performs replacement before insert only when requested, and returns exact distinct-document/chunk counts.

- [ ] **Step 5: Run the new database tests and verify RED**

Run the Step 2 command.

Expected: FAIL because `replace_and_upsert_review_case_rows` is absent.

- [ ] **Step 6: Implement transactional idempotent upsert**

Use `psycopg2.extras.execute_values` with:

```sql
INSERT INTO review_case_documents (
  review_case_id, review_no, source_ref, source_type,
  source_reliability_score, parse_status, quality_flags, raw_json
) VALUES %s
ON CONFLICT (review_case_id) DO UPDATE SET
  review_no = EXCLUDED.review_no,
  source_ref = EXCLUDED.source_ref,
  source_type = EXCLUDED.source_type,
  source_reliability_score = EXCLUDED.source_reliability_score,
  parse_status = EXCLUDED.parse_status,
  quality_flags = EXCLUDED.quality_flags,
  raw_json = EXCLUDED.raw_json,
  updated_at = now()
```

and:

```sql
INSERT INTO review_case_chunks (
  chunk_id, review_case_id, review_no, chunk_type, sequence_no,
  chunk_text, search_text, char_count, token_count, text_hash,
  source_ref, source_type, source_reliability_score,
  parse_status, quality_flags, raw_json
) VALUES %s
ON CONFLICT (chunk_id) DO UPDATE SET
  chunk_text = EXCLUDED.chunk_text,
  search_text = EXCLUDED.search_text,
  text_hash = EXCLUDED.text_hash,
  embedding_status = CASE
    WHEN review_case_chunks.text_hash IS DISTINCT FROM EXCLUDED.text_hash
    THEN 'pending'
    ELSE review_case_chunks.embedding_status
  END,
  updated_at = now()
```

Replacement deletes review-case rows only inside the same transaction. The service must not create schemas, indexes, or call providers.

- [ ] **Step 7: Run tests and verify GREEN**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add app/services/review_case_seed_service.py test/test_review_case_seed_service.py
git commit -m "feat: add review case pgvector seed loader"
```

---

### Task 3: Add fail-closed paid embedding orchestration

**Files:**
- Create: `backend/chatbot/management/commands/load_review_case_pgvector_seed.py`
- Create: `backend/chatbot/test_review_case_pgvector_seed_command.py`

**Interfaces:**
- Consumes:
  - `load_and_validate_rag_seed_manifest(manifest)`
  - Task 2 row loader
  - `create_embeddings(limit=None, dry_run=False)`
  - `create_hnsw_index()`
  - `count_embedding_rows()`
- Produces: `python backend/manage.py load_review_case_pgvector_seed --manifest /run/production-rag-seed/rag-seed-manifest.json --replace --allow-paid-provider-call --format json`

- [ ] **Step 1: Write failing command tests**

Use a complete bundle-shaped test double and patch only external DB/provider boundaries. Assert:

```python
def test_command_rejects_paid_work_without_explicit_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks_path = tmp_path / "review.jsonl"
    chunks_path.write_text(
        json.dumps(
            {
                "review_case_id": "review_case_2018_051544",
                "chunk_id": "review_case_2018_051544_case_overview",
                "review_no": "2018-051544",
                "chunk_type": "case_overview",
                "chunk_text": "교차로 사고 심의사례의 과실비율 판단 근거를 설명하는 충분한 길이의 본문",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    bundle = SimpleNamespace(
        artifacts={
            "review_case_chunks": SimpleNamespace(path=chunks_path, row_count=1)
        }
    )
    database_writes: list[object] = []
    provider_calls: list[object] = []
    monkeypatch.setattr(command_module, "load_and_validate_rag_seed_manifest", lambda _: bundle)
    monkeypatch.setattr(
        command_module,
        "replace_and_upsert_review_case_rows",
        lambda *args, **kwargs: database_writes.append((args, kwargs)),
    )
    monkeypatch.setattr(
        command_module,
        "create_embeddings",
        lambda *args, **kwargs: provider_calls.append((args, kwargs)),
    )

    with pytest.raises(CommandError, match="explicit paid provider approval"):
        call_command(
            "load_review_case_pgvector_seed",
            manifest=str(tmp_path / "rag-seed-manifest.json"),
            replace=True,
            format="json",
        )
    assert database_writes == []
    assert provider_calls == []
```

Also assert the approved path validates the manifest role, loads exactly the manifest row count, embeds pending rows, confirms the HNSW index, and reports only counts/model metadata.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/chatbot/test_review_case_pgvector_seed_command.py -q
```

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement the management command**

The command must:

1. validate the full production seed manifest;
2. reject before writes unless `--allow-paid-provider-call` is present;
3. parse and upsert only `review_case_chunks`;
4. call `create_embeddings(limit=None, dry_run=False)`;
5. call `create_hnsw_index()` idempotently;
6. require embedding count to equal manifest review-case row count;
7. require the canonical index to exist;
8. emit `review_case_pgvector_seed_load.v1` with counts and canonical embedding metadata.

Convert `RagSeedValidationError`, `ReviewCaseSeedError`, DB failures, and provider failures into credential-safe `CommandError` messages.

- [ ] **Step 4: Run focused command tests and verify GREEN**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Run service and readiness regression tests**

Run:

```powershell
python -m pytest test/test_review_case_seed_service.py test/test_pgvector_rag_readiness.py test/test_production_rag_seed.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/chatbot/management/commands/load_review_case_pgvector_seed.py backend/chatbot/test_review_case_pgvector_seed_command.py
git commit -m "feat: orchestrate review case pgvector bootstrap"
```

---

### Task 4: Wire maintenance and private RAG staging in fail-closed order

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `deploy/aws-pilot/Maintain-PilotDatabase.ps1`
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`

**Interfaces:**
- Consumes: Task 3 management command and Task 1 schema
- Produces:
  - `Maintain-PilotDatabase.ps1` applies review schema before app grants
  - `Load-Rag-Seed-Pilot.ps1 -AllowPaidReviewCaseEmbedding`

- [ ] **Step 1: Write failing deployment-order tests**

Assert the maintenance script applies:

```text
python -m etl.fault_cases.src.review_case.db_loading.schema_manager --apply-schema
```

before the `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES` command.

Assert the RAG loader:

- declares `[switch]$AllowPaidReviewCaseEmbedding`;
- fails before S3/SSM work if it is absent;
- invokes `load_review_case_pgvector_seed` with the read-only mounted manifest and `--allow-paid-provider-call`;
- orders manifest verify → review-case load/embed → legal load → law smoke → readiness → text smoke → completion marker.

- [ ] **Step 2: Run focused infrastructure tests and verify RED**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py -q
```

Expected: FAIL on the new source-specific bootstrap assertions.

- [ ] **Step 3: Implement maintenance schema application**

Inside the maintenance-role remote command, after Django migrations and before app grants, run the backend image with `$WORK/master.env`:

```text
python -m etl.fault_cases.src.review_case.db_loading.schema_manager --apply-schema
```

The runtime file supplies `REVIEW_CASE_DB=law_db`, so the command must not create a separate database.

- [ ] **Step 4: Implement the paid stage guard and source load**

Add:

```powershell
[switch]$AllowPaidReviewCaseEmbedding
```

and before Terraform output:

```powershell
if (-not $AllowPaidReviewCaseEmbedding) {
    throw "RAG seed maintenance requires explicit -AllowPaidReviewCaseEmbedding consent."
}
```

Run the Task 3 command against the mounted manifest before legal load:

```text
load_review_case_pgvector_seed
  --manifest /run/production-rag-seed/$RagSeedManifestRelativePath
  --replace
  --allow-paid-provider-call
  --format json
```

- [ ] **Step 5: Run PowerShell parser and tests and verify GREEN**

Run:

```powershell
C:\tmp\powershell-7.6.3\pwsh.exe -NoProfile -Command "[void][System.Management.Automation.Language.Parser]::ParseFile('deploy/aws-pilot/Maintain-PilotDatabase.ps1',[ref]`$null,[ref]`$null); [void][System.Management.Automation.Language.Parser]::ParseFile('deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1',[ref]`$null,[ref]`$null)"
python -m pytest test/test_aws_pilot_infrastructure.py -q
```

Expected: parser exit 0 and tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add deploy/aws-pilot/Maintain-PilotDatabase.ps1 deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 test/test_aws_pilot_infrastructure.py
git commit -m "fix: bootstrap review case pgvector before promotion"
```

---

### Task 5: Verify the complete local release change

**Files:**
- Modify: `docs/ops/release-checklist.md`
- Modify: `docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: Tasks 1–4 verification results
- Produces: evidence-backed `[x]`, `[~]`, and remaining human-gate states

- [ ] **Step 1: Run focused Python/Django regression**

```powershell
python -m pytest test/test_review_case_seed_service.py test/test_pgvector_rag_readiness.py test/test_production_rag_seed.py test/test_aws_pilot_infrastructure.py -q
python -m pytest backend/chatbot/test_review_case_pgvector_seed_command.py -q
```

Expected: all PASS.

- [ ] **Step 2: Run broader release validation**

```powershell
python -m pytest test -q
python -m pytest backend -q
npm --prefix app/web run build -- --configLoader runner
docker compose -f deploy/aws-pilot/docker-compose.pilot.yml --env-file deploy/aws-pilot/runtime.env.example config --quiet
```

Expected: pytest PASS, Vite build succeeds, Compose config exits 0 after generated-value placeholders are supplied by the existing contract-test harness or a private non-secret validation env.

- [ ] **Step 3: Update documents with exact evidence**

Record:

- manifest role counts and SHA-256;
- successful focused/full test counts;
- schema/loader/order protections;
- remaining paid embedding, RunPod, Google live OAuth, and acceptance-smoke human gates;
- 2nd-phase CloudFront work remains unchecked.

- [ ] **Step 4: Run documentation and diff checks**

```powershell
git diff --check
rg -n "TBD|TODO|FIXME|REPLACE_ME" docs/ops docs/superpowers
git status --short
```

Expected: no new placeholders or whitespace errors; only intended files and private ignored/untracked evidence remain.

- [ ] **Step 5: Commit**

```powershell
git add docs/ops/project-readiness-master-checklist.md docs/ops/release-checklist.md docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md
git commit -m "docs: record pilot RAG bootstrap readiness"
```

---

### Task 6: Publish the branch and run the private AWS stage

**Files:**
- Private, untracked: `C:\tmp\SKN27-release-readiness-integration\tmp\pilot-rag-bundle`
- Private, untracked: runtime env outside Git

**Interfaces:**
- Consumes: clean verified commits, AWS profile `skn27-pilot`, approved manifest, existing ECR/S3/SSM/RDS/EC2
- Produces: pushed branch, PR-ready evidence, initialized app database, staged images, loaded RAG seed, private readiness evidence

- [ ] **Step 1: Review before publishing**

Use `review-before-git-publish` to inspect all commits and rerun the smallest decisive verification commands. Confirm private seed artifacts and runtime secrets are not staged.

- [ ] **Step 2: Push the feature branch**

```powershell
git push -u origin feat-pilot-deployment-readiness
```

Expected: push succeeds without large/private artifacts.

- [ ] **Step 3: Build a private runtime env**

Generate three independent 32+ character secrets, copy Google client ID/secret and OpenAI key from the existing private production env without printing them, and set:

```dotenv
APP_DOMAIN=skn27-traffic-pilot.duckdns.org
ACME_EMAIL=<operator-email>
REVIEW_CASE_DB=law_db
VISION_RUNTIME_PROVIDER=runpod
```

Keep RunPod key/endpoint empty only until the human gate; do not print values.

- [ ] **Step 4: Initialize the RDS schema and app role**

Run `Maintain-PilotDatabase.ps1` through PowerShell 7.6.3 with `AWS_PROFILE=skn27-pilot`. Verify maintenance-role restoration and absence of the maintenance marker.

- [ ] **Step 5: Upload the versioned RAG bundle**

Upload the exact bundle under:

```text
s3://<clean-bucket>/_rag-seed/279e78cf70db05156c316ddfbddff2eb4c08ea8c199fcb1df1f0f40600eeed6c/
```

Resolve and record object version IDs without printing artifact content.

- [ ] **Step 6: Build, push, and stage the exact release**

Run `Deploy-Pilot.ps1 -StageForInitialRagBootstrap` with the approved manifest hash. Verify only Redis, ClamAV, and backend are running and no public `current` symlink exists.

- [ ] **Step 7: Request the explicit paid embedding approval**

Before `Load-Rag-Seed-Pilot.ps1`, show the user the exact operation: embed up to 904 review-case chunks once with `text-embedding-3-large`, then create/verify HNSW. Do not proceed without the approval.

- [ ] **Step 8: Load the RAG seed privately**

After approval, run `Load-Rag-Seed-Pilot.ps1 -AllowPaidReviewCaseEmbedding`. Require legal and review-case readiness plus both retrieval smokes and the exact `.production-rag-seed.complete` hash.

- [ ] **Step 9: Stop at remaining human gates**

Do not run public promotion until all are supplied/approved:

- RunPod restricted API key and Endpoint ID;
- Google one-time live OAuth code;
- canonical fine-notice fixture in Clean S3;
- paid Supervisor and non-DL acceptance smoke approvals.

- [ ] **Step 10: Update checklist and prepare PR**

Record AWS stage evidence without secrets, mark only actually completed gates, and prepare a PR title/body with costs, tests, rollback, remaining human tasks, and the deferred 2nd-phase CloudFront scope.
