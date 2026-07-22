# pgvector 법령 RAG 전환 게이트 해소 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 법령 RAG pgvector의 HNSW 사후 필터 빈 결과를 해소하고, 전체 latency와 안전한 phase latency 증적을 이용해 #289 전환 gate를 재검증한다.

**Architecture:** pgvector SQL과 같은 transaction에서 HNSW 후보 수와 strict-order iterative scan을 요청 단위로 설정한다. OpenAI embedding client는 프로세스 내에서 재사용하며, service는 preflight·embedding·vector query·result mapping의 non-sensitive timing만 response에 추가한다. evaluator는 이 네 key만 artifact에 whitelist하고, 전체 latency gate는 기존 `latency_ms`로 유지한다.

**Tech Stack:** Python 3.13.14 live evaluation environment, Django 6.0.6, PostgreSQL/pgvector 0.8.2, OpenAI SDK, pytest.

## Global Constraints

- 모든 production 변경은 해당 failing test를 먼저 실행해 RED를 확인한 뒤 작성한다.
- HNSW 설정은 `SET LOCAL`만 사용하며 DB 전역 설정·index DDL·seed data를 바꾸지 않는다.
- `LAW` temporal/scope/evidence/embedding-space filter와 lexical/Django fallback 순서를 유지한다.
- 전체 `latency_ms`가 전환 gate의 유일한 latency 입력이다. phase 지표는 진단용이다.
- phase artifact에는 `preflight_ms`, `embedding_ms`, `vector_query_ms`, `result_mapping_ms` 네 non-negative integer만 허용한다.
- API key, 원문 질의·답변·context, 예외 전문은 테스트 assertion·artifact·문서에 기록하지 않는다.
- Git commit/push/PR/merge는 사용자가 실행한다.

---

### Task 1: HNSW 요청 단위 iterative scan으로 법령 필터 후 후보 부족 해소

**Files:**
- Modify: `app/services/legal_rag_service.py:354-414`
- Modify: `test/test_legal_rag_service.py:40-74, 223-250`

**Interfaces:**
- Consumes: `_query_pgvector_rows(connection, query_vector, top_k, source_type, allowed_source_types, effective_at, embedding_space)`
- Produces: 동일한 `list[dict[str, Any]]`; vector SELECT 직전에 transaction-local HNSW 설정을 적용한다.

- [ ] **Step 1: SQL 실행 순서를 저장하는 failing test를 작성한다.**

`FakeCursor`가 마지막 SQL만 보관하지 않고 모든 실행을 기록하도록 확장하고, 아래 테스트를 `test_pgvector_applies_legal_family_scope_and_effective_date` 뒤에 추가한다.

```python
def test_pgvector_sets_local_hnsw_options_before_vector_select(monkeypatch):
    cursor = FakeCursor([])
    connection = FakeConnection(cursor)

    class FakeAtomic:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    monkeypatch.setattr(service.transaction, "atomic", lambda: FakeAtomic())

    service._query_pgvector_rows(
        connection,
        query_vector=[1.0] + [0.0] * 1023,
        top_k=5,
        source_type="law",
        allowed_source_types=("law",),
        effective_at=date(2026, 7, 21),
        embedding_space={"provider": "hash", "model": "hashing-vectorizer", "dimensions": 1024},
    )

    sql_statements = [sql for sql, _params in cursor.executions]
    assert sql_statements[:2] == [
        "SET LOCAL hnsw.ef_search = 400",
        "SET LOCAL hnsw.iterative_scan = 'strict_order'",
    ]
    assert "ORDER BY e.embedding_vector <=> %s::vector" in sql_statements[2]
    assert "c.source_type = ANY(%s)" in sql_statements[2]
    assert "c.enforce_date <= %s" in sql_statements[2]
    assert "btrim(c.source_url) <> ''" in sql_statements[2]
```

`FakeCursor`의 실제 변경은 아래와 같다.

```python
class FakeCursor:
    def __init__(self, rows, description=None):
        self.rows = rows
        self.description = description or VECTOR_DESCRIPTION
        self.sql = ""
        self.params = []
        self.executions = []

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params or []
        self.executions.append((sql, self.params))
```

- [ ] **Step 2: failing test를 실행해 RED를 확인한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_service.py::test_pgvector_sets_local_hnsw_options_before_vector_select --timeout=30 -p no:cacheprovider
```

Expected: `AttributeError` (`service.transaction` 또는 `cursor.executions` 없음) 혹은 첫 HNSW assertion 실패.

- [ ] **Step 3: 최소 production 구현을 작성한다.**

`app/services/legal_rag_service.py` 상단 import에 다음을 추가한다.

```python
from django.db import transaction
```

`_query_pgvector_rows()`의 기존 cursor block을 아래로 교체한다. SQL 문자열과 `params` 구성은 변경하지 않는다.

```python
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = 400")
            cursor.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
```

- [ ] **Step 4: targeted service tests를 GREEN으로 확인한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_service.py::test_pgvector_sets_local_hnsw_options_before_vector_select test/test_legal_rag_service.py::test_pgvector_applies_legal_family_scope_and_effective_date --timeout=30 -p no:cacheprovider
```

Expected: `2 passed`.

- [ ] **Step 5: 사용자 Git checkpoint를 준비한다.**

```powershell
git add app/services/legal_rag_service.py test/test_legal_rag_service.py
git commit -m "fix: use iterative pgvector scan for legal filters"
```

### Task 2: OpenAI embedding client 재사용으로 전체 latency의 연결 비용 제거

**Files:**
- Modify: `app/services/legal_rag_service.py:665-688`
- Modify: `test/test_legal_rag_service.py:574-600`

**Interfaces:**
- Produces: `_openai_embedding_client() -> Any`, process-scoped cached OpenAI client.
- Preserves: `_openai_embedding(query, model_id, dimensions) -> list[float]`의 request payload와 L2-normalized vector 반환값.

- [ ] **Step 1: 동일 설정에서 client를 한 번만 만드는 failing test를 작성한다.**

`test_sentence_transformer_model_is_cached_per_process` 뒤에 추가한다.

```python
def test_openai_embedding_client_is_reused_without_exposing_the_key(monkeypatch):
    created = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            assert kwargs == {
                "model": "text-embedding-3-large",
                "input": "public law query",
                "encoding_format": "float",
                "dimensions": 1024,
            }
            return SimpleNamespace(data=[SimpleNamespace(embedding=[3.0, 4.0])])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.embeddings = FakeEmbeddings()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("LEGAL_RAG_OPENAI_API_KEY", "test-key-not-for-output")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS", "12")
    service._openai_embedding_client.cache_clear()

    first = service._openai_embedding("public law query", model_id="text-embedding-3-large", dimensions=1024)
    second = service._openai_embedding("public law query", model_id="text-embedding-3-large", dimensions=1024)

    assert first == second == [0.6, 0.8]
    assert len(created) == 1
    assert created[0]["base_url"] == "https://api.openai.com/v1"
    assert "test-key-not-for-output" not in repr(first)
    service._openai_embedding_client.cache_clear()
```

- [ ] **Step 2: failing test를 실행해 RED를 확인한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_service.py::test_openai_embedding_client_is_reused_without_exposing_the_key --timeout=30 -p no:cacheprovider
```

Expected: `AttributeError: module ... has no attribute '_openai_embedding_client'`.

- [ ] **Step 3: cached client factory와 기존 embedding 호출의 최소 변경을 작성한다.**

`_openai_embedding()` 바로 앞에 아래 helper를 추가하고, 기존 client 생성 block을 helper 호출로 바꾼다.

```python
@lru_cache(maxsize=1)
def _openai_embedding_client() -> Any:
    api_key = _text(_setting("LEGAL_RAG_OPENAI_API_KEY", "")) or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("openai_api_key_required")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai_sdk_unavailable") from exc
    timeout = _int_setting("LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS", 12)
    return OpenAI(api_key=api_key, timeout=timeout, base_url="https://api.openai.com/v1")


def _openai_embedding(query: str, *, model_id: str, dimensions: int) -> list[float]:
    kwargs: dict[str, Any] = {
        "model": model_id,
        "input": query,
        "encoding_format": "float",
    }
    if dimensions > 0:
        kwargs["dimensions"] = dimensions
    response = _openai_embedding_client().embeddings.create(**kwargs)
    return _normalize_l2([float(item) for item in response.data[0].embedding])
```

- [ ] **Step 4: targeted cache tests를 GREEN으로 확인한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_service.py::test_openai_embedding_client_is_reused_without_exposing_the_key test/test_legal_rag_service.py::test_sentence_transformer_model_is_cached_per_process --timeout=30 -p no:cacheprovider
```

Expected: `2 passed`.

- [ ] **Step 5: 사용자 Git checkpoint를 준비한다.**

```powershell
git add app/services/legal_rag_service.py test/test_legal_rag_service.py
git commit -m "perf: reuse legal rag embedding client"
```

### Task 3: 안전한 phase latency artifact와 summary 집계 추가

**Files:**
- Modify: `app/services/legal_rag_service.py:207-282, 822-845`
- Modify: `etl/legal/evaluation.py:92-107, 164-217, 241-249`
- Modify: `test/test_legal_rag_service.py`
- Modify: `test/test_legal_rag_evaluation.py:81-111, 113-175`

**Interfaces:**
- Produces: pgvector response `latency_breakdown_ms: dict[str, int]` with exactly `preflight_ms`, `embedding_ms`, `vector_query_ms`, `result_mapping_ms`.
- Produces: per-backend summary `latency_breakdown_ms[phase] = {count, p50_ms, p95_ms, mean_ms}`.
- Preserves: `latency_ms` and `transition_decision()` inputs without semantic change.

- [ ] **Step 1: artifact whitelist와 summary aggregation failing tests를 작성한다.**

`test_normalize_backend_response_removes_raw_text_and_keeps_ranked_metadata`에 response field와 assertion을 추가한다.

```python
            "latency_breakdown_ms": {
                "preflight_ms": 4,
                "embedding_ms": 12,
                "vector_query_ms": -3,
                "result_mapping_ms": 2,
                "secret_like_detail": "must-not-leak",
            },
```

```python
    assert normalized["latency_breakdown_ms"] == {
        "preflight_ms": 4,
        "embedding_ms": 12,
        "vector_query_ms": 0,
        "result_mapping_ms": 2,
    }
    assert "secret_like_detail" not in repr(normalized)
```

`test_summary_calculates_recall_mrr_ndcg_latency_and_metadata`의 두 run에 각각 다음 값을 넣고, summary assertion을 추가한다.

```python
"latency_breakdown_ms": {
    "preflight_ms": 2,
    "embedding_ms": 4,
    "vector_query_ms": 3,
    "result_mapping_ms": 1,
},
```

두 번째 run에는 `preflight_ms=4`, `embedding_ms=8`, `vector_query_ms=7`, `result_mapping_ms=1`을 넣는다.

```python
    assert lexical["latency_breakdown_ms"]["embedding_ms"] == {
        "count": 2,
        "p50_ms": 4,
        "p95_ms": 8,
        "mean_ms": 6.0,
    }
    assert lexical["p95_latency_ms"] == 30
```

`test_legal_rag_service.py`에는 pgvector happy path response에 네 latency key가 모두 있고 모두 `int` 및 `>= 0`임을 확인하는 test를 추가한다.

- [ ] **Step 2: failing tests를 실행해 RED를 확인한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_evaluation.py::test_normalize_backend_response_removes_raw_text_and_keeps_ranked_metadata test/test_legal_rag_evaluation.py::test_summary_calculates_recall_mrr_ndcg_latency_and_metadata --timeout=30 -p no:cacheprovider
```

Expected: `KeyError: 'latency_breakdown_ms'`.

- [ ] **Step 3: service phase timer와 evaluator whitelist/aggregation을 구현한다.**

`app/services/legal_rag_service.py`에 constants와 helper를 추가한다.

```python
LATENCY_BREAKDOWN_KEYS = (
    "preflight_ms",
    "embedding_ms",
    "vector_query_ms",
    "result_mapping_ms",
)


def _empty_latency_breakdown() -> dict[str, int]:
    return {key: 0 for key in LATENCY_BREAKDOWN_KEYS}


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))
```

In `_search_pgvector()`, initialize `latency_breakdown = _empty_latency_breakdown()`. Time the existing preflight block, `_build_query_embedding()` plus `_validate_query_embedding_space()`, `_query_pgvector_rows()`, and `[_pgvector_row_result(row) for row in rows]` separately. Pass `latency_breakdown_ms=latency_breakdown` to both successful and exception `_search_response()` calls. Do not add query text, exception text, provider credentials, or arbitrary metadata to this mapping.

`etl/legal/evaluation.py`에 다음 helpers를 추가하고 `normalize_backend_response()` return object에 `latency_breakdown_ms=_normalize_latency_breakdown(response.get("latency_breakdown_ms"))`를 포함한다.

```python
LATENCY_BREAKDOWN_KEYS = (
    "preflight_ms",
    "embedding_ms",
    "vector_query_ms",
    "result_mapping_ms",
)


def _normalize_latency_breakdown(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    raw = value
    return {key: _nonnegative_int(raw.get(key)) for key in LATENCY_BREAKDOWN_KEYS}


def _summarize_latency_breakdown(runs: Sequence[Mapping[str, object]]) -> dict[str, dict[str, float | int]]:
    values_by_key = {key: [] for key in LATENCY_BREAKDOWN_KEYS}
    for run in runs:
        raw = run.get("latency_breakdown_ms")
        if isinstance(raw, Mapping):
            for key in LATENCY_BREAKDOWN_KEYS:
                if key in raw:
                    values_by_key[key].append(_nonnegative_int(raw.get(key)))
    return {
        key: {
            "count": len(values),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "mean_ms": _mean(values),
        }
        for key, values in values_by_key.items()
    }
```

Add `"latency_breakdown_ms": _summarize_latency_breakdown(runs)` to `_summarize_single_backend()` without changing any existing metric calculation or `transition_decision()`.

- [ ] **Step 4: service and evaluator telemetry tests를 GREEN으로 확인한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_service.py test/test_legal_rag_evaluation.py --timeout=30 -p no:cacheprovider
```

Expected: all selected tests pass, including existing raw-text and error sanitization tests.

- [ ] **Step 5: 사용자 Git checkpoint를 준비한다.**

```powershell
git add app/services/legal_rag_service.py etl/legal/evaluation.py test/test_legal_rag_service.py test/test_legal_rag_evaluation.py
git commit -m "feat: record safe pgvector latency phases"
```

### Task 4: 회귀 검증, 실제 A/B·RAGAS 실행, 보고서·C-1 갱신

**Files:**
- Modify after measured execution only: `docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md`
- Modify after measured execution only: `docs/ops/project-readiness-master-checklist.md`
- Local ignored only: `output/law_ingestion/evaluation/legal-ab-017-pgvector-gates-20260722/`

**Interfaces:**
- Consumes: `summary.json` with existing backend metrics, transition decision, and phase aggregates.
- Produces: evidence-backed report; never fabricates a passed gate or pgvector RAGAS aggregate.

- [ ] **Step 1: 전체 automated regression을 실행한다.**

Run:

```powershell
D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py test/test_legal_rag_service.py --timeout=30 -p no:cacheprovider --basetemp C:\tmp\issue289-regression
```

Expected: all tests pass with no failure or timeout.

- [ ] **Step 2: changed-file integrity를 확인한다.**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: whitespace error 없음; source/test/spec/plan 외의 변경 없음.

- [ ] **Step 3: 사용자에게 live OpenAI·PostgreSQL 실행 승인을 받은 뒤 preflight와 A/B·RAGAS를 실행한다.**

Run:

```powershell
C:\tmp\skn27-ragas313\Scripts\python.exe -m etl.legal.run_evaluation --env-file D:\dev\project\SKN27-FINAL-3Team-issue-282\.env.rag-eval --run-id legal-ab-017-pgvector-gates-20260722 --run-ragas
```

Expected: `summary.json`이 생성되고 public-law 20개 질의의 lexical/pgvector 결과, RAGAS status, transition decision을 포함한다. 출력에서 key·원문·context·예외 전문을 공유하지 않는다.

- [ ] **Step 4: 실행 산출물에서 정확한 gate 지표를 추출한다.**

Check:

```text
pgvector query_count = 20
pgvector completed_run_count = 20
pgvector no_result_rate = 0
pgvector p95_latency_ms <= 1413
pgvector RAGAS evaluated count = 20
pgvector RAGAS aggregate status = evaluated
transition_decision.eligible = true
```

하나라도 다르면 `eligible=false`를 유지하고 failed gate, 전체 A/B metrics, phase p50/p95/mean, RAGAS evaluated/not-evaluated counts를 보고한다.

- [ ] **Step 5: 측정값으로만 보고서와 C-1을 갱신한다.**

보고서에는 corpus snapshot, embedding/RAGAS model, 각 backend의 query/completed count, Recall@1/3/5, MRR, nDCG@5, no-result/unavailable rate, 전체 p50/p95, phase count/p50/p95/mean, RAGAS count·metrics·latency, transition gate verdict를 기록한다. C-1은 `eligible=true`일 때만 완료로 바꾸며, 그렇지 않으면 `[~]`를 유지하고 보고서 section을 연결한다.

- [ ] **Step 6: 사용자 Git handoff를 준비한다.**

```powershell
git add app/services/legal_rag_service.py etl/legal/evaluation.py test/test_legal_rag_service.py test/test_legal_rag_evaluation.py docs/tech-validation-reports/legal-rag/2026-07-22-legal-rag-ab-execution-report.md docs/ops/project-readiness-master-checklist.md docs/superpowers/specs/2026-07-22-pgvector-rag-transition-gates-design.md docs/superpowers/plans/2026-07-22-pgvector-rag-transition-gates.md
git commit -m "fix: meet pgvector legal rag transition gates"
git push origin fix/289-pgvector-rag-transition-gates
```

PR description must link `Closes #289`, list both HNSW and client-reuse changes, state all automated test counts, and copy measured gate values without keys or raw retrieval content.
