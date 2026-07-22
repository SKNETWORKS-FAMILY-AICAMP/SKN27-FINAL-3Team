# RAGAS Batch Failure Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Preserve a safe query/backend RAGAS execution ledger and return aggregate RAGAS metrics only when every public-law evaluation record has all four valid metrics.

**Architecture:** run_ragas evaluates one public-law record at a time, retains only a sanitized ledger in its returned result, and keeps per-record metric values in memory for aggregation. Existing evaluation-environment loading, PostgreSQL preflight, deterministic lexical/pgvector collection, and runtime routing remain unchanged.

**Tech Stack:** Python 3.13, pytest, Django evaluation helpers, RAGAS, OpenAI SDK, JSON local artifacts.

## Global Constraints

- Modify only etl/legal/run_evaluation.py, test/test_legal_rag_evaluation.py, the legal RAG execution report, and C-1 checklist text.
- Do not change .env.rag-eval, evaluation_environment.py, Docker/PowerShell runner, PostgreSQL preflight, production RAG routing, Elasticsearch, Neo4j, embeddings, or legal corpus data.
- Per-query persisted ledger entries contain exactly query_id, backend, status, error_code, and latency_ms; never persist question, answer, context, exception text, credentials, OCR, attachment, or user data.
- Required RAGAS metrics are context_precision, context_recall, faithfulness, and answer_relevancy. Every value must be finite and in the inclusive range 0–1.
- A backend result is evaluated only when every supplied record succeeds with all four metrics. Otherwise return not_evaluated and incomplete_ragas_evidence, without aggregate metrics.
- Keep C-1 at [~]: pgvector no-result and p95 gates are already unfulfilled even if the RAGAS batch becomes evaluable.

---

### Task 1: Freeze the query-level failure ledger with RED tests

**Files:**
- Modify: test/test_legal_rag_evaluation.py
- Modify: etl/legal/run_evaluation.py

**Interfaces:**
- Consumes: run_ragas(records, generator_model, judge_model, embedding_model), _generate_ragas_answers, and _evaluate_ragas_samples.
- Produces: run_ragas result key query_results. Each ledger entry contains exactly query_id, backend, status, error_code, and latency_ms.
- Produces: _safe_ragas_error_code(exc: Exception) -> str that returns only a documented safe code.

- [ ] **Step 1: Add complete-metric and record fixtures to the test module**

~~~python
COMPLETE_RAGAS_METRICS = {
    "context_precision": 0.8,
    "context_recall": 0.7,
    "faithfulness": 0.9,
    "answer_relevancy": 0.6,
}


def ragas_record(
    query_id: str,
    backend: str = "postgres_lexical",
    contexts: list[str] | None = None,
) -> dict[str, object]:
    return {
        "query_id": query_id,
        "backend": backend,
        "question": "공개 법령 질의",
        "ground_truth": "공개 법령 정답",
        "contexts": contexts if contexts is not None else ["공개 법령 조문"],
    }
~~~

- [ ] **Step 2: Add the failing isolation and sanitization test**

~~~python
def test_run_ragas_continues_after_one_query_failure_without_leaking_exception_text(monkeypatch) -> None:
    generated: list[str] = []

    def generate(rows, **_kwargs):
        query_id = rows[0]["query_id"]
        generated.append(query_id)
        if query_id == "law-q002":
            raise RuntimeError("provider response included api_key=secret-value")
        return [{**rows[0], "answer": "생성 답변"}]

    monkeypatch.setattr(run_evaluation, "_generate_ragas_answers", generate)
    monkeypatch.setattr(
        run_evaluation,
        "_evaluate_ragas_samples",
        lambda _rows, **_kwargs: COMPLETE_RAGAS_METRICS,
    )

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001"), ragas_record("law-q002"), ragas_record("law-q003")],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert generated == ["law-q001", "law-q002", "law-q003"]
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "incomplete_ragas_evidence"
    assert result["query_results"][1]["query_id"] == "law-q002"
    assert result["query_results"][1]["status"] == "not_evaluated"
    assert result["query_results"][1]["error_code"] == "ragas_runtime_unavailable"
    assert set(result["query_results"][1]) == {
        "query_id", "backend", "status", "error_code", "latency_ms",
    }
    assert "secret-value" not in json.dumps(result, ensure_ascii=False)
~~~

- [ ] **Step 3: Run the focused test and confirm RED**

Run: python -m pytest -q test/test_legal_rag_evaluation.py -k continues_after_one_query_failure --timeout=30

Expected: FAIL because the current backend-level try block stops after law-q002, returns no query ledger, and never runs law-q003.

- [ ] **Step 4: Implement a single-record execution loop with a sanitized ledger**

~~~python
RAGAS_METRIC_NAMES = (
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
)


def _safe_ragas_error_code(exc: Exception) -> str:
    if isinstance(exc, ImportError):
        return "ragas_dependencies_not_installed"
    if isinstance(exc, RuntimeError):
        return _safe_ragas_reason(exc)
    return "ragas_runtime_unavailable"


def _ragas_ledger_entry(
    record: Mapping[str, object],
    *,
    status: str,
    error_code: str,
    latency_ms: int,
) -> dict[str, object]:
    return {
        "query_id": _required_text(record, "query_id"),
        "backend": _required_text(record, "backend"),
        "status": status,
        "error_code": error_code,
        "latency_ms": max(0, latency_ms),
    }
~~~

In run_ragas, iterate records; time one _generate_ragas_answers([record], ...) and one _evaluate_ragas_samples([answered_record], ...); append only _ragas_ledger_entry; and continue after each exception. Keep successful per-record metric mappings in a local list only. If any ledger entry is not evaluated, return not_evaluated with reason incomplete_ragas_evidence and omit metrics.

- [ ] **Step 5: Run the focused test and confirm GREEN**

Run: python -m pytest -q test/test_legal_rag_evaluation.py -k continues_after_one_query_failure --timeout=30

Expected: PASS with three ledger entries and no secret text in the result.

- [ ] **Step 6: User-run Git checkpoint**

~~~powershell
git add etl/legal/run_evaluation.py test/test_legal_rag_evaluation.py
git commit -m "test: isolate legal ragas query failures"
~~~

### Task 2: Enforce complete, finite RAGAS metric evidence

**Files:**
- Modify: test/test_legal_rag_evaluation.py
- Modify: etl/legal/run_evaluation.py

**Interfaces:**
- Consumes: one in-memory mapping from _evaluate_ragas_samples([record], ...).
- Produces: _validate_ragas_metrics(metrics: Mapping[str, object]) -> tuple[dict[str, float] | None, str].
- Produces: _mean_ragas_metrics(metric_rows: Sequence[Mapping[str, float]]) -> dict[str, float] after every row validates.

- [ ] **Step 1: Add failing tests for incomplete, invalid, and successful complete metrics**

~~~python
@pytest.mark.parametrize(
    ("metrics", "error_code"),
    [
        ({"faithfulness": 1.0, "answer_relevancy": 0.9}, "ragas_metrics_incomplete"),
        ({**COMPLETE_RAGAS_METRICS, "context_recall": float("nan")}, "ragas_metrics_invalid"),
        ({**COMPLETE_RAGAS_METRICS, "faithfulness": 1.1}, "ragas_metrics_invalid"),
    ],
)
def test_run_ragas_rejects_incomplete_or_invalid_metrics(monkeypatch, metrics, error_code) -> None:
    monkeypatch.setattr(
        run_evaluation,
        "_generate_ragas_answers",
        lambda rows, **_kwargs: [{**rows[0], "answer": "답변"}],
    )
    monkeypatch.setattr(run_evaluation, "_evaluate_ragas_samples", lambda _rows, **_kwargs: metrics)

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001")],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert result["status"] == "not_evaluated"
    assert result["query_results"][0]["error_code"] == error_code
    assert "metrics" not in result


def test_run_ragas_aggregates_only_complete_metrics(monkeypatch) -> None:
    values = iter(
        [
            {"context_precision": 0.8, "context_recall": 0.6, "faithfulness": 0.7, "answer_relevancy": 0.9},
            {"context_precision": 0.6, "context_recall": 0.8, "faithfulness": 0.9, "answer_relevancy": 0.7},
        ]
    )
    monkeypatch.setattr(
        run_evaluation,
        "_generate_ragas_answers",
        lambda rows, **_kwargs: [{**rows[0], "answer": "답변"}],
    )
    monkeypatch.setattr(run_evaluation, "_evaluate_ragas_samples", lambda _rows, **_kwargs: next(values))

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001"), ragas_record("law-q002")],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert result["status"] == "evaluated"
    assert result["metrics"] == {
        "context_precision": 0.7,
        "context_recall": 0.7,
        "faithfulness": 0.8,
        "answer_relevancy": 0.8,
    }
~~~

- [ ] **Step 2: Run the metric tests and confirm RED**

Run: python -m pytest -q test/test_legal_rag_evaluation.py -k "incomplete_or_invalid_metrics or aggregates_only_complete_metrics" --timeout=30

Expected: FAIL because the current code accepts partial mappings as evaluated and neither rejects NaN nor values above one.

- [ ] **Step 3: Implement strict validation and aggregation**

~~~python
def _validate_ragas_metrics(
    metrics: Mapping[str, object],
) -> tuple[dict[str, float] | None, str]:
    normalized: dict[str, float] = {}
    for metric_name in RAGAS_METRIC_NAMES:
        if metric_name not in metrics:
            return None, "ragas_metrics_incomplete"
        try:
            value = float(metrics[metric_name])
        except (TypeError, ValueError):
            return None, "ragas_metrics_invalid"
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            return None, "ragas_metrics_invalid"
        normalized[metric_name] = value
    return normalized, ""


def _mean_ragas_metrics(
    metric_rows: Sequence[Mapping[str, float]],
) -> dict[str, float]:
    return {
        metric_name: round(
            sum(row[metric_name] for row in metric_rows) / len(metric_rows),
            6,
        )
        for metric_name in RAGAS_METRIC_NAMES
    }
~~~

Call _validate_ragas_metrics immediately after each single-record evaluation. A validation failure writes a not_evaluated ledger entry with the safe code, adds no metric row, and continues. Update test_run_ragas_uses_fixed_generator_and_judge_for_each_backend_record to use COMPLETE_RAGAS_METRICS; its purpose remains model propagation.

- [ ] **Step 4: Run metric and existing model-configuration tests and confirm GREEN**

Run: python -m pytest -q test/test_legal_rag_evaluation.py -k "run_ragas or transition" --timeout=30

Expected: PASS.

- [ ] **Step 5: User-run Git checkpoint**

~~~powershell
git add etl/legal/run_evaluation.py test/test_legal_rag_evaluation.py
git commit -m "feat: require complete ragas metric evidence"
~~~

### Task 3: Prevent empty-context calls and preserve transition-gate behavior

**Files:**
- Modify: test/test_legal_rag_evaluation.py
- Modify: etl/legal/run_evaluation.py

**Interfaces:**
- Consumes: RAGAS record contexts from build_ragas_records.
- Produces: a no_ragas_contexts ledger entry without calling generation or RAGAS evaluation helpers.
- Preserves: evaluation.transition_decision behavior: any backend status other than evaluated yields ragas_not_evaluated.

- [ ] **Step 1: Add failing empty-context and transition-gate tests**

~~~python
def test_run_ragas_skips_empty_context_without_external_calls(monkeypatch) -> None:
    monkeypatch.setattr(
        run_evaluation,
        "_generate_ragas_answers",
        lambda *_args, **_kwargs: pytest.fail("generator must not run"),
    )
    monkeypatch.setattr(
        run_evaluation,
        "_evaluate_ragas_samples",
        lambda *_args, **_kwargs: pytest.fail("ragas must not run"),
    )

    result = run_evaluation.run_ragas(
        [ragas_record("law-q001", contexts=[])],
        generator_model="g",
        judge_model="j",
        embedding_model="e",
    )

    assert result["status"] == "not_evaluated"
    assert result["query_results"][0]["error_code"] == "no_ragas_contexts"
~~~

- [ ] **Step 2: Run the focused test and confirm RED**

Run: python -m pytest -q test/test_legal_rag_evaluation.py -k empty_context --timeout=30

Expected: FAIL because the current runner forwards an empty-context record to the generator and lacks the ledger shape.

- [ ] **Step 3: Add the no-context guard before generation**

~~~python
contexts = record.get("contexts")
if not isinstance(contexts, list) or not any(
    isinstance(value, str) and value.strip() for value in contexts
):
    query_results.append(
        _ragas_ledger_entry(
            record,
            status="not_evaluated",
            error_code="no_ragas_contexts",
            latency_ms=0,
        )
    )
    continue
~~~

Existing transition_decision tests already confirm not_evaluated yields ragas_not_evaluated. Do not modify transition_decision unless that regression test fails.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: python -m pytest -q test/test_legal_rag_evaluation.py -k empty_context --timeout=30

Expected: PASS with no external helper calls.

- [ ] **Step 5: User-run Git checkpoint**

~~~powershell
git add etl/legal/run_evaluation.py test/test_legal_rag_evaluation.py
git commit -m "fix: skip ragas records without legal context"
~~~

### Task 4: Record the verified contract without overstating live RAGAS results

**Files:**
- Modify: docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md
- Modify: docs/ops/project-readiness-master-checklist.md

**Interfaces:**
- Consumes: focused regression results and any separately executed local RAGAS summary.json.
- Produces: a truthful report entry distinguishing test-contract completion from a live RAGAS aggregate result.
- Preserves: C-1 status [~] and existing p95/no-result gate evidence.

- [ ] **Step 1: Add the report update without inventing evaluation metrics**

Append this section:

~~~markdown
## Issue #285 — 배치 실패 격리 계약

- 질의·backend별 상태는 안전한 오류 코드와 소요 시간만 남긴다.
- 한 질의 실패 후에도 남은 질의를 계속 평가하는 회귀 테스트를 통과했다.
- 모든 질의·필수 metric이 완전하지 않으면 aggregate는 not_evaluated / incomplete_ragas_evidence이며 전환 gate는 계속 차단된다.
- 이 변경 자체는 live RAGAS metric을 생성하지 않는다. 별도 로컬 실행 결과가 있을 때만 run ID와 aggregate를 추가한다.
~~~

- [ ] **Step 2: Update C-1 while retaining its in-progress status**

Replace the current C-1 evidence suffix with text including #280, #282, #285, stating that the 20×2 RAGAS batch has a safe isolation contract, and retaining [~] because actual aggregate evidence and pgvector no-result/p95 gates remain incomplete or failed.

- [ ] **Step 3: Run documentation and focused regression verification**

Run: python -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py --timeout=30

Expected: PASS. Then run git diff --check; expected output is empty.

- [ ] **Step 4: User-run Git checkpoint**

~~~powershell
git add docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md docs/ops/project-readiness-master-checklist.md
git commit -m "docs: record ragas isolation contract"
~~~

### Task 5: Full targeted regression and external handoff

**Files:**
- Verify only: etl/legal/run_evaluation.py, test/test_legal_rag_evaluation.py, test/test_legal_rag_evaluation_environment.py, test/test_legal_rag_service.py

**Interfaces:**
- Verifies: evaluation-only changes preserve legal RAG service behavior and do not change runtime routing.

- [ ] **Step 1: Run the full legal RAG regression suite**

Run: python -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py test/test_legal_rag_service.py --timeout=30

Expected: PASS with no RAGAS network call because every RAGAS test monkeypatches external helpers.

- [ ] **Step 2: Run the repository regression suite**

Run: python -m pytest -q --timeout=30

Expected: PASS. If it fails outside touched files, report the exact failing test and do not classify it as an #285 regression without comparison to the clean baseline.

- [ ] **Step 3: Inspect the final change set**

Run: git diff --check origin/dev...HEAD

Expected: no output.

- [ ] **Step 4: User-run Git/issue handoff**

~~~powershell
git status --short --branch
git log --oneline origin/dev..HEAD
~~~

In Issue #285, record focused/full test results and whether a live local RAGAS run was performed. Do not mark C-1 complete or claim live metrics unless the local summary.json contains both backend aggregates with status evaluated.

