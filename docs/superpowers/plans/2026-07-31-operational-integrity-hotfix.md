# Operational Integrity Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make legal-data operational evidence, monitoring, access-log privacy, and Neo4j temporal readiness verifiable and fail-closed before the pilot production redeployment.

**Architecture:** Build a release-bound `run_summary.json` only from the already validated immutable RAG seed, validate it before cutover, and promote it atomically into the shared read-only monitor mount. Extend the monitor to reject dataset/release provenance mismatches, remove all request headers from Caddy access logs, and make Neo4j temporal metadata part of schema and readiness checks without changing the product UI.

**Tech Stack:** Python 3, Django management commands, pytest, PowerShell deployment scripts, Docker Compose, Caddy 2.11, Neo4j/Cypher

## Global Constraints

- Baseline is local commit `a880e0b4` on `feat-pilot-safety-hotfix`, based on `origin/dev` commit `61e0c56b`.
- Do not modify the production UI in G3.
- Use test-driven development: establish a focused RED result before every production-code change, then prove GREEN.
- Do not fabricate legal ingestion evidence; derive it only from a manifest-validated immutable production RAG seed.
- `run_summary.json` must bind both `LEGAL_DATASET_VERSION` and `APP_RELEASE_VERSION`.
- Missing, malformed, stale, or provenance-mismatched evidence must prevent monitor startup and production cutover.
- Never print raw legal text, credentials, authorization headers, cookies, guest credentials, or secrets in diagnostics.
- Do not rotate production credentials or delete production logs during local implementation; document those authorized G7/G8 operator actions.
- Keep current legal search and agent safe fallbacks operational when Neo4j is unavailable.
- Do not stage, commit, push, merge, deploy, or alter remote state during implementation; the user owns Git and deployment actions.
- Final scope remains actual production redeployment followed by all 13 E2E scenarios; local G3 completion is not production acceptance.

---

## File Responsibility Map

- `app/services/legal_operational_evidence.py`: pure construction and validation boundary for release-bound legal operational evidence.
- `backend/chatbot/management/commands/build_legal_operational_evidence.py`: safe CLI adapter that loads the validated seed and emits one JSON document.
- `backend/chatbot/operational_observability.py`: evidence freshness, status, and provenance evaluation.
- `backend/chatbot/management/commands/observe_operational_health.py`: settings-to-monitor adapter.
- `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`: creates and validates release-local evidence only after seed readiness succeeds.
- `deploy/aws-pilot/Deploy-Pilot.ps1`: validates, atomically promotes, preflights, and rolls back shared evidence.
- `deploy/aws-pilot/Caddyfile`: structured access logging with all request headers removed.
- `etl/legal/export_neo4j.py`: idempotent temporal-property indexes.
- `backend/chatbot/management/commands/verify_legal_graph_readiness.py`: temporal metadata readiness contract.
- `docs/ops/caddy-credential-log-incident-runbook.md`: authorized production credential/log response procedure.
- `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`: G3 evidence and residual production gates.

---

### Task 1: Build release-bound legal operational evidence

**Files:**
- Create: `app/services/legal_operational_evidence.py`
- Create: `backend/chatbot/management/commands/build_legal_operational_evidence.py`
- Create: `test/test_legal_operational_evidence.py`
- Modify: `test/test_legal_run_summary_validation.py`

**Interfaces:**
- Consumes: `load_and_validate_rag_seed_manifest(manifest_path: Path) -> RagSeedBundle` and `iter_rag_seed_jsonl(artifact: RagSeedArtifact) -> Iterator[dict[str, Any]]`, called with `bundle.artifacts["legal_chunks"]`.
- Produces: `build_legal_operational_evidence(bundle: RagSeedBundle, *, dataset_version: str, release_version: str, verified_at: datetime) -> dict[str, object]`.
- Produces command: `python manage.py build_legal_operational_evidence --manifest PATH --dataset-version VERSION --release-version VERSION --verified-at ISO8601`.
- Output contract adds required top-level `release_version` to `legal_ingestion_run_summary.v2`; stdout contains only compact JSON on success.

- [ ] **Step 1: Add failing evidence-builder tests**

  Add tests that construct a minimal validated bundle with two legal sources and assert:

  ```python
  summary = build_legal_operational_evidence(
      bundle,
      dataset_version="pilot-2026-07-31",
      release_version="release-abc123",
      verified_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
  )
  assert summary["contract_version"] == "legal_ingestion_run_summary.v2"
  assert summary["dataset_version"] == "pilot-2026-07-31"
  assert summary["release_version"] == "release-abc123"
  assert summary["status"] == "success"
  assert {row["source_id"] for row in summary["source_summaries"]} == expected_source_ids
  assert all(row["status"] == "success" for row in summary["source_summaries"])
  ```

  Also assert rejection of an unsafe/blank dataset version, unsafe/blank release version, naive timestamp, missing source identity, duplicate chunk identity, and an empty legal chunk artifact. Assert the serialized document contains neither representative legal provision text nor credential-like input values.

- [ ] **Step 2: Run focused tests and record RED**

  Run:

  ```powershell
  python -m pytest test/test_legal_operational_evidence.py test/test_legal_run_summary_validation.py -q
  ```

  Expected: FAIL because the service, command, and `release_version` validation do not exist.

- [ ] **Step 3: Implement the pure evidence builder**

  Implement:

  ```python
  def build_legal_operational_evidence(
      bundle: RagSeedBundle,
      *,
      dataset_version: str,
      release_version: str,
      verified_at: datetime,
  ) -> dict[str, object]:
      ...
  ```

  Iterate only `bundle` artifacts through `iter_rag_seed_jsonl`. Group `legal_chunks` by normalized source identity, count chunks/searchable chunks, derive effective-date bounds, and use the verified manifest hash in a deterministic `run_id`/`data_version`. Emit counts and identifiers only, never raw chunk text. Sort `source_summaries` by `source_id` for deterministic output.

- [ ] **Step 4: Extend summary validation with release provenance**

  Add optional `expected_dataset_version` and `expected_release_version` keyword arguments to `evaluate_run_summary`. Existing historical callers remain compatible when both are omitted; operational/deployment callers pass both values, which requires exact safe matches and returns fixed `dataset_version_mismatch` or `release_version_mismatch` error codes.

- [ ] **Step 5: Implement the management command**

  The command must load and validate the manifest before calling the builder, serialize one compact JSON object to stdout, and translate expected validation errors to `CommandError` with fixed safe messages. It must not write files itself; atomic file creation belongs to the host deployment scripts.

- [ ] **Step 6: Run Task 1 GREEN tests**

  Run:

  ```powershell
  python -m pytest test/test_legal_operational_evidence.py test/test_legal_run_summary_validation.py test/test_legal_ingestion_operational_summary.py -q
  ```

  Expected: all tests PASS and no raw source text appears in captured output.

- [ ] **Step 7: Review checkpoint**

  Inspect:

  ```powershell
  git diff --check
  git diff -- app/services/legal_operational_evidence.py backend/chatbot/management/commands/build_legal_operational_evidence.py test/test_legal_operational_evidence.py test/test_legal_run_summary_validation.py
  ```

  Do not stage or commit. Record this as the Task 1 checkpoint in the master checklist.

---

### Task 2: Make operational monitoring fail closed on provenance

**Files:**
- Modify: `backend/chatbot/operational_observability.py`
- Modify: `backend/chatbot/management/commands/observe_operational_health.py`
- Modify: `backend/chatbot/test_operational_observability.py`
- Modify: `config/settings/base.py` only if the command cannot consume existing `LEGAL_DATASET_VERSION` and `APP_RELEASE_VERSION` settings directly.

**Interfaces:**
- Consumes: the strict `legal_ingestion_run_summary.v2` document from Task 1.
- Produces: `build_operational_health_snapshot(..., expected_dataset_version: str, expected_release_version: str, ...) -> dict[str, object]`.
- Produces safe legal-data fields: `status`, `reason_code`, `dataset_version`, `release_version`, `age_seconds`; never includes raw parser errors or evidence content.

- [ ] **Step 1: Add failing provenance tests**

  Cover exact dataset match, exact release match, dataset mismatch, release mismatch, missing release version, malformed JSON, missing file, stale evidence, and a failed source summary. Mismatch assertions:

  ```python
  assert legal_data["status"] == "fail"
  assert legal_data["reason_code"] == "legal_data_provenance_mismatch"
  assert "secret" not in json.dumps(snapshot).lower()
  ```

  Add a command test proving `LEGAL_DATASET_VERSION` and `APP_RELEASE_VERSION` are passed as expected values.

- [ ] **Step 2: Run the monitor tests and record RED**

  Run:

  ```powershell
  python -m pytest backend/chatbot/test_operational_observability.py -q
  ```

  Expected: new mismatch cases FAIL because release provenance is not evaluated.

- [ ] **Step 3: Implement strict provenance evaluation**

  Extend `_legal_data_snapshot` and `build_operational_health_snapshot` with keyword-only expected versions. Check in this order: file presence, parse/schema validity, evidence status, freshness, dataset equality, release equality. Return fixed reason codes; log unexpected details only through existing safe logging helpers.

- [ ] **Step 4: Wire settings into the command**

  Resolve expected versions from Django settings/environment and fail with `monitor_configuration_invalid` when either configured value is absent or unsafe. Preserve current one-shot and loop behavior.

- [ ] **Step 5: Run Task 2 GREEN tests**

  Run:

  ```powershell
  python -m pytest backend/chatbot/test_operational_observability.py backend/chatbot/test_operational_log_privacy.py -q
  ```

  Expected: all tests PASS; missing/stale/invalid/mismatched evidence remains fail-closed.

- [ ] **Step 6: Review checkpoint**

  Run `git diff --check` and inspect only the monitor/command/test diff. Do not stage or commit.

---

### Task 3: Generate and promote evidence atomically

**Files:**
- Modify: `deploy/aws-pilot/Load-Rag-Seed-Pilot.ps1`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `test/test_deployment_readiness_artifacts.py`

**Interfaces:**
- Consumes: Task 1 builder command and Task 2 one-shot monitor.
- Produces release-local file: `$TARGET_RELEASE/operational-evidence/run_summary.json`.
- Produces shared file: `/opt/skn27-pilot/operational-evidence/run_summary.json`.
- Promotion invariant: validate temporary file, set read-only permissions, then same-filesystem `mv -f` to the final name.

- [ ] **Step 1: Add failing RAG-load sequence tests**

  Assert script ordering by index:

  ```python
  assert verify_graph_index < build_summary_index
  assert smoke_law_index < build_summary_index
  assert build_summary_index < validate_summary_index
  assert validate_summary_index < atomic_move_index
  assert atomic_move_index < completion_marker_index
  assert completion_marker_index < cleanup_index
  ```

  Assert builder arguments include manifest, dataset version, release version, and verified timestamp. Assert the temporary filename is not the final monitor path.

- [ ] **Step 2: Add failing deployment precheck/promotion tests**

  Assert `Deploy-Pilot.ps1`:

  - requires release-local evidence before any destructive cutover;
  - validates schema, freshness, dataset version, and release version;
  - starts ordinary background workers separately from `ops-monitor`;
  - atomically installs the shared evidence;
  - runs one-shot operational monitoring before starting loop mode;
  - restores the previous release evidence on rollback, or removes only the just-promoted file on an initial-release rollback.

- [ ] **Step 3: Run infrastructure tests and record RED**

  Run:

  ```powershell
  python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py -q
  ```

  Expected: FAIL on evidence generation, precheck, atomic promotion, monitor startup ordering, and rollback assertions.

- [ ] **Step 4: Implement release-local evidence generation**

  Keep the downloaded seed directory until Neo4j readiness, law smoke, PGVector readiness, and text-search checks pass. Write builder stdout to `run_summary.json.tmp`, validate the temporary file with strict required sources and maximum age, set mode `0444`, then rename it to `run_summary.json`. Write `.production-rag-seed.complete` only after the final evidence file exists and validates; clean the seed directory last.

- [ ] **Step 5: Implement fail-closed deployment precheck**

  Before cutover, verify the release-local summary exists and run strict validation against `LEGAL_DATASET_VERSION`, `RELEASE_TAG`, and the configured freshness limit. A failed check must exit non-zero without changing the active release, shared evidence, or running services.

- [ ] **Step 6: Implement atomic promotion and rollback**

  Copy to a unique temporary file inside `/opt/skn27-pilot/operational-evidence`, validate it, apply read-only permissions, and rename it atomically. Preserve the prior summary in rollback state. Start `agent-worker` and `file-scan-worker`, run `observe_operational_health` once against the promoted evidence, require a passing `legal_data` result, then start `ops-monitor`. On later failure, restore the prior summary atomically before restoring prior services.

- [ ] **Step 7: Run Task 3 GREEN tests**

  Run:

  ```powershell
  python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py backend/chatbot/test_operational_observability.py -q
  ```

  Expected: all tests PASS and script-order assertions prove fail-closed behavior.

- [ ] **Step 8: Review checkpoint**

  Run `git diff --check`, inspect both PowerShell diffs end to end, and confirm no command logs environment values or evidence contents. Do not execute a production deployment.

---

### Task 4: Remove credential-bearing headers from Caddy access logs

**Files:**
- Modify: `deploy/aws-pilot/Caddyfile`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Create: `docs/ops/caddy-credential-log-incident-runbook.md`
- Modify: `test/test_deployment_readiness_artifacts.py`

**Interfaces:**
- Produces Caddy log encoder:

  ```caddyfile
  format filter {
      request>headers delete
      wrap json
  }
  ```

- Preserves request method, URI, status, size, duration, and timestamps while removing every request header, including `Authorization`, `Cookie`, and `X-Guest-Credential`.

- [ ] **Step 1: Add failing static configuration tests**

  Assert the Caddy log block contains `format filter`, `request>headers delete`, and `wrap json`; assert `log_credentials` is absent. Also assert the reverse proxy still forwards required authentication headers to the backend—the change is logging-only.

- [ ] **Step 2: Add failing incident-runbook contract tests**

  Require the runbook to include:

  - Caddy log volume, CloudWatch/backup/replication inventory;
  - access-control and accessor review;
  - authorized `APP_JWT_SECRET` rotation through SSM;
  - restart of every backend-image service;
  - proof that pre-rotation app JWT and guest credentials return `401`;
  - approved purge/retention handling for exposed logs;
  - credential canary requests followed by zero-match log verification;
  - evidence recording limited to counts, timestamps, release SHA, dataset version, and resource identifiers.

- [ ] **Step 3: Run privacy contract tests and record RED**

  Run:

  ```powershell
  python -m pytest test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py backend/chatbot/test_operational_log_privacy.py -q
  ```

  Expected: FAIL because the request-header deletion filter and runbook do not exist.

- [ ] **Step 4: Apply the Caddy filter and write the runbook**

  Replace `format json` in the access log with the filter encoder above. Document exact preconditions, commands/templates, expected status codes, rollback conditions, and redacted evidence fields. Mark credential rotation and log purge as production-authorized actions that are not performed by local tests.

- [ ] **Step 5: Run Task 4 GREEN tests**

  Run the same focused command. Expected: all tests PASS.

- [ ] **Step 6: Review checkpoint**

  Confirm the filter removes all request headers, proxy behavior is unchanged, and the runbook never asks operators to paste secret values into evidence. Do not rotate credentials or delete logs.

---

### Task 5: Enforce Neo4j temporal schema and readiness

**Files:**
- Modify: `etl/legal/export_neo4j.py`
- Modify: `backend/chatbot/management/commands/verify_legal_graph_readiness.py`
- Modify: `test/test_legal_graph_seed_commands.py`
- Modify: the existing legal-search fallback test module only if the current regression is not already explicit.

**Interfaces:**
- Produces idempotent indexes:

  ```cypher
  CREATE INDEX law_version_temporal IF NOT EXISTS
  FOR (n:LawVersion) ON (n.enforce_date, n.expire_date)
  ```

  ```cypher
  CREATE INDEX law_chunk_temporal IF NOT EXISTS
  FOR (n:LawChunk) ON (n.enforce_date, n.expire_date)
  ```

- Readiness rule: every legal version/chunk has `enforce_date`; historical versions require `expire_date`; active versions may legitimately omit `expire_date`.
- Failure codes: `law_version_temporal_metadata_invalid` and `law_chunk_temporal_metadata_invalid`.

- [ ] **Step 1: Add failing schema/readiness tests**

  Assert both index statements are issued. Extend the fake Neo4j session to return temporal counts, then cover:

  ```python
  historical_missing_expire_count = 1
  ```

  resulting in `CommandError` containing only `law_version_temporal_metadata_invalid`. Add a success case where active records have no `expire_date`, and a failure case where any chunk lacks `enforce_date`.

- [ ] **Step 2: Run graph tests and record RED**

  Run:

  ```powershell
  python -m pytest test/test_legal_graph_seed_commands.py -q
  ```

  Expected: FAIL because temporal indexes and readiness counts are not checked.

- [ ] **Step 3: Add temporal indexes**

  Add the two `CREATE INDEX ... IF NOT EXISTS` statements beside existing constraints. Do not backfill or invent `expire_date`; the seed remains the source of truth.

- [ ] **Step 4: Add readiness queries**

  Query aggregate counts only. Verify version/chunk totals, enforce-date presence, and historical expiration completeness. Translate failures to fixed reason codes without emitting graph rows or legal text.

- [ ] **Step 5: Prove safe fallback remains intact**

  Run the existing tests that patch Neo4j session acquisition to `None` and assert the legal/search agent returns the established safe fallback. Add a narrow regression test only if no existing test asserts this behavior.

- [ ] **Step 6: Run Task 5 GREEN tests**

  Run:

  ```powershell
  python -m pytest test/test_legal_graph_seed_commands.py backend/chatbot/tests.py -q
  ```

  Expected: all tests PASS; representative readiness produces no missing-property warning under the new schema contract.

- [ ] **Step 7: Review checkpoint**

  Run `git diff --check` and inspect Cypher for idempotence, correct labels, and correct active-versus-historical semantics.

---

### Task 6: Integrate G3 evidence into the master checklist

**Files:**
- Modify: `docs/tech-validation-reports/2026-07-31-pilot-hotfix-master-checklist.md`
- Modify: `docs/tech-validation-reports/2026-07-31-e2e-cross-analysis-final-hotfix-report.md` only if a finding or control changed.

**Interfaces:**
- Produces one auditable G3 section containing local evidence, production-only residual actions, and explicit gate status.

- [ ] **Step 1: Record implemented controls**

  For HFX-013, record exact file paths, focused test commands, pass counts, and the release/dataset provenance contract. Record Caddy header deletion and Neo4j temporal readiness separately so one cannot mask another.

- [ ] **Step 2: Keep production-only items open**

  Leave these unchecked until executed against the real environment:

  - authorized credential rotation and old-token `401` proof;
  - exposed-log access/retention/replication review and approved purge;
  - production-like 10-minute monitor observation;
  - Caddy credential-canary zero-match result;
  - Neo4j representative-query warning count of zero;
  - actual redeployment and all 13 E2E scenarios.

- [ ] **Step 3: Cross-check report coverage**

  Search the checklist for `HFX-013`, `DISC-002`, `13`, `run_summary.json`, `APP_RELEASE_VERSION`, `LEGAL_DATASET_VERSION`, `Caddy`, and `expire_date`. Every approved requirement must map to either completed local evidence or an explicitly open production gate.

---

### Task 7: Run G3 regression and build gates

**Files:**
- Modify: only files required to fix a regression directly caused by Tasks 1–6.

**Interfaces:**
- Produces the local G3 handoff decision: `GREEN`, `RED`, or `BLOCKED`, with commands and counts.

- [ ] **Step 1: Run focused G3 suites**

  ```powershell
  python -m pytest test/test_legal_operational_evidence.py test/test_legal_run_summary_validation.py test/test_legal_ingestion_operational_summary.py backend/chatbot/test_operational_observability.py backend/chatbot/test_operational_log_privacy.py test/test_aws_pilot_infrastructure.py test/test_deployment_readiness_artifacts.py test/test_legal_graph_seed_commands.py -q
  ```

  Expected: zero failures.

- [ ] **Step 2: Run the full Python suite**

  ```powershell
  python -m pytest -q
  ```

  Expected: zero failures. Existing intentional skips must be reported by count and not silently reclassified.

- [ ] **Step 3: Run frontend tests**

  Use the repository’s existing Node test command that produced the G2 `52/52` baseline.

  Expected: at least the same 52 tests pass with zero failures.

- [ ] **Step 4: Run the production frontend build**

  Use the existing Vite build command from G2.

  Expected: exit code 0; no new unresolved import, syntax, or bundle errors.

- [ ] **Step 5: Run static and secret-safety checks**

  ```powershell
  git diff --check
  git status --short
  ```

  Review changed files for tokens, passwords, copied environment values, raw legal text, and generated evidence. None may be committed.

- [ ] **Step 6: Update the final local gate**

  Mark G3 local implementation `GREEN` only when all focused tests, full pytest, frontend tests, and build pass. Keep G7/G8/G9 production redeployment and 13-scenario E2E gates open.

- [ ] **Step 7: User-owned Git checkpoint**

  Present the exact changed-file list, validation counts, residual risks, and suggested commit message:

  ```text
  fix: enforce pilot operational evidence integrity
  ```

  Wait for the user to review, stage, and commit. Do not perform Git publication actions.

---

## G3 Exit Criteria

- Release-local evidence is generated from the validated immutable seed after all readiness checks.
- Evidence schema, freshness, dataset version, and release version are validated before cutover.
- Shared evidence promotion and rollback are atomic.
- `ops-monitor` cannot start with missing, stale, malformed, failed, or provenance-mismatched evidence.
- Caddy access logs contain no request headers.
- Credential/log incident remediation is executable but remains an authorized production action.
- Neo4j temporal property keys are indexed and temporal completeness is part of readiness.
- Neo4j-unavailable safe fallback remains covered.
- Focused tests, full pytest, frontend tests, and frontend build are GREEN.
- Production redeployment, 10-minute observation, credential-canary inspection, and all 13 E2E scenarios remain explicit final gates rather than inferred success.
