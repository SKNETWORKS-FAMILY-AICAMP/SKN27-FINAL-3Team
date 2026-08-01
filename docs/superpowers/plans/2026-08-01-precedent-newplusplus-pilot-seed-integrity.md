# Precedent NEW++ Pilot Seed Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the tracked NEW++ Qwen bootstrap into the Pilot's existing `law_db` without provider calls, expose only a verified active version to runtime, and support compare-and-swap promotion and rollback.

**Architecture:** Store immutable corpus versions in the dedicated `precedent_newplusplus` schema and expose the active version through the existing `precedent_newplusplus.blocks` runtime name as a read-only view. Database maintenance uses the master role for schema, stage, promotion, SSM evidence synchronization, and rollback; the runtime app role receives only `USAGE` and `SELECT` and reuses existing `POSTGRES_*` credentials.

**Tech Stack:** Python 3.13/3.14, Django management commands, psycopg 3, PostgreSQL 16, pgvector, NumPy, PowerShell 7.2+, AWS SSM, pytest.

## Global Constraints

- Use the existing Pilot RDS database `law_db`; do not create another RDS instance or database.
- Active NEW++ corpus must be exactly `3,339 blocks / 825 cases / 2,560 dimensions`.
- Reuse `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy` and `02_document_embedding_metadata.jsonl`.
- Do not invoke Qwen document embedding, BGE/Qwen model download, OpenAI, or another paid provider.
- Do not merge the legacy 343-row `precedent_fault_ratio_chunks` artifact into NEW++.
- Runtime app role has `USAGE + SELECT` only in `precedent_newplusplus`.
- Stage failure must not change the active pointer; promotion and rollback use compare-and-swap and one database transaction.
- `PRECEDENT_NEWPLUSPLUS_SEED_VERSION` is required runtime evidence and must equal the database active version.
- Do not claim production completion until merge, deployment, 600-second acceptance, and all 13 E2E scenarios pass.
- Preserve all existing uncommitted exact-legal-seed and zero-target-job hotfix changes in this worktree.

---

### Task 0: Preserve the Already-Verified Exact-Seed Hotfix Boundary

**Files:**
- Existing modified: `backend/chatbot/management/commands/load_legal_rag_pgvector.py`
- Existing modified: `backend/chatbot/management/commands/load_production_rag_seed.py`
- Existing modified: `backend/chatbot/management/commands/verify_pgvector_rag_readiness.py`
- Existing modified: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Existing modified: `etl/fault_cases/src/review_case/embedding/run_embedding.py`
- Existing modified: `test/test_aws_pilot_infrastructure.py`
- Existing modified: `test/test_pgvector_rag_readiness.py`
- Existing modified: `test/test_production_rag_seed.py`
- Existing created: `test/test_review_case_embedding_run.py`
- Existing modified: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`

**Interfaces:**
- Consumes: previously observed RED/GREEN evidence for exact legal replacement, post-load counts, zero-target jobs, required fault-ratio readiness, and NEW++ readiness imports.
- Produces: a clean committed baseline so Tasks 1-7 cannot accidentally absorb or overwrite the existing hotfix.

- [ ] **Step 1: Invoke `review-before-git-publish` and inspect only the existing hotfix diff**

Confirm no bootstrap binary, runtime secret, generated output, or unrelated user file is present. Confirm the design and plan documents are already committed separately and are not part of this baseline commit.

- [ ] **Step 2: Re-run the focused baseline**

```powershell
python -m pytest `
  test/test_production_rag_seed.py `
  test/test_pgvector_rag_readiness.py `
  test/test_review_case_embedding_run.py `
  test/test_aws_pilot_infrastructure.py `
  test/test_deployment_readiness_artifacts.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run diff integrity and exact file review**

```powershell
git diff --check
git status --short
git diff --stat
```

Expected: only the ten existing hotfix files above are uncommitted.

- [ ] **Step 4: Commit the existing hotfix baseline**

```powershell
git add backend/chatbot/management/commands/load_legal_rag_pgvector.py backend/chatbot/management/commands/load_production_rag_seed.py backend/chatbot/management/commands/verify_pgvector_rag_readiness.py deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 etl/fault_cases/src/review_case/embedding/run_embedding.py test/test_aws_pilot_infrastructure.py test/test_pgvector_rag_readiness.py test/test_production_rag_seed.py test/test_review_case_embedding_run.py docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md
git diff --cached --check
git commit -m "fix: enforce exact rag seed replacement"
```

### Task 1: Versioned NEW++ Schema Contract

**Files:**
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql`
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/01_init_pgvector.sql`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity_schema.py`

**Interfaces:**
- Consumes: PostgreSQL `vector` extension already created by Pilot database maintenance.
- Produces: `seed_releases`, `block_versions`, `active_seed`, and read-only `blocks` view used by existing candidate/context SQL.

- [ ] **Step 1: Write the failing schema contract test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]


def test_newplusplus_schema_is_versioned_and_runtime_view_is_read_only() -> None:
    schema = (ROOT / "etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS precedent_newplusplus.seed_releases" in schema
    assert "CREATE TABLE IF NOT EXISTS precedent_newplusplus.block_versions" in schema
    assert "PRIMARY KEY (seed_version, block_id)" in schema
    assert "CREATE TABLE IF NOT EXISTS precedent_newplusplus.active_seed" in schema
    assert "CHECK (singleton)" in schema
    assert "CREATE OR REPLACE VIEW precedent_newplusplus.blocks" in schema
    assert "JOIN precedent_newplusplus.active_seed" in schema
    assert "embedding vector(2560) NOT NULL" in schema
    assert "unexpected existing precedent_newplusplus.blocks relation" in schema


def test_local_newplusplus_init_matches_canonical_schema() -> None:
    canonical = (ROOT / "etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql").read_text(encoding="utf-8")
    local = (ROOT / "etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/01_init_pgvector.sql").read_text(encoding="utf-8")
    assert local == canonical
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```powershell
python -m pytest etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity_schema.py -q
```

Expected: FAIL because versioned tables and active view do not exist and the two schema files differ.

- [ ] **Step 3: Implement the versioned schema**

Use these exact logical objects in both SQL files:

```sql
CREATE SCHEMA IF NOT EXISTS precedent_newplusplus;

CREATE TABLE IF NOT EXISTS precedent_newplusplus.seed_releases (
    seed_version TEXT PRIMARY KEY,
    source_npy_sha256 CHAR(64) NOT NULL,
    source_metadata_sha256 CHAR(64) NOT NULL,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    block_count INTEGER NOT NULL CHECK (block_count = 3339),
    case_count INTEGER NOT NULL CHECK (case_count = 825),
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension = 2560),
    status TEXT NOT NULL CHECK (status IN ('staged', 'active', 'previous')),
    verified_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS precedent_newplusplus.block_versions (
    seed_version TEXT NOT NULL REFERENCES precedent_newplusplus.seed_releases(seed_version),
    block_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    block_type TEXT NOT NULL,
    semantic_role TEXT NOT NULL,
    block_text TEXT NOT NULL,
    case_number TEXT,
    case_name TEXT,
    court_name TEXT,
    decision_date TEXT,
    internal_grade TEXT NOT NULL CHECK (internal_grade IN ('GENERAL_READY_DIRECT', 'SEED_READY')),
    source_metadata JSONB NOT NULL,
    embedding vector(2560) NOT NULL,
    PRIMARY KEY (seed_version, block_id)
);

CREATE TABLE IF NOT EXISTS precedent_newplusplus.active_seed (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    active_seed_version TEXT NOT NULL REFERENCES precedent_newplusplus.seed_releases(seed_version),
    previous_seed_version TEXT NULL REFERENCES precedent_newplusplus.seed_releases(seed_version),
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW precedent_newplusplus.blocks AS
SELECT blocks.block_id, blocks.record_id, blocks.block_type, blocks.semantic_role,
       blocks.block_text, blocks.case_number, blocks.case_name, blocks.court_name,
       blocks.decision_date, blocks.internal_grade, blocks.source_metadata,
       blocks.embedding
FROM precedent_newplusplus.block_versions AS blocks
JOIN precedent_newplusplus.active_seed AS active
  ON active.singleton IS TRUE
 AND active.active_seed_version = blocks.seed_version;
```

Add indexes `(seed_version, record_id)` and `(seed_version, block_type, record_id)`. Do not add provider calls or a new retrieval index.
Before creating the view, use a `DO $$ ... $$` preflight that raises
`unexpected existing precedent_newplusplus.blocks relation` when `blocks` already exists
as a physical table or another non-view relation. Never drop or silently migrate an unknown
existing corpus.

- [ ] **Step 4: Run the schema tests and existing NEW++ adapter tests**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity_schema.py `
  etl/fault_cases/src/traffic_precedents/tests/test_agent_connection_contract.py `
  etl/fault_cases/src/traffic_precedents/tests/test_search_adapter.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/01_init_pgvector.sql etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity_schema.py
git commit -m "feat: add versioned precedent seed schema"
```

### Task 2: Runtime Connection Fallback and Exact Readiness

**Files:**
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/db.py`
- Modify: `backend/chatbot/management/commands/verify_pgvector_rag_readiness.py`
- Modify: `test/test_pgvector_rag_readiness.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py`

**Interfaces:**
- Consumes: optional `PRECEDENT_NEWPLUSPLUS_DSN`; otherwise existing `POSTGRES_*` and `PGSSLMODE`.
- Produces: `resolve_connection_target(environ) -> tuple[str | None, dict[str, object]]` and readiness containing `active_seed_version`, blocks, cases, and dimensions.

- [ ] **Step 1: Write RED tests for DSN precedence and Pilot fallback**

```python
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.db import resolve_connection_target


def test_explicit_precedent_dsn_has_priority() -> None:
    dsn, kwargs = resolve_connection_target({"PRECEDENT_NEWPLUSPLUS_DSN": "postgresql://explicit"})
    assert dsn == "postgresql://explicit"
    assert kwargs == {}


def test_pilot_falls_back_to_existing_postgres_environment() -> None:
    dsn, kwargs = resolve_connection_target({
        "POSTGRES_HOST": "db.internal",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "law_db",
        "POSTGRES_USER": "app_role",
        "POSTGRES_PASSWORD": "secret",
        "PGSSLMODE": "require",
    })
    assert dsn is None
    assert kwargs == {
        "host": "db.internal", "port": 5432, "dbname": "law_db",
        "user": "app_role", "password": "secret", "sslmode": "require",
    }
```

- [ ] **Step 2: Write RED readiness tests**

Extend `test/test_pgvector_rag_readiness.py` so `_verify_fault_ratio_precedent()` must:

```python
assert result["active_seed_version"] == "sha256:" + "a" * 64
assert result["embedding_count"] == 3339
assert result["case_count"] == 825
assert result["embedding_space"]["dimensions"] == 2560
```

Also set `PRECEDENT_NEWPLUSPLUS_SEED_VERSION` to a different value and assert status `unavailable` with `fault_ratio_precedent_seed_version_mismatch`.

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py `
  test/test_pgvector_rag_readiness.py -q
```

Expected: FAIL because fallback resolution and active seed identity are absent.

- [ ] **Step 4: Implement minimal connection and readiness behavior**

In `db.py`, implement:

```python
def resolve_connection_target(environ: Mapping[str, str] | None = None) -> tuple[str | None, dict[str, object]]:
    env = os.environ if environ is None else environ
    explicit = str(env.get("PRECEDENT_NEWPLUSPLUS_DSN") or "").strip()
    if explicit:
        return explicit, {}
    required = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    if any(not str(env.get(key) or "").strip() for key in required):
        raise SearchStageError("DATABASE_NOT_READY", "판례 데이터베이스 연결 설정이 필요합니다.", "database")
    return None, {
        "host": env["POSTGRES_HOST"], "port": int(env["POSTGRES_PORT"]),
        "dbname": env["POSTGRES_DB"], "user": env["POSTGRES_USER"],
        "password": env["POSTGRES_PASSWORD"], "sslmode": env.get("PGSSLMODE", "require"),
    }
```

Make `connect_database()` pass either the DSN or kwargs to `psycopg.connect`. Update `database_readiness()` to join `active_seed` and return active version plus exact counts. Update `_verify_fault_ratio_precedent()` to compare actual version with `PRECEDENT_NEWPLUSPLUS_SEED_VERSION` without returning any connection fields.

- [ ] **Step 5: Run tests and verify GREEN**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py `
  test/test_pgvector_rag_readiness.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/db.py backend/chatbot/management/commands/verify_pgvector_rag_readiness.py test/test_pgvector_rag_readiness.py etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py
git commit -m "fix: verify active precedent seed identity"
```

### Task 3: Versioned Stage, Promotion, Verification, and Rollback Service

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/seed_integrity.py`
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/loader.py`
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/run.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py`

**Interfaces:**
- Produces: `SeedIdentity`, `compute_seed_identity`, `stage_seed`, `verify_seed`, `promote_seed`, `rollback_seed`.
- Consumes: existing `load_bootstrap_pair()` for pre-transaction source verification.

- [ ] **Step 1: Write RED deterministic identity tests**

```python
def test_seed_identity_is_deterministic() -> None:
    first = compute_seed_identity()
    second = compute_seed_identity()
    assert first == second
    assert first.seed_version.startswith("sha256:")
    assert first.block_count == 3339
    assert first.case_count == 825
    assert first.embedding_dimension == 2560
```

- [ ] **Step 2: Write RED transaction behavior tests**

Use a recording fake connection and cursor to assert:

- source validation is invoked before `SELECT pg_advisory_xact_lock`;
- exact staged counts are checked inside the transaction;
- same verified version returns `status="reused"` without inserting rows;
- promotion rejects an unexpected active version;
- rollback rejects missing previous version;
- rollback swaps active/previous only after expected-active comparison.

Required signatures:

```python
def stage_seed(*, embeddings_path: Path, metadata_path: Path, connection_factory: Callable[[], ContextManager[Any]]) -> dict[str, Any]: ...
def verify_seed(*, expected_seed_version: str, connection_factory: Callable[[], ContextManager[Any]]) -> dict[str, Any]: ...
def promote_seed(*, seed_version: str, expected_active_seed_version: str | None, connection_factory: Callable[[], ContextManager[Any]]) -> dict[str, Any]: ...
def rollback_seed(*, expected_active_seed_version: str, connection_factory: Callable[[], ContextManager[Any]]) -> dict[str, Any]: ...
```

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py -q
```

Expected: FAIL because the service and functions do not exist.

- [ ] **Step 4: Implement deterministic identity and staging**

Canonical identity payload:

```python
{
    "contract_version": "precedent_newplusplus_seed.v1",
    "source_npy_sha256": SOURCE_NPY_SHA256,
    "source_metadata_sha256": SOURCE_METADATA_SHA256,
    "model_id": QWEN_MODEL_ID,
    "model_revision": QWEN_REVISION,
    "block_count": 3339,
    "case_count": 825,
    "embedding_dimension": 2560,
}
```

Hash `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` and prefix with `sha256:`. Stage rows into `block_versions` with the version key, validate exact counts/dimensions/grades inside the same transaction, then mark the release `staged`.

- [ ] **Step 5: Implement compare-and-swap promotion and rollback**

Acquire one fixed transaction-scoped advisory lock before reading or changing the pointer. For promotion, compare actual active with the explicit expected value, set existing active to `previous`, set target to `active`, and upsert the singleton pointer. For rollback, require non-null previous and atomically swap both versions and statuses.

- [ ] **Step 6: Cut the legacy CLI load stage over to the service**

Keep dry-run provider-free. `--apply` stages only unless `--promote` is explicitly provided. Remove direct writes to `precedent_newplusplus.blocks`, because it is now a view.

- [ ] **Step 7: Run service and pipeline tests**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py `
  etl/fault_cases/src/traffic_precedents/tests/test_pipeline_core.py `
  etl/fault_cases/src/traffic_precedents/tests/test_run_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```powershell
git add etl/fault_cases/src/traffic_precedents/precedent_db_loading etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py
git commit -m "feat: stage and promote versioned precedent seeds"
```

### Task 4: Credential-Safe Django Management Commands

**Files:**
- Create: `backend/chatbot/management/commands/stage_precedent_newplusplus_seed.py`
- Create: `backend/chatbot/management/commands/promote_precedent_newplusplus_seed.py`
- Create: `backend/chatbot/management/commands/rollback_precedent_newplusplus_seed.py`
- Create: `backend/chatbot/management/commands/verify_precedent_newplusplus_seed.py`
- Create: `backend/chatbot/test_precedent_newplusplus_seed_commands.py`

**Interfaces:**
- Consumes: Task 3 service functions and Task 2 connection fallback.
- Produces: four credential-safe JSON command envelopes.

- [ ] **Step 1: Write RED command wrapper tests**

Test each command through `call_command` with service functions monkeypatched at the module boundary. Assert:

```python
assert result["contract_version"] == "precedent_newplusplus_seed.v1"
assert "password" not in json.dumps(result).lower()
assert "dsn" not in json.dumps(result).lower()
```

Assert `promote` requires `--seed-version` and `--expected-active-seed-version`, initial promotion accepts the literal `none`, rollback requires expected active, and verify is read-only.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest backend/chatbot/test_precedent_newplusplus_seed_commands.py -q
```

Expected: FAIL because the commands do not exist.

- [ ] **Step 3: Implement minimal command wrappers**

Default bootstrap paths:

```python
DEFAULT_EMBEDDINGS = Path("etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy")
DEFAULT_METADATA = Path("etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl")
```

Use `json.dumps(..., ensure_ascii=False, sort_keys=True)` for output. Convert domain errors to `CommandError` without embedding raw DB/provider exception messages.

- [ ] **Step 4: Run command and service tests**

```powershell
python -m pytest `
  backend/chatbot/test_precedent_newplusplus_seed_commands.py `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add backend/chatbot/management/commands/stage_precedent_newplusplus_seed.py backend/chatbot/management/commands/promote_precedent_newplusplus_seed.py backend/chatbot/management/commands/rollback_precedent_newplusplus_seed.py backend/chatbot/management/commands/verify_precedent_newplusplus_seed.py backend/chatbot/test_precedent_newplusplus_seed_commands.py
git commit -m "feat: add precedent seed lifecycle commands"
```

### Task 5: Pilot Maintenance, Read-Only Grants, SSM Evidence, and Seed Rollback

**Files:**
- Modify: `deploy/aws-pilot/runtime.env.example`
- Modify: `deploy/aws-pilot/Maintain-PilotDatabase.ps1`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Create: `deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1`
- Modify: `infra/terraform-pilot/iam.tf`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `test/test_deployment_readiness_artifacts.py`

**Interfaces:**
- Consumes: Task 4 management commands, Terraform runtime parameter output, existing maintenance role/master secret flow.
- Produces: promoted DB pointer, synchronized `PRECEDENT_NEWPLUSPLUS_SEED_VERSION`, app read-only grants, explicit recoverable seed rollback.

- [ ] **Step 1: Write RED runtime and ordering tests**

Add assertions that:

```python
assert "PRECEDENT_NEWPLUSPLUS_SEED_VERSION=INJECTED_BY_DATABASE_MAINTENANCE" in runtime_env
assert maintenance.index("precedent_db_loading/schema.sql") < maintenance.index("stage_precedent_newplusplus_seed")
assert maintenance.index("stage_precedent_newplusplus_seed") < maintenance.index("promote_precedent_newplusplus_seed")
assert maintenance.index("promote_precedent_newplusplus_seed") < maintenance.index("aws ssm put-parameter")
assert "GRANT USAGE ON SCHEMA precedent_newplusplus" in maintenance
assert "GRANT SELECT ON precedent_newplusplus.blocks, precedent_newplusplus.seed_releases, precedent_newplusplus.active_seed" in maintenance
assert "PRECEDENT_NEWPLUSPLUS_SEED_VERSION" in deploy
assert "Get-VerifiedPrecedentSeedVersion" in deploy
```

Assert the precedent grant segment contains no `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, or `CREATE` grant to the app role.

- [ ] **Step 2: Write RED rollback script tests**

Require exact target version, maintenance profile identity check, maintenance lock, explicit `rollback_precedent_newplusplus_seed`, SSM update/read-back, post-rollback verify, credential cleanup, and fail-closed behavior when previous is absent.

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest `
  test/test_aws_pilot_infrastructure.py `
  test/test_deployment_readiness_artifacts.py -q
```

Expected: FAIL only on the new NEW++ maintenance/rollback assertions.

- [ ] **Step 4: Implement maintenance stage and promotion**

Within the existing maintenance SSM command and master environment:

1. apply `precedent_db_loading/schema.sql` with `psql -v ON_ERROR_STOP=1`;
2. run stage command and capture credential-safe JSON;
3. parse `seed_version` with Python;
4. query current active version and pass the explicit value or `none` to promote;
5. verify exact active version;
6. replace only the `PRECEDENT_NEWPLUSPLUS_SEED_VERSION` line in a private runtime parameter temp file;
7. `aws ssm put-parameter --type SecureString --overwrite` and read it back;
8. grant app role schema `USAGE` and `SELECT` only on `blocks`, `seed_releases`, and
   `active_seed`; do not expose inactive `block_versions` directly;
9. run verify with app credentials.

The transient database-maintenance role must receive `ssm:PutParameter` only for the
existing `runtime_env_parameter_name` ARN. Do not add this mutation permission to the
normal runtime or app-release roles.

Do not place passwords or full runtime env values in stdout/stderr.

Implement `Get-VerifiedPrecedentSeedVersion` in `Deploy-Pilot.ps1`: after Terraform
outputs identify the runtime parameter, read its current SecureString value, extract exactly
one `PRECEDENT_NEWPLUSPLUS_SEED_VERSION=sha256:<64 lowercase hex>` line, and add it to
`$generatedValues` before the unresolved `INJECTED_` check. This makes SSM the authority
for the promoted seed version and prevents the local template from overwriting it.

- [ ] **Step 5: Implement explicit seed rollback script**

Follow `Maintain-PilotDatabase.ps1` identity/profile/lock/secret cleanup patterns. Accept required `-ExpectedActiveSeedVersion`, call rollback, synchronize SSM to returned active version, read back, and run exact verification. Do not combine this script with image rollback.

- [ ] **Step 6: Run infrastructure tests and PowerShell parse checks**

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py -q
pwsh -NoProfile -Command '$errors=$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "deploy/aws-pilot/Maintain-PilotDatabase.ps1"),[ref]$null,[ref]$errors) > $null; if($errors){$errors; exit 1}'
pwsh -NoProfile -Command '$errors=$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1"),[ref]$null,[ref]$errors) > $null; if($errors){$errors; exit 1}'
```

Expected: PASS and parser error list empty.

- [ ] **Step 7: Commit Task 5**

```powershell
git add deploy/aws-pilot/runtime.env.example deploy/aws-pilot/Maintain-PilotDatabase.ps1 deploy/aws-pilot/Deploy-Pilot.ps1 deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1 infra/terraform-pilot/iam.tf test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py docs/superpowers/plans/2026-08-01-precedent-newplusplus-pilot-seed-integrity.md
git commit -m "fix: provision precedent seed with rollback evidence"
```

### Task 6: Seed and App-Release Fail-Closed Gates

**Files:**
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Modify: `deploy/aws-pilot/Release-PilotApp-FromPipeline.sh`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `test/test_codebuild_pilot_contract.py`

**Interfaces:**
- Consumes: required runtime version and Task 2 readiness.
- Produces: no legal seed marker/descriptor or app promotion when NEW++ is unavailable or version-mismatched.

- [ ] **Step 1: Write RED release-gate tests**

Require both scripts to read a non-empty `PRECEDENT_NEWPLUSPLUS_SEED_VERSION` and invoke:

```text
python backend/manage.py verify_precedent_newplusplus_seed --expected-seed-version "$PRECEDENT_NEWPLUSPLUS_SEED_VERSION" --format json
python backend/manage.py verify_pgvector_rag_readiness --format json
```

In `Load-Rag-Seed-Pilot.ps1`, both checks must occur before `.production-rag-seed.complete` and `legal-operational-evidence-source.env` moves. In the app-release runner, checks must occur with the target backend image before container replacement and evidence promotion.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest `
  test/test_aws_pilot_infrastructure.py::test_rag_seed_maintenance_path_is_explicit_integrity_checked_and_fail_closed `
  test/test_codebuild_pilot_contract.py -q
```

Expected: FAIL because app release does not currently verify NEW++ and the legal seed flow does not assert expected version explicitly.

- [ ] **Step 3: Implement target-image preflight checks**

Read expected version only from `.runtime.env`, validate `^sha256:[0-9a-f]{64}$`, and run both read-only commands. Keep the legal source descriptor's existing three keys unchanged; NEW++ evidence lives in required runtime env and readiness output, not the legal S3 descriptor.

- [ ] **Step 4: Run release contract tests and shell syntax check**

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_codebuild_pilot_contract.py -q
bash -n deploy/aws-pilot/Release-PilotApp-FromPipeline.sh
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```powershell
git add deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1 deploy/aws-pilot/Release-PilotApp-FromPipeline.sh test/test_aws_pilot_infrastructure.py test/test_codebuild_pilot_contract.py
git commit -m "fix: gate releases on active precedent seed"
```

### Task 7: Documentation, Full Regression, and Handoff

**Files:**
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Modify: `etl/fault_cases/docs/precedent_rag_replacement_handoff.md`
- Modify: `docs/ops/operational-observability-runbook.md`

**Interfaces:**
- Consumes: Tasks 1-6 verified behavior.
- Produces: exact operator sequence, evidence, rollback boundary, and unchanged G8/G9 acceptance requirements.

- [ ] **Step 1: Update operator documentation**

Record:

- provider-free bootstrap paths and source hashes;
- deterministic seed version and active/previous pointer behavior;
- database maintenance stage/promotion command;
- SSM expected version synchronization;
- explicit `Rollback-PilotPrecedentSeed.ps1` usage and rejection conditions;
- legal 97,394 seed independence;
- app release and 13 E2E remain pending until operations run.

- [ ] **Step 2: Run NEW++ and fault-agent focused tests**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests `
  etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py `
  etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_ratio_precedent_evidence_mapper.py `
  backend/chatbot/test_precedent_newplusplus_seed_commands.py `
  test/test_pgvector_rag_readiness.py -q
```

- [ ] **Step 3: Run seed and deployment focused tests**

```powershell
python -m pytest `
  test/test_production_rag_seed.py `
  test/test_review_case_embedding_run.py `
  test/test_aws_pilot_infrastructure.py `
  test/test_deployment_readiness_artifacts.py `
  test/test_codebuild_pilot_contract.py -q
```

- [ ] **Step 4: Run complete Python regression**

```powershell
python -m pytest -q
```

Expected: zero failures; existing LangGraph pending-deprecation warning may remain documented.

- [ ] **Step 5: Run frontend regression and production build**

```powershell
Set-Location app/web
node --test *.test.js
npm run build
Set-Location ../..
```

Expected: all Node tests pass and Vite production build exits 0.

- [ ] **Step 6: Review final diff and secret/provider boundaries**

```powershell
git diff --check
git status --short
rg -n "build_embeddings|embed_texts|OpenAI|allow-paid-provider-call" deploy/aws-pilot/Maintain-PilotDatabase.ps1 deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1
```

Expected: no diff-check errors; provider search output empty for the two operational scripts; only approved files changed.

- [ ] **Step 7: Update the master checklist with exact results**

Record focused/full test counts, build result, current commit SHA, untouched production state, and remaining gates:

1. review-before-git-publish;
2. push/PR/merge;
3. immutable image digest;
4. separately approved database maintenance;
5. app release;
6. 600-second acceptance;
7. 13/13 E2E and GO/NO-GO.

- [ ] **Step 8: Commit Task 7**

```powershell
git add docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md etl/fault_cases/docs/precedent_rag_replacement_handoff.md docs/ops/operational-observability-runbook.md
git commit -m "docs: record precedent seed release gates"
```
