# Precedent Seed Pre-Publish Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the three publish-blocking NEW++ permission, domain-error, and rollback-recovery defects without widening the app role or touching production.

**Architecture:** Keep inactive `block_versions` master-only and add an active-only verification query for app credentials. Limit connection error translation to connection establishment so lifecycle domain codes survive transaction execution. Treat seed rollback as a journaled DB/SSM state transition with verified compensation and conservative maintenance fencing.

**Tech Stack:** Python 3.14, Django management commands, psycopg/pgvector, PostgreSQL SQL, PowerShell 7.2, AWS SSM/IAM orchestration, pytest.

## Global Constraints

- Do not grant the app role `SELECT` on `precedent_newplusplus.block_versions`.
- Do not add provider, embedding, model-download, AWS, or production DB calls to local verification.
- Preserve exact seed identity `sha256:af0a4a40f983dcdaeaaeb57e54962a514338b8644c33a6a807f1e6214878b2db` and `3,339 blocks / 825 cases / 2,560 dimensions`.
- Keep legal 97,394 seed state independent from the NEW++ pointer.
- Never print credentials, decrypted runtime env contents, SSM values, or private command output.
- A timeout, cancellation without terminal confirmation, missing journal, or failed compensation must retain the database-maintenance profile and marker.
- App release, 600-second acceptance, and 13 E2E remain separate post-merge operational gates.

---

### Task 1: Make active seed verification app-readable and preserve domain errors

**Files:**
- Modify: `etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py`
- Modify: `etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py`
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/db.py`
- Modify: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/seed_integrity.py`
- Verify: `backend/chatbot/test_precedent_newplusplus_seed_commands.py`
- Verify: `test/test_pgvector_rag_readiness.py`

**Interfaces:**
- Consumes: existing `connect_database()`, `database_readiness()`, `verify_seed(expected_seed_version, connection_factory)` and the `precedent_newplusplus.blocks` active-only view.
- Produces: `_read_active_verified_seed(cursor, seed_version) -> dict[str, Any] | None`, app-visible SQL with no `block_versions` reference, and unchanged credential-safe `verify_seed` JSON.

- [ ] **Step 1: Write the failing active-view readiness test**

Update `test_database_readiness_is_scoped_to_the_active_seed` so the captured SQL requires the view and rejects the private table:

```python
assert "FROM precedent_newplusplus.blocks AS blocks" in statements[0]
assert "CROSS JOIN precedent_newplusplus.active_seed AS active" in statements[0]
assert "block_versions" not in statements[0]
```

- [ ] **Step 2: Write the failing active-only exact verification test**

Change `test_verify_seed_returns_exact_credential_safe_evidence` to return an active snapshot only for the public query and assert that the executed verification SQL does not expose `block_versions`:

```python
def response(sql: str, _params: Any):
    if "FROM precedent_newplusplus.seed_releases AS release" in sql:
        assert "JOIN precedent_newplusplus.active_seed AS active" in sql
        assert "LEFT JOIN precedent_newplusplus.blocks AS blocks" in sql
        assert "block_versions" not in sql
        return _snapshot(status="active")
    return None
```

Also retain an assertion in a stage test that the master-only `_read_verified_seed` SQL still contains `precedent_newplusplus.block_versions`.

- [ ] **Step 3: Write the failing contextmanager domain-error test**

Add a fake `psycopg.connect` whose connection context opens successfully, then raise a real `SeedIntegrityError` inside `connect_database()`:

```python
def test_connect_database_preserves_domain_errors_from_transaction_body(
    monkeypatch,
) -> None:
    service = importlib.import_module(
        "etl.fault_cases.src.traffic_precedents.precedent_db_loading.seed_integrity"
    )

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        types.SimpleNamespace(connect=lambda *args, **kwargs: FakeConnection()),
    )

    with pytest.raises(service.SeedIntegrityError) as exc_info:
        with db.connect_database():
            raise service.SeedIntegrityError(
                "ACTIVE_SEED_CHANGED",
                "active seed changed before promotion",
            )

    assert exc_info.value.code == "ACTIVE_SEED_CHANGED"
```

- [ ] **Step 4: Run the three tests and verify RED**

Run:

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py::test_database_readiness_is_scoped_to_the_active_seed `
  etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py::test_connect_database_preserves_domain_errors_from_transaction_body `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py::test_verify_seed_returns_exact_credential_safe_evidence -q
```

Expected: all three fail for the current private-table query or `DATABASE_NOT_READY` conversion, not for imports or fixture errors.

- [ ] **Step 5: Restrict error translation to connection establishment**

Refactor `connect_database` so only target resolution and `psycopg.connect` are inside the translating `try` block:

```python
try:
    dsn, kwargs = resolve_connection_target()
    connection_context = (
        psycopg.connect(dsn) if dsn is not None else psycopg.connect(**kwargs)
    )
except SearchStageError:
    raise
except Exception as exc:
    raise SearchStageError(
        "DATABASE_NOT_READY",
        "판례 테스트 DB에 연결할 수 없습니다.",
        "database",
        True,
    ) from exc

with connection_context as connection:
    yield connection
```

- [ ] **Step 6: Implement active-only readiness and exact verification**

In `database_readiness`, replace the private table with the active view:

```sql
FROM precedent_newplusplus.blocks AS blocks
CROSS JOIN precedent_newplusplus.active_seed AS active
WHERE active.singleton IS TRUE
GROUP BY active.active_seed_version
```

In `seed_integrity.py`, keep `_read_verified_seed` unchanged for master lifecycle operations and add `_read_active_verified_seed`. Its query must join the expected release to the singleton pointer and aggregate only the `blocks` view:

```sql
FROM precedent_newplusplus.seed_releases AS release
JOIN precedent_newplusplus.active_seed AS active
  ON active.singleton IS TRUE
 AND active.active_seed_version = release.seed_version
LEFT JOIN precedent_newplusplus.blocks AS blocks ON TRUE
WHERE release.seed_version = %s
```

Extract the shared row-to-evidence validation into `_verified_seed_from_row(row, seed_version)` so both private lifecycle and public active verification enforce the same hash, count, dimension, and grade contract. Make public `verify_seed` call `_read_active_verified_seed`; do not change stage/promote/rollback callers.

- [ ] **Step 7: Run Task 1 tests and verify GREEN**

Run:

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py `
  backend/chatbot/test_precedent_newplusplus_seed_commands.py `
  test/test_pgvector_rag_readiness.py -q
```

Expected: all pass; added tests prove app-visible SQL contains no `block_versions` and domain error code remains `ACTIVE_SEED_CHANGED`.

- [ ] **Step 8: Prepare the Task 1 commit**

```powershell
git add `
  etl/fault_cases/src/traffic_precedents/tests/test_database_connection.py `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_integrity.py `
  etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/db.py `
  etl/fault_cases/src/traffic_precedents/precedent_db_loading/seed_integrity.py
git diff --cached --check
git commit -m "fix: verify active precedent seed with app privileges"
```

---

### Task 2: Make precedent seed rollback compensating and fail-closed

**Files:**
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1`

**Interfaces:**
- Consumes: `rollback_precedent_newplusplus_seed`, the private runtime SSM parameter, database-maintenance IAM profile, and `/opt/skn27-pilot/maintenance/database-maintenance.active`.
- Produces: root-only `precedent-seed-rollback.state` journal with `prepared`, `db_swapped`, `ssm_synced`, `verified`, `compensated`, or `recovery_required`; no credential-bearing output.

- [ ] **Step 1: Write failing source-contract tests for the journal and compensation**

Extend `test_precedent_seed_rollback_is_explicit_verified_and_fail_closed` with assertions for:

```python
assert "precedent-seed-rollback.state" in rollback
assert "prepared" in rollback
assert "db_swapped" in rollback
assert "ssm_synced" in rollback
assert "verified" in rollback
assert "compensated" in rollback
assert "recovery_required" in rollback
assert "compensate_precedent_seed_rollback" in rollback
assert "trap compensate_precedent_seed_rollback ERR" in rollback
```

Require the compensation body to execute a second `rollback_precedent_newplusplus_seed` using the failed target active version, restore the original private SSM file, read it back, and verify the original active version.

- [ ] **Step 2: Write failing orchestration-state tests**

Add a separate test that fixes the terminal/success distinction:

```python
def test_precedent_rollback_only_releases_maintenance_after_verified_state() -> None:
    rollback = _read_deploy("Rollback-PilotPrecedentSeed.ps1")

    assert "$databaseMaintenanceCommandSucceeded = $false" in rollback
    assert "$databaseMaintenanceSafeToRelease = $false" in rollback
    terminal = rollback.index("$script:databaseMaintenanceTerminalConfirmed = $true")
    success = rollback.index("$script:databaseMaintenanceCommandSucceeded = $true")
    status_gate = rollback.index('$result.Status -eq "Success"')
    assert terminal < status_gate < success
    assert "Get verified precedent rollback journal state" in rollback
    assert "recovery_required" in rollback
```

Assert the final cleanup branch uses `databaseMaintenanceSafeToRelease`, and the unsafe branch retains both profile and marker.

- [ ] **Step 3: Run rollback contract tests and verify RED**

Run:

```powershell
python -m pytest `
  test/test_aws_pilot_infrastructure.py::test_precedent_seed_rollback_is_explicit_verified_and_fail_closed `
  test/test_aws_pilot_infrastructure.py::test_precedent_rollback_only_releases_maintenance_after_verified_state -q
```

Expected: FAIL because the journal, compensation trap, success flag, and safe-release gate do not exist.

- [ ] **Step 4: Add a credential-safe remote journal**

Define a root-owned state path beside the existing maintenance marker. At the beginning of the maintenance SSM command, create it with mode `0600` and write `prepared` only after verifying current DB active, previous, and the single original SSM seed-version line.

Before invoking the mutating Django rollback command, write `recovery_required`. Immediately after its successful transaction, set the shell `DB_SWAPPED=1` flag and write `db_swapped`. After SSM read-back write `ssm_synced`; after master/app verification write `verified` and disarm the error trap.

- [ ] **Step 5: Implement the remote compensation trap**

Add `compensate_precedent_seed_rollback` under `set -eEuo pipefail`. If `DB_SWAPPED=1`, it must:

1. run `rollback_precedent_newplusplus_seed` with the target active version to restore the original pointer;
2. restore the untouched `$WORK/base.env` through `aws ssm put-parameter`;
3. read the SSM parameter back and require the original seed-version line exactly once;
4. verify the original active version with master credentials;
5. write `compensated` only when every compensation step passes, otherwise write `recovery_required`.

The trap must preserve the original non-zero exit status and must not print command JSON, credentials, runtime env, or SSM contents.

- [ ] **Step 6: Separate terminal, successful, and safe-to-release state**

Set `databaseMaintenanceTerminalConfirmed` whenever SSM reaches a terminal state, but set `databaseMaintenanceCommandSucceeded` only when status is `Success`. After the primary command terminates, issue a maintenance-role SSM state probe that returns exactly one allowed journal token. Set `databaseMaintenanceSafeToRelease` only for:

- `verified` with a successful primary command; or
- `compensated` with a failed primary command whose original DB/SSM state was reverified.

For `prepared`, `db_swapped`, `ssm_synced`, `recovery_required`, missing/invalid journal, timeout, or unconfirmed cancellation, retain the maintenance profile and marker. Cleanup removes both marker and journal only when safe-to-release is true. A compensated rollback still returns failure to the operator.

- [ ] **Step 7: Parse every embedded shell command**

Run the existing generated-command syntax tests and PowerShell parser tests:

```powershell
python -m pytest `
  test/test_aws_pilot_infrastructure.py `
  test/test_deployment_readiness_artifacts.py -q
```

Also parse the script itself:

```powershell
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path .\deploy\aws-pilot\Rollback-PilotPrecedentSeed.ps1),
  [ref]$null,
  [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { $errors | Format-List; exit 1 }
```

Expected: all tests pass and parser error count is zero.

- [ ] **Step 8: Prepare the Task 2 commit**

```powershell
git add `
  deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1 `
  test/test_aws_pilot_infrastructure.py
git diff --cached --check
git commit -m "fix: compensate failed precedent seed rollbacks"
```

---

### Task 3: Reconcile documentation and rerun all publish gates

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-precedent-newplusplus-pilot-seed-integrity-design.md`
- Create: `docs/superpowers/plans/2026-08-01-precedent-seed-prepublish-hardening.md`
- Modify: `docs/ops/operational-observability-runbook.md`
- Modify: `etl/fault_cases/docs/precedent_rag_replacement_handoff.md`
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`

**Interfaces:**
- Consumes: Task 1 and Task 2 final behavior and fresh verification output.
- Produces: operator documentation that distinguishes `verified`, `compensated`, and `recovery_required`, plus an evidence-backed pre-publish handoff.

- [ ] **Step 1: Update operator documents**

Document that app verification uses only the active view, a compensated rollback restores original DB/SSM but still reports failure, and `recovery_required` means the maintenance profile and marker must remain until explicit recovery. Keep production maintenance, image/app release, 600-second acceptance, and 13 E2E unchecked.

- [ ] **Step 2: Run focused seed and deployment tests**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests `
  backend/chatbot/test_precedent_newplusplus_seed_commands.py `
  test/test_pgvector_rag_readiness.py `
  test/test_aws_pilot_infrastructure.py `
  test/test_deployment_readiness_artifacts.py `
  test/test_codebuild_pilot_contract.py -q
```

- [ ] **Step 3: Run the full Python regression**

```powershell
python -m pytest -q
```

Expected: zero failures; record exact pass, skip, warning, and subtest counts rather than copying earlier evidence.

- [ ] **Step 4: Run frontend regression and production build**

From `app/web`:

```powershell
node --test *.test.js
npm run build
```

Expected: 66/66 Node tests and a successful Vite production build, unless the current tree legitimately changes the test count; record the actual output.

- [ ] **Step 5: Run final scope and secret checks**

```powershell
git diff --check
git status --short
rg -n "build_embeddings|embed_texts|OpenAI|allow-paid-provider-call" `
  deploy/aws-pilot/Maintain-PilotDatabase.ps1 `
  deploy/aws-pilot/Rollback-PilotPrecedentSeed.ps1
```

Expected: no whitespace errors, only planned files changed, and no provider-call paths in maintenance or rollback.

- [ ] **Step 6: Update exact evidence and prepare the documentation commit**

Record the final HEAD and fresh test/build counts, then prepare:

```powershell
git add `
  docs/superpowers/specs/2026-08-01-precedent-newplusplus-pilot-seed-integrity-design.md `
  docs/superpowers/plans/2026-08-01-precedent-seed-prepublish-hardening.md `
  docs/ops/operational-observability-runbook.md `
  etl/fault_cases/docs/precedent_rag_replacement_handoff.md `
  docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md
git diff --cached --check
git commit -m "docs: record precedent rollback compensation gates"
```

- [ ] **Step 7: Repeat the pre-publish review**

Compare the complete range against freshly fetched `origin/dev`, inspect CI policy and secret scope, and do not push or create a PR until no actionable P0/P1/P2 findings remain.
