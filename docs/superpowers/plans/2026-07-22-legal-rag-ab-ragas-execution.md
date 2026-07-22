# Legal RAG Local A/B and RAGAS Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the PostgreSQL lexical ↔ pgvector evaluation reproducible in a local Docker PostgreSQL environment, fail closed when the corpus or credentials are absent, and record only real A/B/RAGAS evidence.

**Architecture:** A small Python environment module loads an explicitly selected ignored evaluation env file and reports sanitized readiness state. The existing evaluator accepts that file before Django settings load, persists run metadata beside local artifacts, and an opt-in PowerShell wrapper starts only the local PostgreSQL service and invokes the evaluator. No production runtime setting, service route, or data source is changed.

**Tech Stack:** Python 3.13+, pytest, Django, PostgreSQL pgvector Docker service, PowerShell, SentenceTransformers E5 1024-dimension embeddings, optional OpenAI/RAGAS.

## Global Constraints

- Only local Docker `postgres` is in scope; never modify AWS/RDS, Docker production defaults, Elasticsearch, Neo4j, or the current `LEGAL_RAG_VECTOR_ENABLED=0` shared default.
- `.env.rag-eval` is local and ignored. No API key, database password, query text, raw law context, OCR, attachment, or user data is committed or printed.
- The actual comparison requires a single corpus snapshot, matching seed/query provider-model-dimension metadata, identical temporal/scope filters, and top-5.
- Missing artifact, law provider credential, PostgreSQL readiness, or RAGAS dependency must yield a named `not_ready`/`not_evaluated` result; never fabricate corpus rows or quality scores.
- RAGAS is opt-in, backend-separated, limited to 20 public-law queries and five contexts each.

---

### Task 1: Evaluation-only environment contract

**Files:**
- Create: `.env.rag-eval.example`
- Modify: `.gitignore`
- Create: `etl/legal/evaluation_environment.py`
- Create: `test/test_legal_rag_evaluation_environment.py`

**Interfaces:**
- Produces `load_evaluation_environment(path: Path) -> dict[str, str]`.
- Produces `validate_evaluation_environment(values: Mapping[str, str]) -> dict[str, object]` with `status`, `missing`, and sanitized `embedding_space` fields.
- The loader accepts only `KEY=VALUE` lines, ignores blank/comment lines, and never returns secret values in validation output.

- [ ] **Step 1: Write failing tests for ignored env files and exact embedding-space requirements**

```python
def test_validate_evaluation_environment_requires_enabled_matching_1024_space():
    result = environment.validate_evaluation_environment({"LEGAL_RAG_VECTOR_ENABLED": "0"})
    assert result["status"] == "not_ready"
    assert "LEGAL_RAG_VECTOR_ENABLED" in result["missing"]


def test_sanitized_environment_result_never_contains_api_key_or_password(tmp_path: Path):
    path = tmp_path / ".env.rag-eval"
    path.write_text("OPENAI_API_KEY=secret\nPOSTGRES_PASSWORD=secret\n", encoding="utf-8")
    result = environment.validate_evaluation_environment(environment.load_evaluation_environment(path))
    assert "secret" not in repr(result)
```

- [ ] **Step 2: Run RED verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation_environment.py`

Expected: FAIL because the module and env contract do not exist.

- [ ] **Step 3: Implement the parser and example file**

```python
REQUIRED_VECTOR_KEYS = (
    "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD",
    "LEGAL_RAG_VECTOR_ENABLED", "LEGAL_RAG_QUERY_EMBEDDING_PROVIDER",
    "LEGAL_RAG_QUERY_EMBEDDING_MODEL", "LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS",
    "LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "LEGAL_RAG_SEED_EMBEDDING_MODEL",
    "LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS",
)
```

Require vector enablement to equal `1`, both dimension values to equal `1024`, and seed/query provider-model-dimension equality. Add `.env.rag-eval` to `.gitignore`; keep `.env.rag-eval.example` value-free except safe localhost and E5 defaults.

- [ ] **Step 4: Run GREEN verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation_environment.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .gitignore .env.rag-eval.example etl/legal/evaluation_environment.py test/test_legal_rag_evaluation_environment.py
git commit -m "test: add legal rag evaluation environment contract"
```

### Task 2: Evaluator preflight and reproducible local metadata

**Files:**
- Modify: `etl/legal/run_evaluation.py`
- Modify: `etl/legal/evaluation.py`
- Modify: `test/test_legal_rag_evaluation.py`
- Modify: `test/test_legal_rag_evaluation_environment.py`

**Interfaces:**
- Adds CLI flag `--env-file` defaulting to `.env.rag-eval`.
- Produces `collect_evaluation_preflight() -> dict[str, object]` with `status`, sanitized embedding space, table counts, source-type counts, and corpus snapshot hash.
- Writes `environment.json` and embeds the preflight result in `summary.json`; raw provisions and credentials are excluded.

- [ ] **Step 1: Write failing tests for env-before-service loading and unavailable corpus**

```python
def test_preflight_marks_missing_law_tables_not_ready(monkeypatch):
    monkeypatch.setattr(run_evaluation, "_table_counts", lambda: {"law_chunks": 0, "law_embeddings": 0})
    preflight = run_evaluation.collect_evaluation_preflight()
    assert preflight["status"] == "not_ready"
    assert preflight["reason"] == "law_rag_seed_missing"
```

- [ ] **Step 2: Run RED verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py -k preflight`

Expected: FAIL because preflight metadata is missing.

- [ ] **Step 3: Implement preflight before backend collection**

```python
if preflight["status"] != "ready":
    write_summary(status="not_ready", preflight=preflight, runs=[])
    return 2
```

Load `.env.rag-eval` into the current evaluation process before importing Django settings. Query only table/schema metadata and aggregate counts; hash stable chunk IDs plus embedding metadata, never provision text. Make `--run-ragas` refuse execution unless preflight and deterministic A/B are both ready.

- [ ] **Step 4: Run GREEN verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add etl/legal/evaluation.py etl/legal/run_evaluation.py test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py
git commit -m "feat: add legal rag evaluation preflight"
```

### Task 3: Local Docker execution wrapper

**Files:**
- Create: `scripts/run-legal-rag-ab-evaluation.ps1`
- Create: `test/test_legal_rag_evaluation_script_contract.py`
- Modify: `docs/tech-validation-reports/legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md`

**Interfaces:**
- Wrapper parameters: `-EnvFile`, `-RunId`, `-RunRagas`, `-StartPostgres`.
- The wrapper runs `docker compose up -d postgres` only when `-StartPostgres` is supplied, checks Docker readiness, then runs `python -m etl.legal.run_evaluation --env-file <path> --run-id <id>`.
- It never runs the data pipeline automatically; missing legal artifacts or provider credentials are returned by preflight for an explicit follow-up command.

- [ ] **Step 1: Write failing static contract tests**

```python
def test_wrapper_requires_explicit_postgres_start_and_env_file():
    source = read_text(ROOT / "scripts" / "run-legal-rag-ab-evaluation.ps1")
    assert "[switch]$StartPostgres" in source
    assert "Test-Path -LiteralPath $EnvFile" in source
    assert "docker compose up -d postgres" in source
```

- [ ] **Step 2: Run RED verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation_script_contract.py`

Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Implement the explicit wrapper and runbook**

```powershell
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "Evaluation env file not found: $EnvFile" }
if ($StartPostgres) { docker compose up -d postgres }
python -m etl.legal.run_evaluation --env-file $EnvFile --run-id $RunId
if ($RunRagas) { python -m etl.legal.run_evaluation --env-file $EnvFile --run-id "$RunId-ragas" --run-ragas }
```

Use a distinct run ID for RAGAS so a rerun never overwrites deterministic artifacts. Update the report with prerequisites and the rule that a preflight failure is a recorded outcome, not a quality score.

- [ ] **Step 4: Run GREEN verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation_script_contract.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/run-legal-rag-ab-evaluation.ps1 test/test_legal_rag_evaluation_script_contract.py docs/tech-validation-reports/legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md
git commit -m "feat: add local legal rag evaluation runner"
```

### Task 4: Execute only when dependencies are present and record the actual conclusion

**Files:**
- Modify: `docs/tech-validation-reports/legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes `output/law_ingestion/evaluation/<run-id>/summary.json` and `environment.json`.
- Produces a Markdown result containing only aggregate metrics, source coverage, runtime/cost totals, failed-gate reason codes, and the decision.

- [ ] **Step 1: Add a failing report-contract test**

```python
def test_report_does_not_mark_pgvector_transition_complete_without_ready_ab_and_ragas():
    report = read_text(REPORT_PATH)
    assert "전환 결론: 보류" in report
    assert "실제 A/B 결과" in report
```

- [ ] **Step 2: Run RED verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation_script_contract.py -k report`

Expected: FAIL until the report distinguishes environment readiness from quality results.

- [ ] **Step 3: Run the evaluation with explicit conditions**

```powershell
Copy-Item .env.rag-eval.example .env.rag-eval
# Add local database password and keys locally; do not commit this file.
pwsh scripts/run-legal-rag-ab-evaluation.ps1 -EnvFile .env.rag-eval -RunId legal-ab-001 -StartPostgres
pwsh scripts/run-legal-rag-ab-evaluation.ps1 -EnvFile .env.rag-eval -RunId legal-ab-001 -RunRagas
```

If preflight reports missing artifacts/provider credentials, record `전환 결론: 보류` with the exact sanitized reason and stop. Do not call a law provider or OpenAI until the required key is present locally.

- [ ] **Step 4: Run final verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py test/test_legal_rag_evaluation_script_contract.py test/test_legal_rag_service.py --timeout=30`

Expected: PASS. If a real run occurred, inspect `summary.json` and confirm it contains no credential/raw provision fields.

- [ ] **Step 5: Commit only truthful report/checklist state**

```bash
git add docs/tech-validation-reports/legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md docs/ops/project-readiness-master-checklist.md test/test_legal_rag_evaluation_script_contract.py
git commit -m "docs: record legal rag evaluation result"
```

## Self-Review

- Spec coverage: Task 1 isolates secrets and enforces embedding-space compatibility; Task 2 prevents a false A/B run; Task 3 provides an explicit local Docker path; Task 4 records only executed results and keeps the checklist honest.
- Scope: no task changes the production vector default, search priority, AWS, Elasticsearch, Neo4j, or teammate-owned RAG data.
- Type consistency: environment loader feeds preflight; preflight gates the evaluator; evaluator writes the exact files consumed by the report step.
- No placeholder: absent corpus/key/service has the explicit `not_ready` outcome rather than an implicit or fabricated fallback.
