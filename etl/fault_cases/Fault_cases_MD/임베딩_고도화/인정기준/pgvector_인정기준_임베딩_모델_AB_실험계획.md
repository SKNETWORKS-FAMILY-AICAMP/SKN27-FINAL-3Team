# pgvector 인정기준 임베딩 모델 A/B 실험 계획

개정 기준일: 2026-07-17

> [!CAUTION]
> RunPod의 기존 **`SKN27-3T-OJH` Pod (`c7ool8ji5f17fj`)는 OJH 전용 보호 자원**이다. 인정기준 실험에서는 접속, 명령 실행, 설정 변경, 재시작, 중지, 복제, volume 연결, 종료·삭제를 포함한 어떠한 작업도 하지 않는다. 화면에 보이는 GPU나 시간당 비용은 바뀔 수 있으므로 보호 대상 식별에는 이름과 Pod ID를 함께 사용한다. 실제 로컬 모델 임베딩은 공통 계획 11.2의 Pod 선택 우선순위를 따른다. 즉 임베딩 A/B용 기존 Pod가 있으면 사용자에게 Start와 JupyterLab 열기를 요청해 재사용하고, 그런 Pod가 없고 OJH 보호 Pod만 있을 때에만 신규 공통 Pod를 만든다. 인정기준 모델 작업 채팅은 별도 Pod를 만들거나 공통 Pod를 종료하지 않는다.

> [!IMPORTANT]
> 세 코퍼스의 실제 임베딩 생성 순서, 모델별 별도 작업 채팅, batch, 병렬 허용 범위와 RunPod 소유권은 [3코퍼스 공통 임베딩 모델별 실행 계획](../pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md)을 따른다. 각 모델 작업 채팅은 공통 계획과 판례·인정기준·심의사례 계획을 모두 읽은 뒤 시작한다. 이 문서는 그중 인정기준 Rule corpus, 인정기준 adapter, 인정기준 qrels와 평가 규칙을 소유한다. Track A는 최신 6개 모델의 기본/native 차원을 비교한다.

> [!IMPORTANT]
> Track A는 6개 모델 각각에 대해 인정기준 Rule 277개와 Query 50개를 `repeat_01`, `repeat_02`, `repeat_03`에서 모두 새로 생성한다. 이전 vector 재사용은 허용하지 않으며, 인정기준 기준 6 × 3 = 18개 model-repeat 결과를 만든다.

## 1. 문서 목적

이 문서는 `fault_standard_db`에 적재된 과실비율 인정기준만을 대상으로 임베딩 모델의 Rule 검색 품질을 비교하기 위한 오프라인 A/B/n 실험 계획이다.

판례·심의사례 실험계획의 공통 원칙인 `동일 코퍼스`, `동일 query`, `동일 Ground Truth`, `모델별 기본/native 차원`, `exact cosine 우선 평가`를 재사용한다. 세 코퍼스는 동일한 공통 사용자 query 50개를 입력으로 공유하되, 인정기준의 검색 단위와 계산 구조에 맞는 `rule_id` qrels는 독립적으로 작성한다.

이번 실험의 핵심 질문은 다음 하나다.

```text
동일한 인정기준 Rule 검색 문서 277개와 동일한 공통 정식 평가 질의 50개를 사용했을 때,
어떤 임베딩 모델이 사용자의 사고 설명에 적용되는 정확한 rule_id를 가장 잘 검색하는가?
```

Vision/OCR 보강, 보험사 주장 비교, Neo4j 관계 검증, 최종 과실 계산은 임베딩 모델 선정 후 별도 후속 실험으로 분리한다.

---

## 2. 먼저 확정할 결론

### 2.1 기본 모델 A/B는 사용자 텍스트만 사용한다

서비스 입력에는 Vision, OCR, 보험사 주장 등 선택 필드가 있을 수 있다. 그러나 임베딩 모델 자체를 비교하는 1차 실험에서는 모든 모델에 `agent_input.query_text`만 입력한다.

```text
1차 모델 A/B 입력:
agent_input.query_text

1차 모델 A/B에서 제외:
vision_evidence
ocr_evidence
insurer_claim
required_outputs
```

사용자 텍스트만 있어도 검색이 완주해야 한다는 서비스 목표를 baseline으로 둔다.

### 2.2 세 코퍼스가 같은 공통 query를 사용하고 정답지만 독립 작성한다

판례·심의사례·인정기준은 검색 모델에 같은 사용자 사고 문장 50개를 입력한다. 그래야 같은 입력에서 데이터 source별 검색 성능을 비교할 수 있다. 다만 문서 구조와 정답 단위가 다르므로 qrels는 절대로 공유하지 않는다.

```text
공통 입력:
query_id + query_text 50개

심의사례:
정답 = review_case_id

판례:
정답 = case_id / chunk_id

인정기준:
정답 = rule_id
보조 정답 = party mapping, variant/scenario, adjustment, base ratio
```

공유하는 것과 분리하는 것은 다음과 같다.

```text
- 공유: query_id, raw_user_text, query_text, accident_group, participants, difficulty
- 분리: 코퍼스별 qrels, relevance, no_relevant_document, 계산 annotation
- agent_input.query_text를 query 임베딩의 논리 입력으로 사용
- 동결된 document embedding text를 사용
- 동일한 Native-6 모델 후보와 모델별 기본/native 차원 정책
- exact cosine 기반 품질 평가
- Hit@K, MRR@10, nDCG@10
- Ground Truth를 모델 실행 전에 동결
- 모델별 raw cosine 절대값을 직접 비교하지 않음
```

### 2.3 공통 질문을 고정한 뒤 모델 결과 없이 정답 Rule을 판정한다

현재 질문은 세 코퍼스 공통 50개로 이미 고정됐다. 따라서 인정기준 Rule에 맞춰 질문을 새로 쓰지 않고, 각 공통 query에 대응하는 Rule을 Core와 원문에서 독립 판정한다.

```text
1. 공통 query_id/query_text 50개를 동결
2. 구조화 필드와 lexical 후보군으로 후보 Rule을 넓게 수집
3. Core와 PDF 원문에서 사고조건과 A/B 당사자를 확인
4. relevance 2/1/0 또는 no_relevant_document를 판정
5. 계산 가능한 경우에만 variant/scenario, 수정요소와 비율을 보조 annotation
```

후보 수집에는 모델 A/B 결과를 사용하지 않는다. 이 순서로 만들어야 특정 모델의 검색 순위나 보험사 주장 비율이 Ground Truth에 섞이지 않는다.

### 2.4 임베딩 모델 A/B와 Graph-RAG A/B를 분리한다

한 번에 다음 두 질문을 비교하지 않는다.

```text
질문 1:
어떤 임베딩 모델이 정확한 Rule을 잘 찾는가?

질문 2:
Vector Only보다 Vector + Neo4j가 A/B, variant, adjustment를 더 잘 검증하는가?
```

먼저 본 문서의 실험으로 임베딩 모델을 선정한다. 이후 선정 모델을 고정하고 `Vector Only vs Vector + Neo4j`를 별도 실험한다.

### 2.5 정식 50개 중 공통 파일럿 10개를 먼저 라벨링한다

공통 평가셋은 총 50개다. 판례·심의사례 계획과 같은 사고그룹별 1개 파일럿 query 10개를 사용해 인정기준 relevance, `no_relevant_document`, party mapping과 계산 annotation 기준을 먼저 합의한다. 합의된 기준으로 나머지 40개를 라벨링하며, 승인된 파일럿 10개도 정식 50개 점수에 포함한다.

```text
공통 파일럿 query_id:
q01, q11, q17, q25, q30,
q34, q38, q43, q46, q50
```

파일럿 문장은 기술 smoke의 shape, dimension, NaN/Inf 확인에도 재사용할 수 있다. 단, 파일럿 검색 성능을 본 뒤 특정 모델의 instruction, 문서 template 또는 전처리를 조정해서는 안 된다.

### 2.6 모델별 별도 작업 채팅과 데이터 batch를 분리한다

공통 6개 모델은 모델마다 별도 작업 채팅 하나가 담당한다. 각 채팅은 아래 문서 네 개를 순서대로 읽는다.

```text
1. ../pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md
2. ../판례/pgvector_판례_임베딩_모델_AB_실험계획.md
3. ./pgvector_인정기준_임베딩_모델_AB_실험계획.md
4. ../심의사례/pgvector_심의사례_임베딩_모델_AB_실험계획.md
```

공통 계획은 채팅·Pod·잠금·batch 순서를 소유하고, 세 코퍼스 계획은 각자의 입력 문서, adapter, qrels와 평가 기준을 소유한다. 인정기준 작업은 모든 모델에서 첫 번째 문서 batch다.

```text
모델 하나를 한 번 준비한 뒤:
batch_01_fault_standard = Rule 277개 + 인정기준 Query 50개
batch_02_review_case    = 심의사례 청크 904개 + 심의사례 Query 50개
batch_03_precedent      = 판례 청크 8,334개 + 판례 Query 50개
```

여기서 batch는 현재 모델이 여러 문서를 묶어 추론하는 단위이지 서로 다른 모델을 동시에 GPU에 올린다는 뜻이 아니다. RunPod의 Qwen 3개·BGE·E5 작업은 공통 GPU에서 절대 병렬 실행하지 않는다. OpenAI small과 large도 세 정식 repeat 모두 비용·재시도·로그 추적을 위해 순차 실행한다.

인정기준 batch가 끝난 모델 채팅은 산출물을 검증하고 다음 코퍼스로 인계한다. 인정기준 작업만 끝났다는 이유로 모델을 unload하거나 공통 Pod를 중지·종료하지 않는다.

---

## 3. 인정기준 데이터 구조와 분리 근거

현재 인정기준 데이터는 역할이 다른 세 PostgreSQL schema 계층으로 구성된다.

```text
전처리 JSONL
  ↓
staging
  ↓
core
  ↓
search documents + embedding
```

### 3.1 Staging

전처리 JSONL을 거의 그대로 보존하는 검수·배치 관리 계층이다.

```text
- JSONL 행 수 검증
- batch와 source path 추적
- raw_json 원본 보존
- 필수키 및 파싱 오류 검사
- 재적재와 복구
```

검색과 과실 계산이 Staging을 직접 조회하지 않는다.

### 3.2 Core

Core는 서비스, 관계 검증, 과실 계산의 원본 기준정보다.

```text
rulebooks
rules
rule_parties
base_faults
variants
rule_scenarios
adjustment_factors
contexts
evidence_chunks
law_refs
reference_cases
usage_notes
lane_paths
lane_steps
```

Core는 검색 표현 실험 때문에 흔들리면 안 되는 구조 데이터다.

### 3.3 Search Documents

Search Documents는 Core 데이터를 사용자 자연어 검색에 맞는 문장으로 다시 조합한 파생 계층이다.

```text
Core
= 계산과 관계의 기준

Search Documents
= 검색과 임베딩을 위해 재생성 가능한 표현
```

pgvector는 Core 테이블을 직접 임베딩 검색하지 않는다. `search.rule_search_documents`의 `search_text`와 `embedding`을 검색하고 `rule_id` 후보를 반환한다.

---

## 4. 청크 생성 위치와 검색 역할

청크는 Core에서 처음 만드는 것이 아니라 전처리 단계에서 생성된다.

```text
PDF 전처리 chunker.py
  ↓ chunks.jsonl
staging.stg_evidence_chunks
  ↓
core.evidence_chunks
  ↓
search.rule_search_documents
  document_type = evidence_chunk
```

인정기준 검색에는 서로 다른 두 문서 역할이 있다.

```text
rule_summary
  = 사용자 사고에 맞는 Rule 후보 검색

evidence_chunk
  = 선택된 Rule의 원문 근거 검색
```

Rule 전체에는 사고상황, 기본과실, 수정요소, 법규, 참고사례와 설명이 함께 존재한다. 원문 전체를 하나의 벡터로 만들면 핵심 사고상황 의미가 희석될 수 있으므로 근거 문단은 의미 block 단위로 분할한다.

그러나 임베딩 모델의 1차 선정에서는 `evidence_chunk`를 Rule 후보와 섞지 않는다. 3,793개 전체 문서를 한 번에 검색하면 법규와 근거 청크의 수가 Rule 문서보다 훨씬 많아 모델의 Rule Matching 품질을 해석하기 어렵다. 더구나 Rule마다 근거 문서 수가 달라 `max score` 집계만으로도 문서 수가 많은 Rule이 유리해질 수 있다. 따라서 1차는 Rule당 문서가 정확히 하나인 `rule_summary`만 사용하고, 전체 3,793문서는 최종 후보 2개의 2차 근거검색에만 사용한다.

---

## 5. 현재 데이터 상태

### 5.1 수집 및 전처리 결과

| 기준서 | 페이지 | Rule | Party | Base fault | Adjustment |
|---|---:|---:|---:|---:|---:|
| 2020 비정형 기준 | 63 | 23 | 46 | 23 | 205 |
| 2021 PM 대 자동차 기준 | 80 | 38 | 76 | 38 | 282 |
| 2023 공식 인정기준 | 600 | 201 | 402 | 201 | 1,697 |
| 2025 2차로형 회전교차로 기준 | 76 | 15 | 30 | 15 | 119 |
| 합계 | 819 | 277 | 554 | 277 | 2,303 |

페이지 coverage는 네 기준서 모두 누락과 중복 없이 성공했다.

### 5.2 전처리 품질 및 재적재 결과

```text
전처리 배치: quality-fix-2026-07-15
staging batch_id: 3
parse_status=valid: 277
parse_status=review_required: 0
```

기존 검토대상 15개 Rule은 공통 파서·분류·빌더 수정 후 전부 재처리했다. 특정 Rule ID를 하드코딩하지 않았고, 64개 JSONL을 새 배치로 적재한 뒤 다음 무결성 검사를 통과했다.

```text
adjustment target invalid = 0
base fault missing = 0
JSON parse error = 0
lane step path invalid = 0
party count != 2 = 0
variant missing = 0
```

따라서 현재는 277개 Rule 모두 정식 qrels의 정답 후보가 될 수 있다. 단, qrels 작성자는 구조 검증 통과를 곧바로 의미상 정답으로 간주하지 않고 Core와 원문 PDF를 다시 확인한다.

### 5.3 Core 적재 결과

2026-07-15 재적재 후 로컬 `fault_standard_db` 확인 결과다. 실험 기준 Core는 `core_load_id=2`, 원본 Staging은 `source_batch_id=3`이다.

| 항목 | 건수 | 판정 |
|---|---:|---|
| `core.rules` | 277 | 정상 |
| `core.rule_parties` | 554 | Rule당 2개 |
| `core.base_faults` | 277 | Rule 누락 0 |
| `core.adjustment_factors` | 2,303 | orphan 0 |
| `core.evidence_chunks` | 2,200 | 정상 |
| `core.contexts` | 251 | 정상 |
| `core.law_refs` | 848 | 정상 |
| `core.reference_cases` | 307 | 정상 |
| `core.usage_notes` | 183 | 정상 |
| `core.variants` | 40 | 정상 |
| `core.lane_steps` | 75 | 정상 |
| 중복 `rule_id` | 0 | 정상 |
| party 없는 Rule | 0 | 정상 |
| base fault 없는 Rule | 0 | 정상 |
| target party id 없는 adjustment | 0 | 정상 |

### 5.4 Search Documents 결과

현재 하나의 `search.rule_search_documents` 테이블에서 `document_type`으로 구분한다. 실험 고정 대상은 `search_load_id=2`, `source_batch_id=3`, `source_core_load_id=2`다.

| `document_type` | 건수 | 역할 | 1차 모델 A/B |
|---|---:|---|---:|
| `rule_summary` | 277 | Rule 후보 검색 | 사용 |
| `evidence_chunk` | 2,200 | 원문 근거 검색 | 제외, 후속 |
| `law_ref` | 848 | 관련 법규 검색 | 제외, 후속 |
| `reference_case` | 285 | 기준서 내 참고사례 | 제외, 후속 |
| `usage_note` | 183 | 적용 설명 | 제외, 후속 |
| 합계 | 3,793 |  |  |

초기 DB 계획서의 `adjustment_summary`는 현재 별도 문서 유형으로 생성되지 않는다. 실제 구현은 수정요소를 `rule_summary.search_text` 안에 조합한다.

### 5.5 Rule 문서 길이

현재 `rule_summary.search_text` 기준이다.

| 문서 수 | 최소 | 평균 | p50 | p90 | p95 | p99 | 최대 | 총 문자 수 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 277 | 218자 | 592자 | 600자 | 720자 | 764자 | 815자 | 1,516자 | 163,978자 |

현재 문서 크기만 보면 고사양 GPU가 필요한 실험이 아니다. 실제 시간은 모델 다운로드와 실행환경 설치가 더 큰 비중을 차지할 수 있다.

### 5.6 전체 Search 코퍼스 길이 분석

`search_load_id=2`의 실제 `search_text`를 SQL로 집계한 결과다.

| 문서 유형 | 문서 수 | 총 문자 | 평균 | p95 | 최대 |
|---|---:|---:|---:|---:|---:|
| `rule_summary` | 277 | 163,978 | 592.0 | 764 | 1,516 |
| `evidence_chunk` | 2,200 | 1,113,142 | 506.0 | 1,210 | 1,384 |
| `law_ref` | 848 | 22,088 | 26.0 | 30 | 84 |
| `reference_case` | 285 | 25,858 | 90.7 | 97 | 102 |
| `usage_note` | 183 | 50,558 | 276.3 | 610 | 894 |
| 합계 | 3,793 | 1,375,624 | 362.7 | 1,148 | 1,516 |

`cl100k_base`로 계산한 계획용 token 추정치는 Rule 코퍼스 104,103 token, 전체 코퍼스 1,307,292 token이다. 실제 API 비용은 응답의 `usage.total_tokens`, 로컬 모델 길이는 각 모델 tokenizer audit 값으로 확정한다.

### 5.7 현재 임베딩 상태와 실험 출발점

```text
search_load_id: 2
search document: 3,793
embedding IS NOT NULL: 0
embedding_model IS NOT NULL: 0
document_id 중복: 0
빈 search_text: 0
document strategy: rule_summary_plus_evidence
```

Search 문서를 모델 중립 상태로 재생성했기 때문에 기존 OpenAI 벡터를 baseline으로 재사용할 수 없다. `text-embedding-3-small`도 다른 후보와 동일한 스냅샷에서 새로 생성해야 한다. A/B 후보는 운영 `embedding` 컬럼에 차례로 덮어쓰지 않고 별도 실험 schema에 모델별로 저장한다.

### 5.8 실험 동결 식별자

```text
source_batch_id = 3
core_load_id = 2
search_load_id = 2
search_document_count = 3,793
search_embedding_count = 0
canonical_corpus_sha256 = 5a122deca62babf470819f56d71b44064edd09ebe22cd3d53f93d0a10e82fd8f
```

위 SHA-256은 `document_id`로 정렬한 뒤 `document_id + NUL + search_text + LF`를 연결해 계산한 전체 Search 코퍼스 식별자다. 실험 export 파일은 별도의 파일 SHA-256도 기록한다. 둘 중 하나라도 바뀌면 기존 run을 이어 쓰지 않고 새 `corpus_version`을 발급한다.

---

## 6. 실험 범위

### 6.1 1차 필수 범위: Rule Matching

```text
코퍼스:
document_type = rule_summary, 277개

query:
agent_input.query_text, 공통 정식 test 50개

정답:
rule_id

검색:
pgvector exact cosine
```

포함 항목:

- 공통 본 실험 6개 모델의 document/query embedding 생성
- 모델 manifest별 기본/native 차원 통제
- 별도 실험 schema 적재
- Rule 단위 Ground Truth 평가
- 기준서별·사고유형별 오류 분석
- 모델별 비용과 생성시간 기록
- 품질 상위 후보 HNSW 운영성 보조 평가

### 6.2 2차 보조 범위: Evidence Retrieval

Rule Matching 상위 1~2개 모델에 한해 다음 문서를 평가한다.

```text
evidence_chunk: 2,200
law_ref: 848
reference_case: 285
usage_note: 183
```

이 트랙의 정답은 `document_id/chunk_id + rule_id`다. 1차 Rule 모델 선정 점수와 섞지 않는다.

### 6.3 제외

- 심의사례·판례와 통합 검색
- BM25, hybrid, reranker 비교
- chunk size 또는 overlap A/B
- 검색 문장 template A/B
- Vision/OCR query augmentation
- 보험사 주장 기반 query 확장
- Neo4j Graph-RAG 비교
- 최종 과실 계산 정확도
- 생성형 답변 문장 품질

위 항목들은 임베딩 모델을 선정한 후 별도 실험으로 수행한다.

### 6.4 전체 실험 매트릭스

| 실험 ID | 바꾸는 것 | 고정하는 것 | 대상 | 목적 | 승자 선정 영향 |
|---|---|---|---|---|---:|
| `R0_PIPELINE` | 없음 | 10 smoke, 277 Rule | 공통 5모델 | 구현 검증 | 아니오 |
| `R1_RULE_MODEL` | embedding model | corpus·50 test·qrels·차원·exact cosine | 공통 5모델 | **주 모델 선정** | 예 |
| `R2_EVIDENCE` | 상위 모델 | 3,516 근거문서·Evidence qrels | 상위 2모델 | 근거검색 검증 | 보조 |
| `R3_INDEX` | exact/HNSW | 상위 모델·query·index parameter | 상위 2모델 | ANN 운영성 | tie-break |
| `R4_INPUT` | Text/Vision/OCR 조합 | 최종 모델·fact card·rule qrels | 최종 1모델 | 선택 입력의 가치 | 후속 |
| `R5_GRAPH` | Vector Only/Vector+Neo4j | 최종 모델·계산기·최종 정답 | 최종 1모델 | 관계검증 효과 | 별도 |

한 실험에서 두 축을 동시에 바꾸지 않는다. 예를 들어 Qwen3는 Text+Vision, BGE는 Text Only로 비교하거나, 한 모델은 HNSW이고 다른 모델은 exact인 결과를 같은 모델 점수표에 넣지 않는다.

---

## 7. 입력 스키마

### 7.1 서비스 입력과 임베딩 입력을 분리한다

서비스 입력 계약은 다음 형태다.

```json
{
  "agent_input": {
    "session_id": "ses_20260623_0001",
    "message_id": "msg_0001",
    "job_id": "job_0002",
    "node_code": "text_ml_case_search",
    "raw_user_text": "신호 없는 교차로에서 저는 직진 중이었고 상대 차량은 오른쪽에서 진입했습니다.",
    "query_text": "신호 없는 교차로에서 사용자 차량은 직진, 상대 차량은 우측에서 진입한 사고",
    "vision_evidence": [],
    "insurer_claim": null,
    "ocr_evidence": null,
    "required_outputs": null
  }
}
```

1차 모델 A/B에서 실제 query 임베딩에 사용하는 값은 `query_text` 하나다.

| 필드 | 1차 query 임베딩 | 역할 |
|---|---:|---|
| `query_text` | 예 | 모델 공통 검색 입력 |
| `raw_user_text` | 아니오 | 사용자 원문과 query 작성 근거 |
| `vision_evidence` | 아니오 | 후속 입력 보강 실험 |
| `ocr_evidence` | 아니오 | 후속 입력 보강 실험 |
| `insurer_claim` | 아니오 | 검색 후 주장 비교 |
| `required_outputs` | 아니오 | 출력 제어 |

### 7.2 선택 입력의 역할

```text
Vision:
진행 방향, 충돌 위치, 차로, 신호, 선진입 등 사실 보강 후보

OCR:
사고 장소, 사고 유형, 사고 원인, 사고 설명 등 공식 기록 보강 후보

보험사 주장:
claimed_ratio와 reason_text를 최종 계산 결과와 비교
검색 정답이나 Ground Truth를 결정하지 않음
```

보험사 주장은 확인된 사고 사실이 아니라 `claim_context`로 분리한다. 인정기준 검색용 `retrieval_context`에 `claimed_ratio`를 넣지 않는다.

현재 공통 검색문 builder는 보험사 주장까지 검색 텍스트에 포함할 수 있으므로, 인정기준 retriever에서는 `query_text` 전용 경로를 명시적으로 사용해야 한다.

### 7.3 평가 query 레코드

실제 공통 query 원본과 인정기준 전용 qrels 위치:

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl
etl/fault_cases/evaluation/common/embedding_ab/v1/common_fault_query_schema_v1.json
etl/fault_cases/evaluation/common/embedding_ab/v1/query_manifest.json
etl/fault_cases/evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2.jsonl
etl/fault_cases/evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2_해설.md
```

공통 질문은 `fault_common_queries_v1` 그대로 고정한다. 인정기준 정답지만 `fault_standard_qrels_v1.2`를 사용하며, 질문 문장·ID·순서·버전은 수정하지 않는다. q31처럼 판정할 Rule이 하나도 없는 Query도 판례 정답지와 같은 `no_relevant_document` negative-control 행으로 qrels 안에 저장한다.

공통 query 레코드 예시:

```json
{
  "query_id": "fault_common_q01",
  "raw_user_text": "저는 녹색 신호에 직진했는데 오른쪽에서 적색 신호를 무시한 차량이 들어와 충돌했습니다.",
  "query_text": "신호기 있는 사거리에서 사용자 차량은 녹색 신호에 직진하고 상대 차량은 우측 도로에서 적색 신호에 직진하여 충돌한 사고",
  "accident_group": "signalized_intersection",
  "participants": ["car", "car"],
  "issue_tags": ["상대 차량 신호위반", "녹색 신호 직진", "측면 충돌"],
  "difficulty": "easy",
  "split": "test",
  "retrieval_targets": ["review_case", "fault_standard", "precedent"],
  "annotation_status": "approved",
  "eval_set_version": "fault_common_queries_v1"
}
```

모델에는 `query_text`만 전달한다. 정답 `rule_id`나 예상 기준서는 query JSON에 넣지 않고 인정기준 qrels에만 둔다. 나머지 필드는 층화, 라벨 검증과 오류 분석에 사용한다.

### 7.4 Rule 문서 임베딩 입력

1차 baseline은 현재 `rule_summary.search_text`를 의미 변경 없이 사용하고 이를 `rule_embedding_text_v1`으로 동결한다.

현재 논리 구성:

```text
[기준서]
[기준 코드와 제목]
[사고분류]
[기본과실]
[당사자 A/B와 행동]
[수정요소]
[variant/scenario]
[상황정보]
```

동결 규칙:

```text
1. 모든 모델이 동일한 문자열을 사용
2. Unicode NFC 정규화
3. 줄바꿈 LF 통일
4. 앞뒤 공백과 불필요한 연속 공백만 정리
5. 의미 문장과 필드 순서를 모델별로 바꾸지 않음
6. rule_embedding_text_hash를 SHA-256으로 저장
7. source_batch_id와 search_load_id 기록
```

문서 template의 품질을 변경하고 싶다면 모델 A/B와 분리해 선정 모델로 `rule_embedding_text_v1 vs v2` ablation을 수행한다.

---

## 8. 공통 평가 질의 50개와 파일럿 설계

### 8.0 100개에서 50개로 줄인 이유와 동결값

판례 계획과 동일하게 기존 100개 질문을 사고군 비율, 질문 자체의 난이도와 희소 당사자 유형이 최대한 유지되도록 50개로 층화 선정했다. 공통 6개 모델을 같은 입력으로 paired 비교하기에는 50개가 실행·이중검수 가능한 범위이며, 파일럿 10개와 나머지 40개를 모두 사람 검수할 수 있다. 선정된 50개는 파일 순서대로 `fault_common_q01`부터 `fault_common_q50`까지 연속 재번호했다.

```text
query file: etl/fault_cases/evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl
query set version: fault_common_queries_v1
query count: 50
query SHA-256: a50921b0ea409ebfdd46d50c8ef632fb1fdac7c53b80ebb95fbb353c4ea02102
split: test 50

fault_standard_qrels_v1.2 rows: 111
fault_standard_qrels_v1.2 unique queries: 50
fault_standard_qrels_v1.2 SHA-256: 0eb20fd6666fcba8d8e10d071f459877a65dd4802dbd2e164208cfc261ff9343
fault_standard_qrels_v1.2_해설.md SHA-256: ad8481f4bc7c80aaa8cd4fdfe6ba2f7d567e14679619be6e073f4cc9eab9b140
```

질문 번호는 `q01`부터 `q50`까지 연속이며 세 코퍼스 qrels와 동일한 매핑을 사용한다. 정식 실행 전에 파일 hash와 50줄을 다시 검증하고 값이 달라지면 같은 run으로 이어 쓰지 않는다.

### 8.1 파일럿 10개, 나머지 40개, 정식 50개

| 단계 | 수량 | 용도 | 승인 후 정식 점수 포함 |
|---|---:|---|---:|
| `pilot` | 10 | 사고그룹별 relevance와 qrels 형식 합의 | 예 |
| `remaining` | 40 | 합의된 기준으로 나머지 인정기준 qrels 작성 | 예 |
| `final test` | 50 | 동결 후 공통 6개 후보 모델 비교 | 예 |
| `robustness` | 별도 10 | 정보 부족 시 Rule을 억지로 확정하지 않는 후속 평가 | 아니오 |

파일럿은 모델 검색 결과가 아니라 Core, 전처리 구조화 데이터와 PDF 원문을 보고 작성한다. 10개에서 기준을 합의한 뒤 나머지 40개를 같은 방식으로 판정하고, 정식 50개 query/qrels SHA를 동결한 다음에만 모델을 실행한다.

기술 smoke에는 파일럿 10개 문장을 재사용하되 shape, dimension, norm, NaN/Inf와 코드 계약만 확인한다. 파일럿 retrieval 점수를 보고 instruction, 문서 template, qrels 또는 전처리를 조정하면 공식 비교가 오염되므로 금지한다.

### 8.2 공통 파일럿 10개

판례·심의사례와 입력 문장을 맞추기 위해 다음 동일한 10개 `query_id`를 사용하고, 인정기준 정답만 독립 작성한다.

| query_id | 사고그룹 | 공통 난이도 |
|---|---|---|
| `fault_common_q01` | 신호 교차로 | easy |
| `fault_common_q11` | 무신호 교차로 | hard |
| `fault_common_q17` | 회전·차로규칙 | medium |
| `fault_common_q25` | 차로변경·추돌 | easy |
| `fault_common_q30` | 주차·도로진입 | easy |
| `fault_common_q34` | 회전교차로 | hard |
| `fault_common_q38` | 고속도로 | hard |
| `fault_common_q43` | 이륜차 | medium |
| `fault_common_q46` | 보행자 | easy |
| `fault_common_q50` | 자전거·PM | hard |

`fault_standard_qrels_pilot_v1.jsonl`은 초기 라벨 기준 합의와 기술 smoke용 이력 파일이다. 정식 50개 평가는 반드시 `ground_truth/fault_standard_qrels_v1.2.jsonl` 하나를 기준으로 한다.

최종 검토를 반영한 정답지는 Rule 판정 110행과 q31 무정답 negative-control 1행을 합친 qrels 111행이다. q01~q50이 모두 한 파일에 존재한다. q31 행은 `rule_id`와 `relevance`가 없으므로 일반 retrieval 지표가 아니라 별도 abstention 진단에 사용한다. q13은 `차16-3`, 근거 298쪽, B +10, 사용자 최종 90으로 승인됐으며 `source_evidence_review_status=approved`다. 현재 query·qrels·해설 SHA는 `ground_truth_manifest_v1.2.json`으로 동결한다.

### 8.3 정식 50개 사고군 층화

| 사고군 | 기존 100개 | 정식 50개 | 정식 비율 |
|---|---:|---:|---:|
| 신호 교차로 | 15 | 8 | 16% |
| 무신호 교차로 | 15 | 7 | 14% |
| 회전·차로규칙 | 10 | 5 | 10% |
| 차로변경·추돌 | 15 | 8 | 16% |
| 주차·도로진입 | 8 | 4 | 8% |
| 회전교차로 | 7 | 3 | 6% |
| 고속도로 | 8 | 4 | 8% |
| 이륜차 | 12 | 6 | 12% |
| 보행자 | 5 | 3 | 6% |
| 자전거·PM | 5 | 2 | 4% |
| 합계 | 100 | 50 | 100% |

정확히 절반이 0.5건이 되는 사고군은 총합이 50이 되도록 올림과 내림을 분산했다. 자전거·PM 2개는 자전거 1개와 개인형 이동장치 1개다. 이 분포는 인정기준 Rulebook 비율을 억지로 맞춘 것이 아니라 세 코퍼스에 공통으로 넣을 사용자 사고 입력 분포다. `ground_truth` qrels의 고유 query 50개도 이 사고군 분포와 easy 25개·medium 21개·hard 4개를 그대로 보존한다. Rulebook별 성능은 qrels 확정 뒤 별도 slice와 `Rulebook Macro`로 보고한다.

`no_exact_rule`을 제외하고 가능하면 30개 이상의 서로 다른 exact Rule을 사용한다. v1.2는 relevance 2가 있는 Query 39개와 서로 다른 exact Rule 30개를 확보했다. 공통 query 자체가 같은 인정기준을 반복 검증하는 경우에는 정답을 억지로 다른 Rule로 바꾸지 않는다. 기준서별 query 수는 qrels 결과로 기록하고 사전에 임의 배정하지 않는다.

### 8.4 공통 난이도 층화와 해석

| 난이도 | 개수 | 비율 | 기준 |
|---|---:|---:|---|
| easy | 25 | 50% | 한 가지 주된 충돌 관계와 우선·위반 쟁점으로 설명 가능 |
| medium | 21 | 42% | 둘 이상의 진행조건이나 추가 쟁점을 함께 비교해야 함 |
| hard | 4 | 8% | 복합 우선관계, 다차로 회전, 안전조치 또는 희소 당사자 조건 결합 |
| 합계 | 50 | 100% | - |

hard는 `q11`, `q34`, `q38`, `q50` 네 개다. 표본 1개가 hard slice의 25%p이므로 hard 점수만으로 모델 순위를 정하지 않고 실패 유형을 설명하는 진단 지표로 사용한다.

공통 `difficulty`는 질문 문장과 사고 사실관계 자체의 복잡도다. 인정기준에 exact Rule이 없는 `no_relevant_document`와 같은 개념이 아니다. similarity threshold나 abstention을 평가하지 않는 기본 top-K 실험에서는 정답 없는 query를 표준 Hit/MRR/nDCG 분모에서 분리하고 코퍼스 공백으로 별도 보고한다.

Hard negative는 공통 difficulty와 별도로 qrels에서 관리한다. 방향·신호·차로·선진입 중 한 조건만 다른 유사 Rule을 `relevance=0`과 `reason`으로 기록한다.

### 8.5 사용자 표현 유지 규칙

```text
유지:
- 사고 장소와 도로 구조
- 신호 조건
- 사용자와 상대방의 진행 방향 및 행동
- 충돌 형태
- Rule 검색에 필요한 핵심 쟁점

제외:
- rule_id와 rule_code
- 기준서명
- Rule 제목을 그대로 복사한 문장
- 정답을 노출하는 고유 문구
- 목표 과실비율 숫자
- 보험사 claimed_ratio
```

ratio와 Rule 코드가 query에 들어가면 의미 검색이 아니라 정답 문자열 탐색이 될 수 있으므로 기본 질의에서 제외한다.

질의 작성자가 문서의 제목이나 문장을 그대로 외워 옮기는 것을 막기 위해 fact card 화면에는 `rule_id`, `rule_code`, 기준서명과 제목을 숨긴 사용자용 작성 view를 별도로 둔다. 현재 공통 50개 문장은 그대로 동결하고 인정기준에 맞추기 위해 query 문장을 임의 수정하지 않는다. 수정이 필요하면 공통 query v2를 만들고 세 코퍼스를 모두 재평가한다.

### 8.6 파일럿과 기술 smoke의 분리

별도 dev 20개를 새로 만들지 않는다. 공통 파일럿 10개를 기술 smoke 입력으로 재사용하되 정답 성능은 보지 않는다.

```text
- 50개 중 파일럿 10개: relevance 기준 합의 후 정식 점수에 포함
- 기술 smoke: 같은 문장으로 vector count/dimension/norm만 검사
- robustness 10개: 정보 부족 처리용 별도 후속 set
```

smoke에서 검색이 완전히 실패한 모델도 먼저 차원·prefix·pooling·normalization 구현을 확인하며, 구현 오류가 아닌 것이 확인된 뒤에만 `실행 불가`로 기록한다.

### 8.7 질의 누출 방지 체크

```text
[ ] rule_id/rule_code 없음
[ ] 기준서명 없음
[ ] rule_title 연속 8자 이상 복사 없음
[ ] 정답 기본과실 숫자 없음
[ ] insurer_claim.claimed_ratio 없음
[ ] source page 없음
[ ] 정답 Rule에서만 등장하는 비자연적 고유문구 없음
[ ] 동일 fact_card의 paraphrase가 split을 넘나들지 않음
```

---

## 9. Ground Truth 작성 방법

### 9.1 Query 파일과 qrels 파일을 분리한다

파일:

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl
etl/fault_cases/evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2.jsonl
etl/fault_cases/evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2_해설.md
```

`pilot/fault_standard_qrels_pilot_v1.jsonl`은 공통 파일럿 10개를 담은 이력·smoke용 부분집합이다. 정식 평가는 `ground_truth/` 아래의 v1.2 파일만 사용한다. Qrels는 `judgments` 배열을 두지 않고 Rule 판정 1건당 1줄로 저장하며, 판정할 Rule이 없는 Query도 판례 qrels와 같은 무정답 negative-control 행으로 같은 파일에 저장한다.

| 항목 | 결과 |
|---|---:|
| 공통 query 원본 | 50행 |
| 전체 qrels | 111행 / 50 Query |
| Rule 판정행 | 110행 |
| q31 무정답 negative-control | 1행 |
| `relevance=2` 판정 | 42행 / 39 Query |
| `relevance=1` 판정 | 23행 |
| `relevance=0` hard negative | 45행 |
| exact Rule이 없는 Query | 11개 |
| 서로 다른 exact Rule | 30개 |

exact Rule이 없는 11개 중 10개는 부분 관련 또는 hard-negative Rule 판정행이 qrels에 존재한다. q31은 판정할 Rule 행이 없지만 같은 qrels에 `judgment_status=no_relevant_document`, `negative_control=true` 행으로 존재한다. Hit@K·MRR은 relevance 2가 있는 39개 Query를 대상으로 하고, relevance가 없는 q31은 일반 nDCG에서도 제외해 별도 abstention/negative-control 결과로 보고한다.

qrels 구조 예시다. 아래 세 객체는 모두 같은 qrels의 별도 줄이다.

```jsonl
{"query_id":"fault_common_q30","rule_id":"official_2023_차51-1","relevance":2,"is_hard_negative":false,"query_set_version":"fault_common_queries_v1","ground_truth_version":"fault_standard_qrels_v1.2","query_answerability":"has_exact_rule"}
{"query_id":"fault_common_q30","rule_id":"official_2023_차51-2","relevance":0,"is_hard_negative":true,"query_set_version":"fault_common_queries_v1","ground_truth_version":"fault_standard_qrels_v1.2","query_answerability":"has_exact_rule"}
{"query_id":"fault_common_q31","judgment_status":"no_relevant_document","negative_control":true,"query_answerability":"no_exact_rule","query_set_version":"fault_common_queries_v1","ground_truth_version":"fault_standard_qrels_v1.2"}
```

`relevance` 의미:

```text
2 = 사고 관계와 핵심 적용조건이 직접 일치하는 정답 Rule
1 = 동일 Rule family 또는 사고구조는 유사하지만 세부 적용조건이 일부 다름
0 = 표면 키워드만 같거나 적용하면 잘못된 과실기준
```

Hit@K와 MRR의 정답은 `relevance=2`만 사용한다. nDCG는 0/1/2 관련도를 사용한다. 동일 `query_id`의 여러 행은 평가 시 그룹화하되 qrels 원본에는 다시 배열로 묶어 저장하지 않는다.

### 9.2 라벨링 순서

1. 공통 `query_id/query_text`와 query SHA를 확인한다.
2. 전체 277개 Rule에서 구조화 필드와 lexical 기준으로 후보군을 넓게 모은다.
3. `rule_parties`에서 A/B 행동과 방향을 확인한다.
4. `base_faults`에서 기본과실 구조를 확인한다.
5. `variants/rule_scenarios`에서 세부 조건을 확인한다.
6. `contexts`, `adjustment_factors`, `evidence_chunks`에서 적용조건을 확인한다.
7. 필요하면 원본 PDF 해당 페이지를 직접 확인한다.
8. 후보별 Rule fact card와 hard negative 차이를 기록한다.
9. exact Rule이 없으면 `query_answerability=no_exact_rule`로 판정한다. 부분 관련 또는 hard-negative Rule이 없더라도 `no_relevant_document` negative-control 행을 qrels에 남긴다.
10. 두 명의 검수자가 서로의 답과 모델명·순위를 보지 않고 relevance를 판정한다.
11. `relevance=2`, party mapping, variant/scenario 중 하나라도 다르면 제3 검수자가 원문을 보고 판정한다.
12. q31을 포함한 flat qrels 111행, 문항별 해설과 라벨 변경 이력을 하나의 v1.2 manifest로 동결한다.

### 9.3 Rule fact card

Rule fact card는 공통 query를 다시 쓰기 위한 자료가 아니라 후보 Rule의 적용조건과 party mapping을 비교·검수하기 위한 근거표다.

권장 필드:

```text
rule_id
rulebook_id
rule_code
rule_title
rule_type
accident_group
accident_subgroup
party A type/movement/road_position/signal_state
party B type/movement/road_position/signal_state
base_fault_type
base ratio
variant/scenario conditions
road/signal/context
adjustment target/condition/delta
source page
parse_status
```

### 9.4 Rule 제목과 기본과실만으로 정답을 만들지 않는다

유사 제목 또는 같은 사고군이라도 다음 값이 다르면 잘못된 Rule일 수 있다.

```text
- 사용자와 상대방의 A/B 방향
- 진입·선진입 관계
- 신호 상태
- 도로 형태와 차로
- variant/scenario 조건
- 수정요소 적용 대상
```

판정 우선순위:

```text
1. 양측 party 행동과 방향
2. 장소·도로·신호·충돌 관계
3. variant/scenario 조건
4. 사고분류와 Rule 제목
5. 기본과실과 수정요소 구조
```

### 9.5 계산 정답은 보조 annotation으로 저장한다

임베딩 모델 A/B의 1차 정답은 `rule_id`다. 다만 후속 Graph-RAG와 계산기 평가를 위해 계산 가능한 query에는 다음 annotation을 함께 둔다.

```text
expected_user_party_key
expected_opponent_party_key
expected_base_ratio
expected_variant_id
expected_scenario_id
expected_adjustments
expected_final_ratio
calculation_status
missing_facts
```

이 필드는 임베딩 모델 선정의 주 지표에 포함하지 않는다.

### 9.6 정보 부족 query는 별도 robustness set으로 만든다

정식 공통 50개 Rule Matching query는 적용 Rule을 확정할 수 있는 사고 설명을 우선 사용한다. 다만 공통 질문지가 특정 인정기준 Rule을 직접 지원하지 않으면 `no_relevant_document`로 판정하고 문장을 인정기준에 맞게 몰래 고치지 않는다.

실제 서비스의 불충분 입력은 별도 10개 robustness set으로 평가한다.

```json
{
  "calculation_status": "needs_more_information",
  "candidate_rule_ids": ["..."],
  "missing_facts": ["도로 우선관계", "선진입 여부"],
  "expected_final_ratio": null
}
```

불충분 query에 억지로 하나의 Rule과 최종 비율을 붙이지 않는다. 이 세트는 임베딩 모델 순위보다 후속 Agent·Neo4j·계산기의 중단 및 추가질문 능력을 평가한다.

### 9.7 전처리 품질과 qrels 정책

```text
- 현재 batch_id=3은 valid 277, review_required 0
- 모든 Rule이 정답 후보지만 qrels 작성 시 Core와 PDF 원문 대조 필수
- 전처리나 Search 문서가 수정되면 새 corpus_version과 qrels_version 생성
- 이전 모델 결과와 새 결과를 모두 보존
```

### 9.8 라벨 품질 합격 조건

정식 test 동결 전에 다음을 계산한다.

| 검사 | 합격 조건 |
|---|---:|
| query 2인 독립 검수율 | 100% |
| exact Rule 존재 여부 미판정 query | 0 |
| party mapping 미확정 query | 0 또는 해당 query를 계산 지표에서 제외 |
| hard negative 1개 이상 보유 query | 10개 이상 |
| source page 확인 가능 비율 | 100% |
| 동일 fact card의 split 누출 | 0 |
| adjudication 미완료 | 0 |
| qrels의 고유 query coverage | 50 |
| 무정답 negative-control 행 | q31 1행 |

초기 독립 라벨의 일치도는 exact Rule에 대해 Cohen's kappa 또는 단순 일치율을 함께 보고한다. 합의 후 점수만 남기지 않고 어떤 조건에서 의견이 갈렸는지 `labeling_disagreements.jsonl`에 보존한다.

### 9.9 모델 결과에서 새 정답을 발견한 경우

모델이 qrels에 없지만 실제로 유효한 Rule을 찾을 수 있다.

```text
1. 모델 정보를 가리고 적합성 재검수
2. 모든 모델에 동일한 새 qrels 버전 생성
3. 기존 결과와 새 결과 모두 보존
4. 동일 qrels 버전으로 전 모델 점수를 재계산
```

---

## 10. 모델 후보와 통제 변수

### 10.1 세 코퍼스 공통 후보 6개

이름은 A/B지만 실제로는 A/B/n 비교다. 심의사례 실험과 모델 축을 맞춰 데이터 source별 결과를 나란히 볼 수 있게 하되, 인정기준 test qrels는 별도로 사용한다.

| model_key | 모델 | 기본/native 차원 | 실행 |
|---|---|---:|---|
| `openai_small_native_1536` | `text-embedding-3-small` | 1,536 | 로컬 OpenAI API |
| `openai_large_native_3072` | `text-embedding-3-large` | 3,072 | 로컬 OpenAI API |
| `qwen3_06b_native_1024` | `Qwen/Qwen3-Embedding-0.6B` | 1,024 | RunPod |
| `qwen3_4b_native_2560` | `Qwen/Qwen3-Embedding-4B` | 2,560 | RunPod |
| `bge_m3_dense_native_1024` | `BAAI/bge-m3` | 1,024 | RunPod |
| `e5_large_native_1024` | `intfloat/multilingual-e5-large` | 1,024 | RunPod |

후보 근거와 실행 전 확인할 공식 출처:

- OpenAI 두 모델은 Track A에서 `dimensions` 축소 인자를 보내지 않고 small 1,536, large 3,072차원을 검증한다. [small 모델](https://developers.openai.com/api/docs/models/text-embedding-3-small), [large 모델](https://developers.openai.com/api/docs/models/text-embedding-3-large), [Embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
- Qwen 공식 모델 카드는 0.6B가 최대 1024차원, 100개 이상 언어, 32K context, MRL과 query instruction을 지원하며 Apache-2.0 라이선스라고 설명한다. [Qwen3 0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- BGE-M3 공식 모델 카드는 1024차원, 최대 8192 token, 100개 이상 언어, MIT 라이선스를 명시한다. 이번 실험은 비교 변수를 하나로 유지하기 위해 dense vector만 사용한다. [BGE-M3](https://huggingface.co/BAAI/bge-m3)
- multilingual-e5-large 공식 모델 카드는 1024차원, `query:`/`passage:` prefix 필수, 최대 512 token truncation과 MIT 라이선스를 명시한다. [multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large)

Qwen3 0.6B와 4B에는 동일한 인정기준 instruction을 적용하고 각 native 차원을 사용한다. Qwen 공식 다국어 MTEB 평균에서 4B는 69.45, 8B는 70.58로 차이가 1.13점인 반면 파라미터 수는 2배이고 native 벡터 차원은 2,560에서 4,096으로 60% 증가한다. 세 코퍼스 전체를 3회 반복하는 자원·비용 구조를 고려해 4B를 Qwen 계열 품질 상한 대표로 확정하고 8B는 공식 비교에서 제외한다. 이는 실행 결과에 따른 탈락이 아니라 설계 단계의 후보 축소이며, 필요할 때 별도 후속 확장 실험으로 검증한다. 근거는 [Qwen3-Embedding-4B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-4B)와 [Qwen3-Embedding-8B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-8B)다. 외부 벤치마크 순위는 후보 선정 참고일 뿐 한국 교통사고 인정기준 정답으로 간주하지 않는다.

### 10.2 사전 추천 우선순위와 검증 질문

```text
운영비·품질 균형 예상 1순위: Qwen3-Embedding-0.6B
장문·다국어 안정 기준선: BGE-M3
현재 프로젝트 API 기준선: text-embedding-3-small
API 품질 상한 확인: text-embedding-3-large
회귀 확인: multilingual-e5-large
```

이는 실험 전 가설이지 결론이 아니다. 실제로 검증할 질문은 다음과 같다.

```text
H1. Qwen3 0.6B가 OpenAI small보다 Rule nDCG@10/Hit@1을 개선하는가?
H2. BGE-M3가 장문 rule_summary와 evidence_chunk에서 truncation 없이 안정적인가?
H3. OpenAI large가 API 비용 증가만큼 인정기준 한국어 hard negative를 더 잘 구분하는가?
H4. E5의 512-token truncation이 긴 공식2023 Rule에서 실제 성능 저하로 이어지는가?
```

### 10.3 독립 변수와 통제 변수

독립 변수:

```text
embedding model
```

통제 변수:

```text
rule corpus 277개
corpus_version
document_id/rule_id
rule_embedding_text_v1
rule_embedding_text_hash
embedding dimension = 모델 manifest의 기본/native 차원
query set: pilot/smoke 10, remaining 40, locked final test 50, robustness 별도 10
Ground Truth version
distance metric = cosine
top_k
model revision
vector normalization rule
pooling implementation
output dimension reduction = Track A에서는 사용하지 않음
runtime library version
```

### 10.4 모델별 입력 adapter

| 모델 | query adapter | document adapter |
|---|---|---|
| OpenAI small/large | `query_text` | `rule_embedding_text_v1` |
| BGE-M3 | `query_text` | `rule_embedding_text_v1` |
| Qwen3 0.6B/4B | 동일한 고정 instruction + `query_text` | `rule_embedding_text_v1` |
| multilingual-e5-large | `query: {query_text}` | `passage: {rule_embedding_text_v1}` |

Qwen query instruction 예시:

```text
Instruct: Given a Korean traffic-accident description, retrieve the applicable Korean fault-ratio standard rule
Query:{query_text}
```

Instruction과 prefix는 실행 전에 고정한다. 모델별로 query 의미나 문서 내용을 다르게 재작성하지 않는다.

모델마다 공식 권장 adapter가 다르므로 물리 문자열까지 똑같게 만드는 것은 공정하지 않다. 비교에서 동일한 것은 `query_text`의 의미 payload와 `rule_embedding_text_v1`이다. prefix/instruction은 모델별 공식 사용법을 구현하는 고정 adapter로 허용하고, adapter 전체 문자열과 SHA-256을 manifest에 기록한다.

모든 로컬 모델은 `eval()`과 inference mode로 실행하며 최종 벡터는 float32, L2 norm 약 1.0으로 저장한다. OpenAI 결과도 저장 전에 차원, NaN/Inf와 norm을 검사한다.

### 10.5 입력 길이 검사

현재 Rule 문서 최대 길이는 1,516자지만 tokenizer별 token 길이는 다르다.

```text
1. 후보 tokenizer별 document/query token 길이 계산
2. 모델 최대 입력 초과 건수 기록
3. 특정 모델만 silent truncation하지 않음
4. E5 512 token 초과 시 overflow와 영향 문서를 보고
5. overflow가 있으면 E5를 legacy 참고 후보로 표시하고 winner 자격 제외
6. Qwen/BGE의 `max_length`는 실제 tokenizer p99 이상이면서 모델 한도 이하로 고정
```

현재 `cl100k_base` 추정에서 Rule 최대가 1,277 token이므로 E5 overflow 가능성이 있다. 그러나 tokenizer가 다르므로 이 수치만으로 탈락시키지 않고 실제 E5 tokenizer 결과로 판정한다. E5에 맞추려고 공통 Rule 문서를 다시 잘게 쪼개면 다른 모델의 입력까지 바뀌므로 금지한다.

### 10.6 모델 manifest 계약

모델 폴더마다 다음 정보를 기계가 읽을 수 있는 JSON으로 저장한다.

```json
{
  "run_id": "fs_emb_ab_20260715_001",
  "experiment_group_id": "embedding_native7_3repeat_YYYYMMDD_HHMMSS",
  "run_group_id": "embedding_native7_3repeat_YYYYMMDD_HHMMSS_repeat_01",
  "corpus_key": "fault_standard",
  "repeat_id": "repeat_01",
  "model_key": "qwen3_06b_native_1024",
  "provider": "huggingface",
  "model_id": "Qwen/Qwen3-Embedding-0.6B",
  "model_revision": "<commit_sha>",
  "license": "apache-2.0",
  "native_dimension": 1024,
  "output_dimension": 1024,
  "dimension_method": "native_1024",
  "query_adapter_version": "fault_standard_qwen_query_v1",
  "document_adapter_version": "fault_standard_document_v1",
  "pooling": "last_token",
  "normalize_embeddings": true,
  "dtype": "bfloat16",
  "batch_size": 32,
  "max_length": 2048,
  "corpus_version": "fault_standard_search_load_2_v1",
  "query_set_version": "fault_common_queries_v1",
  "ground_truth_version": "fault_standard_qrels_v1.2"
}
```

`run_group_id`, `corpus_key`, `model_key`, `model_revision`, adapter version, pooling, dimension method 중 하나라도 다르면 같은 결과를 이어 쓰지 않는다. `model_key`는 공통 실행계획과 판례 계획에서 사용하는 위 다섯 키만 허용하며 인정기준 전용 축약 별칭을 새로 만들지 않는다. API 모델은 응답에 고정 snapshot ID가 없으면 호출 날짜, API 모델명, request body와 client library version을 기록한다.

---

## 11. 코퍼스 동결

### 11.1 동결 대상

```text
1차 rule corpus:
  search_load_id = 2
  document_type = rule_summary
  document_count = 277

2차 evidence corpus:
  search_load_id = 2
  document_type in (evidence_chunk, law_ref, reference_case, usage_note)
  document_count = 3,516

전체 search corpus:
  document_count = 3,793
  canonical SHA-256 = 5a122deca62babf470819f56d71b44064edd09ebe22cd3d53f93d0a10e82fd8f
```

1차와 2차는 같은 `search_load_id`에서 export하지만 서로 다른 corpus manifest를 가진다. 1차 모델 선정에서 전체 corpus를 검색하지 않는다.

### 11.2 Snapshot 필드

권장 snapshot 필드:

```text
snapshot_id
document_id
source_batch_id
search_load_id
source_core_load_id
rulebook_id
rule_id
document_type
title
rule_embedding_text_version
rule_embedding_text
rule_embedding_text_hash
metadata
parse_status
```

`rule_embedding_text`는 현재 `search_text`를 NFC/LF 정규화한 값이며, 원본 `search_text_hash`와 정규화 후 `embedding_text_hash`를 둘 다 남긴다.

### 11.3 동결 절차와 합격 조건

동결 순서:

```text
1. search.rule_search_documents에서 rule_summary 277개 export
2. rule_embedding_text_v1 정규화
3. SHA-256 hash 생성
4. Core rule/party/base/adjustment 건수 검증
5. valid=277, review_required=0을 manifest에 기록
6. tokenizer length audit
7. document_id 중복, 빈 텍스트, FK 누락 검사
8. JSONL/Parquet 각각 SHA-256 계산
9. corpus_manifest.json 동결
```

문서 template, Core batch 또는 전처리 결과가 달라지면 같은 run을 이어가지 않고 새 corpus version을 생성한다.

완료 SQL/파일 검증:

```text
rule_summary count = 277
evidence corpus count = 3,516
total count = 3,793
duplicate document_id = 0
empty search_text = 0
unknown rule_id = 0
embedding present in neutral search source = 0
manifest count == exported row count
manifest hash == recomputed hash
```

### 11.4 코드·평가원본·실행결과 분리

```text
etl/fault_cases/src/embedding_ab_shared/
  common/paths.py                                         # Track A/B 경로 계약만 공유
  track_b_5models_fixed1024/                              # 과거 5모델·1024차원 재현 전용
    run_ab.py
    runpod_local_models.sh
    runpod_bundles/
  track_a_6models_native_3repeats/                        # 새 공식 Native-6 전체 3회 runner
    run_native7.py
    run_openai_models.py
    run_local_models.py
    runpod_native7_3repeats.sh
    corpora/fault_standard/
      build_corpus_snapshot.py
      adapter.py
      load_pgvector.py
      evaluate_retrieval.py
      build_corpus_report.py
etl/fault_cases/evaluation/fault_standard/embedding_ab/   # 사람이 관리하는 qrels 원본
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/  # Native-6 공통 실행 산출물
```

실행 산출물을 평가 원본 폴더에 덮어쓰지 않는다. qrels는 사람이 승인한 별도 파일이고, RunPod에는 검색 정답이 없어도 벡터 생성이 가능하므로 qrels를 전송하지 않는다. 인정기준만의 별도 legacy run 루트를 만들지 않으며, 공통 계획 7.1의 동일 폴더·파일명 계약을 따른다. Track B 코드는 동결된 참고 실험 재현에만 사용하고 Track A가 import하거나 실행하지 않는다.

인정기준용으로 새로 만드는 `.md`, README, 표, 보고서와 오류 안내는 한국어로 작성한다. 모든 Python/Bash 파일은 한국어 파일 설명과 함수 docstring을 가지며, 매개변수·반환값·예외·부작용과 각 주요 실행 줄의 의미·필요 이유·실패 영향을 한국어 주석으로 설명한다. 고유 모델명·API 필드·경로·CLI만 원문 영문을 유지하며 공통 계획 7.1.1의 검토 실패 기준을 그대로 적용한다.

### 11.5 작성할 실행 CLI 계약

RunPod를 열기 전에 다음 CLI가 로컬 smoke fixture에서 동작해야 한다. 파일명은 구현 시 바꿀 수 있지만 입력·출력 계약은 유지한다.

```text
export_fault_standard_corpus.py
  --search-load-id 2 --track rule|evidence --output <dataset_dir>

audit_embedding_inputs.py
  --corpus <jsonl> --models <model_config.yaml> --output token_length_audit.json

embed_fault_standard_openai.py
  --model-key <key> --corpus <jsonl> --queries <jsonl> --output <model_dir>

embed_fault_standard_local.py
  --model-key <key> --config <model_config.yaml> --corpus <jsonl> --queries <jsonl> --output <model_dir>

validate_embedding_artifacts.py
  --model-dir <model_dir> --expected-dim <native_dimension> --expected-docs 277 --expected-queries 50

load_embedding_experiment.py
  --run-dir <run_dir> --schema embedding_ab_fault_standard

evaluate_fault_standard_retrieval.py
  --run-id <run_id> --qrels <qrels.jsonl> --mode exact --top-k 50

build_fault_standard_report.py
  --run-id <run_id> --output <result.md>
```

모든 CLI는 `--dry-run`, `--resume`와 명확한 exit code를 지원한다. `--resume`은 이미 hash가 일치하는 완전한 model artifact만 건너뛰며 부분 parquet에 append하지 않는다.

---

## 12. 실험용 pgvector 적재 구조

운영 `search.rule_search_documents.embedding`과 분리된 실험 schema를 사용한다.

```text
embedding_ab_fault_standard.experiment_runs
  run_id
  repeat_id
  corpus_version
  query_set_version
  ground_truth_version
  created_at
  metadata

embedding_ab_fault_standard.rule_corpus
  run_id
  corpus_version
  document_id
  rule_id
  rulebook_id
  embedding_text_version
  embedding_text
  embedding_text_hash
  metadata

embedding_ab_fault_standard.document_vectors__<model_key>
  run_id
  repeat_id
  model_key
  document_id
  document_type
  rule_id
  embedding_provider
  embedding_model
  embedding_revision
  embedding_dim
  embedding_vector vector(<native_dimension>)
  inference_ms
  input_token_count
  metadata

embedding_ab_fault_standard.query_vectors__<model_key>
  run_id
  repeat_id
  model_key
  query_id
  embedding_vector vector(<native_dimension>)
  inference_ms
  metadata

embedding_ab_fault_standard.retrieval_results
  run_id
  repeat_id
  model_key
  query_id
  retrieval_track
  rank
  document_id
  rule_id
  cosine_distance
  exact_or_ann

embedding_ab_fault_standard.metric_results
  run_id
  repeat_id
  model_key
  split
  slice_key
  metric_name
  metric_value
  ci_low
  ci_high
```

완료 조건:

```text
model-repeat별 document vector = 277
model-repeat별 final test query vector = 50
인정기준 전체 model-repeat 결과 = 7 x 3 = 21
NULL vector = 0
dimension != model_manifest.native_dimension = 0
duplicate (run_id, repeat_id, model_key, document_id) = 0
embedding_text_hash mismatch = 0
model revision 누락 = 0
NaN/Inf = 0
L2 norm 허용범위 이탈 = 0
```

최종 모델이 확정되기 전 운영 임베딩을 교체하지 않는다.

모델 간 벡터 공간은 호환되지 않으므로 `model_key`가 다른 document vector와 query vector를 절대로 조합하지 않는다. HNSW index도 모델별 partition 또는 별도 테이블에 만든다.

---

## 13. 검색 실행

### 13.1 Exact cosine 우선

```sql
SELECT
    v.document_id,
    v.rule_id,
    v.embedding_vector <=> CAST(:query_vector AS vector(<native_dimension>)) AS cosine_distance
FROM embedding_ab_fault_standard.document_vectors__<model_key> AS v
WHERE v.run_id = :run_id
  AND v.model_key = :model_key
  AND v.document_type = 'rule_summary'
ORDER BY cosine_distance ASC, v.document_id ASC
LIMIT 50;
```

Rule 문서는 277개뿐이므로 exact 검색 비용이 작다. HNSW 근사 오차와 모델 품질 차이를 분리하기 위해 모델 선정은 exact 결과로 수행한다.

Top-50을 원본 산출물로 저장하고 공식 지표는 Top-10까지 계산한다. 거리 동률은 `document_id ASC`로 결정해 실행마다 순서가 바뀌지 않게 한다.

### 13.2 Rule 순위

1차 코퍼스는 Rule당 `rule_summary` 하나이므로 `document_id`와 `rule_id`가 사실상 1:1이다.

```text
exact Top-10 documents
→ rule_id Top-10
→ qrels 평가
```

Evidence Retrieval에서는 같은 Rule의 여러 문서가 상위 결과를 독점할 수 있으므로 다음 두 결과를 모두 저장한다.

```text
raw_document_ranking
rule_dedup_ranking
```

### 13.3 Evidence Retrieval은 두 모드로 나눈다

| 모드 | 검색 범위 | 평가 질문 |
|---|---|---|
| `E1_global` | 근거 문서 3,516개 전체 | 사용자 질의만으로 올바른 Rule의 근거가 회수되는가 |
| `E2_conditional` | 정답 또는 검색 Top-K Rule의 문서만 | Rule을 찾은 뒤 근거 문단을 정확히 찾는가 |

`E1_global`은 Rule별 문서 수 차이의 영향을 받으므로 raw document 순위와 rule-dedup 순위를 모두 보고한다. `E2_conditional`은 실제 파이프라인의 `Rule 후보 → 근거 검색` 구조를 더 직접적으로 평가한다. 두 점수를 평균내지 않는다.

Rule별 집계는 다음 세 방식을 모두 산출하되 사전 주 지표는 `rule_summary` 트랙의 점수다.

```text
max_score(rule)                  # 가장 강한 문서 1개
mean_top3_score(rule)            # Rule 안 상위 3개 평균
reciprocal_rank_fusion_by_type   # 문서유형별 순위 결합
```

문서 수가 많은 Rule이 유리한지 `documents_per_rule` 구간별 성능도 보고한다. 집계식을 test 결과를 본 뒤 선택하지 않는다.

### 13.4 HNSW 보조 평가

품질 상위 2개 모델만 동일 파라미터로 평가한다.

```text
operator class = vector_cosine_ops
m = 16
ef_construction = 64
search ef = 동일 값
```

확인 지표:

```text
HNSW Recall@10 against exact Top-10
index build time
index size
DB search latency p50/p95
```

277개 Rule에 HNSW는 성능상 필수는 아니므로 인덱스가 exact보다 빠르지 않아도 실패가 아니다. HNSW는 향후 심의사례·판례 통합 또는 전체 근거 문서 확장을 대비한 운영성 확인이다. 모델별 HNSW를 같은 테이블에 섞지 않고 모델 partition별로 생성한다.

### 13.5 지연시간 측정 프로토콜

```text
query embedding cold: 모델 load 포함, 5회
query embedding warm: warm-up 20회 후 100회, batch=1
exact DB search: warm-up 20회 후 query 50개 x 5회
HNSW DB search: 동일 query와 반복수
동시성: 1로 고정한 단일 요청 지연 + 별도 batch throughput
보고: p50, p95, p99, 평균, 표준편차
```

API 모델의 네트워크 지연과 로컬 GPU 추론 지연은 별도 열에 기록한다. API 호출 위치, 네트워크와 retry 횟수를 manifest에 남기고 순수 모델 품질 지표와 지연 지표를 섞지 않는다.

---

## 14. 평가 지표

### 14.1 1차 모델 선정 지표

| 지표 | 의미 |
|---|---|
| `Rule Hit@1` | 첫 번째 Rule이 relevance=2 정답인가 |
| `Rule Hit@3` | 상위 3개 안에 정답 Rule이 있는가 |
| `Rule Hit@5` | 상위 5개 안에 정답 Rule이 있는가 |
| `Rule MRR@10` | 첫 정답 Rule이 얼마나 위에 있는가 |
| `Rule nDCG@10` | 직접·부분 관련 Rule의 순위 품질 |
| `Rulebook Macro nDCG@10` | 대형 기준서가 평균을 지배하지 않는가 |

공동 주 지표:

```text
Exact Rule Hit@1
Rulebook Macro Rule nDCG@10
```

`Hit@1`은 바로 Core 계산으로 넘길 1위 Rule의 정확도를 나타내고, `nDCG@10`은 Neo4j 또는 후속 reranker가 활용할 후보 목록의 직접·부분 관련 순서를 나타낸다. 둘 중 하나만 높다고 승자로 확정하지 않는다.

보조 지표:

```text
Rule Hit@1
Rule Hit@3
Rule Hit@5
Rule MRR@10
```

### 14.2 인정기준 전용 보조 지표

| 지표 | 의미 |
|---|---|
| `Hard-negative Confusion Rate` | 비슷하지만 잘못된 Rule이 정답보다 위에 있는 비율 |
| `Party-direction Correct@K` | A/B 방향이 맞는 Rule을 회수하는가 |
| `Variant/Scenario Rule Hit@5` | 세부 시나리오가 있는 Rule을 찾는가 |
| `Adjustment-intent Hit@5` | 수정요소 쟁점에 맞는 Rule을 찾는가 |
| `Accident-type Macro nDCG@10` | 특정 사고유형 편향 확인 |
| `Intent Macro nDCG@10` | 질문 의도별 편향 확인 |
| `Long-document nDCG@10` | rule_summary token p90 이상에서 성능이 무너지는가 |
| `Rare-rulebook Floor` | query 수가 적은 기준서의 최저 nDCG/Hit@K |

계산 보조 annotation은 오류 분석에 사용하지만 모델 선정 점수로 직접 합치지 않는다.

### 14.3 Evidence Retrieval 지표

```text
Evidence Hit@5
Evidence Recall@10
Evidence nDCG@10
document_type별 Hit@K
정답 Rule 외 문서 혼입률
```

### 14.4 통계적 불확실성

```text
fact_card_id 군집 단위 paired bootstrap 10,000회
95% confidence interval
baseline 대비 paired difference
기준서별·의도별·사고유형별 지표
승패가 뒤집히는 query 목록
Hit@1 쌍 비교 McNemar exact test
```

모델마다 cosine 분포가 다르므로 raw cosine 절대값은 모델 간 품질 지표로 사용하지 않는다.

같은 fact card의 paraphrase가 여러 개면 query 단위 bootstrap은 표본 수를 부풀린다. 따라서 `fact_card_id`를 resampling 단위로 사용한다. 다중 모델 쌍비교의 p-value는 Holm 방식으로 보정하되, p-value 하나로 모델을 선정하지 않고 효과크기와 신뢰구간을 함께 보고한다.

### 14.5 오류 분류표

Top-1 오답은 최소 다음 중 하나로 분류한다.

```text
wrong_rulebook
same_family_wrong_condition
party_direction_reversed
signal_condition_missed
road_priority_missed
variant_or_scenario_missed
adjustment_intent_overweighted
long_document_truncation
query_underspecified
qrels_or_preprocess_issue
```

모델별 오답 수뿐 아니라 동일 query에서 어떤 모델만 성공/실패했는지 paired 비교표를 만든다. `qrels_or_preprocess_issue`가 발견되면 해당 query만 임의로 제거하지 않고 라벨 변경 절차에 따라 새 버전을 만든다.

### 14.6 최종 과실비율은 별도 downstream 지표다

임베딩 모델은 과실비율을 계산하지 않는다. Rule 검색 평가에서는 정답 숫자를 query에 넣지 않고 `rule_id` 검색 품질만으로 모델을 고른다. 이후 동일 계산기를 붙이는 downstream 실험에서만 다음을 측정한다.

```text
Rule Top-1 정확도
user/opponent party mapping 정확도
variant/scenario 정확도
적용 adjustment precision/recall
기본과실 exact match
최종 사용자 과실 MAE
최종 비율 exact match
needs_more_information 정확도
```

검색 Rule이 틀렸는데 우연히 같은 숫자가 나온 경우는 최종 비율 exact match로만 보이고 Rule 정확도에서는 실패다. 반대로 Rule은 맞지만 사고 사실이 부족하면 계산 실패가 아니라 `needs_more_information` 정답일 수 있다.

---

## 15. 속도, 비용 및 실행환경

### 15.1 데이터 규모

실제 `search_load_id=2` 분석값은 다음과 같다.

| 트랙 | 문서 | 총 문자 | `cl100k_base` 계획 token | 모델당 raw vector |
|---|---:|---:|---:|---:|
| Rule Matching | 277 | 163,978 | 104,103 | 약 1.08 MiB |
| Evidence 포함 전체 | 3,793 | 1,375,624 | 1,307,292 | 약 14.82 MiB |

```text
Track A raw vector 저장량은 6개 native 차원 합계(10,240차원)를 기준으로 별도 산정
```

실제 저장량은 테이블과 index overhead로 더 커지지만 데이터 파일 크기가 GPU 선택을 결정하지 않는다. VRAM은 모델 parameter, dtype, 실제 tokenizer 최대길이와 batch size가 결정한다. 이 실험은 embedding 연산보다 이미지 pull, 패키지 설치와 모델 다운로드 시간이 더 클 가능성이 높다.

### 15.2 기존 OJH Pod 보호와 신규 Pod 생성 원칙

> [!CAUTION]
> RunPod Pods 목록에 이미 존재하는 **`SKN27-3T-OJH`는 OJH 작업 전용 보호 대상**이다. 인정기준 임베딩 A/B 실험에서는 이 Pod를 절대 사용하거나 변경하지 않는다. 목록에서 이름을 확인하는 것 외에는 해당 행, 상세 화면, 더보기 메뉴를 열지 않는다.

2026-07-15 제공 화면에서 확인한 보호 대상 식별값은 다음과 같다. 이 값은 오조작 방지용 fingerprint일 뿐이며 인정기준 실험 자원이나 예산 단가로 사용하지 않는다.

```text
protected pod name: SKN27-3T-OJH
protected pod id: c7ool8ji5f17fj
protected GPU: RTX A6000 x1
화면 표시 비용: $0.57/hr
소유/용도: OJH 전용, 접근 금지
```

`SKN27-3T-OJH`에 대해 금지하는 작업은 다음과 같다.

```text
- Pod 행 클릭, 상세 화면 또는 더보기 메뉴 열기
- Connect, Web Terminal, SSH, Jupyter 접속
- 로그 열람, 파일 업로드, 명령 실행
- Start, Stop, Restart, Reset, Redeploy
- GPU, template, 환경변수, container disk 설정 변경
- 기존 Pod volume 또는 network volume 연결·분리·재사용
- Clone, Edit, Terminate, Delete
```

비용이 계속 발생해 보여도 `SKN27-3T-OJH`를 Stop 또는 Terminate하지 않는다. 상태와 비용에 관한 조치는 OJH 본인만 결정한다.

공통 Pod는 새로 만드는 것이 기본이 아니다. 공통 계획 11.2의 우선순위대로 `SKN27-embedding-ab-*` 등 임베딩 A/B용 기존 Pod가 있으면 사용자에게 Start와 JupyterLab 열기를 요청하여 그 Pod를 사용한다. 기존 임베딩 Pod가 없고 보호 대상 `SKN27-3T-OJH`만 있을 때에만 `00_preflight_orchestrator`가 신규 Pod를 생성한다. 기존 Pod의 GPU 불가·migration·GPU 변경은 사용자 확인 전 자동으로 처리하지 않는다. 이전 Track B vector·검색·점수는 재사용하지 않고, Track A 결과 경로를 새로 만든다.

`00_preflight_orchestrator`만 위 선택 분기와 필요 시 신규 Pod 생성을 수행한다. 인정기준 모델 작업은 manifest에 등록된 공통 Pod를 인계받아 자기 모델의 `batch_01_fault_standard`만 실행하며, Pod를 새로 만들거나 종료하지 않는다. 재사용·신규 여부와 무관하게 Pod Stop, Terminate, Delete는 결과 회수와 SHA 검증 후 사용자 확인 없이는 수행하지 않는다.

신규 리소스 식별 규칙:

```text
Pod name: SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>
예시: SKN27-3T-EMBED-AB-ALL-HR-20260715
금지 이름: SKN27-3T-OJH 또는 OJH가 포함된 이름
Container disk: 신규 생성
Pod volume: 신규 40GB 생성
Network volume: 연결하지 않음
기존 Storage/Volume: 선택하지 않음
```

신규 Pod 생성 직후 아래 값을 로컬 `runpod_resource_manifest.json`에 기록한다.

```json
{
  "protected_pod_name": "SKN27-3T-OJH",
  "protected_pod_id": "c7ool8ji5f17fj",
  "experiment_pod_name": "SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>",
  "experiment_pod_id": "신규 Pod ID",
  "experiment_volume_id": "신규 volume ID",
  "created_by": "작업자",
  "created_at": "ISO-8601 시각"
}
```

접속, 중지, 종료, 삭제 전에는 화면의 Pod 이름과 Pod ID가 manifest의 `experiment_pod_name`, `experiment_pod_id`와 모두 일치하는지 확인한다. 하나라도 다르거나 대상이 불명확하면 **아무 작업도 수행하지 않고 중단**한다. 특히 `SKN27-3T-OJH`에는 비용 절감 목적이라도 Stop이나 Terminate를 실행하지 않는다.

### 15.3 RunPod 후보군과 2026-07-15 표시 가격

RunPod 공식 Pods 가격 페이지의 Community Cloud 표시값 기준이다. 실제 가격과 재고는 지역·Cloud 유형·시점에 따라 바뀌므로 Pod 생성 직전 화면과 시작 시각의 가격을 캡처하거나 manifest에 적는다. VRAM은 RunPod 공식 GPU 유형 문서로 교차 확인한다. [RunPod GPU 가격](https://www.runpod.io/pricing), [RunPod GPU 종류와 VRAM](https://docs.runpod.io/references/gpu-types), [RunPod Pods 개요](https://docs.runpod.io/pods/overview)

| 후보 | VRAM | 표시 가격 | 이 데이터에서의 판단 |
|---|---:|---:|---|
| `A40` | 48GB | 약 $0.44/hr | **기본 권장**. Qwen3-4B를 최대 모델로 하는 로컬 모델 4종 순차 실행 |
| `RTX A6000` | 48GB | 약 $0.49/hr | A40 재고가 없을 때의 동급 대안 |
| `RTX 4090` | 24GB | 약 $0.69/hr | 연산은 빠르지만 코퍼스가 작아 다운로드 중심 총시간 대비 비용 이점이 작음 |
| `RTX A6000` | 48GB | 약 $0.49/hr | A40 재고가 없을 때의 동급 대안 |
| `L40S` | 48GB | 약 $0.99/hr | 대규모 처리량이 필요할 때만. 이번에는 과사양 |
| `A100 80GB` | 80GB | 약 $1.39/hr | 이번 후보·코퍼스에는 불필요 |

### 15.4 최종 GPU 선택

RunPod에서 실행하는 모델은 다음 **4개 로컬 공개모델**이다.

```text
Qwen/Qwen3-Embedding-0.6B
Qwen/Qwen3-Embedding-4B
BAAI/bge-m3
intfloat/multilingual-e5-large
```

`text-embedding-3-small`과 `text-embedding-3-large`는 RunPod에 모델을 다운로드하거나 GPU로 실행하지 않는다. 두 모델은 로컬 실행 코드에서 OpenAI Embeddings API를 호출하고, 실제 추론은 OpenAI 인프라에서 수행된다. 따라서 OpenAI 사용료는 RunPod 청구액과 별도다.

```text
기본 실행안:
A40 48GB x 1 또는 동급 48GB GPU
4개 로컬 모델을 같은 Pod에서 한 개씩 순차 실행
```

Qwen3 4B를 로컬 최대 모델로 하며, smoke에서 확정한 batch를 안정적으로 처리할 수 있는 GPU 한 대에서 로컬 모델 4종을 순차 실행한다. 실제 선택은 배포 직전 표시 재고·가격과 smoke의 peak VRAM을 manifest에 기록해 확정한다.

공개 인정기준과 합성 평가 질의만 전송한다면 Community Cloud로 시작할 수 있다. 실제 사용자 원문, 개인정보, 비공개 qrels가 들어가면 Secure Cloud 또는 사내 GPU로 전환한다. qrels는 벡터 생성에 필요하지 않으므로 기본적으로 RunPod에 보내지 않는다.

### 15.5 권장 신규 Pod 구성

```text
Pod name: SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>
GPU count: 1
GPU: A40 48GB 기본, 재고가 없으면 동급 48GB GPU 재승인
Template: RunPod 공식 PyTorch template
Container disk: 신규 30GB 이상
Volume disk: 신규 40GB 이상
Network volume: 일회성 실행에는 불필요
Python: 3.11
실행: model load → documents encode → queries encode → validate → save → unload
```

모델 cache는 공통 실험을 위해 새로 만든 volume의 `/workspace/.cache/huggingface`에 둔다. `SKN27-3T-OJH` 또는 다른 기존 Pod의 volume은 검색·선택·연결하지 않는다. 로컬 모델 4개·세 코퍼스·전체 3회 산출물을 모두 로컬로 회수하고 hash를 확인한 뒤에만 공통 오케스트레이터가 manifest에 기록한 신규 실험 Pod와 신규 volume을 종료·삭제한다. 인정기준 작업은 종료·삭제 권한을 갖지 않는다.

권장 패키지의 시작 조건:

```text
torch
transformers>=4.51.0
sentence-transformers>=2.7.0
FlagEmbedding
accelerate
numpy
pandas
pyarrow
psutil
```

Qwen3 공식 모델 카드가 요구하는 버전 하한을 따른다. 첫 실행은 기본 SDPA로 수행한다. FlashAttention 2는 선택사항이며, 설치 유무가 모델 간 비교 변수가 되지 않게 모든 Qwen run에 동일하게 적용하거나 전부 적용하지 않는다.

### 15.6 모델별 시작 설정

tokenizer audit 후 실제 p99/max에 맞게 `max_length`를 확정한다.

| 모델 | dtype | 시작 document batch | query batch | max_length 원칙 | OOM 순서 |
|---|---|---:|---:|---|---|
| Qwen3 0.6B | bf16 우선, 미지원 시 fp16 | 64 | 32 | audit max 이상, 최대 2048부터 시작 | 64 → 32 → 16 → 8 |
| Qwen3 4B | bf16 우선, 미지원 시 fp16 | 32 | 32 | audit max 이상, 최대 2048부터 시작 | 32 → 16 → 8 → 4 |
| BGE-M3 | fp16 | 64 | 32 | audit max 이상, 최대 2048부터 시작 | 64 → 32 → 16 → 8 |
| multilingual-e5-large | fp16 | 64 | 32 | 512 고정, 초과 0건만 본 실험 진행 | 64 → 32 → 16 → 8 |

위 batch는 공통 계획과 판례 계획에 맞춘 시작값이지 보장값이 아니다. 각 모델은 인정기준 20문서 smoke로 peak VRAM과 shape를 확인한 뒤 안정적인 batch를 확정한다. 모델별 document run 안에서는 batch를 고정하고, 변경 시 이전 부분 벡터와 섞지 않고 해당 모델을 처음부터 재생성한다. 처리량 측정 전 warm-up batch 3회를 제외한다.

### 15.7 실행 원칙과 보안 경계

```text
- RunPod에서는 벡터만 생성
- PostgreSQL DB를 외부에 노출하지 않음
- corpus JSONL/Parquet와 query_text만 전송
- qrels, DB 비밀번호, OpenAI API key, 서비스 secret은 전송하지 않음
- document/query parquet와 model manifest를 로컬로 회수
- 로컬에서 pgvector 적재와 Ground Truth 평가
- 모델 revision commit, license, dtype, pooling, batch, max_length 기록
- 회수 전 count/dimension/NaN/Inf/norm/hash 검증
```

OpenAI 두 모델은 로컬에서 API로 실행하고 RunPod와 분리한다. 이렇게 해야 API key가 Pod에 남지 않고 API 네트워크 지연과 GPU 추론 지연도 구분된다.

### 15.8 RunPod 예상 시간과 GPU 예산

RunPod 예산은 인정기준만의 별도 비용이 아니라 **로컬 모델 4개 × 세 코퍼스 × 전체 3회**에 대해 잡는다. 정확한 시간·단가·스토리지 비용·중단 상한은 공통 계획과 `runpod_resource_manifest.json`이 소유한다.

```text
공통 본 실험 문서 수: 9,515
  batch_01_fault_standard: 277
  batch_02_review_case: 904
  batch_03_precedent: 8,334

공통 query vector: 모델당 50 x 3 corpus adapter
RunPod 모델: Qwen3 0.6B -> Qwen3 4B -> BGE-M3 -> multilingual-e5-large
기본 GPU: Qwen3 4B smoke를 통과한 GPU x 1
공통 비용 중단 상한: $3.00
```

인정기준 작업의 완료 조건은 각 model-repeat에 대해 `batch_01_fault_standard` 문서 277개와 인정기준용 query vector 50개를 저장·검증하는 것이다. 이 배치가 끝나도 Pod를 종료하지 않고 같은 model-repeat의 심의사례 904개와 판례 8,334개 배치로 인계한다. RunPod 모델 4개·세 배치·세 repeat가 완료되고 산출물이 회수된 뒤에만 공통 오케스트레이터가 공통 Pod와 volume을 종료한다.

| GPU | 1시간 | 2시간 | 3시간 | 공통 실행 판단 |
|---|---:|---:|---:|---|
| A40 | 약 $0.44 | 약 $0.88 | 약 $1.32 | 기본 권장 |
| 동급 48GB GPU | 배포 시 확인 | 배포 시 확인 | 배포 시 확인 | A40 재고 대안 |

표는 GPU compute 계획값이며 실제 배포 화면의 가격과 storage 비용을 별도로 기록한다. 비용을 코퍼스별로 나눠 보고할 필요가 있으면 모델별 실측 GPU 초를 기준으로 배분하되, 청구·종료 판단은 공통 run 단위로 한다. 공통 오케스트레이터는 누적 예상 비용이 `$3.00`에 도달하기 전에 실행을 중단하고 원인을 점검한다.

### 15.9 OpenAI API 계획 비용 — RunPod와 별도

OpenAI 두 모델은 RunPod가 아니라 로컬의 모델별 작업에서 실행한다. 아래 값은 현재 `cl100k_base` token 추정치를 사용한 인정기준 계획값이며, 실제 비용은 API 응답의 usage와 실행 시점 공식 단가로 확정한다.

| 범위 | 추정 token | small $0.02/1M | large $0.13/1M |
|---|---:|---:|---:|
| Rule 277개 | 104,103 | 약 $0.0021 | 약 $0.0135 |
| 후속 Evidence 포함 전체 3,793개 | 1,307,292 | 약 $0.0261 | 약 $0.1700 |

본 실험의 인정기준 문서는 Rule 277개뿐이다. 두 OpenAI 모델의 문서 임베딩 계획 합계는 약 `$0.0156`이고, 인정기준 adapter로 만든 query 50개의 비용과 재시도 비용을 별도로 더한다. 3,793개 전체 생성은 상위 모델의 Evidence Retrieval 후속 실험이며 본 A/B 점수와 비용에 섞지 않는다.

OpenAI 비용은 RunPod 비용표에 합산해 청구되는 것이 아니라 OpenAI 계정에 별도로 청구된다. 따라서 결과 보고서에는 `runpod_total_usd`, `openai_api_total_usd`, `experiment_total_usd`를 분리해 기록한다. 공식 단가: [OpenAI small](https://developers.openai.com/api/docs/models/text-embedding-3-small), [OpenAI large](https://developers.openai.com/api/docs/models/text-embedding-3-large)

세 코퍼스 전체 OpenAI 비용은 공통 통합 작업이 각 모델의 세 corpus usage를 합산해 계산한다. 인정기준 문서는 `openai_usage_<model>_fault_standard.json`에 독립 기록하고, RunPod 공통 비용과 합쳐 임의의 인정기준 전용 Pod 비용으로 보고하지 않는다.

### 15.10 정확한 RunPod 실행 순서

```text
공통 사전 작업
1. search_load_id=2에서 본 실험용 rule_summary 277개 export
2. corpus/query manifest와 SHA-256 동결, qrels를 제외한 전송 bundle 생성
3. `00_preflight_orchestrator`가 OJH 보호 name/ID를 확인하고 공통 신규 Pod/volume만 생성
4. 공통 Pod name/ID/volume ID를 runpod_resource_manifest.json에 기록하고 preflight 완료

각 로컬 모델 작업: Qwen3 0.6B -> Qwen3 4B -> BGE-M3 -> E5
5. 자기 model lock을 획득하고 다른 모델이 실행 중이 아님을 확인
6. 해당 모델을 한 번 load하고 20문서 smoke로 shape/norm/VRAM 확인
7. `batch_01_fault_standard` 문서 277개 encode
8. 같은 모델·인정기준 adapter로 query 50개 encode
9. count/dimension/NaN/Inf/norm/hash 검증 후 인정기준 산출물 원자 저장
10. 같은 모델을 유지한 채 `batch_02_review_case`, `batch_03_precedent`로 인계
11. 세 코퍼스가 모두 끝난 뒤 model unload, gc, CUDA cache clear, model lock 해제

공통 회수·평가
12. 모델별 세 코퍼스 산출물의 hash와 행 수 재검증
13. 로컬 pgvector 실험 schema에 corpus_key/model_key를 분리해 적재
14. 인정기준 qrels로 exact cosine 평가와 통계 분석
15. 로컬 모델 4개와 세 코퍼스 전체 3회가 완료된 뒤 오케스트레이터만 공통 Pod/volume 종료
16. `SKN27-3T-OJH`의 상태가 변경되지 않았는지 이름과 표시 상태만 최종 확인
```

### 15.11 모델별 별도 작업 채팅 계약

작업을 시작할 때 다음 채팅 단위로 분리한다. 채팅 이름은 사람이 구분하기 위한 권장값이고, 실제 동시 실행 허용 여부는 `run_state.json`과 `runpod_execution_lock.json`이 결정한다.

| 작업 채팅 | model_key·역할 | 인정기준에서 할 일 | 병렬 허용 |
|---|---|---|---|
| `00_preflight_orchestrator` | 공통 사전검사·자원 소유자 | Query/qrels/해설/corpus SHA, 코드, DB, API key 존재, RunPod 로그인·잔액·보호 Pod 확인 | 다른 유료 작업 시작 전 단독 |
| `01_openai_small` | `openai_small_native_1536` | 로컬 API로 Rule 277 + Query 50 × 3회 생성·검증 | 세 repeat 모두 순차 |
| `02_openai_large` | `openai_large_native_3072` | 로컬 API로 Rule 277 + Query 50 × 3회 생성·검증 | 세 repeat 모두 순차 |
| `03_qwen3_06b` | `qwen3_06b_native_1024` | 공통 Pod에서 `batch_01_fault_standard` × 3회 실행 | 다른 GPU 모델과 병렬 금지 |
| `04_qwen3_4b` | `qwen3_4b_native_2560` | 공통 Pod에서 `batch_01_fault_standard` × 3회 실행 | 다른 GPU 모델과 병렬 금지 |
| `05_bge_m3` | `bge_m3_dense_native_1024` | 공통 Pod에서 `batch_01_fault_standard` × 3회 실행 | 다른 GPU 모델과 병렬 금지 |
| `06_e5_large` | `e5_large_native_1024` | 공통 Pod에서 `batch_01_fault_standard` × 3회 실행 | 다른 GPU 모델과 병렬 금지 |
| `07_integrate_evaluate` | 회수·적재·평가 | 18개 model-repeat 결과 적재·평가·집계·보고 | 모든 모델 검증 후 |

각 모델 채팅의 시작 입력에는 다음 값을 명시한다.

```text
run_group_id
model_key
공통 계획과 세 코퍼스 계획의 절대 경로
common query path + SHA-256
fault_standard corpus path + SHA-256 + expected_documents=277
fault_standard qrels v1.2 path + SHA-256 + expected_rows=111 + expected_queries=50
query_adapter_version + adapter_hash
document_adapter_version + adapter_hash
허용 output root
현재 allowed_next_model_key와 lock 상태
```

모델 채팅은 다음 규칙을 지킨다.

```text
1. 공통 Query, qrels, 해설집과 corpus를 수정하지 않는다.
2. 자기 model_key + corpus_key=fault_standard 경로 외에는 덮어쓰지 않는다.
3. 임시 파일에 저장한 뒤 count/dimension/finite/norm/ID/hash 검증 후 atomic rename한다.
4. 인정기준 Query vector는 같은 모델이어도 corpus_key별 별도 artifact로 생성한다.
5. Qwen은 인정기준 전용 instruction과 adapter_hash를 사용한다.
6. BGE-M3는 dense만, E5는 query:/passage: prefix와 512-token gate를 사용한다.
7. RunPod 채팅은 신규 Pod 생성·중지·종료·volume 삭제를 하지 않는다.
8. 다른 active_task_owner가 있거나 입력 SHA가 다르면 실행하지 않고 오케스트레이터에 반환한다.
9. OOM으로 batch를 바꾸면 해당 모델의 부분 결과를 폐기하고 같은 설정으로 처음부터 재생성한다.
10. 인정기준 277 + Query 50 검증 후 완료표를 갱신하고 같은 모델의 심의사례·판례 batch로 인계한다.
```

별도 채팅에 전달할 인정기준 전용 문장은 다음과 같이 고정한다.

```text
이 작업은 3코퍼스 공통 임베딩 A/B의 <model_key> 전용 작업이다.
공통 계획과 판례·인정기준·심의사례 계획을 모두 읽고, 공통 Query와 각 정답지를 수정하지 않는다.
인정기준에서는 search_load_id=2의 rule_summary 277개와 fault_common_queries_v1의 query_text 50개만 처리한다.
출력은 run_group_id/model_key/fault_standard 아래에 저장하고, corpus_key·model_key·adapter_hash가 모두 일치할 때만 완료한다.
RunPod 모델이면 manifest의 신규 공통 Pod만 사용하며 SKN27-3T-OJH에는 절대 접근하지 않는다.
```

### 15.12 비용 및 성능 기록

| 항목 | 단위 |
|---|---|
| Pod 표시 단가·Cloud 유형·지역 | USD/hr, Community/Secure, region |
| container pull·환경설치 | 초/분 |
| 모델 다운로드 | 초/분 |
| 모델 로딩 | 초 |
| document embedding | 초/분 |
| document throughput | docs/sec, tokens/sec |
| query warm latency | p50/p95/p99 ms |
| query cold start | p50/p95 ms |
| exact DB search | p50/p95/p99 ms |
| HNSW DB search | p50/p95/p99 ms |
| API/GPU 비용 | USD 및 실행시점 원화 |
| 최대 GPU 메모리 | GB |
| 벡터/index 저장공간 | MB |
| 실패·OOM·재시도 | 건 |

OpenAI 비용은 API 응답의 실제 token usage, RunPod 비용은 실제 청구액을 기준으로 확정한다. GPU 종류가 달라진 run의 처리량은 같은 표에 표시하되 모델 품질 점수와는 독립적으로 해석한다.

### 15.13 실패 대응표

| 실패 | 즉시 조치 | run 처리 |
|---|---|---|
| CUDA OOM | batch를 절반으로 감소 | 해당 모델 처음부터 재실행, 변경 이력 기록 |
| tokenizer overflow | overflow 목록 저장 | E5는 legacy 처리, 다른 모델은 max_length 재검토 |
| NaN/Inf 또는 norm 이상 | pooling·dtype·normalization 확인 | 해당 모델 벡터 전량 폐기 후 재실행 |
| 모델 revision 불명 | commit SHA 재조회 | revision 확정 전 정식 run 금지 |
| Pod 중단 | 파일 hash/행 수 검사 | 불완전 파일과 완전 파일을 섞지 않음 |
| `SKN27-3T-OJH`가 작업 대상으로 보임 | 즉시 아무 작업도 하지 않고 화면에서 이탈 | 사용자와 공통 오케스트레이터가 대상 name+ID를 확인할 때까지 RunPod 작업 전체 중단 |
| API rate limit | 지수 backoff와 idempotent batch | retry와 usage 기록 |
| corpus hash 불일치 | 전송·개행·정규화 확인 | 평가 중단, 새 export 금지 |

---

## 16. 실험 실행 단계

### Phase 0. 데이터와 정답지 준비

1. `source_batch_id=3`, `core_load_id=2`, `search_load_id=2`를 확인한다.
2. 공통 질문이 `common_fault_queries_v1.jsonl` 50행이고 SHA-256이 `a50921b0ea409ebfdd46d50c8ef632fb1fdac7c53b80ebb95fbb353c4ea02102`인지 확인한다. 질문지는 수정하지 않는다.
3. `fault_standard_qrels_v1.2.jsonl`이 111행·50 Query인지 검증한다.
4. q31이 `no_relevant_document`, `negative_control=true`인 한 행으로 qrels에 존재하는지 검증한다.
5. 문항별 해설 q01~q50과 qrels의 Rule·relevance·계산 annotation이 일치하는지 기계 검증한다.
6. q13이 `official_2023_차16-3`, 근거 298쪽, 사용자 최종 90, `source_evidence_review_status=approved`인지 확인한다.
7. 현재 query, qrels, 해설 SHA가 승인된 `ground_truth_manifest_v1.2.json`과 일치하는지 확인한다.
8. `rule_summary` 277개와 후속 evidence corpus 3,516개를 별도로 export한다.
9. canonical corpus SHA-256과 export 파일 SHA-256을 검증한다.
10. `rule_embedding_text_v1`을 생성하고 hash를 동결한다.
11. valid 277, review_required 0과 Core 무결성 결과를 manifest에 기록한다.
12. 공통 키를 사용하는 6개 후보 tokenizer length audit를 수행하고 E5 winner 자격을 확정한다.
13. 공통 runner, output 경로 차단, model/corpus key 조합과 pgvector 별도 schema를 로컬 fixture로 검증한다.

**Gate 0:** count/hash/라벨 검수가 하나라도 실패하면 GPU/API 실행을 시작하지 않는다.

### Phase 1. Smoke 실험

Smoke는 adapter·shape·파이프라인 오류만 확인하는 무점수 기술 검사다. 정식 품질 결과나 세 repeat 중 하나로 포함하지 않는다.

1. 10개 smoke query를 사용한다.
2. 6개 후보의 277 document와 10 query vector count/dim/norm을 확인한다.
3. 모델별 adapter, pooling과 native 차원 출력 계약을 검증한다.
4. exact cosine, tie-break와 qrels 평가 코드가 동일하게 동작하는지 확인한다.
5. 품질과 무관한 파이프라인 오류만 수정한다.

Smoke 결과로 모델을 탈락시키지 않는다. adapter나 pooling을 수정하면 모든 smoke 벡터를 폐기하고 재생성한다.

**Gate 1:** 모델별 vector 누락·차원오류·NaN/Inf·hash mismatch가 모두 0이어야 한다.

### Phase 2. 정식 Rule Matching 평가

1. `repeat_01`, `repeat_02`, `repeat_03`마다 Rule 277개와 동결된 final test 50개를 6개 모델로 전부 새로 임베딩한다.
2. 모델별 exact Top-50을 생성하고 Top-10 지표를 계산한다.
3. 공동 주 지표 Hit@1과 Rulebook Macro nDCG@10을 계산한다.
4. 기준서·의도·난이도·사고유형·문서길이 slice를 계산한다.
5. fact-card paired bootstrap 10,000회와 Hit@1 McNemar 검정을 수행한다.
6. hard negative와 paired 성공/실패 query를 블라인드 오류 분류한다.
7. 18개 model-repeat 결과의 개별 점수와 모델별 3회 평균·표준편차·min/max·rank 안정성을 계산한다.
8. 품질 상위 2개와 운영 대체 후보 1개를 정한다.

**Gate 2:** 정식 test를 본 뒤 adapter, qrels, template를 바꾸지 않는다. 변경이 필요하면 질문지는 그대로 둔 채 새 Ground Truth 버전으로 올리고 6개 모델 전체를 동일 버전으로 재평가한다.

### Phase 3. Evidence Retrieval

1. Rule 품질 상위 2개 모델만 진행한다.
2. 1차 RunPod/API 실행에서 미리 생성한 evidence/law/reference/note 3,516문서 벡터 중 상위 2개 모델 결과만 사용한다.
3. 최소 40개 query의 Evidence 전용 document-level qrels를 2인 검수한다.
4. `E1_global`과 `E2_conditional` exact 검색을 각각 수행한다.
5. raw document, rule-dedup, document_type과 documents-per-rule 편향을 분석한다.

**Gate 3:** Evidence 점수는 Rule Matching 점수와 평균내지 않는다. Rule winner를 뒤집으려면 별도 의사결정 기록이 필요하다.

### Phase 4. 운영성 평가

1. 상위 모델의 모델별 partition에 동일 HNSW parameter index를 생성한다.
2. exact 대비 ANN Recall@10을 측정한다.
3. 정해진 warm-up/반복수로 embedding과 DB latency를 측정한다.
4. index build 시간·크기, GPU/API 비용과 운영 난이도를 비교한다.
5. 최종 모델 1개와 장애 대체 모델 1개를 승인한다.

**Gate 4:** 최종 승인 전 `search.rule_search_documents.embedding`은 비어 있는 중립 상태로 유지한다.

### Phase 5. 입력 보강 후속 실험

선정된 임베딩 모델을 고정하고 동일한 최소 30개 사고 fact card를 다음 입력 variant로 평가한다.

```text
Text Only
Text + Vision
Text + OCR
Text + Vision + OCR
```

모든 variant는 같은 `rule_id` Ground Truth를 사용한다.

보험사 주장은 검색 입력 variant에서 제외한다. `claimed_ratio/reason_text`는 계산 결과와 비교하는 별도 Agent 평가에만 사용한다.

---

## 17. 최종 과실 계산 및 Neo4j와의 관계

본 문서의 모델 A/B는 정확한 `rule_id` 후보 검색까지만 평가한다.

최종 운영 목표는 다음 구조다.

```text
사용자 query_text
→ 선정 임베딩 모델 + pgvector Top-K
→ Neo4j로 후보 Rule의 관계 검증
→ Core에서 확정 수치 조회
→ 공통 과실 계산기
```

### 17.1 Vector Only 후속 비교안

```text
query_text
→ Vector Top-K
→ Vector 1위 Rule 선택
→ Core hydrate
→ 공통 계산기
```

### 17.2 Vector + Neo4j 후속 비교안

```text
query_text
→ Vector Top-K
→ Neo4j A/B·variant·adjustment 검증 및 후보 재정렬
→ Core hydrate
→ 동일한 공통 계산기
```

두 방식은 같은 사고 입력과 같은 최종 Ground Truth를 사용한다.

```text
correct_rule_id
correct_party_mapping
correct_variant/scenario
correct_adjustments
correct_base_ratio
correct_final_ratio
needs_more_information 여부
```

Neo4j는 최종 수치 원본이 아니라 관계 검증용 projection이다. 최종 숫자는 Core에서 조회하고 계산기는 두 실험군이 공동으로 사용한다.

### 17.3 과실 계산기 입력 계약을 먼저 고정한다

Neo4j 설계와 무관하게 계산기가 받을 최소 구조를 먼저 정의한다.

```json
{
  "rule_id": "official_2023_차47-3",
  "user_party_key": "B",
  "opponent_party_key": "A",
  "variant_id": null,
  "scenario_id": null,
  "satisfied_adjustment_ids": [],
  "fact_evidence_refs": [],
  "missing_facts": []
}
```

계산 순서:

```text
1. Core에서 rule_id와 A/B 기본과실 조회
2. 사용자 차량이 A인지 B인지 mapping
3. 명시적으로 충족된 variant/scenario 선택
4. 증거로 확인된 adjustment만 target party에 적용
5. 기준서의 상·하한 및 합계 100 규칙 적용
6. 사용자:상대방 비율로 변환
7. 정보가 부족하면 계산하지 않고 missing_facts 반환
```

보험사 `claimed_ratio`는 위 계산 입력이 아니다. 계산 결과가 나온 뒤 차이와 설명을 비교하는 출력 검증용이다. Vector Only와 Vector + Neo4j 모두 이 동일 계산기와 동일 fact card를 사용해야 검색/관계 검증의 효과만 비교할 수 있다.

### 17.4 임베딩 A/B 정답지와 계산 A/B 정답지는 연결하되 분리한다

| 단계 | 정답 단위 | 정식 임베딩 모델 선정에 사용 |
|---|---|---:|
| Rule retrieval | `rule_id`, relevance 0/1/2 | 예 |
| Evidence retrieval | `document_id/chunk_id + rule_id` | 후속 |
| 관계 검증 | party, variant/scenario, adjustment | 후속 |
| 계산 | base ratio, final ratio, missing facts | 후속 |

따라서 Vector Only와 Vector + Neo4j의 최종 비율 정답지가 달라지는 것이 아니다. 같은 fact card에서 같은 정답을 사용하되, 두 방식이 그 정답에 도달하는 과정만 다르다.

---

## 18. 모델 선정 규칙

가중합 점수 하나로 품질·비용을 섞지 않고 다음 순서로 판단한다.

### 18.1 Gate A: 실행 적격성

```text
commercial use/license 검토 완료
model revision 고정
dimension = model_manifest.native_dimension
document/query 누락 = 0
NaN/Inf = 0
input/hash mismatch = 0
winner 후보의 silent truncation = 0
```

하나라도 실패하면 품질 점수가 높아도 winner가 될 수 없다.

### 18.2 Gate B: 검색 품질

1. `Exact Rule Hit@1`과 `Rulebook Macro Rule nDCG@10` 공동 주 지표를 본다.
2. baseline `text-embedding-3-small` 대비 paired delta와 95% CI를 본다.
3. `Hit@3/5`, `MRR@10`, hard-negative confusion을 확인한다.
4. 특정 기준서·사고유형·긴 문서에서 급락하는 후보를 제외한다.
5. 정답 숫자가 아니라 Rule과 party 방향을 맞혔는지 대표 오류를 직접 검토한다.

품질 동급의 사전 기준:

```text
Hit@1 절대 차이 <= 0.02
Rulebook Macro nDCG@10 절대 차이 <= 0.02
두 지표의 paired 95% CI가 0을 포함
특정 rulebook Hit@5가 최고 모델보다 0.05 이상 낮지 않음
```

### 18.3 Gate C: 운영성 tie-break

품질 동급 후보에만 다음 순서로 적용한다.

```text
1. warm query p95 latency
2. 1,000 query당 비용과 전체 재임베딩 비용
3. peak VRAM과 필요한 GPU 등급
4. 배포·모니터링·장애복구 난이도
5. API 의존성, 데이터 정책, license
```

최종 모델 1개와 장애 시 대체 모델 1개를 기록한다. `winner`, `runner_up`, `selection_reason`, `rejected_reason_by_model`을 결과 manifest에 남긴다.

권장 방어선:

```text
최고 모델 대비 Rule Hit@5 차이 <= 0.03
특정 rulebook의 Hit@5 차이 <= 0.05
document/query vector 누락 0
HNSW Recall@10 against exact >= 0.98
```

50개 test에서 차이가 작고 신뢰구간이 넓으면 승자를 억지로 확정하지 않는다. 모델 간 승패가 갈린 query와 희소 사고유형을 중심으로 새 공통 query 또는 fact card를 추가해 `test_v2`를 만들고, 기존 test 점수와 새 점수를 분리해 보고한다.

---

## 19. 결과 보고서 구조

```text
1. 실험 목적과 한 줄 결론
2. 인정기준 수집·전처리·적재 품질
3. Rule corpus와 제외 문서 유형
4. corpus/query/qrels version
5. 모델과 입력 adapter
6. qrels 작성·독립검수·라벨 일치도
7. 후보 모델·공식 adapter·token length audit
8. RunPod 후보 비교와 실제 선택 근거
9. 전체 Rule 정량 점수표와 95% CI
10. 기준서·난이도·길이·사고유형·의도별 점수표
11. hard negative 및 paired 오류 분석
12. 비용·VRAM·throughput·지연 비교
13. 대표 성공·실패 query
14. Ground Truth 변경 이력
15. Gate A/B/C 판정표
16. 최종 모델과 대체 모델 선정
17. Evidence Retrieval 결과
18. Vision/OCR 보강 후속 결과
19. Vector + Neo4j 및 과실 계산 후속 실험 항목
```

필수 재현성 식별자:

```text
run_id
git_commit
source_batch_id
core_load_id
search_load_id
canonical_corpus_sha256
corpus_version
embedding_text_version
embedding_text_hash
query_set_version
ground_truth_version
model_key
model_revision
embedding_dim
query_adapter_version
document_adapter_version
runtime_gpu
runtime_gpu_vram
runtime_dtype
runtime_batch_size
runtime_max_length
runtime_pooling
runtime_library_versions
runpod_cloud_type
runpod_region
runpod_price_per_hour
runpod_billed_seconds
distance_metric
top_k
```

---

## 20. 권장 산출물

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/
  common_fault_queries_v1.jsonl
  common_fault_query_schema_v1.json
  query_manifest.json

etl/fault_cases/evaluation/fault_standard/embedding_ab/v1/
  pilot/
    fault_standard_qrels_pilot_v1.jsonl  # 공통 파일럿 10개, 기술 smoke용
  ground_truth/
    fault_standard_qrels_v1.2.jsonl
    fault_standard_qrels_v1.2_해설.md
    ground_truth_manifest_v1.2.json       # 승인·동결된 현재 manifest
    README.md
  fault_standard_robustness_queries_v1.jsonl
  fault_standard_fact_cards_v1.jsonl
  labeling_guide.md
  labeling_disagreements.jsonl

etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_<experiment_group_id>/repeat_<NN>/
  00_input/
    common/queries.jsonl
    common/query_manifest.json
    corpora/fault_standard/
      documents.jsonl
      corpus_manifest.json
  00_manifest/
    run_group_manifest.json
    run_state.json
    runpod_resource_manifest.json
    runpod_execution_lock.json
    model_manifests/<model_key>.json
    eval_snapshots/fault_standard/
      queries.jsonl
      qrels.jsonl
      ground_truth_manifest.json
  01_token_audit/<model_key>/fault_standard/token_length_audit.json
  02_vectors/<model_key>/fault_standard/
    document_embeddings.parquet
    query_embeddings.parquet
    artifact_manifest.json
    failures.jsonl
  03_retrieval/fault_standard/<model_key>/
    raw_top50.jsonl
    primary_top10.jsonl
    retrieval_manifest.json
  04_metrics/fault_standard/
    scores.csv
    query_details.jsonl
    bootstrap.json
    cost_latency.json
    error_analysis.csv
    cosine_similarity_summary.csv
    cosine_similarity_query_details.jsonl
```

인정기준 코사인 유사도는 `raw_top50.jsonl`에만 보관하지 않는다. 모델·회차별 Top-1 유사도 평균·중앙값·p95, 최초 정답 Rule 유사도, Top-1 정답·오답 유사도 평균과 그 차이, exact Rule이 없는 Query의 Top-1 유사도를 별도 집계한다. 이 값과 `cosine_similarity = 1 - cosine_distance` 계산식을 공통 스코어 비교표와 분석 리포트에 한국어 컬럼 설명과 함께 표시하되 모델 선정용 nDCG@10 평균에는 섞지 않는다.

`evaluation/`은 사람이 관리하는 고정 질문·정답 원본이고 `artifacts/embedding_ab_shared/track_a_6models_native_3repeats/`는 재생성 가능한 Native-6 실행 산출물이다. 모델 채팅은 evaluation 파일을 수정하지 않으며, `<model_key>/fault_standard` 외 다른 모델·코퍼스 디렉터리에 쓰지 않는다.

최종 공유 문서는 인정기준 폴더에 별도 복사하지 않고 공통 run의 두 파일을 정본으로 사용한다.

```text
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_<experiment_group_id>/05_report/
  pgvector_3코퍼스_임베딩_모델_AB_스코어_비교표.md
  pgvector_3코퍼스_임베딩_모델_AB_분석_리포트.md
  corpora/fault_standard/corpus_result.md
```

두 파일의 필수 표·분석·완료 게이트는 공통 계획 14장을 따른다. 인정기준 전용 상세 결과는 `05_report/corpora/fault_standard/corpus_result.md`에만 둔다.

---

## 21. 완료 체크리스트

```text
[ ] rule_summary 277개 snapshot 및 hash 동결
[ ] search_load_id=2 전체 3,793개 canonical hash 일치
[ ] evidence/law/reference/usage 3,516개가 1차 코퍼스에서 제외됐는지 확인
[ ] valid 277 / review_required 0 확인
[ ] rule_embedding_text_v1 277개 생성
[ ] 6개 후보 token length audit 완료
[ ] E5 512-token overflow 및 winner 자격 기록
[x] 공통 정식 query 50개 층화 선정 및 SHA 확인
[x] 질문지 `fault_common_queries_v1`을 수정하지 않고 그대로 유지
[x] 인정기준 qrels v1.2 Rule 판정 110행 작성
[x] q31을 qrels의 무정답 negative-control 한 행으로 복원하여 전체 111행·50 Query 확보
[x] 불완전한 q31 전용 query metadata 파일 제거
[x] q01~q50 문항별 해설집과 qrels 구조 일치 확인
[x] 나머지 40개 인정기준 qrels 1차 작성
[x] relevance 2 Query 39개 / no-exact Query 11개 / 서로 다른 exact Rule 30개 확인
[x] final test 50 구성 확인 / robustness 별도 10은 후속 작업
[x] qrels가 사고유형 10개군·난이도 25/21/4 분포를 보존하는지 검증
[x] 최종 피드백 반영 및 q31 qrels 구조 수정 완료
[x] q13 `official_2023_차16-3` 최종 판정 및 pending 상태 해소
[x] query v1 / qrels v1.2 / 해설 SHA를 ground_truth_manifest_v1.2에 기록하고 동결
[ ] 보험사 주장이 retrieval query에 포함되지 않음
[ ] 모델별 작업 채팅이 공통 계획과 세 코퍼스 계획을 모두 읽었는지 확인
[ ] 공통 model_key 6개가 판례·공통 계획과 정확히 일치
[ ] run_group_id / run_state / output root 생성 및 덮어쓰기 방지 테스트
[ ] OpenAI small 1,536 / large 3,072차원 확인(`dimensions` 축소 인자 미사용)
[ ] 보호 대상 `SKN27-3T-OJH` / `c7ool8ji5f17fj` 접속·변경·복제·종료 금지 공유
[ ] 기존 임베딩 A/B Pod 확인 결과와 `resource_origin=reused|new`를 manifest로 확인
[ ] 기존 Pod면 사용자 Start·JupyterLab 열기 후 사용, 없으면 신규 Pod name/ID/volume ID를 manifest에 기록
[ ] 보호 Pod name/ID와 선택된 experiment Pod name/ID를 runpod_resource_manifest.json에 기록
[ ] 모든 접속·중지·재시작·종료 전 선택된 experiment Pod name+ID 이중 대조
[ ] 로컬 모델 revision과 adapter manifest 저장
[ ] model-repeat별 document vector 277개, 전체 4,986개 확인
[ ] model-repeat별 final test query vector 50개, 전체 1,050개 확인
[ ] dimension/NaN/Inf/norm/hash 검사 통과
[ ] pgvector exact cosine 결과 생성
[ ] Rule Hit@1/3/5, MRR@10, nDCG@10 계산
[ ] Rulebook/intent/accident type/difficulty/length 지표 계산
[ ] hard-negative confusion 분석
[ ] fact-card paired bootstrap 10,000회 및 McNemar 수행
[ ] 공통 GPU 선택 사유와 실제 RunPod 단가 기록(A40 48GB 또는 동급)
[ ] 모델별 peak VRAM/batch/max_length/throughput 기록
[ ] 인정기준 산출물 회수 후 Pod를 유지하고 다음 corpus batch로 인계
[ ] RunPod 5개 모델·세 코퍼스·전체 3회 완료 후 결과 SHA를 확인하고 Pod 종료 여부를 사용자에게 확인
[ ] `SKN27-3T-OJH` 상태가 변경되지 않았음을 최종 확인
[ ] 상위 2개 HNSW 운영성 평가
[ ] 비용·지연 기록
[ ] Evidence Retrieval 후속 평가
[ ] Text/Vision/OCR 입력 보강 실험 분리
[ ] 운영 embedding 교체 여부 별도 승인
[ ] 최종 결과 보고서 작성
```

---

## 22. 팀 공유용 요약

현재 인정기준은 네 기준서 819쪽에서 277개 Rule을 구조화하고, 품질수정 전처리 `batch_id=3`을 Staging에 적재한 뒤 `core_load_id=2`로 승격했다. Search는 `search_load_id=2`이며 `rule_summary` 277개, `evidence_chunk` 2,200개, 법규 848개, 참고사례 285개, 적용설명 183개로 총 3,793개다. 현재 임베딩과 모델 label은 모두 NULL인 모델 중립 상태다.

임베딩 모델 A/B/n은 3,793개 전체를 섞지 않고 정확한 Rule 후보를 찾는 `rule_summary` 277개만 1차 코퍼스로 사용한다. 모든 모델은 같은 `rule_embedding_text_v1`, 같은 공통 final test `query_text` 50개와 같은 인정기준 `rule_id` qrels를 사용한다. 질문 분포는 사고유형 10개군 기준 8/7/5/8/4/3/4/6/3/2, 난이도 easy/medium/hard 기준 25/21/4다. 후보는 OpenAI small/large, Qwen3 0.6B/4B, BGE-M3와 multilingual-e5-large의 세 코퍼스 공통 6개다.

정답지는 고정 질문 `fault_common_queries_v1`을 바꾸지 않고 `fault_standard_qrels_v1.2.jsonl` 하나에 q01~q50을 모두 담았다. Rule 판정 110행과 q31 무정답 negative-control 1행을 합쳐 총 111행이며, relevance 2가 있는 Query는 39개, exact Rule이 없는 Query는 11개, 서로 다른 exact Rule은 30개다. q31 전용 metadata 파일은 별도 의미 없이 구조 분리용으로만 존재했으므로 제거했다. 문항별 해설집도 같은 q31 처리로 수정했다. q13 최종 판정과 query·qrels·해설 SHA를 `ground_truth_manifest_v1.2.json`에 기록해 물리적으로 동결했다. 사용자 텍스트 baseline을 먼저 평가하고 Vision/OCR 보강은 선정 모델을 고정한 후 별도 paired 실험으로 확인한다.

공통 6개 모델을 `repeat_01/02/03`에서 독립 실행한다. 각 repeat는 `fault_standard 277 → review_case 904 → precedent 8,334` 전체와 코퍼스별 Query 50개를 새로 임베딩하며 이전 vector를 재사용하지 않는다. OpenAI small/large는 로컬 API에서, Qwen 0.6B/4B·BGE-M3·E5는 공통 오케스트레이터가 만든 신규 실험 Pod에서 모델 하나씩 실행한다. 인정기준 batch가 끝나도 Pod나 모델을 독자 종료하지 않고 다음 코퍼스로 인계한다. 기존 `SKN27-3T-OJH`와 그 storage/volume은 OJH 전용 보호 자원이므로 어떤 이유로도 접근·변경·중지·복제·삭제하지 않는다.
