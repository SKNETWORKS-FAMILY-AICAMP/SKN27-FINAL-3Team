# 판례 RAG 전체 파이프라인 교체 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 판례 ETL과 검색 구현을 업그레이드된 수집·검증·의미 블록·4등급+씨드·NEW++-BGE 파이프라인으로 교체하되, 과실비율 에이전트가 호출하는 경로·함수·반환 형식은 변경하지 않는다.

**Architecture:** 현재 `etl/fault_cases/src/traffic_precedents` 구현은 `old` 아래에 임시 보관하고, 활성 경로에는 `precedents_test`에서 검증한 로직을 운영용 Python 패키지로 옮긴다. 파이프라인은 독립 검증을 통과한 `GENERAL_READY_DIRECT`와 검색 근거 블록이 있는 `SEED_READY`만 고정적으로 RAG 레코드로 만들고, Qwen 임베딩·적재·NEW++-BGE 검색까지 한 흐름으로 제공한다. 최초 배포는 저장소에 함께 올린 기존 4,185행 NPY와 metadata를 직접 읽어 최종 3,339행만 적재하므로 재임베딩하지 않으며, 이후 전체 재생성은 같은 저장소의 임베딩 Python으로 수행한다.

**Tech Stack:** Python 3, pytest, JSONL, NumPy float32, PostgreSQL/pgvector, Qwen/Qwen3-Embedding-4B, BAAI/bge-reranker-v2-m3

## Global Constraints

- 이번 계획의 구현 범위는 `etl/fault_cases/src/traffic_precedents/**`와 그 판례 전용 테스트·문서뿐이다.
- `etl/fault_cases/precedents_test`, `etl/fault_cases/review_case_test`, `etl/fault_cases/standard_TEST`는 참고 원본일 뿐이며 활성 코드가 import하거나 런타임 파일을 읽어서는 안 된다.
- supervisor, `etl/fault_cases/rag_runtime`, 인정기준 RAG, 심의사례 RAG는 수정하지 않는다.
- 다음 과실비율 에이전트 연결 파일은 수정하지 않는다.

```text
etl/fault_cases/src/agents/text_ml_case_search/agent.py
etl/fault_cases/src/agents/text_ml_case_search/rag/pgvector_unified_retriever.py
etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_evidence_mapper.py
```

- 활성 판례 코드는 `traffic_precedents.old`를 import하지 않는다. `old`는 임시 비교·삭제용 보관본이며 런타임 fallback이 아니다.
- legacy/backend 선택 환경변수와 구 검색 fallback 분기는 만들지 않는다.
- 이번 구현 작업에서는 실제 외부 수집, 실제 모델 임베딩, DB 생성·적재, AWS 배포를 실행하지 않는다. 해당 작업을 나중에 실행할 Python·SQL·계약과 mock 기반 테스트만 만든다.
- 최종 검색 코퍼스는 동적 플래그 판단 결과가 아니다. 아래 두 집합만 고정 사용한다.

```text
GENERAL_READY_DIRECT의 검증된 evidence_block_ids
+ 검색 근거 블록이 존재하는 SEED_READY의 검증된 evidence_block_ids
= 3,339 의미 블록 / 825 판례
```

- `GENERAL_READY_LEGAL_SUPPORT`, `GENERAL_QUARANTINE`, `GENERAL_EXCLUDED`는 최종 판례 RAG에 넣지 않는다.
- 분류 체계는 “일반 판례 4등급 + 별도 씨드”이다.

```text
SEED_READY
GENERAL_READY_DIRECT
GENERAL_READY_LEGAL_SUPPORT
GENERAL_QUARANTINE
GENERAL_EXCLUDED
```

- 검색 근거에서 다음 역할은 항상 제외한다.

```text
OTHER
PARTY_ARGUMENT
INLINE_CITATION
INSURANCE_DAMAGE_PROCEDURE
```

- 문서·질문 임베딩 모델은 `Qwen/Qwen3-Embedding-4B`, revision `5cf2132abc99cad020ac570b19d031efec650f2b`, 2,560차원, float32, L2 정규화로 고정한다.
- 리랭커는 `BAAI/bge-reranker-v2-m3`, revision `324cc40576b08b305b9c65a867c26c173a477ae2`, max length 2048로 고정한다.

## 확정 파이프라인

```text
수집
→ 수집 검증
→ 전처리·중복 제거
→ 의미 블록 생성
→ 일반 판례 4등급 + 씨드 분류
→ 독립 검증
→ 검증된 근거 블록 선별(1등급 DIRECT + eligible SEED 고정)
→ RAG용 레코드 생성
→ 임베딩
→ 적재
```

`run_pipeline.py`는 다음 stage를 제공한다.

```text
collect
validate-collection
preprocess
semantic-blocks
classify
validate-classification
build-rag-records
embed
load
all
```

`all`은 위 순서 전체를 의미한다. 최초 배포에서는 `embed`를 실행하지 않고 저장소의 NPY+metadata 두 파일을 `load`에 직접 전달할 수 있어야 한다.

## 실제 에이전트 연결 계약

과실비율 에이전트는 현재 다음 함수를 직접 호출한다.

```python
from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever import (
    search_query as search_fault_ratio_precedent_pgvector,
)

rows = search_fault_ratio_precedent_pgvector("fault_ratio", selected_text, top_k)
```

따라서 신형 검색은 반드시 같은 위치와 시그니처로 제공한다.

```text
search_query(
    dataset: str,
    query: str,
    top_k: int | None = None
) -> list[dict[str, Any]]
```

각 반환 row에는 최소한 다음 키가 있어야 한다.

```text
case_id
case_number
chunk_id
chunk_index
chunk_type
chunk_strategy
case_name
court_name
decision_date
chunk_text
search_text
cosine_similarity
rank
metadata
```

NEW++의 `rerank_score`, 후보 순위, 모델 버전은 `metadata`에 추가한다. 기존 에이전트 연결부와 evidence mapper는 수정하지 않는다.

## 목표 파일 구조

```text
etl/fault_cases/src/traffic_precedents/
├─ old/                              # 기존 구현 임시 보관, 활성 import 금지
├─ collection/
│  ├─ seed/
│  ├─ general/
│  └─ validate.py
├─ preprocessing/
├─ semantic_blocks/
├─ classification/
│  ├─ classifier.py
│  ├─ validator.py
│  └─ contracts.py
├─ rag_records/
│  ├─ builder.py
│  ├─ validator.py
│  └─ contracts.py
├─ precedent_embedding/
│  ├─ qwen_embedder.py
│  ├─ build_bootstrap.py
│  ├─ archive.py
│  └─ validate_archive.py
├─ precedent_db_loading/
│  ├─ schema.sql
│  ├─ loader.py
│  └─ validate_loaded.py
├─ precedent_search/
│  ├─ newplusplus/
│  │  ├─ query_embedder.py
│  │  ├─ candidate_retriever.py
│  │  ├─ case_context_builder.py
│  │  ├─ bge_reranker.py
│  │  ├─ result_adapter.py
│  │  └─ search_service.py
│  └─ pgvector/
│     └─ retriever.py                # 기존 public import 경로 유지
├─ tests/
├─ config.py
├─ contracts.py
└─ run_pipeline.py
```

---

### Task 1: 기존 판례 구현을 `old`로 보관하고 변경 금지 계약 고정

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/old/README.md`
- Move: 현재 `etl/fault_cases/src/traffic_precedents/run_pipeline.py`
- Move: 현재 `etl/fault_cases/src/traffic_precedents/traffic_precedents_*`
- Move: 현재 `etl/fault_cases/src/traffic_precedents/precedent_chunking`
- Move: 현재 `etl/fault_cases/src/traffic_precedents/precedent_embedding`
- Move: 현재 `etl/fault_cases/src/traffic_precedents/precedent_db_loading`
- Keep active until Task 8: 현재 `etl/fault_cases/src/traffic_precedents/precedent_search`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_agent_connection_contract.py`
- Do not modify: `etl/fault_cases/src/agents/text_ml_case_search/agent.py`
- Do not modify: `etl/fault_cases/src/agents/text_ml_case_search/rag/pgvector_unified_retriever.py`
- Do not modify: `etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_evidence_mapper.py`

**Interfaces:**
- Consumes: 현재 추적 중인 구 판례 ETL·검색 코드.
- Produces: 삭제하기 쉬운 구 코드 보관본과 신형 코드가 지켜야 할 연결 계약 테스트.

- [ ] **Step 1: 수정 금지 파일의 SHA-256을 작업 기록에 남긴다**

```powershell
Get-FileHash -Algorithm SHA256 `
  etl/fault_cases/src/agents/text_ml_case_search/agent.py,`
  etl/fault_cases/src/agents/text_ml_case_search/rag/pgvector_unified_retriever.py,`
  etl/fault_cases/src/agents/text_ml_case_search/rag/fault_ratio_precedent_evidence_mapper.py
```

- [ ] **Step 2: 구 ETL·임베딩·적재 구현을 `git mv`로 `old` 아래에 옮긴다**

생성 JSONL, NPY, ZIP, tar.gz, 캐시, `__pycache__`는 보관 대상에서 제외한다. 기존 `precedent_search`는 public import 단절을 막기 위해 Task 8까지 활성 위치에 두고, Task 8에서 구 검색 보관과 신 검색 생성을 같은 커밋으로 처리한다. `old/README.md`에는 “임시 비교용, 활성 import 금지, 교체 검증 후 삭제 가능”을 명시한다.

- [ ] **Step 3: 기존 public 함수 계약을 테스트로 고정한다**

```python
import inspect

from etl.fault_cases.src.traffic_precedents.precedent_search.pgvector.retriever import (
    search_query,
)


def test_search_query_signature_is_stable():
    assert list(inspect.signature(search_query).parameters) == [
        "dataset",
        "query",
        "top_k",
    ]
```

- [ ] **Step 4: 필수 row 키 계약을 테스트에 고정한다**

```python
REQUIRED_ROW_KEYS = {
    "case_id", "case_number", "chunk_id", "chunk_index", "chunk_type",
    "chunk_strategy", "case_name", "court_name", "decision_date",
    "chunk_text", "search_text", "cosine_similarity", "rank", "metadata",
}
```

- [ ] **Step 5: 활성 코드가 `old`를 import하지 않는 테스트를 추가한다**

```python
def test_active_code_does_not_import_old():
    active_root = Path(__file__).parents[1]
    for path in active_root.rglob("*.py"):
        if "old" in path.parts or "tests" in path.parts:
            continue
        assert "traffic_precedents.old" not in path.read_text(encoding="utf-8")
```

- [ ] **Step 6: public import와 무의존성 계약 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_agent_connection_contract.py -q
```

- [ ] **Step 7: 보관 작업을 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "refactor: archive legacy precedent pipeline"
```

---

### Task 2: 수집과 수집 검증을 운영용 패키지로 승격

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/config.py`
- Create: `etl/fault_cases/src/traffic_precedents/contracts.py`
- Create: `etl/fault_cases/src/traffic_precedents/collection/seed/`
- Create: `etl/fault_cases/src/traffic_precedents/collection/general/`
- Create: `etl/fault_cases/src/traffic_precedents/collection/validate.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_seed_collection.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_general_collection.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_collection_validation.py`

**Source references to promote, never import:**
- `etl/fault_cases/precedents_test/01_seed_precedents/src/precedents_seed/*.py`
- `etl/fault_cases/precedents_test/01_seed_precedents/run_seed_collection.py`
- `etl/fault_cases/precedents_test/02_general_collection/src/general_collection/*.py`
- `etl/fault_cases/precedents_test/02_general_collection/run_general_collection.py`
- `etl/fault_cases/precedents_test/02_general_collection/retry_empty_details.py`
- `etl/fault_cases/precedents_test/02_general_collection/validate_general_collection.py`

**Interfaces:**
- Consumes: 씨드 레지스트리, 법령 API 입력, 일반 판례 검색 조건.
- Produces: `collected_seed.jsonl`, `collected_general.jsonl`, `collection_validation.json`.

- [ ] **Step 1: 경로를 모두 실행 인자로 받는 설정 계약을 만든다**

```python
@dataclass(frozen=True)
class PipelinePaths:
    work_dir: Path
    input_dir: Path
    output_dir: Path
```

하드코딩된 `precedents_test`, `99_runtime_data`, 개인 절대경로를 허용하지 않는다.

- [ ] **Step 2: 씨드 수집의 사건번호 정규화·레지스트리·API 응답 테스트를 먼저 옮긴다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_seed_collection.py -q
```

Expected: 운영 패키지 구현 전 import 실패.

- [ ] **Step 3: 씨드 수집 코드를 운영 패키지로 옮겨 테스트를 통과시킨다**

씨드 레코드는 `record_id`, 사건번호, 사건명, 법원명, 선고일자, 원문, 수집 출처를 보존한다.

- [ ] **Step 4: 일반 수집·빈 상세 재시도 테스트를 옮긴 뒤 구현을 승격한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_general_collection.py -q
```

- [ ] **Step 5: 수집 검증을 별도 stage로 만든다**

검증 항목은 JSONL 파싱, `record_id` 존재·유일성, 필수 본문, 수집 실패·빈 상세 목록, 씨드와 일반 판례 간 ID 충돌이다. 실패 보고서가 있으면 후속 stage를 중단한다.

- [ ] **Step 6: 테스트 폴더 의존성이 없는지 검사한다**

```powershell
rg -n "precedents_test|review_case_test|standard_TEST|99_runtime_data" `
  etl/fault_cases/src/traffic_precedents/collection `
  etl/fault_cases/src/traffic_precedents/config.py
```

Expected: 출력 없음.

- [ ] **Step 7: 수집 단계를 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "feat: add upgraded precedent collection stages"
```

---

### Task 3: 전처리·중복 제거와 의미 블록 생성 승격

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/preprocessing/cleaner.py`
- Create: `etl/fault_cases/src/traffic_precedents/preprocessing/merger.py`
- Create: `etl/fault_cases/src/traffic_precedents/preprocessing/run.py`
- Create: `etl/fault_cases/src/traffic_precedents/semantic_blocks/parser.py`
- Create: `etl/fault_cases/src/traffic_precedents/semantic_blocks/run.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_preprocessing.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_semantic_blocks.py`

**Source references to promote, never import:**
- `etl/fault_cases/precedents_test/03_preprocessing/src/preprocessing/*.py`
- `etl/fault_cases/precedents_test/03_preprocessing/run_preprocessing.py`
- `etl/fault_cases/precedents_test/04_semantic_blocks/src/semantic_blocks/*.py`
- `etl/fault_cases/precedents_test/04_semantic_blocks/run_semantic_blocks.py`

**Interfaces:**
- Consumes: 수집 검증을 통과한 씨드·일반 판례 JSONL.
- Produces: `preprocessed_cases.jsonl`, `duplicate_report.json`, `semantic_blocks.jsonl`, stage manifest.

- [ ] **Step 1: 전처리 불변 조건 테스트를 작성한다**

```python
def test_preprocessing_keeps_one_case_per_record_id(rows):
    ids = [row["record_id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert all(row["full_text"].strip() for row in rows)
```

- [ ] **Step 2: cleaner·merger를 승격하고 씨드 우선 중복 제거를 고정한다**

같은 `record_id`가 씨드와 일반 수집에 모두 있으면 씨드 provenance를 보존하면서 본문은 하나만 남긴다. 원문 ID와 사건 메타데이터를 변경하지 않는다.

- [ ] **Step 3: 의미 블록 계약 테스트를 작성한다**

```python
def test_semantic_block_contract(block):
    assert block["block_id"]
    assert block["record_id"]
    assert block["semantic_role"]
    assert block["speaker_role"]
    assert block["source_scope"]
    assert block["text"].strip()
    assert 0 <= block["start_offset"] <= block["end_offset"]
```

- [ ] **Step 4: 의미 블록 parser를 승격하고 offset 원문 일치 검증을 포함한다**

각 블록은 `full_text[start_offset:end_offset]`와 `text`가 일치해야 한다. `block_id`는 전체 출력에서 유일해야 한다.

- [ ] **Step 5: 두 stage 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_preprocessing.py `
  etl/fault_cases/src/traffic_precedents/tests/test_semantic_blocks.py -q
```

- [ ] **Step 6: 전처리·의미 블록 단계를 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "feat: add precedent preprocessing and semantic blocks"
```

---

### Task 4: 일반 판례 4등급 + 씨드 분류와 독립 검증 승격

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/classification/contracts.py`
- Create: `etl/fault_cases/src/traffic_precedents/classification/classifier.py`
- Create: `etl/fault_cases/src/traffic_precedents/classification/validator.py`
- Create: `etl/fault_cases/src/traffic_precedents/classification/run_classification.py`
- Create: `etl/fault_cases/src/traffic_precedents/classification/run_validation.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_classification.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_classification_validation.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_evidence_gates.py`

**Source references to promote, never import:**
- `etl/fault_cases/precedents_test/05_classification_validation/classifier.py`
- `etl/fault_cases/precedents_test/05_classification_validation/validator.py`
- `etl/fault_cases/precedents_test/05_classification_validation/run_classification.py`
- `etl/fault_cases/precedents_test/91_tests/05_classification_validation/test_evidence_gates.py`

**Interfaces:**
- Consumes: 전처리 판례와 의미 블록.
- Produces: `classification_candidates.jsonl`, `validated_classifications.jsonl`, 검증 보고서.

- [ ] **Step 1: 등급 enum을 정확히 고정한다**

```python
class PrecedentGrade(str, Enum):
    SEED_READY = "SEED_READY"
    GENERAL_READY_DIRECT = "GENERAL_READY_DIRECT"
    GENERAL_READY_LEGAL_SUPPORT = "GENERAL_READY_LEGAL_SUPPORT"
    GENERAL_QUARANTINE = "GENERAL_QUARANTINE"
    GENERAL_EXCLUDED = "GENERAL_EXCLUDED"
```

- [ ] **Step 2: 분류기 테스트를 작성하고 기존 검증 로직을 운영 코드로 승격한다**

분류기는 `internal_grade`, `evidence_block_ids`, `reason_codes`, `classifier_version`, `source_route`를 출력한다. 씨드 입력은 일반 4등급으로 재분류하지 않고 `SEED_READY` 경로를 유지한다.

- [ ] **Step 3: 독립 validator를 별도 실행 파일로 승격한다**

validator는 분류기의 결론을 그대로 신뢰하지 않고, 원본 판례·전체 의미 블록·선정 evidence ID를 다시 대조한다. 결과에는 `validation.status`, `validator_version`, 실패 사유가 있어야 한다.

- [ ] **Step 4: 검증 실패가 다음 단계로 전달되지 않는 테스트를 작성한다**

```python
def test_only_independently_validated_rows_are_released(validated_rows):
    assert all(row["validation"]["status"] == "PASSED" for row in validated_rows)
```

- [ ] **Step 5: 분류와 독립 검증 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_classification.py `
  etl/fault_cases/src/traffic_precedents/tests/test_classification_validation.py `
  etl/fault_cases/src/traffic_precedents/tests/test_evidence_gates.py -q
```

- [ ] **Step 6: 분류·검증 단계를 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "feat: add validated precedent grade pipeline"
```

---

### Task 5: 1등급 DIRECT + eligible SEED만 RAG 레코드로 생성

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/rag_records/contracts.py`
- Create: `etl/fault_cases/src/traffic_precedents/rag_records/builder.py`
- Create: `etl/fault_cases/src/traffic_precedents/rag_records/validator.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_rag_record_builder.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_rag_record_validation.py`

**Source reference to promote, never import:**
- `etl/fault_cases/precedents_test/05_classification_validation/build_grade_outputs.py`

**Interfaces:**
- Consumes: `preprocessed_cases.jsonl`, `semantic_blocks.jsonl`, `validated_classifications.jsonl`.
- Produces: `precedent_newplusplus_retrieval_blocks.jsonl`, `rag_record_report.json`, `rag_record_manifest.json`.

- [ ] **Step 1: 고정 선별 규칙의 실패 테스트를 작성한다**

```python
ALLOWED_GRADES = {"GENERAL_READY_DIRECT", "SEED_READY"}
FORBIDDEN_ROLES = {
    "OTHER", "PARTY_ARGUMENT", "INLINE_CITATION",
    "INSURANCE_DAMAGE_PROCEDURE",
}


def test_final_records_have_only_fixed_grades(records):
    assert {row["internal_grade"] for row in records} <= ALLOWED_GRADES
    assert not ({row["semantic_role"] for row in records} & FORBIDDEN_ROLES)
```

- [ ] **Step 2: “사용 여부 결정” 없이 고정 선별기를 구현한다**

선별기는 다음 순서만 수행한다.

```text
validation.status == PASSED 확인
→ internal_grade가 GENERAL_READY_DIRECT 또는 SEED_READY인지 확인
→ 해당 판례의 evidence_block_ids만 펼치기
→ is_valid_evidence == true 확인
→ 금지 semantic_role 제거
→ 판례 메타데이터를 블록에 결합
```

`GENERAL_READY_LEGAL_SUPPORT`를 포함하는 별도 법리검색 입력은 생성하지 않는다.

- [ ] **Step 3: RAG 레코드 필드 계약을 고정한다**

```text
retrieval_document_id = block_id
record_id
block_id
block_type
semantic_role
text
start_offset
end_offset
internal_grade
validator_status
case_number
case_name
court_name
decision_date
classifier_version
validator_version
```

- [ ] **Step 4: 완전성 validator를 구현한다**

validator는 ID 유일성, 사건-블록 join, 원문 offset, evidence ID 누락, 금지 역할, DIRECT 무벡터 후보를 검사한다. 현재 확정 데이터에서는 다음 수치를 release gate로 사용한다.

```text
GENERAL_READY_DIRECT: 3,109블록 / 768판례
eligible SEED_READY:    230블록 / 57판례
최종 합계:            3,339블록 / 825판례
```

전체 `SEED_READY` 59판례 중 검색 근거 블록이 없는 2판례는 오류가 아니라 non-eligible로 보고서에 기록한다.

- [ ] **Step 5: builder·validator 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_rag_record_builder.py `
  etl/fault_cases/src/traffic_precedents/tests/test_rag_record_validation.py -q
```

- [ ] **Step 6: RAG 레코드 단계를 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "feat: build fixed precedent retrieval records"
```

---

### Task 6: Git 추적용 임베딩 파일 쌍과 이후 재생성용 임베딩 Python 제공

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/precedent_embedding/qwen_embedder.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_embedding/archive.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_embedding/build_bootstrap.py`
- Create: `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/README.md`
- Copy unchanged: `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy`
- Copy unchanged: `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_embedding_contract.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_bootstrap_archive.py`

**Interfaces:**
- Consumes for normal runs: `precedent_newplusplus_retrieval_blocks.jsonl`.
- Consumes for initial load: Git에 저장된 기존 Qwen 문서 벡터 NPY와 metadata.
- Produces: 배포 담당자가 재임베딩 없이 직접 적재할 수 있는 파일 쌍과 loader.

- [ ] **Step 1: 임베딩 결과 계약 테스트를 작성한다**

```python
def test_embedding_matrix_contract(matrix, records):
    assert matrix.shape == (len(records), 2560)
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-4)
```

- [ ] **Step 2: 이후 전체 파이프라인에서 사용할 Qwen 임베딩 Python을 승격한다**

`qwen_embedder.py`는 RAG 레코드 순서를 그대로 유지하여 2,560차원 float32 정규화 벡터를 생성한다. 모델 ID와 revision이 다르면 실행을 거부하고, batching·device·output 경로는 CLI 인자로 받는다.

- [ ] **Step 3: 최초 적재용 두 파일을 재임베딩 없이 Git 추적 폴더에 복사한다**

검증된 canonical 입력은 ZIP이 아니라 현재 프로젝트에 이미 추출되어 있는 다음 두 파일이다.

```text
현재 프로젝트 canonical source:
etl/fault_cases/precedents_test/99_runtime_data/03_output/07_qwen_embeddings/
run_20260729_precedent30_v4/01_extracted/01_document_embeddings_qwen3_4b.npy

etl/fault_cases/precedents_test/99_runtime_data/03_output/07_qwen_embeddings/
run_20260729_precedent30_v4/01_extracted/02_document_embedding_metadata.jsonl

원본 문서 행렬: 4,185 × 2,560 float32
원본 고유 판례: 1,221
원본 NPY SHA-256:
bc4bc1146b76784f2ba95f9287e7f1b8d0280e41fa249d0154c94789d453126c
원본 metadata SHA-256:
ab6ab0bedafd3152f9b5ee668b503c35d28288e0c6b421e872866b2f014ff9ff
```

백업 프로젝트의 동일 경로에도 같은 두 파일이 있으며 2026-07-30 확인 결과 크기와 SHA-256이 모두 동일하다. 현재 프로젝트 파일을 `etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/`에 원본 그대로 복사한다. 이 경로는 `.gitignore`된 `etl/fault_cases/artifacts/`와 분리되어 Git에서 추적되어야 한다.

loader는 Git에 저장된 두 파일의 해시·shape·행 정렬을 확인한 뒤 metadata의 `enabled_in_general_accident_search=true`인 행만 선택한다. 이 플래그는 기존 4,185행에서 확정된 3,339행을 고르는 bootstrap 입력 계약이며, 적재 후 운영 DB에는 DIRECT+eligible SEED만 존재한다.

```text
etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/
├─ README.md
├─ 01_document_embeddings_qwen3_4b.npy
└─ 02_document_embedding_metadata.jsonl
```

- [ ] **Step 4: 두 파일의 Git 추적 가능 여부와 직접 적재 dry-run을 검증한다**

```powershell
git check-ignore `
  etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy `
  etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl

python -m etl.fault_cases.src.traffic_precedents.precedent_db_loading.run `
  --embeddings etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy `
  --metadata etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl
```

`git check-ignore`는 아무 경로도 출력하지 않아야 하고 dry-run은 3,339블록/825판례여야 한다.

- [ ] **Step 5: mock 소형 fixture로 행 선택·해시 검증 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_embedding_contract.py `
  etl/fault_cases/src/traffic_precedents/tests/test_bootstrap_archive.py -q
```

이 단계의 구현 세션에서는 실제 4,185행 파일을 다시 임베딩하지 않는다. 두 파일은 모델 설치 파일이 아니라 초기 DB 적재 데이터다.

- [ ] **Step 6: 임베딩 코드와 두 bootstrap 파일을 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents etl/fault_cases/bootstrap
git commit -m "feat: add tracked precedent embedding bootstrap"
```

---

### Task 7: 적재 Python과 판례 전용 스키마 계약 제공

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/schema.sql`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/loader.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_db_loading/validate_loaded.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_loader.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_schema_contract.py`

**Interfaces:**
- Consumes: Git에 저장된 `01_document_embeddings_qwen3_4b.npy`와 `02_document_embedding_metadata.jsonl`.
- Produces when later executed: 판례 전용 테이블의 3,339개 의미 블록과 Qwen 벡터.

- [ ] **Step 1: 기존 법률 DB 안의 판례 전용 schema/table 계약을 테스트로 고정한다**

```python
def test_schema_uses_precedent_namespace():
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "vector(2560)" in sql
    assert "record_id" in sql
    assert "block_id" in sql
```

새 DB 컨테이너를 만들지 않는다. 같은 PostgreSQL 인스턴스를 사용하더라도 판례 데이터는 별도 schema/table로 분리한다.

- [ ] **Step 2: NPY+metadata validator를 먼저 호출하는 loader를 작성한다**

loader는 압축 파일 해시, manifest, JSONL-NPY 행 정렬을 검증한 후 transaction 안에서 적재한다. 검증 실패 시 DDL/DML을 수행하지 않는다.

- [ ] **Step 3: 적재 행을 최종 3,339개로 제한한다**

loader는 metadata에서 `enabled_in_general_accident_search=true`인 행만 고르고, 결과가 DIRECT+eligible SEED 3,339행/825판례인지 검증한다. 선택 결과에 `GENERAL_READY_LEGAL_SUPPORT`, quarantine, excluded 행이 있으면 적재를 거부한다.

- [ ] **Step 4: idempotent 적재와 사후 검증을 테스트한다**

```text
block_id unique
record_id count = 825
block count = 3,339
embedding dimension = 2,560
model/revision exact match
transaction rollback on mismatch
```

- [ ] **Step 5: mock DB로 loader 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_loader.py `
  etl/fault_cases/src/traffic_precedents/tests/test_schema_contract.py -q
```

실제 PostgreSQL 연결, schema 생성, 데이터 적재는 이 구현 세션에서 수행하지 않는다.

- [ ] **Step 6: 적재 코드를 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "feat: add precedent embedding pair loader"
```

---

### Task 8: 기존 `search_query` 내부를 NEW++-BGE로 교체

**Files:**
- Move: 기존 `etl/fault_cases/src/traffic_precedents/precedent_search` → `etl/fault_cases/src/traffic_precedents/old/precedent_search`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/query_embedder.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/candidate_retriever.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/case_context_builder.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/bge_reranker.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/result_adapter.py`
- Create: `etl/fault_cases/src/traffic_precedents/precedent_search/newplusplus/search_service.py`
- Create/Replace: `etl/fault_cases/src/traffic_precedents/precedent_search/pgvector/retriever.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_newplusplus_search.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_result_adapter.py`

**Source references to promote, never import:**
- `etl/fault_cases/precedents_test/07_rag_search/30_newplusplus_service/*.py`
- `etl/fault_cases/precedents_test/91_tests/11_newplusplus_service/*.py`

**Interfaces:**
- Consumes: `search_query("fault_ratio", query, top_k)`.
- Produces: 기존 과실비율 evidence mapper가 그대로 읽는 `list[dict]`.

- [ ] **Step 1: 구 검색을 보관하고 같은 작업 안에서 public package 뼈대를 즉시 다시 만든다**

기존 `precedent_search`를 `old/precedent_search`로 `git mv`한 뒤, 활성 위치에 `precedent_search/__init__.py`, `precedent_search/pgvector/__init__.py`, `precedent_search/pgvector/retriever.py`를 바로 생성한다. 이 Task가 끝날 때 public import는 항상 가능해야 한다.

- [ ] **Step 2: NEW++ 흐름을 테스트로 고정한다**

```text
질문 Qwen 임베딩(2,560)
→ 최종 3,339 의미 블록 exact cosine
→ 판례별 최고 점수 블록 1개
→ 고유 판례 Top 200
→ ACCIDENT_FACT + FAULT_DECISION 문맥 구성
→ BGE로 200건 재정렬
→ 요청 top_k 반환
```

- [ ] **Step 3: query embedder를 단일 로드 구조로 승격한다**

질문 벡터는 문서와 같은 모델·revision·차원·정규화를 사용한다. 테스트에서는 모델을 mock하고 실제 가중치를 다운로드하지 않는다.

- [ ] **Step 4: candidate retriever를 최종 테이블 기준으로 작성한다**

최종 테이블에는 이미 DIRECT+eligible SEED만 있으므로 별도 등급/검색 사용 플래그 분기를 두지 않는다. 동점은 cosine score, `record_id`, `block_id` 순으로 결정적으로 정렬한다.

- [ ] **Step 5: 판례별 BGE 문맥 생성기를 승격한다**

같은 `record_id`의 `ACCIDENT_FACT`와 `FAULT_DECISION`을 우선 결합하며, 길이는 BGE max length 2048 계약에 맞춘다. 인용문·당사자 주장·보험 절차 블록은 코퍼스에 없다는 전제를 validator로 확인한다.

- [ ] **Step 6: BGE 리랭커와 결정적 정렬을 승격한다**

```text
rerank_score DESC
→ candidate_rank ASC
→ record_id ASC
```

- [ ] **Step 7: 기존 에이전트 row adapter를 구현한다**

```python
def to_agent_row(case: RankedCase, rank: int) -> dict[str, Any]:
    return {
        "case_id": case.record_id,
        "case_number": case.case_number,
        "chunk_id": case.candidate_block_id,
        "chunk_index": rank,
        "chunk_type": case.candidate_block_type,
        "chunk_strategy": "semantic_newplusplus_bge",
        "case_name": case.case_name,
        "court_name": case.court_name,
        "decision_date": case.decision_date,
        "chunk_text": case.evidence_text,
        "search_text": case.evidence_text,
        "cosine_similarity": case.retrieval_score,
        "rank": rank,
        "metadata": {
            "rerank_score": case.rerank_score,
            "candidate_rank": case.candidate_rank,
            "score_type": "qwen_cosine_then_bge_rerank",
        },
    }
```

- [ ] **Step 8: 같은 public 경로에 `search_query`를 제공한다**

`dataset != "fault_ratio"`이면 명시적 `ValueError`를 발생시키고, 정상 호출은 NEW++ 서비스 결과를 기존 row로 변환한다. 구 검색 fallback은 두지 않는다.

- [ ] **Step 9: mock 기반 검색과 기존 연결 계약 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/traffic_precedents/tests/test_newplusplus_search.py `
  etl/fault_cases/src/traffic_precedents/tests/test_result_adapter.py `
  etl/fault_cases/src/traffic_precedents/tests/test_agent_connection_contract.py `
  etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py -q
```

- [ ] **Step 10: Task 1의 수정 금지 파일 SHA-256과 다시 비교한다**

세 파일의 해시는 모두 Task 1 기록과 같아야 한다.

- [ ] **Step 11: 검색 교체를 커밋한다**

```powershell
git add etl/fault_cases/src/traffic_precedents
git commit -m "feat: replace precedent retrieval with newplusplus bge"
```

---

### Task 9: `run_pipeline.py` 통합과 전체 인수 검증

**Files:**
- Create: `etl/fault_cases/src/traffic_precedents/run_pipeline.py`
- Create: `etl/fault_cases/src/traffic_precedents/tests/test_run_pipeline.py`
- Create: `etl/fault_cases/docs/precedent_rag_replacement_handoff.md`

**Interfaces:**
- Consumes: Tasks 2~8의 각 stage 실행 함수.
- Produces: 단일 판례 파이프라인 CLI와 실행하지 않은 외부 작업이 명확한 인수 문서.

- [ ] **Step 1: stage 순서 테스트를 작성한다**

```python
EXECUTION_STAGES = (
    "collect",
    "validate-collection",
    "preprocess",
    "semantic-blocks",
    "classify",
    "validate-classification",
    "build-rag-records",
    "embed",
    "load",
)
CLI_STAGE_CHOICES = (*EXECUTION_STAGES, "all")


def test_all_runs_the_fixed_stage_order():
    assert PIPELINE_STAGES == EXECUTION_STAGES
    assert CLI_STAGES == CLI_STAGE_CHOICES
```

- [ ] **Step 2: 단일 CLI에 각 stage를 연결한다**

`all`은 위 9개 stage를 순서대로 실행하고 하나라도 실패하면 즉시 종료한다. 각 stage는 명시적 입력·출력 경로를 받고 manifest를 다음 stage에 전달한다.

- [ ] **Step 3: Git에 저장된 임베딩 파일 쌍의 최초 적재 경로를 제공한다**

```powershell
python -m etl.fault_cases.src.traffic_precedents.run_pipeline `
  --stage load `
  --embeddings etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/01_document_embeddings_qwen3_4b.npy `
  --metadata etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/02_document_embedding_metadata.jsonl
```

이 호출은 `embed`를 실행하지 않는다. 반면 이후 전체 재구축의 `all`은 RAG 레코드 생성 뒤 저장소의 Qwen 임베딩 Python과 loader를 차례로 호출한다.

- [ ] **Step 4: 활성 코드의 테스트 폴더·old 의존성을 최종 검사한다**

```powershell
rg -n "precedents_test|review_case_test|standard_TEST|traffic_precedents\\.old|99_runtime_data" `
  etl/fault_cases/src/traffic_precedents `
  -g "*.py" `
  -g "!old/**" `
  -g "!tests/**"
```

Expected: 출력 없음.

- [ ] **Step 5: 판례 파이프라인 단위 테스트 전체를 실행한다**

```powershell
python -m pytest etl/fault_cases/src/traffic_precedents/tests -q
```

- [ ] **Step 6: 기존 과실비율 에이전트 연결 테스트를 실행한다**

```powershell
python -m pytest `
  etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py `
  etl/fault_cases/src/agents/text_ml_case_search/tests/test_fault_ratio_precedent_evidence_mapper.py -q
```

- [ ] **Step 7: 수정 금지 범위에 이번 작업 diff가 없는지 검사한다**

```powershell
git diff -- `
  backend `
  etl/fault_cases/src/agents/text_ml_case_search `
  etl/fault_cases/rag_runtime `
  etl/fault_cases/src/review_case `
  etl/fault_cases/src/fault_standard
```

Expected: 이번 판례 RAG 교체로 생긴 diff 없음.

- [ ] **Step 8: 인수 문서에 실행·비실행 범위를 기록한다**

```text
제공:
- 수집부터 적재까지의 운영용 Python
- DIRECT+eligible SEED 고정 RAG 레코드 builder
- Git에 저장된 4,185행 NPY+metadata와 3,339행 선택·적재 계약
- 이후 재생성용 Qwen 임베딩 Python
- 적재 Python과 schema 계약
- 기존 search_query 뒤의 NEW++-BGE 검색

이번 구현 세션에서 실행하지 않음:
- 실제 판례 재수집
- 실제 Qwen 문서 임베딩
- 실제 DB/schema 생성
- 실제 데이터 적재
- 실제 AWS 배포
- supervisor 또는 과실비율 에이전트 연결부 수정
```

- [ ] **Step 9: 최종 통합을 커밋한다**

```powershell
git add `
  etl/fault_cases/src/traffic_precedents `
  etl/fault_cases/docs/precedent_rag_replacement_handoff.md
git commit -m "feat: complete precedent rag replacement pipeline"
```

---

## 완료 조건

- [ ] 구 판례 코드는 `etl/fault_cases/src/traffic_precedents/old`에 모여 있고 활성 코드가 import하지 않는다.
- [ ] 세 개 test 폴더를 삭제·차단해도 새 판례 파이프라인과 검색이 import된다.
- [ ] 수집부터 적재까지 9개 stage가 `run_pipeline.py`에 연결된다.
- [ ] 분류와 독립 검증이 서로 다른 stage다.
- [ ] 최종 RAG 레코드는 `GENERAL_READY_DIRECT`와 eligible `SEED_READY`만 포함한다.
- [ ] 최종 RAG 레코드는 3,339블록/825판례 release gate를 통과한다.
- [ ] 최초 적재는 Git에 저장된 기존 Qwen NPY+metadata를 직접 사용하고 문서 재임베딩을 하지 않는다.
- [ ] 이후 재생성용 Qwen 임베딩 Python과 적재 Python이 저장소에 존재한다.
- [ ] 검색은 Qwen 후보 검색 → 판례별 Top 200 → BGE 리랭크 → Top K 흐름이다.
- [ ] 기존 `search_query(dataset, query, top_k)` import 경로·시그니처·row 계약이 유지된다.
- [ ] 과실비율 에이전트 연결 파일, supervisor, `rag_runtime`, 인정기준, 심의사례 코드는 수정되지 않는다.
- [ ] 실제 외부 수집·임베딩·DB 생성·적재·AWS 배포는 이 구현 세션에서 실행되지 않는다.
