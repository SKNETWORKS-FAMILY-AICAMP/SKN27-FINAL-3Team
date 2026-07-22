# Legal RAG pgvector Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a reproducible, legal-domain-only PostgreSQL lexical ↔ pgvector evaluation tool that produces local artifacts and a truthful Markdown report input without changing the production retrieval order.

**Architecture:** A pure evaluation module validates public-law fixtures, normalizes backend responses, and calculates deterministic retrieval metrics. A thin CLI invokes the existing legal RAG backend helpers independently with the identical temporal/scope filters, writes ignored local JSON artifacts, and optionally exports a RAGAS-ready public-only dataset; it never calls the public runtime selector or changes its fallback policy.

**Tech Stack:** Python 3.13, pytest, Django legal RAG helpers, PostgreSQL/pgvector, JSON/JSONL artifacts; optional RAGAS is invoked only by an explicit live command and is not a CI dependency.

## Global Constraints

- Scope is only `law`, `enforcement_decree`, `enforcement_rule`, `administrative_rule`, and `notice`; do not touch Elasticsearch, fault-ratio precedent/review-case data, text ML, or the Jae-gang RAG path.
- Use identical query, `top_k=5`, `temporal_basis`, and `scope` for lexical and pgvector candidates.
- Preserve existing production `search_legal_rag()` priority/fallback behavior and never switch `LEGAL_RAG_VECTOR_ENABLED` in application code.
- Evaluation fixtures must contain public legal text only; never write user chat, OCR, attachments, credentials, or raw retrieved provisions to Git-tracked artifacts/logs.
- Generated results live below ignored `output/law_ingestion/`; checked-in Markdown may only state results that were actually executed.
- RAGAS is optional, capped at 20 public-law queries and top-5 contexts; unavailable credentials/dependencies produce `not_evaluated`, never an invented score.

---

### Task 1: Public legal evaluation fixture and validation contract

**Files:**
- Create: `etl/legal/evaluation.py`
- Create: `etl/legal/evaluation_fixtures/public_law_queries.json`
- Create: `test/test_legal_rag_evaluation.py`

**Interfaces:**
- Produces `load_public_law_queries(path: Path) -> list[dict[str, object]]`.
- Produces `validate_public_law_query(row: Mapping[str, object]) -> dict[str, object]`.
- Each query has `query_id`, `query`, `temporal_basis`, `scope`, `expected_source_references`, `reference_answer`, `scenario`, and `data_classification="public_law"`.

- [ ] **Step 1: Write the failing fixture-validation tests**

```python
def test_load_public_law_queries_requires_twenty_public_law_rows(tmp_path: Path):
    fixture = tmp_path / "queries.json"
    fixture.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="at least 20"):
        evaluation.load_public_law_queries(fixture)


def test_validate_public_law_query_rejects_non_public_classification():
    with pytest.raises(ValueError, match="data_classification"):
        evaluation.validate_public_law_query({"query_id": "q1", "data_classification": "ocr"})
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py -k fixture`

Expected: FAIL because the evaluation module does not exist.

- [ ] **Step 3: Implement validation and a 20-query public-law fixture**

```python
REQUIRED_QUERY_FIELDS = frozenset({
    "query_id", "query", "temporal_basis", "scope", "expected_source_references",
    "reference_answer", "scenario", "data_classification",
})

def validate_public_law_query(row: Mapping[str, object]) -> dict[str, object]:
    missing = REQUIRED_QUERY_FIELDS - set(row)
    if missing or row.get("data_classification") != "public_law":
        raise ValueError("data_classification and all required public-law fields are required")
    return dict(row)
```

Use stable law/article references such as `도로교통법|제5조`, not volatile `chunk_id` values. The fixture must cover all five allowed legal source types and have no personal or incident-specific content.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py -k fixture`

Expected: PASS.

- [ ] **Step 5: Commit the fixture contract**

```bash
git add etl/legal/evaluation.py etl/legal/evaluation_fixtures/public_law_queries.json test/test_legal_rag_evaluation.py
git commit -m "test: add public legal rag evaluation fixture"
```

### Task 2: Deterministic lexical ↔ pgvector metrics and safe result normalization

**Files:**
- Modify: `etl/legal/evaluation.py`
- Modify: `test/test_legal_rag_evaluation.py`

**Interfaces:**
- Produces `normalize_backend_response(query_id: str, response: Mapping[str, object]) -> dict[str, object]`.
- Produces `summarize_backend_runs(runs: Sequence[Mapping[str, object]], queries: Sequence[Mapping[str, object]]) -> dict[str, object]`.
- Candidate identities are `source_name|article`; normalizer omits `provision_text`, `summary`, and the query text from persisted results.

- [ ] **Step 1: Write the failing metric tests**

```python
def test_summary_calculates_recall_mrr_ndcg_and_latency_without_raw_text():
    queries = [{"query_id": "q1", "expected_source_references": ["도로교통법|제5조"]}]
    runs = [{"query_id": "q1", "backend": "postgres_lexical", "latency_ms": 10,
             "status": "ready", "results": [{"source_name": "도로교통법", "article": "제5조",
                                                    "source_url": "https://law.go.kr/x"}]}]
    summary = evaluation.summarize_backend_runs(runs, queries)
    assert summary["postgres_lexical"]["recall_at_1"] == 1.0
    assert "provision_text" not in summary
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py -k "metric or summary"`

Expected: FAIL because metrics/normalization are missing.

- [ ] **Step 3: Implement deterministic calculations**

```python
def candidate_reference(result: Mapping[str, object]) -> str:
    return f"{str(result.get('source_name', '')).strip()}|{str(result.get('article', '')).strip()}"

def reciprocal_rank(results: Sequence[Mapping[str, object]], expected: set[str]) -> float:
    for rank, result in enumerate(results, start=1):
        if candidate_reference(result) in expected:
            return 1.0 / rank
    return 0.0
```

Calculate Recall@1/3/5, MRR, nDCG@5, no-result rate, p50/p95 latency, and metadata validity (nonempty URL/reference plus temporal/filter-safe backend status). Store aggregate values and per-rank metadata only; omit provisions, summaries, query strings, tokens, and credentials.

- [ ] **Step 4: Run focused module tests and confirm GREEN**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py`

Expected: PASS.

- [ ] **Step 5: Commit the metric contract**

```bash
git add etl/legal/evaluation.py test/test_legal_rag_evaluation.py
git commit -m "feat: add legal rag evaluation metrics"
```

### Task 3: Independent backend collection CLI and RAGAS-ready public export

**Files:**
- Create: `etl/legal/run_evaluation.py`
- Modify: `etl/legal/evaluation.py`
- Modify: `test/test_legal_rag_evaluation.py`
- Modify: `requirements-etl.txt`

**Interfaces:**
- Produces `collect_backend_runs(queries, *, top_k=5) -> list[dict[str, object]]`.
- Produces CLI `python -m etl.legal.run_evaluation --fixture ... --output-dir ...`.
- CLI invokes `resolve_legal_search_filters`, `_search_law_chunks_lexical`, and `_search_pgvector` once each per fixture query with identical resolved filters.
- Produces ignored local `summary.json`, `candidates.json`, and `ragas_input.jsonl`; the last has public question/reference answer/retrieved contexts only and is capped at 20 × 5.

- [ ] **Step 1: Write failing CLI collector tests with fake backend helpers**

```python
def test_collect_backend_runs_uses_identical_resolved_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(run_evaluation.service, "resolve_legal_search_filters", lambda **_: (("law",), date(2026, 7, 21), ""))
    monkeypatch.setattr(run_evaluation.service, "_search_law_chunks_lexical", lambda query, **kw: calls.append(("lexical", kw)) or response("postgres_lexical"))
    monkeypatch.setattr(run_evaluation.service, "_search_pgvector", lambda query, **kw: calls.append(("vector", kw)) or response("postgres_pgvector"))
    run_evaluation.collect_backend_runs([public_query()])
    assert calls[0][1]["effective_at"] == calls[1][1]["effective_at"]
    assert calls[0][1]["allowed_source_types"] == calls[1][1]["allowed_source_types"]
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py -k collector`

Expected: FAIL because the CLI module does not exist.

- [ ] **Step 3: Implement a no-runtime-mutation CLI and optional RAGAS dependency declaration**

```python
def collect_backend_runs(queries: Sequence[Mapping[str, object]], *, top_k: int = 5) -> list[dict[str, object]]:
    runs = []
    for row in queries:
        allowed, effective_at, error = service.resolve_legal_search_filters(
            source_type="law", temporal_basis=row["temporal_basis"], scope=row["scope"],
        )
        for search in (service._search_law_chunks_lexical, service._search_pgvector):
            response = search(str(row["query"]), top_k=top_k, source_type="law",
                              allowed_source_types=allowed, effective_at=effective_at)
            runs.append(evaluation.normalize_backend_response(str(row["query_id"]), response))
    return runs
```

Add `ragas>=0.2,<1` only to `requirements-etl.txt` as an optional evaluation dependency; production `requirements.txt` stays unchanged. The CLI must return an actionable error when PostgreSQL/pgvector is unavailable and must never send data to RAGAS by default.

- [ ] **Step 4: Run focused tests and a safe CLI help check**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py && python -m etl.legal.run_evaluation --help`

Expected: Tests PASS and CLI usage is printed without DB/API access.

- [ ] **Step 5: Commit the runner**

```bash
git add etl/legal/run_evaluation.py etl/legal/evaluation.py test/test_legal_rag_evaluation.py requirements-etl.txt
git commit -m "feat: add legal rag backend evaluation runner"
```

### Task 4: Report procedure, transition decision rendering, and regression verification

**Files:**
- Modify: `docs/tech-validation-reports/legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md`
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `test/test_legal_rag_evaluation.py`

**Interfaces:**
- Produces `transition_decision(summary: Mapping[str, object]) -> dict[str, object]` with `eligible`, `failed_gates`, and no recommendation when RAGAS is `not_evaluated`.
- Documents exact local commands and outputs; reports only actual run metadata/aggregates.

- [ ] **Step 1: Write failing transition-gate tests**

```python
def test_transition_decision_rejects_missing_ragas_evidence():
    decision = evaluation.transition_decision(passing_deterministic_summary(ragas_status="not_evaluated"))
    assert decision["eligible"] is False
    assert "ragas_not_evaluated" in decision["failed_gates"]
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py -k transition`

Expected: FAIL because decision rendering is missing.

- [ ] **Step 3: Implement gates and update the report/checklist without claiming unrun results**

```python
def transition_decision(summary: Mapping[str, object]) -> dict[str, object]:
    failed_gates = []
    if summary.get("ragas", {}).get("status") != "evaluated":
        failed_gates.append("ragas_not_evaluated")
    return {"eligible": not failed_gates, "failed_gates": failed_gates}
```

Keep the checklist at `[~]` until an executed comparison is attached to the report. Add a runbook describing `summary.json`, `candidates.json`, `ragas_input.jsonl`, failure statuses, and the rule that only aggregate results belong in committed Markdown.

- [ ] **Step 4: Run regression verification**

Run: `python -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_service.py --timeout=30`

Expected: PASS, proving evaluation tooling did not change legal RAG runtime behavior.

- [ ] **Step 5: Commit documentation and runbook**

```bash
git add docs/tech-validation-reports/legal-rag/2026-07-21-legal-rag-pgvector-evaluation-report.md docs/ops/project-readiness-master-checklist.md test/test_legal_rag_evaluation.py
git commit -m "docs: add legal rag evaluation runbook"
```

## Self-Review

- Spec coverage: Tasks 1–3 create the public fixture, independent lexical/vector A/B, embedding-space-safe metadata, local artifacts, and RAGAS-ready export. Task 4 implements all transition gates and the truthful report/checklist rule.
- Exclusions: No task modifies Elasticsearch, Jae-gang data paths, production retrieval priority, or application UI/API.
- Placeholder scan: No implementation task is deferred; live PostgreSQL/RAGAS execution is deliberately external-state dependent and its non-execution status is a required result, not a placeholder.
- Type consistency: The fixture loader returns rows consumed by the collector; collector returns normalized runs consumed by summaries; summary feeds the transition decision and report.
