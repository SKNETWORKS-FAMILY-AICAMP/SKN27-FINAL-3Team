# Review Case RAG Direct Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DEV의 기존 심의사례 RAG에 BGE-v2-M3 리랭커를 도입하여, 기존 Qwen 검색 후보 중 결정 과실비율이 포함된 고유 심의사례 최대 5개를 반환한다.

**Architecture:** 기존 `review_case_db.rag_qwen4`와 Qwen3-Embedding-4B 검색 로직은 변경하지 않는다. 현재 Qwen 검색기가 고유 심의사례 5개를 고른 뒤 BGE-v2-M3가 같은 5개의 순서만 재정렬하며, DB·임베딩·적재·인덱스에는 어떠한 쓰기도 수행하지 않는다. 기존 구현을 선택하는 legacy/shadow 분기는 만들지 않고 새 리랭커 Runtime으로 직접 교체하며, 코드 롤백은 Git revert로 수행한다.

**Tech Stack:** Python 3.13, pytest, PostgreSQL/pgvector, Qwen3-Embedding-4B, sentence-transformers CrossEncoder, BAAI/bge-reranker-v2-m3.

## Implementation Status (2026-07-30)

- 심의사례 Runtime 교체 코드와 활성 회귀 테스트 구현 완료.
- 활성 심의사례 테스트 20개 및 전체 `rag_runtime` 관련 회귀 테스트 43개 통과.
- Strict32 고정 계약에서 Qwen Hit@1 20/32, BGE Hit@1 24/32, BGE Recall@5 32/32를 정답 사례 ID로 재계산.
- 복사한 세 임시 폴더에 대한 활성 Runtime·테스트·requirements 의존성 없음.
- 로컬 PostgreSQL에는 `review_case_db.rag_qwen4`가 없어 운영 DB E2E는 미실행.
- 현재 AWS Pilot 백엔드는 CPU 전용 이미지와 메모리 제한을 사용하므로 GPU 운영 배포 승인은 보류한다. CUDA 이미지, 고정 CUDA PyTorch, GPU 할당, 모델 revision 로드, 100회 순차·5회 동시 호출 검증을 별도 배포 게이트로 통과해야 한다.

## Global Constraints

- 작업 범위는 `etl/fault_cases/rag_runtime/review_case`의 심의사례 검색 Runtime과 BGE 리랭커 도입으로 제한한다.
- 기존 `review_case_db.rag_qwen4`의 문서 226건, 청크 904개, Qwen 벡터 904개를 그대로 사용한다.
- DB 스키마, pgvector 인덱스, 임베딩 값, 임베딩 모델, 전처리 결과 및 적재 방식을 변경하지 않는다.
- 벡터 적재, DB migration, staging schema 생성, schema 승격, 전체·증분 임베딩 파이프라인은 이번 작업에서 제외한다.
- `review_case_test`, `standard_TEST`, `precedents_test`는 로컬 임시 참고 폴더이며 최종 Runtime·테스트·배포의 파일 의존성이 될 수 없다.
- 교체 완료 후 위 세 폴더가 없거나 Git에서 제외되어도 활성 경로의 테스트와 심의사례 RAG가 동일하게 동작해야 한다.
- `etl/fault_cases/rag_runtime/shared/qwen4_retrieval.py`의 기존 거리식, halfvec 검색, 중복 제거 및 질의 임베딩 로직을 변경하지 않는다.
- `text_ml_case_search` 통합 검색기, 판례, 인정기준, 최종 답변 생성 코드는 변경하지 않는다.
- Qwen은 기존 방식으로 후보 청크 200개를 조회한 뒤 고유 심의사례 5개를 선택한다.
- BGE는 Qwen이 선택한 동일한 5개의 순서만 변경하며 사례를 추가하거나 제거하지 않는다.
- BGE 입력은 평가에 사용된 전체 심의사례 문맥을 사용하되 DB 읽기만 수행한다.
- 반환 evidence는 최대 5개이며 `review_case_id`, `decision_fault_ratio`, 사례 근거 본문을 포함한다.
- `decision_fault_ratio`는 검색된 기존 심의사례의 결정 비율이며 사용자 사고의 새 과실비율 계산값이 아니다.
- `calculation_result`는 항상 `None`이다.
- BGE 장애 시 Qwen Top-5 순서를 그대로 반환하고 `status="partial"`로 표시한다.
- Qwen 또는 DB 장애 시 `status="failed"`와 빈 evidence를 반환한다.
- BGE를 끄고 기존 구현을 선택하는 feature flag, legacy 분기 또는 shadow 경로를 추가하지 않는다.
- 평가 데이터, DB 비밀번호, 연결 문자열 및 원본 예외 메시지를 API 결과나 로그에 노출하지 않는다.
- 코드 복구는 배포된 교체 커밋의 `git revert`와 재배포로 수행하며 DB는 변경하지 않는다.

---

## File Map

### Modify

- `etl/fault_cases/rag_runtime/review_case/config.py` — 고정 Top-K와 BGE 모델·GPU 설정.
- `etl/fault_cases/rag_runtime/review_case/retriever.py` — 기존 Qwen Top-5를 받아 BGE 재정렬 후 evidence 생성.
- `etl/fault_cases/rag_runtime/review_case/service.py` — 기존 공개 진입점과 반환 계약 유지.
- `etl/fault_cases/rag_runtime/shared/qwen4_retrieval.py` — 전체 사례 문맥을 읽는 조회 전용 함수만 추가.

### Create

- `etl/fault_cases/rag_runtime/review_case/reranker.py` — BGE 모델 수명주기, 점수 계산, 안정적 정렬 및 실패 fallback.
- `etl/fault_cases/rag_runtime/review_case/context_builder.py` — 사례 청크를 평가와 동일한 전체 사례 문맥으로 조합.
- `etl/fault_cases/rag_runtime/review_case/tests/__init__.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_config.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_context_builder.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_reranker.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_fallback.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_service_contract.py`
- `etl/fault_cases/rag_runtime/review_case/tests/test_strict32_regression.py`
- `etl/fault_cases/rag_runtime/review_case/tests/fixtures/strict32_reranker_contract.json`
- `requirements-review-case-reranker.txt`

### Temporary local references during implementation only

- `etl/fault_cases/review_case_test/07_UPGRADE_V2/rag_runtime/review_case/`
- `etl/fault_cases/review_case_test/07_UPGRADE_V2/tests/review_case/`
- `etl/fault_cases/review_case_test/04_EVALUATION/evaluation/review_case/operational32/v1/`

Required code and the compact Strict32 contract must be promoted into the tracked active paths listed above. No final import, file read, pytest command or deployment command may reference these temporary folders.

### Explicitly do not modify

- `etl/fault_cases/src/shared_embedding/`
- `etl/fault_cases/rag_runtime/database/loaders/`
- `etl/fault_cases/rag_runtime/database/migrations/`
- `etl/fault_cases/src/agents/text_ml_case_search/`
- `etl/fault_cases/rag_runtime/precedent/`
- `etl/fault_cases/rag_runtime/fault_standard/`
- `etl/fault_cases/review_case_test/`
- `etl/fault_cases/standard_TEST/`
- `etl/fault_cases/precedents_test/`
- `ai/agents/`

---

### Task 1: Freeze the direct-replacement public contract

**Files:**
- Create: `etl/fault_cases/rag_runtime/review_case/tests/__init__.py`
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py`
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_service_contract.py`

**Interfaces:**
- Consumes: `search_review_case(request: RagRequest) -> DomainSearchResult`.
- Produces: `handle_request(request: RagRequest) -> DomainSearchResult`.

- [ ] **Step 1: Promote the verified V2 contract tests**

If the temporary local reference is present, compare these tests while promoting their assertions into the active Runtime test directory:

```text
etl/fault_cases/review_case_test/07_UPGRADE_V2/tests/review_case/test_retriever.py
etl/fault_cases/review_case_test/07_UPGRADE_V2/tests/review_case/test_service_contract.py
```

The tests must assert:

```python
assert result["domain"] == "review_case"
assert result["calculation_result"] is None
assert 0 < len(result["evidence"]) <= 5
assert len({row["metadata"]["review_case_id"] for row in result["evidence"]}) == len(result["evidence"])
assert all("decision_fault_ratio" in row["metadata"] for row in result["evidence"])
```

- [ ] **Step 2: Add the candidate-membership invariant**

Add a retriever test that freezes the requirement that BGE changes order only:

```python
qwen_ids = [row["metadata"]["review_case_id"] for row in qwen_rows]
result_ids = [row["metadata"]["review_case_id"] for row in result["evidence"]]

assert set(result_ids) == set(qwen_ids)
assert len(result_ids) == len(qwen_ids) == 5
```

- [ ] **Step 3: Run the contract tests and verify the current Runtime fails**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py `
  etl/fault_cases/rag_runtime/review_case/tests/test_service_contract.py `
  -p no:cacheprovider -v
```

Expected: FAIL because the current Runtime returns Qwen Top-10 and has no BGE metadata.

- [ ] **Step 4: Commit the failing contract tests**

```powershell
git add etl/fault_cases/rag_runtime/review_case/tests
git commit -m "test: freeze review case reranker contract"
```

---

### Task 2: Add the fixed BGE configuration and reranker

**Files:**
- Modify: `etl/fault_cases/rag_runtime/review_case/config.py`
- Create: `etl/fault_cases/rag_runtime/review_case/reranker.py`
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_config.py`
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_reranker.py`

**Interfaces:**
- Produces: `ReviewCaseRagConfig`.
- Produces: `rerank_candidates(query_text: str, candidates: Sequence[Candidate], *, config: ReviewCaseRagConfig, scorer: ScoreFunction | None = None) -> RerankResult`.
- Preserves: candidate membership and deterministic tie ordering.

- [ ] **Step 1: Promote and tighten the verified configuration tests**

If the temporary local reference is present, compare this V2 test while writing the tracked active test:

```text
etl/fault_cases/review_case_test/07_UPGRADE_V2/tests/review_case/test_config.py
```

Freeze these values:

```python
assert config.candidate_chunk_k == 200
assert config.unique_case_k == 5
assert config.reranker_input_k == 5
assert config.final_output_k == 5
assert config.reranker_model_name == "BAAI/bge-reranker-v2-m3"
assert config.reranker_revision == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
assert config.reranker_max_length == 4096
assert config.reranker_device == "cuda"
assert config.reranker_batch_size == 4
assert not hasattr(config, "reranker_enabled")
```

- [ ] **Step 2: Implement the fixed configuration**

Use `apply_patch` to promote `config.py` from the V2 source, then remove `reranker_enabled` and `REVIEW_CASE_RERANKER_ENABLED`. Keep only device and positive batch-size environment overrides:

```python
@dataclass(frozen=True)
class ReviewCaseRagConfig:
    candidate_chunk_k: int = 200
    unique_case_k: int = 5
    reranker_input_k: int = 5
    final_output_k: int = 5
    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"
    reranker_revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    reranker_max_length: int = 4096
    reranker_device: str = "cuda"
    reranker_batch_size: int = 4
```

- [ ] **Step 3: Promote the verified reranker tests**

If the temporary local reference is present, compare this V2 test while writing the tracked active test:

```text
etl/fault_cases/review_case_test/07_UPGRADE_V2/tests/review_case/test_reranker.py
```

Delete only the test for an explicitly disabled reranker. Retain assertions for:

```python
assert set(ranked_ids) == set(source_ids)
assert ranked_ids == ["case_b", "case_a", "case_c"]
assert result.applied is True
assert result.failure_code is None
```

- [ ] **Step 4: Promote the reranker implementation**

If the temporary local reference is present, compare it while implementing the tracked active file with `apply_patch`:

```text
etl/fault_cases/review_case_test/07_UPGRADE_V2/rag_runtime/review_case/reranker.py
```

Remove the `if not config.reranker_enabled` branch. Keep:

- a lazy, process-local `CrossEncoder` cache keyed by the frozen config;
- finite score and candidate-count validation;
- `first_stage_rank`, `first_stage_score` and `rerank_score`;
- deterministic ties by first-stage rank and stable review-case ID;
- exception fallback that retains the Qwen order.

- [ ] **Step 5: Run the configuration and reranker tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests/test_config.py `
  etl/fault_cases/rag_runtime/review_case/tests/test_reranker.py `
  -p no:cacheprovider -v
```

Expected: PASS.

- [ ] **Step 6: Commit the reranker component**

```powershell
git add `
  etl/fault_cases/rag_runtime/review_case/config.py `
  etl/fault_cases/rag_runtime/review_case/reranker.py `
  etl/fault_cases/rag_runtime/review_case/tests
git commit -m "feat: add review case bge reranker"
```

---

### Task 3: Build the evaluated full-case reranker context

**Files:**
- Modify: `etl/fault_cases/rag_runtime/shared/qwen4_retrieval.py`
- Create: `etl/fault_cases/rag_runtime/review_case/context_builder.py`
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_context_builder.py`

**Interfaces:**
- Produces: `fetch_document_chunks(corpus: str, document_ids: Sequence[str]) -> dict[str, list[dict[str, Any]]]`.
- Produces: `build_case_context(candidate: dict[str, Any], chunks: Sequence[dict[str, Any]]) -> str`.
- Does not modify: `search_by_vector`, `encode_live_query`, vector distance expressions or DB records.

- [ ] **Step 1: Write context-order and content tests**

Create tests with four ordered review-case sections:

```python
chunks = [
    {"chunk_type": "decision", "chunk_text": "결정이유와 최종비율"},
    {"chunk_type": "case_overview", "chunk_text": "사고내용과 결정비율"},
    {"chunk_type": "evidence_issue", "chunk_text": "입증자료와 주요쟁점"},
    {"chunk_type": "arguments", "chunk_text": "청구인 및 피청구인 주장"},
]

context = build_case_context(candidate, chunks)

assert context.index("[CASE_OVERVIEW]") < context.index("[ARGUMENTS]")
assert context.index("[ARGUMENTS]") < context.index("[EVIDENCE_ISSUE]")
assert context.index("[EVIDENCE_ISSUE]") < context.index("[DECISION]")
assert "최종비율" in context
```

- [ ] **Step 2: Add a read-only batch chunk fetch**

Add `fetch_document_chunks` to the shared helper. The SQL must:

```sql
SELECT
    c.document_id,
    c.chunk_id,
    c.chunk_type,
    c.chunk_text,
    c.metadata
FROM rag_qwen4.chunks AS c
WHERE c.document_id = ANY(%s)
ORDER BY c.document_id, c.chunk_index, c.chunk_id
```

The function must reject unsupported corpora, return immediately for an empty ID list, use the existing `_connect(corpus)` function and execute only the `SELECT`.

- [ ] **Step 3: Implement the context builder**

Map chunk types in this exact order:

```python
SECTION_ORDER = (
    ("case_overview", "[CASE_OVERVIEW]"),
    ("arguments", "[ARGUMENTS]"),
    ("evidence_issue", "[EVIDENCE_ISSUE]"),
    ("decision", "[DECISION]"),
)
```

If a complete section is unavailable, retain the first-stage `evidence_text` as the context rather than dropping the candidate.

- [ ] **Step 4: Run the context tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests/test_context_builder.py `
  -p no:cacheprovider -v
```

Expected: PASS and no test performs a DB write.

- [ ] **Step 5: Commit the read-only context builder**

```powershell
git add `
  etl/fault_cases/rag_runtime/shared/qwen4_retrieval.py `
  etl/fault_cases/rag_runtime/review_case/context_builder.py `
  etl/fault_cases/rag_runtime/review_case/tests/test_context_builder.py
git commit -m "feat: build review case reranker context"
```

---

### Task 4: Integrate BGE without changing Qwen candidate membership

**Files:**
- Modify: `etl/fault_cases/rag_runtime/review_case/retriever.py`
- Modify: `etl/fault_cases/rag_runtime/review_case/service.py`
- Modify: `etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py`
- Modify: `etl/fault_cases/rag_runtime/review_case/tests/test_service_contract.py`

**Interfaces:**
- Consumes: existing `search_by_vector(corpus: str, query_vector: list[float], top_k: int = 10, candidate_k: int = 200) -> list[dict[str, Any]]`.
- Consumes: `rerank_candidates`.
- Produces: maximum five evidence rows in the `DomainSearchResult` contract.

- [ ] **Step 1: Keep the existing Qwen search call unchanged except for Top-K**

The active retriever must call:

```python
rows = search_by_vector(
    "review_case",
    _resolve_vector(request),
    top_k=config.unique_case_k,
    candidate_k=config.candidate_chunk_k,
)
```

Do not add an `exact` parameter and do not change the shared Qwen SQL.

- [ ] **Step 2: Attach full-case contexts in one batch**

Fetch the five document IDs once, build a context for each row and pass those same five rows to `rerank_candidates`. Assert before and after reranking:

```python
source_ids = {str(row["document_id"]) for row in rows}
ranked_ids = {str(row["document_id"]) for row in outcome.candidates}
if ranked_ids != source_ids:
    raise RuntimeError("BGE reranker changed Qwen candidate membership")
```

- [ ] **Step 3: Preserve the result contract**

Each evidence row must include:

```python
{
    "source_type": "review_case",
    "rank": int(row["rank"]),
    "similarity_score": float(row["cosine_similarity"]),
    "retrieval_score": float(row["rerank_score"]),
    "score_type": "bge_reranker_v2_m3_raw_logit",
    "metadata": {
        "review_case_id": review_case_id,
        "decision_fault_ratio": decision_fault_ratio,
        "first_stage_rank": int(row["first_stage_rank"]),
        "first_stage_score": float(row["first_stage_score"]),
        "reranker_applied": True,
    },
}
```

Merge the existing metadata before adding the frozen keys so other review-case fields are preserved.

- [ ] **Step 4: Keep the service entry point stable**

`service.py` must remain:

```python
def handle_request(request: RagRequest) -> DomainSearchResult:
    return search_review_case(request)
```

- [ ] **Step 5: Run the integration contract tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py `
  etl/fault_cases/rag_runtime/review_case/tests/test_service_contract.py `
  -p no:cacheprovider -v
```

Expected: PASS; the returned set equals the Qwen Top-5 set and only its order may differ.

- [ ] **Step 6: Commit the Runtime integration**

```powershell
git add etl/fault_cases/rag_runtime/review_case
git commit -m "feat: rerank review case top five"
```

---

### Task 5: Preserve decision ratios and failure behavior

**Files:**
- Modify: `etl/fault_cases/rag_runtime/review_case/retriever.py`
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_fallback.py`
- Modify: `etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py`

**Interfaces:**
- Preserves: `decision_fault_ratio` for every returned case.
- Preserves: BGE failure returns Qwen Top-5 with `status="partial"`.
- Preserves: Qwen or DB failure returns no evidence with `status="failed"`.

- [ ] **Step 1: Add ratio extraction tests**

Cover both metadata shapes:

```python
assert extract_ratio({"decision_fault_ratio": "A 30 : B 70"}) == "A 30 : B 70"
assert extract_ratio({"final_ratio": "청구 20 : 피청구 80"}) == "청구 20 : 피청구 80"
```

If neither field exists, the evidence must still contain `decision_fault_ratio` with value `None`, and the result must include a limitation naming the affected `review_case_id`.

- [ ] **Step 2: Promote and adapt fallback tests**

If the temporary local reference is present, compare this verified source while writing the tracked active fallback test:

```text
etl/fault_cases/review_case_test/07_UPGRADE_V2/tests/review_case/test_fallback.py
```

Retain these assertions:

```python
assert result["status"] == "partial"
assert [row["metadata"]["review_case_id"] for row in result["evidence"]] == qwen_ids
assert all(row["metadata"]["reranker_applied"] is False for row in result["evidence"])
assert result["calculation_result"] is None
```

- [ ] **Step 3: Sanitize failures**

Map caught BGE exceptions to:

```python
failure_code = "BGE_RERANKER_UNAVAILABLE"
limitation = "BGE 리랭커를 적용하지 못해 Qwen 사례 순위를 유지했습니다."
```

Do not return exception text, credentials, paths or connection details.

- [ ] **Step 4: Run ratio and fallback tests**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests/test_retriever.py `
  etl/fault_cases/rag_runtime/review_case/tests/test_fallback.py `
  -p no:cacheprovider -v
```

Expected: PASS.

- [ ] **Step 5: Commit ratio and fallback behavior**

```powershell
git add etl/fault_cases/rag_runtime/review_case
git commit -m "fix: preserve review case ratios and fallback"
```

---

### Task 6: Pin the GPU dependency contract

**Files:**
- Create: `requirements-review-case-reranker.txt`
- Modify: deployment dependency manifest only if the active deployment image does not already install these exact packages.

**Interfaces:**
- Consumes: CUDA-compatible PyTorch supplied by the deployment image.
- Produces: a reproducible BGE runtime dependency set.

- [ ] **Step 1: Create the reranker requirements file**

```text
# CUDA-compatible PyTorch is provided by the deployment image.
sentence-transformers==5.5.1
transformers==4.57.6
huggingface-hub>=0.34.0
safetensors>=0.4.5
```

- [ ] **Step 2: Verify imports without downloading or loading a model**

```powershell
python -c "import sentence_transformers, transformers, huggingface_hub, safetensors; print('review-case-reranker-imports-ok')"
```

Expected: `review-case-reranker-imports-ok`.

- [ ] **Step 3: Commit dependency pins**

```powershell
git add requirements-review-case-reranker.txt
git commit -m "build: pin review case reranker dependencies"
```

---

### Task 7: Run read-only DB compatibility and final RAG verification

**Files:**
- No DB, loader, migration or embedding files are modified.
- Create: `etl/fault_cases/rag_runtime/review_case/tests/test_strict32_regression.py`.
- Create: `etl/fault_cases/rag_runtime/review_case/tests/fixtures/strict32_reranker_contract.json`.

**Interfaces:**
- Consumes: active `review_case_db.rag_qwen4`.
- Produces: merge approval or a failed verification gate.

- [ ] **Step 1: Verify the existing DB contract with read-only SQL**

Run against `review_case_db`:

```sql
SELECT
    (SELECT count(*) FROM rag_qwen4.documents) AS documents,
    (SELECT count(*) FROM rag_qwen4.chunks) AS chunks,
    (SELECT count(*) FROM rag_qwen4.embeddings) AS embeddings,
    (SELECT count(*) FROM rag_qwen4.embeddings
       WHERE embedding IS NULL OR vector_dims(embedding) <> 2560) AS invalid_vectors;
```

Expected:

```text
documents = 226
chunks = 904
embeddings = 904
invalid_vectors = 0
```

This step performs no `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER` or schema promotion.

- [ ] **Step 2: Run the complete review-case unit suite**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests `
  -p no:cacheprovider -v
```

Expected: all tests pass.

- [ ] **Step 3: Promote a compact Strict32 regression contract**

Before the temporary reference folders are removed, reduce the verified Strict32 result to a tracked fixture containing only:

```json
{
  "contract_version": "review_case_strict32_bge_v1",
  "query_count": 32,
  "candidate_count_per_query": 5,
  "first_stage_hit_at_1_count": 20,
  "reranker_hit_at_1_count": 24,
  "reranker_recall_at_5_count": 32,
  "queries": [
    {
      "query_id": "fault_common_q01",
      "candidates": [
        {
          "review_case_id": "review_case_2019_008384",
          "first_stage_rank": 1,
          "first_stage_score": 0.75,
          "reranker_score": 1.25,
          "expected_reranker_rank": 1
        }
      ]
    }
  ]
}
```

The actual fixture must contain all 32 query rows and all five candidates per query. It must not contain full case text, credentials, absolute paths or data from the other two copied folders.

- [ ] **Step 4: Run the tracked Strict32 regression**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests/test_strict32_regression.py `
  -p no:cacheprovider -v
```

Expected:

```text
BGE Hit@1 = 24/32 or better
BGE Recall@5 = 32/32
candidate membership equals Qwen Top-5 membership for all 32 queries
```

- [ ] **Step 5: Run GPU lifecycle tests**

After one warm-up, execute 100 sequential service calls and 5 concurrent service calls.

Expected:

```text
CUDA OOM count = 0
BGE model construction count = 1 per process
each successful result returns 5 unique review_case_id values
every evidence row contains decision_fault_ratio
BGE failure fallback success rate = 100%
```

- [ ] **Step 6: Prove the active suite has no copied-folder dependency**

```powershell
rg -n `
  "review_case_test|standard_TEST|precedents_test" `
  etl/fault_cases/rag_runtime/review_case `
  requirements-review-case-reranker.txt
```

Expected: no matches.

Run the active review-case suite without adding any copied folder to `PYTHONPATH`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime/review_case/tests `
  -p no:cacheprovider -v
```

Expected: PASS using only tracked active Runtime tests and fixtures.

- [ ] **Step 7: Run the final repository checks**

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest `
  etl/fault_cases/rag_runtime `
  -p no:cacheprovider -v

git diff --check
git status --short
```

Expected:

- Tests pass.
- `git diff --check` reports no whitespace errors.
- No loader, migration, embedding, precedent, fault-standard or integration-search files are modified.
- No tracked Runtime or test file depends on `review_case_test`, `standard_TEST` or `precedents_test`.
- The three temporary copied folders may be absent without changing the test result.

- [ ] **Step 8: Create the final replacement commit**

```powershell
git add `
  etl/fault_cases/rag_runtime/review_case `
  etl/fault_cases/rag_runtime/shared/qwen4_retrieval.py `
  requirements-review-case-reranker.txt
git commit -m "feat: replace review case rag with bge reranking"
```

- [ ] **Step 9: Roll back only if post-deployment verification fails**

```powershell
$replacementCommit = git log -1 --format=%H --grep="feat: replace review case rag with bge reranking"
git revert $replacementCommit
```

Re-run the review-case tests and redeploy the reverted commit. Do not change or rebuild `review_case_db`.

---

## Final Acceptance Checklist

- [ ] Existing `review_case_db.rag_qwen4` data and indexes were not changed.
- [ ] No loader, migration, staging, embedding pipeline or embedding artifact work was added.
- [ ] No Runtime import, file read, test command or deployment command references the three temporary copied folders.
- [ ] Active tracked tests include the compact 32-query reranker regression contract they need.
- [ ] Existing Qwen distance expression and candidate selection logic remain unchanged.
- [ ] Qwen returns five unique review cases from the existing 904 vectors.
- [ ] BGE receives exactly those five cases and only changes their order.
- [ ] Every returned evidence contains `review_case_id` and `decision_fault_ratio`.
- [ ] `decision_fault_ratio` is presented as an existing case outcome, not a new user-fault calculation.
- [ ] `calculation_result` is `None`.
- [ ] BGE failure returns the Qwen order with `status="partial"`.
- [ ] Qwen or DB failure returns empty evidence with `status="failed"`.
- [ ] No legacy, shadow, backend-selection or reranker-disable branch exists.
- [ ] Strict32 and GPU lifecycle gates pass.
- [ ] Rollback is a Git revert and does not mutate the DB.
