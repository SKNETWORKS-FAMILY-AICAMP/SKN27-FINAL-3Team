# pgvector 심의사례 임베딩 모델 A/B 실험 계획

개정 기준일: 2026-07-17

> [!IMPORTANT]
> 세 코퍼스의 실제 임베딩 생성 순서, 모델별 별도 작업 채팅, batch, 병렬 허용 범위와 RunPod 소유권은 [3코퍼스 공통 임베딩 모델별 실행 계획](../pgvector_3코퍼스_공통_임베딩_모델별_실행계획.md)을 따른다. 이 문서는 심의사례 corpus, 심의사례 adapter, 심의사례 qrels와 평가 규칙을 소유한다. 심의사례만을 위한 별도 RunPod를 만들지 않으며, Track A는 최신 6개 모델의 기본/native 차원을 비교한다.

모델별 작업 채팅은 `공통 실행 계획 -> 판례 계획 -> 인정기준 계획 -> 이 심의사례 계획` 순서로 네 문서를 모두 읽는다. 공통 계획은 모델 순서·batch·병렬 범위·RunPod와 공통 산출물 경로를 소유하고, 이 문서는 `batch_02_review_case`의 904개 입력, 심의사례용 query adapter, 승인 qrels와 평가 완료 조건을 소유한다. 충돌 시 공유 자원과 실행 순서는 공통 계획을, 심의사례 데이터와 판정·지표는 이 문서를 우선한다.

> [!IMPORTANT]
> Track A는 6개 모델 각각에 대해 심의사례 904개 document와 Query 50개를 `repeat_01`, `repeat_02`, `repeat_03`에서 모두 새로 생성한다. 이전 vector 재사용은 허용하지 않으며, 심의사례 기준 6 × 3 = 18개 model-repeat 결과를 만든다.

## 1. 문서 목적

이 문서는 `review_case_db`에 적재된 자동차사고 과실비율분쟁 심의사례만을 대상으로 임베딩 모델 품질을 비교하기 위한 실험 계획이다.

심의사례를 독립 코퍼스로 분리하고, 심의사례의 4종 구조화 청크와 심의번호, 참고기준, 결정비율을 반영한 전용 Ground Truth 작성 방법을 확정한다.

이번 실험의 질문은 다음 하나다.

```text
동일한 심의사례 904개 청크와 동일한 평가 질의를 사용했을 때,
어떤 임베딩 모델이 사용자의 사고 설명과 쟁점에 맞는 심의사례를 가장 잘 검색하는가?
```

검색기 A/B, BM25, hybrid, reranker 비교는 이 실험의 1차 범위가 아니다. 모델 선정이 끝난 뒤 별도 검색 조합 실험에서 다룬다.

---

## 2. 먼저 확정할 결론

### 2.1 세 코퍼스가 공통 Query 50개를 사용한다

판례, 인정기준, 심의사례는 **동일한 사용자 사고 Query 50개와 동일한 `query_id`**를 사용한다. Query는 어느 한 코퍼스의 문서 문장을 복사하지 않은 사용자 중심 사고 설명이어야 하며, 코퍼스별로 다시 작성하거나 표현을 바꾸지 않는다.

공유하는 것은 다음의 평가 계약이다.

```text
공유:
- agent_input.query_text를 query 임베딩의 논리 입력으로 사용
- 동결된 embedding_text_v1을 document 임베딩의 논리 입력으로 사용
- 같은 Native-6 모델 후보와 모델별 기본/native 차원 정책
- exact cosine 기반 품질 평가
- Case Hit@K, Case MRR@10, Case nDCG@10
- 공통 Query 50개와 query version
- 동일한 Ground Truth 동결 및 버전 관리 원칙

심의사례 전용:
- review_case_id와 review_no를 정답 사건 식별자로 사용
- reference_chart_key, 결정비율, 당사자 역할을 보조 정답으로 사용
- 4종 chunk_type별 기대 검색 결과를 평가
- 공통 Query를 수정하지 않고 심의사례 전용 qrels만 작성
```

파일 관계는 다음과 같다.

```text
공통 common_fault_queries_v1.jsonl
  ├─ review_case_qrels_v1.jsonl
  ├─ fault_standard_qrels_v1.jsonl
  └─ precedent_qrels_v1.jsonl
```

동일한 `query_id`라도 정답 문서와 관련도는 코퍼스별로 독립 판정한다. 심의사례 모델 성능은 `review_case_qrels_v1.jsonl`만 사용해 계산하며 다른 두 정답지를 섞지 않는다.

### 2.2 정답지는 사례 단위가 1차이고 청크 단위가 2차다

심의사례 한 건은 다음 4개 청크를 가진다.

```text
case_overview
arguments
evidence_issue
decision
```

사용자 질문 하나에 같은 사례의 여러 청크가 모두 유효할 수 있다. 정답을 `chunk_id` 하나로만 지정하면 동일한 정답 사례의 더 적합한 다른 청크를 찾은 모델이 오답 처리된다.

따라서 평가 우선순위는 다음과 같다.

```text
1차 정답: review_case_id 또는 review_no
2차 정답: 질문 의도에 맞는 expected_chunk_types
보조 검증: reference_chart_key, 결정비율, 당사자 역할
```

### 2.3 공통 Query를 먼저 동결하고 심의사례 정답을 판정한다

심의사례 qrels 작성자는 동결된 공통 Query 50개를 입력으로 받는다. 각 Query에 대해 심의사례 226건 전체에서 유효한 정답을 찾고, 모델명과 검색 순위를 보지 않은 상태에서 관련도를 판정한다. 유효한 심의사례가 없다면 억지로 정답을 만들지 않고 `judgment_status=no_relevant_document`로 기록한다.

이 순서를 지켜야 Query가 특정 코퍼스 정답에 맞춰 변형되거나 특정 모델의 검색 결과가 Ground Truth에 섞이는 것을 막을 수 있다.

---

## 3. 현재 데이터 상태

### 3.1 임베딩 테스트 전 데이터 코멘트

현재 심의사례 데이터는 **임베딩 생성 직전 단계까지 완료된 상태**다. 원본 PDF 수집, 사례 분리, 본문 정리, 구조화 필드 파싱, 의미 단위 청크 생성, 품질검증, PostgreSQL 적재와 건수 검증까지 끝났고 임베딩만 생성하지 않았다.

자동 검증상 임베딩 실험을 막는 치명적 오류는 없다. 다만 이는 구조, 건수, 필수 필드, 파싱 규칙에 대한 전수 자동검증 결과이며, 226건 모두를 사람이 원문 PDF와 대조한 전수 수동검수라는 뜻은 아니다. qrels에 등록하는 모든 정답 사례와 `no_relevant_document` 판정의 경계 후보는 원문과 다시 대조한다.

### 3.2 전처리 진행 순서

```text
보험개발원 게시물에서 원본 PDF 수집
-> PDF 472쪽 텍스트 추출
-> 심의번호와 페이지 경계를 이용해 사례 226건 분리
-> 머리말, 꼬리말, 페이지 번호, 목차 이동 문구 정리
-> 목차 항목 226건과 본문 사례 226건 연결
-> 상단 사고분류, 참고기준, 표준행동, 결정비율 파싱
-> 주장, 입증자료, 주요쟁점, 결정근거, 결정이유 파싱
-> A/B 차량을 청구인/피청구인 역할 및 최종비율로 정규화
-> 사례별 구조화 document 생성
-> 사례별 4종 의미 단위 chunk 생성
-> 필수 필드, 역할, 비율, 문구 누출, chunk 생성 여부 검증
-> JSONL 저장 및 review_case_db 적재
-> 산출물 건수와 DB 테이블 건수 일치 검증
```

### 3.3 전처리 및 적재 결과

2026-07-15 현재 산출물과 DB를 다시 검증한 결과다.

| 항목 | 결과 | 판정 |
|---|---:|---|
| 원본 PDF 페이지 | 472 | 정상 |
| 분리된 심의사례 | 226 | 정상 |
| `parse_status=valid` 문서 | 226 | 정상 |
| 수동검토 필요 문서 | 0 | 정상 |
| 구조화 청크 | 904 | 정상 |
| 원문 추적용 source 청크 | 285 | 정상, 모델 A/B 제외 |
| 품질 리포트 | 226 | 정상 |
| 목차 항목/본문 연결 | 226/226 | 정상 |
| fatal flag | 0 | 정상 |
| `header_road_context=null` | 116 | 원문 제목에 ` - 도로/상황 맥락` 구간이 없는 정상 선택값 |
| 헤더 구조 보정 | 12 | 당사자 접두어 없는 고속도로 사례를 장 제목 위치로 파싱 |
| warning flag | 0 | 정상 |
| 빈 `chunk_text` | 0 | 정상 |
| 중복 `chunk_id` | 0 | 정상 |
| 목차/탐색 문구 누출 청크 | 0 | 정상 |
| DB 적재 불일치 | 0 | `is_complete=true` |
| DB 임베딩 | 0 | 모델별 신규 생성 대상 |

`header_road_context`는 제목에 공백을 포함한 ` - ` 구분자 뒤 도로 맥락이 원래 존재하는 사례에서만 채워지는 선택 필드다. 구분자가 없는 `single_group` 116건의 `null`은 정상값이므로 warning으로 만들지 않는다. 당사자 접두어가 없는 고속도로 사례 12건은 장 제목 다음의 첫 상단 분류행을 사용하는 구조 규칙으로 보정했으며, `header_title_raw`와 중복되지 않는 `case_title`이 모두 채워진다. 이제 `header_road_context_missing`은 구분자가 있는데 우측 맥락 추출에 실패한 경우에만, `header_parse_failed`는 상단 분류행 자체를 찾지 못한 경우에만 발생한다.

### 3.4 청크 기준과 실제 결과

구조화 청크는 고정 글자 수가 아니라 PDF의 의미 섹션을 기준으로 사례당 4개를 만든다.

| `chunk_type` | 포함 내용 | 개수 | 최소 | 평균 | p95 | 최대 |
|---|---|---:|---:|---:|---:|---:|
| `case_overview` | 심의번호, 사고분류, 사례명, 기준상황, 신호·도로, A/B 행동, 결정비율, 사고내용 | 226 | 209자 | 278자 | 325자 | 453자 |
| `arguments` | 청구인 주장, 피청구인 주장 | 226 | 177자 | 281자 | 356자 | 426자 |
| `evidence_issue` | 입증자료, 주요쟁점 | 226 | 125자 | 218자 | 274자 | 308자 |
| `decision` | 결정근거, 결정이유, 최종비율 | 226 | 303자 | 638자 | 848자 | 915자 |

검증 결과 226개 사례 모두 위 4종 청크를 정확히 하나씩 가진다. 전체 `chunk_text`는 약 319,680자, UTF-8 약 0.77MB이며 JSONL 파일 전체는 약 1.19MB다. 현재 최대 청크가 915자이므로 구조화 청크에는 길이 기반 추가 분할이 발생하지 않았다.

별도 `review_case_source_chunks`는 원문 추적용이다. 각 사례의 `clean_text`를 1,800자, overlap 200자로 자른 285개 청크이며 구조화 청크와 내용이 중복되므로 이번 임베딩 모델 A/B 코퍼스에서는 제외한다.

### 3.5 현재 데이터의 임베딩 전 주의점

원본 `review_case_chunks.chunk_text`는 의미 본문이 잘 보존돼 있지만 `reference_chart_key`, `fault_type`, `party_type` 같은 일부 구조화 메타데이터는 모든 청크 본문에 명시적으로 들어 있지 않다. 반대로 BM25용 `search_text`는 검색 메타데이터가 많이 반복돼 dense 모델 비교에 과한 입력이다.

따라서 원본 청크와 DB를 수정하지 않고, 이번 실험 전용 파생 입력인 `embedding_text_v1`을 한 번 생성해 공통 본 실험 6개 모델 모두 동일하게 사용한다. 자세한 구성은 5장에서 확정한다.

### 3.6 실험 사용 데이터

| 항목 | 현재 값 | 실험 사용 여부 |
|---|---:|---:|
| 심의사례 문서 | 226 | Ground Truth 작성에 사용 |
| 구조화 청크 | 904 | document embedding에 사용 |
| 원문 추적용 source 청크 | 285 | 제외 |
| DB 임베딩 | 0 | 모델별 신규 생성 |

실험 코퍼스는 구조화 청크 904개로 고정하고 파생 입력의 hash를 동결한다.

현재 원본 스냅샷:

```text
etl/fault_cases/artifacts/review_case_output/preprocessed/review_case_documents.jsonl
etl/fault_cases/artifacts/review_case_output/preprocessed/review_case_chunks.jsonl
```

기존 `심의사례 검색 A-B 평가 및 로컬 리랭커 계획.md`의 임베딩 904개 완료 표기는 이전 실행 상태다. Track A의 세 정식 repeat에서는 6개 모델의 904개 document와 Query 50개를 매번 원문으로부터 새로 생성하며 기존 native 산출물을 재사용하지 않는다.

---

## 4. 실험 범위

### 4.1 포함

- 심의사례 구조화 청크 904개 동결
- OpenAI 2개, Qwen3 2개, BGE-M3, E5의 최신 6개 모델 비교
- 모델별 document/query embedding 생성
- 별도 `embedding_ab` 스키마에 모델별 벡터 적재
- pgvector exact cosine 검색
- 사례 단위 Ground Truth 평가
- 질문 의도별, 청크 유형별 오류 분석
- 모델별 비용, 생성 시간, 검색 지연 기록
- 최종 후보에 한해 HNSW 운영성 보조 평가

### 4.2 제외

- 판례 및 인정기준과의 통합 검색
- BM25, Elasticsearch vector, hybrid 검색기 비교
- reranker를 포함한 최종 점수 비교
- 청크 크기 또는 청크 전략 A/B
- OCR 및 vision evidence를 붙인 query augmentation
- 생성형 답변의 문장 품질 평가
- 운영 Agent의 source quota와 결과 병합 정책

모델 A/B에 BM25나 reranker를 섞으면 임베딩 모델 자체의 차이를 설명하기 어려워진다. 이들은 최종 임베딩 모델 선정 후 후속 실험으로 분리한다.

---

## 5. 입력 스키마

### 5.1 서비스 입력과 임베딩 입력을 구분한다

서비스 또는 Agent는 여러 필드를 받을 수 있지만, 이번 검색 실험에서 실제로 임베딩하는 논리 입력은 하나다.

```json
{
  "agent_input": {
    "raw_user_text": "상대차가 적색신호에 직진해서 부딪혔는데 저는 녹색신호로 직진 중이었어요.",
    "query_text": "신호기 있는 사거리에서 사용자 차량은 녹색 직진, 상대 차량은 적색 직진 중 충돌한 사고"
  }
}
```

| 필드 | 임베딩 여부 | 용도 |
|---|---:|---|
| `agent_input.query_text` | 예 | query embedding의 공통 논리 입력 |
| `agent_input.raw_user_text` | 아니오 | 원문 보존과 query 생성 근거 |
| 보험사 주장 비율 | 원칙적으로 제외 | 검색 정답을 유도하거나 노이즈가 될 수 있음 |
| OCR/영상 설명 | 제외 | 후속 query augmentation 실험 |
| 출력 형식 요청 | 제외 | 검색과 무관한 제어 정보 |

### 5.2 문서 임베딩 입력 `embedding_text_v1`

모델 A/B의 문서 입력은 원본 `chunk_text` 자체가 아니라, 필요한 메타데이터를 한 번만 붙인 파생 필드 `embedding_text_v1`으로 고정한다.

```text
[출처] 자동차사고 과실비율분쟁 심의사례
[심의번호] 2018-051544
[당사자유형] 차대차
[사고유형] 한쪽 차량 신호위반 사고
[과실유형] 기본과실
[참고기준] 201
[기준상황] 신호등 있음, 사거리, 녹색 직진, 적색 직진
[청크유형] 사례 개요
[결정비율] A(청구) : B(피청구) = 0 : 100
[본문]
<원본 chunk_text>
```

생성 규칙:

```text
1. 모든 모델이 동일한 문자열을 사용한다.
2. 빈 메타데이터 라인은 넣지 않는다.
3. 같은 필드를 두 번 반복하지 않는다.
4. 원본 chunk_text는 수정하지 않는다.
5. 줄바꿈은 LF, Unicode는 NFC로 정규화한다.
6. 앞뒤 공백과 연속 공백만 정리하고 의미 문장은 바꾸지 않는다.
7. embedding_text_v1과 SHA-256 embedding_text_hash를 snapshot에 저장한다.
```

`reference_chart_key`, `fault_type`, `party_type`, `review_no`는 심의사례 검색에 중요한 구조화 정보지만 현재 모든 `chunk_text`에 노출되지는 않는다. 이를 넣어야 도표번호, 기본·수정과실, 당사자 유형 질의도 공정하게 평가할 수 있다.

사용하지 않는 입력:

```text
BM25용 search_text
원문 추적용 source chunk
reranker용 query-document 조합 텍스트
모델별로 다르게 만든 메타데이터
```

`search_text`는 BM25 회수율을 위해 많은 필드를 반복하므로 dense 모델 자체 비교에 사용하지 않는다. 모델 선정이 끝난 뒤 최종 1개 모델에 한해 `raw chunk_text`와 `embedding_text_v1`의 입력 구성 ablation을 별도로 수행한다.

모델별 prefix나 instruction은 허용하되 원래의 `query_text`와 `embedding_text_v1` 의미는 바꾸지 않는다.

### 5.3 공통 평가 Query 레코드

공통 Query 50개의 기준 경로:

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl
```

실제 스키마 예시:

```json
{
  "query_id": "fault_common_q01",
  "raw_user_text": "저는 녹색 신호에 직진했는데 오른쪽에서 적색 신호를 무시한 차량이 들어와 충돌했습니다. 이런 사고와 비슷한 자료를 찾고 싶습니다.",
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

임베딩 모델에는 `query_text`만 전달한다. 나머지 필드는 층화 집계, 오류 분석, 재현성 관리에 사용한다. 공통 Query 파일에는 특정 코퍼스의 Ground Truth version을 넣지 않는다. 코퍼스별 qrels manifest가 `eval_set_version`과 공통 Query SHA-256을 참조한다.

---

## 6. 공통 Query 50개 수용 기준

### 6.1 100개에서 50개로 줄인 이유와 운영 방식

정식 평가셋은 기존 후보 100개 중 사고군 비율, 난이도, 세부 당사자 유형을 유지하도록 층화 선정한 공통 Query 50개를 사용한다. 단순히 앞의 50개를 자른 것이 아니며, 파일럿 10개의 `query_id`와 질문 문장을 유지하고 나머지 40개를 같은 기준으로 라벨링한다.

50개로 줄이는 목적은 세 코퍼스마다 독립 정답지를 사람 검수하는 비용을 통제하면서 relevance 판정 품질을 확보하기 위해서다. 모든 모델이 같은 50개를 사용하므로 모델 간 paired 비교 계약은 유지된다. 표본이 줄어든 불확실성은 paired bootstrap과 query별 승패 목록으로 함께 보고하며, 차이가 불명확하면 희소 사고군 Query를 후속 버전에 추가한다.

현재 동결 전 원본의 구성은 다음과 같다.

| accident_group | 사고군 | 기존 100개 | 정식 50개 | 정식 비율 |
|---|---|---:|---:|---:|
| `signalized_intersection` | 신호 교차로 | 15 | 8 | 16% |
| `unsignalized_intersection` | 무신호 교차로 | 15 | 7 | 14% |
| `turn_and_lane_rule` | 회전·차로규칙 | 10 | 5 | 10% |
| `lane_change_and_rear_end` | 차로변경·추돌 | 15 | 8 | 16% |
| `road_entry_and_parking` | 주차·도로진입 | 8 | 4 | 8% |
| `roundabout` | 회전교차로 | 7 | 3 | 6% |
| `highway` | 고속도로 | 8 | 4 | 8% |
| `vehicle_motorcycle` | 차대이륜차 | 12 | 6 | 12% |
| `vehicle_pedestrian` | 차대보행자 | 5 | 3 | 6% |
| `vehicle_bicycle_pm` | 차대자전거·PM | 5 | 2 | 4% |
| 합계 | - | 100 | 50 | 100% |

| difficulty | 개수 | 비율 |
|---|---:|---:|
| `easy` | 25 | 50% |
| `medium` | 21 | 42% |
| `hard` | 4 | 8% |
| 합계 | 50 | 100% |

자전거·PM 2개는 자전거 1개와 개인형 이동장치 1개로 유지한다. hard는 `fault_common_q11`, `fault_common_q34`, `fault_common_q38`, `fault_common_q50`이며 표본이 4개뿐이므로 hard slice를 단독 모델 선정 지표로 사용하지 않는다.

선정된 Query는 파일 순서대로 `fault_common_q01`부터 `fault_common_q50`까지 연속 재번호했다. manifest의 `query_ids`와 세 코퍼스 qrels는 동일한 번호 매핑을 사용한다.

질문 문장도 함께 정리됐다. 기존 파일럿 10개의 `query_id`, `raw_user_text`, `query_text`는 유지했고, 아직 qrels가 없던 `fault_common_q05`, `fault_common_q07`, `fault_common_q15`, `fault_common_q18`는 이중 위반·보행자신호·시야제한처럼 난도를 불필요하게 올리던 복합조건을 줄여 medium 문장으로 단순화했다. 사건번호, 심의번호, 인정기준 ID나 원문의 고유한 긴 문구를 넣어 검색을 쉽게 만드는 방식은 계속 금지한다.

현재 `query_manifest.json` 기준은 `current_query_count=50`, `query_sha256=a50921b0ea409ebfdd46d50c8ef632fb1fdac7c53b80ebb95fbb353c4ea02102`, `annotation_status=approved`다. 심의사례 작업에서는 이 50개 Query를 추가, 삭제, 재작성하거나 `query_id`를 바꾸지 않는다. 새 query version을 만들면 새 hash를 qrels manifest와 모든 run snapshot에 반영한 뒤 별도 실험으로 실행한다.

심의사례 파일럿 10개를 포함해 50개 전체 Ground Truth를 작성했다. 2026-07-16 3차 원문 검수와 최종 판정 수용 후 판정별 한 줄인 qrels 89줄을 `evaluation/review_case/embedding_ab/v1/ground_truth/`의 유일한 `approved` 정답 원본으로 동결했다. 현재 상태는 `has_relevant_document 41개 / no_relevant_document 9개`, graded answerable coverage 82%, 관련 판정 80건, 서로 다른 정답 사례 71건이다. Recall/MRR 기준인 `relevance >= 2` 정답이 있는 Query는 32개로 binary answerable coverage는 64%다. qrels SHA-256은 `093f70b78484c8d9b4989801debca52e1aae5debbfa9e1788285bd8cae0c6c1f`다.

### 6.2 심의사례 커버리지와 기대 청크 점검

검색 코퍼스는 심의사례 226건과 구조화 청크 904개 전체를 그대로 사용한다. 공통 Query가 먼저 확정되므로 `서로 다른 1차 정답 사례 최소 60건`, `사례당 Query 최대 2개` 같은 심의사례 역설계 기준은 적용하지 않는다. 대신 qrels 작성 후 다음 커버리지를 보고한다.

```text
전체 공통 Query 수 = 50
심의사례 정답 존재 Query 수
no_relevant_document Query 수
graded answerable coverage = R1 이상 판정 Query / 50
binary answerable coverage = R2 이상 판정 Query / 50
서로 다른 정답 review_case_id 수
한 사례에 연결된 Query 수 분포
accident_group별/difficulty별 정답 존재율
```

현재 공통 Query에는 별도 `intent_type` 필드가 없다. 질문별 기대 청크 유형은 심의사례 qrels의 `expected_chunk_types`에서 판정하며 `chunk_id`와 일치하는 주 청크 유형 하나만 저장한다. 사고 상황은 `case_overview`, 쟁점·입증은 `evidence_issue`, 당사자 주장은 `arguments`, 결정 근거와 비율은 `decision`을 우선 기대값으로 사용한다.

정답 존재율이 낮아도 유효하지 않은 사례를 억지로 연결하지 않는다. 필요하면 공통 50개와 분리된 심의사례 보조 평가셋을 후속으로 만들 수 있지만, 그 점수를 공통 50개 기반 3코퍼스 비교 점수에 섞지 않는다.

### 6.3 사고 유형 기준의 2차 분포 점검

질의 의도와 별개로 다음 사고 유형이 한쪽에 과도하게 몰렸는지 점검한다.

- 신호 또는 비신호 교차로, 직진 대 직진
- 좌회전, 비보호 좌회전, 유턴
- 차로 변경, 합류, 끼어들기, 추월
- 추돌, 급정지, 안전거리
- 주차장, 후진, 도로 외 진입
- 보행자, 횡단보도
- 이륜차, 자전거, 개인형 이동장치
- 고속도로, 갓길 및 희소 사고 유형

심의사례 작성자가 유형별 Query 수량을 조정하지 않는다. 부족하거나 편향된 유형이 발견되면 공통 Query 소유자에게 검토 의견을 전달하고, 공통 query version이 갱신된 경우에만 세 코퍼스가 함께 새 버전을 사용한다.

### 6.4 기존 5개 샘플 쿼리의 역할

`review_case/search/sample_queries.py`의 5개 쿼리는 검색 코드가 동작하는지 확인하기 위한 smoke set으로 유지한다.

정식 공통 50개 평가에는 포함하지 않는다. smoke set은 파이프라인 동작 확인에만 사용하며 별도 `query_id`를 부여해 공통 Query와 혼합하지 않는다.

### 6.5 공통 Query 인수 검증 규칙

공통 Query를 전달받으면 다음 항목만 검증한다. 심의사례 쪽에서 문장을 독자적으로 수정하지 않는다.

```text
- 정확히 50개이며 query_id가 `query_manifest.json.query_ids`와 일치
- query_id가 `fault_common_q01`~`fault_common_q50`의 연속 ID이고 중복 없음
- query_text가 비어 있지 않음
- 특정 판례번호, 심의번호, 인정기준 ID 등 정답 식별자 누출 없음
- 판례 문체가 아니라 사용자 사고 설명으로 이해 가능
- eval_set_version과 파일 hash가 제공됨
- 사고군 분포 8/7/5/8/4/3/4/6/3/2 및 난이도 25/21/4가 manifest와 일치
```

검증 실패가 있으면 공통 Query 원본을 직접 고치지 않고 공통 Query 소유자에게 수정 요청한다. 최종 동결된 동일 파일을 세 코퍼스가 함께 사용한다.

---

## 7. Ground Truth 작성 방법

### 7.1 Ground Truth 파일을 query 파일과 분리한다

정답지 원본은 `pilot/`와 분리된 `ground_truth/` 폴더에 둔다.

```text
etl/fault_cases/evaluation/review_case/embedding_ab/v1/ground_truth/
  review_case_qrels_v1.jsonl         # 유일한 정답 원본, 89줄 모두 approved
  ground_truth_manifest.json         # 입력·코퍼스·정답지 건수와 SHA
  labeling_report.md                 # 분포, no relevant, 검수 우선순위
  qrels_explanation.md               # 1~50번 문제별 정답, 원문 근거, 등급 이유와 오답 포인트
```

`review_case_qrels_v1.jsonl`은 Query 50개에 대응하는 유일한 Ground Truth 원본이다. 관련 심의사례 판정마다 한 줄을 사용하므로 50줄보다 많을 수 있으며, 사람 검수 시에는 1번부터 50번까지 문제별 풀이를 담은 `qrels_explanation.md`를 함께 사용한다. 해설은 정답 원본이 아니며 manifest에서 qrels와 해설 각각의 SHA를 고정한다.

2026-07-16 최종 판정 수용 후 89행 모두 `adjudication_status=approved`로 동결했다. 이 필드와 `label_source`는 평가 gain에는 사용하지 않지만 승인·검수 이력을 보존하므로 제거하지 않는다. 평가 validator는 89행 모두 approved인지와 qrels SHA가 `ground_truth_manifest.json`에 기록된 값과 일치하는지만 확인한다.

예시:

```json
{"query_id":"fault_common_q01","judgment_status":"has_relevant_document","review_case_id":"review_case_2019_008384","review_no":"2019-008384","chunk_id":"review_case_2019_008384_case_overview","relevance":2,"expected_chunk_types":["case_overview"],"reason":"기본 사고구조는 같지만 사용자 차량의 좌회전차로 직진이라는 추가 수정요소가 있음","adjudication_status":"approved","label_source":"pilot_draft_promoted","query_set_version":"fault_common_queries_v1","ground_truth_version":"review_case_qrels_v1"}
```

flat qrels는 판정 1건당 JSONL 한 줄을 사용한다. 같은 Query에 관련 심의사례가 여러 건이면 같은 `query_id`의 행이 여러 개 생길 수 있으므로 전체 qrels 행 수는 50보다 클 수 있다. 1차 Case 평가에서는 동일 `review_case_id`의 여러 청크 판정 중 최대 relevance를 사용하고, `chunk_id`는 청크 유형 보조평가에 사용한다. `reference_chart_key`와 결정비율처럼 동결 코퍼스가 소유한 값은 qrels에 중복하지 않고 `review_case_id`로 조인하여 값의 불일치를 막는다.

심의사례에서 유효한 정답을 찾지 못한 Query는 다음처럼 별도 상태로 기록한다.

```json
{
  "query_id": "fault_common_q07",
  "judgment_status": "no_relevant_document",
  "adjudication_status": "approved",
  "label_source": "pilot_draft_promoted",
  "query_set_version": "fault_common_queries_v1",
  "ground_truth_version": "review_case_qrels_v1",
  "reason": "녹색 직진 자동차와 맞은편 적색 우회전 자동차가 충돌한 직접 차대차 사례를 찾지 못함"
}
```

`relevance` 의미:

```text
3 = 사고 구조, 차량 행동, 핵심 쟁점이 직접 일치하는 최우선 정답 사례
2 = 핵심 사고 관계는 일치하고 일부 조건 또는 수정요소만 다른 강한 관련 사례
1 = 상위 사고유형은 유사하고 일부 조건이 참고 가능하지만 이진 정답으로는 쓰지 않는 약한 관련 사례
0 = 표면 키워드만 같거나 방향, 행동, 당사자 유형이 명시적으로 반대인 hard negative
```

Recall/MRR의 이진 정답 기준은 `relevance >= 2`다. R1은 nDCG의 낮은 gain과 오차 분석에만 사용하며, R1만 있는 Query는 Recall/MRR 분모에서 제외한다. 진행 형태는 유사하지만 법적 성격이나 수정요소가 다른 사례는 R1이 될 수 있으나, 방향·행동·당사자 유형이 명시적으로 반대인 사례는 qrels 정답에서 제외한다.

### 7.2 라벨링 순서

1. 동결된 공통 `common_fault_queries_v1.jsonl`의 version과 hash를 확인한다.
2. `query_manifest.json.query_ids`의 연속 50개 순서대로 심의사례 226건 전체에서 후보를 수집한다.
3. 후보 사례별 fact card를 만들고 Query와 사실관계를 대조한다.
4. 같은 `reference_chart_key`, 유사한 `standard_scenario_keywords`, 유사 사고유형의 이웃 사례까지 검토한다.
5. 모델명과 검색 순위를 보지 않고 후보를 `3/2/1/0`으로 판정한다.
6. 유효한 후보가 없으면 `no_relevant_document`의 근거를 기록한다.
7. 두 번째 검수자가 정답 사례와 no-relevant 판정을 독립 검수한다.
8. 불일치를 합의하고 `review_case_qrels_v1.jsonl`을 갱신한다.
9. Query 50개 커버리지, ID 참조와 SHA를 검증해 manifest를 갱신한다.
10. 두 번째 검수 완료 후 새 버전을 `approved`로 동결한다.
11. 모든 모델 평가가 끝날 때까지 승인된 정답지를 수정하지 않는다.

fact card 권장 필드:

```text
review_case_id
review_no
party_type
header_accident_group
header_road_context
case_title
fault_type
reference_chart_key
standard_scenario_keywords
signal_condition
road_feature
standard_a_behavior
standard_b_behavior
accident_content
main_issue
evidence_text
decision_reason
claimant_final_ratio
respondent_final_ratio
```

### 7.3 참고기준 번호만으로 정답을 만들지 않는다

같은 `reference_chart_key`를 공유하는 심의사례라도 수정과실, 신호 상태, 차로 위반, 증거 유무가 다를 수 있다. 따라서 같은 도표번호라는 이유만으로 모두 정답 처리하지 않는다.

판정 순서는 다음과 같다.

```text
1. 사고 구조와 차량 행동 일치
2. 핵심 쟁점 또는 수정요소 일치
3. 신호, 도로, 충돌 관계 일치
4. 참고기준 번호 일치
5. 결정비율과 당사자 역할 일치
```

`reference_chart_key`는 보조 지표와 후보 수집에 유용하지만 단독 Ground Truth는 아니다.

### 7.4 결정비율과 당사자 역할을 코퍼스와 함께 검증한다

`0:100` 같은 비율만 비교하면 사용자 차량과 상대 차량이 뒤집힌 결과를 정답으로 오인할 수 있다. 결정비율은 동결 코퍼스의 `claimant_final_ratio`, `respondent_final_ratio`를 `review_case_id`로 조인한다. 사용자 차량이 청구인인지 피청구인인지 원문으로 확정할 수 있는 비율형 질의에 한해서 다음 파생값을 평가 snapshot에 만든다.

```text
user_vehicle_role = claimant | respondent | unknown
joined_claimant_ratio
joined_respondent_ratio
```

현재 `review_case_qrels_v1`은 검색 relevance 정답지이므로 위 코퍼스 소유값을 중복 저장하지 않는다. 사용자 차량의 당사자 역할을 확정할 수 없는 질의는 사례 검색 품질만 평가하고 비율 정확도 지표에서는 제외한다. 역할 판정을 정답지에 영구 저장해야 한다면 별도 검수 후 qrels 버전과 hash를 올린다.

### 7.5 모델 결과에서 새 정답을 발견한 경우

모델이 Ground Truth에 없지만 실제로 유효한 사례를 찾을 수 있다. 이 경우 해당 실행만 정답으로 바꾸지 않는다.

```text
1. 모델 정보를 가리고 사람이 적합성을 재검수
2. 모든 모델에 동일하게 적용할 qrels 새 버전 생성
3. review_case_qrels_v1에서 v2로 버전 증가
4. 기존 결과와 새 결과를 모두 보존
5. 공식 비교표는 동일 qrels 버전으로 전 모델 재계산
```

---

## 8. 모델 후보와 통제 변수

### 8.1 공통 본 실험 후보 6개

이 실험은 이름은 A/B지만 실제로는 A/B/n 비교다. 판례·인정기준·심의사례의 종합 비교가 가능하도록 세 코퍼스 모두 아래 6개 모델을 공식 기본/native 차원으로 실행한다.

| model_key | 모델 | 출력 차원 | 실행 위치 |
|---|---|---:|---|
| `openai_small_native_1536` | `text-embedding-3-small` | 1,536 | 로컬 OpenAI API |
| `openai_large_native_3072` | `text-embedding-3-large` | 3,072 | 로컬 OpenAI API |
| `qwen3_06b_native_1024` | `Qwen/Qwen3-Embedding-0.6B` | 1,024 | RunPod |
| `qwen3_4b_native_2560` | `Qwen/Qwen3-Embedding-4B` | 2,560 | RunPod |
| `bge_m3_dense_native_1024` | `BAAI/bge-m3` | 1,024 | RunPod |
| `e5_large_native_1024` | `intfloat/multilingual-e5-large` | 1,024 | RunPod |

후보 근거:

- OpenAI 공식 문서는 `text-embedding-3-small`과 `text-embedding-3-large`를 각각 1M token당 현재 $0.02, $0.13으로 안내하고, Embeddings API의 `dimensions` 옵션은 `text-embedding-3` 계열에서 지원한다. [small 모델](https://developers.openai.com/api/docs/models/text-embedding-3-small), [large 모델](https://developers.openai.com/api/docs/models/text-embedding-3-large), [Embeddings API](https://developers.openai.com/api/reference/resources/embeddings/methods/create)
- Qwen3 0.6B/4B는 각각 native 1024/2560차원을 사용하고, 두 모델 모두 동일한 심의사례 query instruction을 적용한다. [Qwen3 0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B)
- BGE-M3는 1024차원과 8192 길이를 지원하며 query instruction이 필수는 아니다. 이번에는 dense vector만 사용한다. [BGE-M3](https://huggingface.co/BAAI/bge-m3)
- multilingual-e5-large는 1024차원이고 비영어 입력에도 `query:`와 `passage:` prefix를 요구하며 예제 기준 최대 512 token에서 truncate한다. [multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large)

### 8.2 8B 제외와 6개 후보 확정 근거

Qwen 공식 다국어 MTEB 평균에서 4B는 69.45, 8B는 70.58로 차이가 1.13점이지만 파라미터 수는 2배이고 native 벡터 차원은 2,560에서 4,096으로 60% 증가한다. 세 코퍼스 전체를 3회 반복하는 본 실험에서는 GPU 메모리, 처리 시간, 벡터 저장량과 검색 연산량 증가가 반복되므로 Qwen3-4B를 Qwen 계열 품질 상한 대표로 확정한다. 8B는 공식 6개 모델 비교에 포함하지 않으며 필요할 때 별도 후속 확장 실험에서 검증한다. 이 결정은 실행 결과를 본 뒤의 탈락이 아니라 사전 후보 선정 기준이다. 근거는 [Qwen3-Embedding-4B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-4B)와 [Qwen3-Embedding-8B 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-Embedding-8B)다.

### 8.3 사전 우승 모델을 정하지 않는다

Qwen3 0.6B·4B, OpenAI small/large, BGE-M3, E5를 같은 50개 Query와 승인 qrels로 평가한다. 최종 결정은 nDCG@10, Hit@1, MRR@10, bootstrap CI와 비용·지연·저장량의 Pareto 관계를 분석한 뒤 내린다.

### 8.4 E5 길이 제한 처리

`embedding_text_v1`을 E5 tokenizer로 검사해 512 token을 초과하는 건수를 먼저 기록한다. 한 건이라도 초과하면 E5만 조용히 truncate하지 않는다.

```text
overflow = 0:
  E5를 정식 후보로 평가

overflow > 0:
  E5는 legacy 참고 점수만 생성
  모델 선정 winner 자격에서는 제외
  truncated_input_count와 영향 query를 결과표에 명시
```

이번 실험의 중심은 최신 장문 지원 모델 비교이므로 E5 때문에 904개 공통 청크를 다시 잘게 쪼개지는 않는다.

### 8.5 독립 변수와 통제 변수

독립 변수:

```text
embedding model
```

통제 변수:

```text
corpus snapshot
chunk_id
embedding_text_v1
embedding_text_hash
embedding dimension = 모델 manifest의 기본/native 차원
query set
Ground Truth version
distance metric = cosine
top_k
case deduplication rule
vector normalization rule
model revision
```

### 8.6 모델별 입력 adapter

| 모델 | query adapter | document adapter |
|---|---|---|
| OpenAI small/large | `query_text` | `embedding_text_v1` |
| BGE-M3 | `query_text` | `embedding_text_v1` |
| Qwen3 0.6B/4B | 동일한 고정 instruction + `query_text` | `embedding_text_v1` |
| multilingual-e5-large | `query: {query_text}` | `passage: {embedding_text_v1}` |

Qwen3 query instruction은 영어 한 문장으로 고정한다.

```text
Instruct: Given a Korean traffic-accident description, retrieve the most relevant fault-ratio dispute review cases
Query:{query_text}
```

Qwen 공식 형식처럼 instruction은 query에만 붙이고 document에는 붙이지 않는다. BGE-M3는 별도 instruction 없이 실행한다. E5는 query/document prefix를 반드시 사용한다.

모든 로컬 모델은 `eval()`과 inference mode를 사용하고 최종 벡터를 L2 normalize한 뒤 float32로 저장한다. 모델 revision, 라이브러리 버전, dtype, batch size, max_length, adapter 문자열을 manifest에 기록한다.

---

## 9. 코퍼스 동결과 입력 길이 검사

모든 모델은 같은 904개 `embedding_text_v1`을 본다. 모델별 tokenizer 차이로 일부 모델만 조용히 truncate하지 않도록 실행 전에 token length audit를 수행한다.

```text
1. review_case_chunks.jsonl에서 공통 snapshot 생성
2. embedding_text_v1 생성
3. 원본 chunk_text_hash와 embedding_text_hash 생성
4. OpenAI와 로컬 모델 tokenizer별 길이 기록
5. 모델 최대 길이 초과 청크 확인
6. E5 overflow가 있으면 8.3 규칙에 따라 legacy 참고 후보로 전환
7. corpus manifest와 hash 동결
```

904개 청크의 내용, 메타데이터 조합, 정규화 또는 분할을 바꿨다면 동일 실험 run으로 이어가지 않고 새 corpus version과 `embedding_text_version`을 만든다.

### 9.1 코드, 평가 원본, 실행 산출물을 분리한다

네 종류의 파일은 소유권과 변경 방식이 다르므로 서로 다른 루트에 둔다.

```text
코드:
etl/fault_cases/src/embedding_ab_shared/track_a_6models_native_3repeats/corpora/review_case/

사람이 작성하고 Git으로 관리하는 공통 Query 원본:
etl/fault_cases/evaluation/common/embedding_ab/v1/

사람이 작성하고 Git으로 관리하는 심의사례 정답지 원본:
etl/fault_cases/evaluation/review_case/embedding_ab/v1/

코드가 생성하며 Git에 넣지 않는 실행 산출물:
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/
```

`etl/fault_cases/artifacts/`는 `.gitignore` 대상이다. 따라서 공통 Query 50개와 심의사례 qrels의 유일한 원본을 artifacts 아래에 두지 않는다. 실행할 때 두 원본을 `embedding_ab_shared/track_a_6models_native_3repeats/run_<experiment_group_id>/repeat_<NN>/00_input`과 eval snapshot에 복사하고 각각의 version과 hash를 기록한다. qrels는 RunPod 전송 bundle에서 제외한다.

### 9.2 평가셋 원본 폴더

공통 Query와 코퍼스별 Ground Truth는 소유권이 다르므로 분리한다.

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/
  common_fault_query_schema_v1.json         # 세 코퍼스 공통 입력 스키마 1개
  common_fault_queries_v1.jsonl             # 공통 평가 query 레코드 50개
  query_manifest.json                       # query version, 건수, 분포, hash

etl/fault_cases/evaluation/review_case/embedding_ab/v1/
  pilot/                                    # 사고군별 파일럿 10개 draft
    qrels_review_cases_pilot_v1.jsonl
    pilot_manifest.json
    pilot_labeling_report.md
  ground_truth/
    review_case_qrels_v1.jsonl              # 유일한 approved 정답 원본이자 평가 입력 89줄
    ground_truth_manifest.json              # query/corpus/qrels 건수와 SHA
    labeling_report.md                      # 분포와 2차 검수 대상
    qrels_explanation.md                    # 1~50번 문제별 정답과 원문 기반 풀이
    README.md                               # 폴더 역할과 수정 원칙
  labeling_guide.md                         # 공통 relevance와 검수 규칙
  README.md                                 # 평가셋 전체 구조
```

`ground_truth/review_case_qrels_v1.jsonl`은 공통 manifest의 연속 `query_id` 50개를 모두 한 번 이상 포함해야 한다. 관련 심의사례가 여러 건이면 동일 `query_id`의 판정 행이 여러 개 생기고, 정답이 없으면 `no_relevant_document` 행을 정확히 한 줄 둔다. 따라서 검증 기준은 전체 행 수 50이 아니라 **공통 Query ID 50개 커버리지 100%, document/chunk ID 유효성 및 중복 판정 없음**이다.

### 9.3 생성 코퍼스와 실행 결과 폴더

심의사례 전용 파생 코퍼스도 공통 run의 `00_input/corpora/review_case`에 snapshot으로 저장하고, 모델별 벡터·검색·평가 산출물은 세 코퍼스 공통 run 아래에 둔다. 같은 벡터를 두 실행 루트에 복사해 서로 다른 정본을 만들지 않는다.

```text
etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/
  run_<experiment_group_id>/repeat_<NN>/
    00_input/
      common/queries.jsonl
      common/query_manifest.json
      corpora/review_case/
        documents.jsonl
        corpus_manifest.json
    00_manifest/
      run_group_manifest.json
      run_state.json
      runpod_resource_manifest.json
      runpod_execution_lock.json
      model_manifests/
      eval_snapshots/review_case/
        queries.jsonl
        qrels.jsonl
        ground_truth_manifest.json
    01_token_audit/<model_key>/review_case/token_length_audit.json
    02_vectors/
      <model_key>/review_case/
        document_embeddings.parquet
        query_embeddings.parquet
        artifact_manifest.json
        failures.jsonl
    03_retrieval/review_case/<model_key>/
      raw_top50.jsonl
      primary_top10.jsonl
      retrieval_manifest.json
    04_metrics/review_case/
      scores.csv
      query_details.jsonl
      bootstrap.json
      cost_latency.json
      error_analysis.csv
      cosine_similarity_summary.csv
      cosine_similarity_query_details.jsonl
    05_report/corpora/review_case/corpus_result.md
```

공통 최종 스코어 비교표와 분석 리포트는 심의사례 폴더가 아니라 공통 run의 `05_report/` 바로 아래에 생성하며, 정확한 파일명과 생성 게이트는 공통 계획 14장을 따른다.

심의사례의 코사인 유사도를 `raw_top50.jsonl`에만 남기지 않는다. 모델·회차별 Top-1 유사도 평균·중앙값·p95, 최초 정답 유사도, Top-1 정답·오답 유사도 평균과 그 차이, 정답 없음 Query의 Top-1 유사도를 `cosine_similarity_summary.csv`로 집계하고 공통 스코어 비교표의 별도 코사인 유사도 표와 분석 리포트에 반드시 표시한다. `cosine_similarity = 1 - cosine_distance` 계산식과 모델 간 절대값 비교의 한계도 한국어로 설명한다.

### 9.4 A/B 코드 폴더

모델 실행·공통 잠금·공통 경로 처리는 공유 runner가 담당하고, 심의사례 전용 입력 생성과 평가는 공유 패키지의 `corpora/review_case` adapter가 담당한다.

```text
etl/fault_cases/src/embedding_ab_shared/
  common/
    paths.py
  track_b_5models_fixed1024/             # 과거 5모델·1024차원 재현 전용, 수정 금지
    run_ab.py
    runpod_local_models.sh
    runpod_bundles/
  track_a_6models_native_3repeats/       # 심의사례 포함 Native-6 공식 실행 전용
    run_native7.py
    run_openai_models.py
    run_local_models.py
    runpod_native7_3repeats.sh
    validate_vectors.py
    integrate_results.py
    build_final_reports.py
    corpora/review_case/
      build_corpus_snapshot.py
      adapter.py
      load_pgvector.py
      evaluate_retrieval.py
      build_corpus_report.py
```

첫 구현 순서는 `common/paths.py`, Track A의 `config.py`, `run_state.py`, 잠금·덮어쓰기 방지 테스트와 심의사례 `build_corpus_snapshot.py`, `adapter.py`다. 이 코드가 904개 `embedding_text_v1`, corpus manifest와 심의사례 batch adapter를 재현 가능하게 생성해야 모델별 채팅을 시작할 수 있다. 공통 Query와 승인 qrels는 코드가 수정하지 않으며 현재 운영용 `embedding/run_embedding.py`도 그대로 둔다. Track A는 Track B의 `run_ab.py` 또는 RunPod bundle을 import·복사·실행하지 않는다.

심의사례용으로 새로 만드는 `.md`, README, 표, 보고서와 오류 안내는 한국어로 작성한다. 모든 Python/Bash 파일은 한국어 파일 설명과 함수 docstring을 가지며, 매개변수·반환값·예외·부작용과 각 주요 실행 줄의 의미·필요 이유·실패 영향을 한국어 주석으로 설명한다. 고유 모델명·API 필드·경로·CLI만 원문 영문을 유지하며 공통 계획 7.1.1의 검토 실패 기준을 그대로 적용한다.

### 9.5 모델별 작업 채팅에 전달할 심의사례 계약

각 모델 채팅은 하나의 `model_key`로 세 코퍼스를 모두 담당한다. 별도의 심의사례 전용 모델 채팅을 추가로 만들지 않고, 해당 모델 채팅이 `batch_01_fault_standard`를 마친 뒤 이 문서의 계약으로 `batch_02_review_case`를 실행한다.

```text
corpus_key = review_case
repeat_id = repeat_01 | repeat_02 | repeat_03
batch_id = batch_02_review_case
document_count = 904
query_count = 50
document_id = chunk_id
case_id = review_case_id
document_text = embedding_text_v1
query_source = common_fault_queries_v1.jsonl.query_text
output_dimension = model_manifest.native_dimension
output_path = repeat_<NN>/02_vectors/<model_key>/review_case/
qrels_on_runpod = 금지
```

심의사례 batch 완료 조건은 **각 model × repeat마다** document 904개와 query 50개의 count·ID·dimension·finite·norm·input SHA·adapter hash 검증 통과다. 완료 전 파일은 `.partial`에 쓰고 검증 후 원자적으로 최종 파일명으로 바꾼다. `batch_02_review_case`가 끝나도 같은 모델을 unload하거나 RunPod lock을 해제하지 않고, 같은 모델 작업이 판례 계획을 따라 `batch_03_precedent`를 계속 실행한다.

---

## 10. pgvector 적재 구조

기존 운영 임베딩 테이블과 분리된 실험 스키마를 사용한다.

```text
embedding_ab.review_case_corpus_chunks
  run_group_id
  repeat_id
  corpus_key = review_case
  corpus_version
  chunk_id
  review_case_id
  review_no
  chunk_type
  chunk_text
  chunk_text_hash
  embedding_text_version
  embedding_text
  embedding_text_hash
  metadata

embedding_ab.review_case_chunk_vectors__<model_key>
  run_group_id
  repeat_id
  corpus_key = review_case
  model_key
  document_adapter_hash
  chunk_id
  embedding_provider
  embedding_model
  embedding_revision
  embedding_dim
  embedding_vector vector(<native_dimension>)
  inference_ms
  input_token_count
  metadata

embedding_ab.review_case_query_vectors__<model_key>
  run_group_id
  repeat_id
  corpus_key = review_case
  model_key
  query_adapter_hash
  query_set_version
  query_id
  embedding_vector vector(<native_dimension>)
  inference_ms
  metadata
```

완료 조건:

```text
model-repeat별 document vector = 904
model-repeat별 query vector = 50
전체 model-repeat 결과 = 7 x 3 = 21
NULL vector = 0
dimension != model_manifest.native_dimension = 0
duplicate (run_group_id, repeat_id, corpus_key, model_key, chunk_id) = 0
duplicate (run_group_id, repeat_id, corpus_key, model_key, query_id) = 0
embedding_text_hash mismatch = 0
adapter_hash mismatch = 0
model revision 누락 = 0
```

검색 SQL은 query와 document의 `run_group_id`, `repeat_id`, `corpus_key`, `model_key`, `embedding_dim`과 승인된 adapter hash가 모두 일치할 때만 실행한다. 모델별 `vector(native_dimension)` 테이블을 사용하며, 다른 repeat·모델·코퍼스·instruction의 벡터 조합은 즉시 실패시킨다.

운영 테이블 `review_case_chunk_embeddings`에는 A/B 모델 벡터를 덮어쓰지 않는다. 최종 모델이 확정된 후 운영 마이그레이션을 별도로 수행한다.

---

## 11. 검색 및 사례 중복 제거

품질 평가는 HNSW가 아닌 exact cosine 검색으로 시작한다.

```sql
ORDER BY embedding_vector <=> :query_vector
LIMIT 50
```

한 심의사례에 4개 청크가 있으므로 chunk Top-10만 바로 평가하면 한 사례가 여러 자리를 차지할 수 있다. 각 질의에서 청크 후보 50개를 가져온 뒤 `review_case_id`별 최고 점수 청크만 남기고 상위 10개 사례를 만든다.

```text
chunk 후보 Top-50
-> review_case_id별 최고 순위 청크 선택
-> case dedup Top-10
-> Ground Truth 평가
```

모델마다 cosine similarity의 점수 분포가 다르므로 raw similarity 절대값은 모델 간 품질 비교 지표로 사용하지 않는다. 정답 사례의 순위와 적중 여부를 비교한다.

---

## 12. 평가 지표

### 12.1 1차 모델 선정 지표

| 지표 | 단위 | 의미 |
|---|---|---|
| `Case Hit@1` | case dedup | 첫 번째 사례가 정답인가 |
| `Case Hit@5` | case dedup | 상위 5개 사례 안에 정답이 있는가 |
| `Case MRR@10` | case dedup | 첫 정답 사례가 얼마나 위에 있는가 |
| `Primary Case nDCG@10` | case dedup, R2 이상 정답 보유 Query 32개 | 직접 정답과 부분 정답의 순위 품질 |

최우선 지표는 R2 이상 정답이 존재하는 32개 Query의 `Primary Case nDCG@10`으로 둔다. 이 32개 안에서는 R3, R2, R1의 graded gain을 모두 사용하되 R1-only Query 9개는 주 모델 선정 분모에서 제외한다. Query별 nDCG는 이상적 순위로 정규화되므로 R1만 있는 Query도 R1을 1위로 찾으면 1.0이 될 수 있기 때문이다. 실제 서비스에서 상위 결과를 바로 참고하는 중요성을 보기 위해 같은 32개 Query의 `Case Hit@1`, `Case Hit@5`, `Case MRR@10`도 함께 본다.

보조 진단으로는 R1 이상 판정이 있는 41개 Query의 `Graded Coverage nDCG@10`, R1-only 9개의 `Near-miss Hit@5/nDCG@10`, 정답 없음 9개의 Top-1 similarity와 false-positive 후보를 별도로 보고한다. 이 보조 점수는 주 모델 선정 점수나 3코퍼스 macro에 섞지 않는다.

### 12.2 심의사례 전용 보조 지표

| 지표 | 적용 대상 | 의미 |
|---|---|---|
| `Expected Chunk Type Hit@5` | 전체 | 질문 의도에 맞는 청크 유형이 상위 후보에 있는가 |
| `Reference Chart Hit@5` | 도표번호 정답이 있는 query | 기대 참고기준 사례가 상위 5개에 있는가 |
| `Ratio Exact Match@5` | 비율형 query | 역할까지 일치하는 정확한 결정비율 사례가 있는가 |
| `Ratio Within 10pp@5` | 비율형 query | 사용자 차량 기준 과실이 10%p 이내인 사례가 있는가 |
| `Accident Group Macro nDCG@10` | `accident_group`별 | 다수 사고군이 평균을 지배하지 않게 함 |
| `Difficulty Macro nDCG@10` | `difficulty`별 | 난이도 한쪽에서만 성능이 무너지는지 확인 |

보조 지표는 모델 선택의 설명력을 높이지만 1차 Case 지표를 대체하지 않는다.

### 12.3 청크 유형 기대값

| 질문 의도 | 1순위 기대 청크 | 허용 청크 |
|---|---|---|
| 사고 상황 탐색 | `case_overview` | `evidence_issue`, `decision` |
| 당사자 주장 비교 | `arguments` | `decision` |
| 증거와 주요쟁점 | `evidence_issue` | `decision` |
| 결정 근거와 가감 사유 | `decision` | `evidence_issue` |
| 최종 비율과 참고기준 | `case_overview`, `decision` | 없음 |

사례를 맞혔지만 기대 청크 유형이 다른 결과는 1차 Case 지표에서는 정답이고, 청크 유형 보조 지표에서만 구분한다.

### 12.4 `no_relevant_document` 처리와 3코퍼스 비교

`judgment_status=no_relevant_document`인 Query는 모델이 맞힐 수 있는 심의사례 정답이 없으므로 Hit, MRR, primary nDCG의 0점 오답으로 넣지 않는다. R1-only Query도 직접 정답 검색 성능을 재는 주 지표 분모에서는 제외한다. 현재 주 모델 선정 대상은 R2 이상 판정이 있는 32개 Query이며, R1-only 9개와 no-relevant 9개는 서로 다른 진단 set으로 유지한다. 기존 해설집의 41개 graded nDCG 정책은 `Graded Coverage nDCG@10`이라는 보조 지표로 그대로 산출하되 primary 지표와 이름을 구분한다.

```text
review_case_graded_answerable_query_count = relevance >= 1인 Query 수
review_case_binary_answerable_query_count = relevance >= 2인 Query 수
review_case_no_relevant_query_count
review_case_primary_metric_query_count = 32
review_case_near_miss_query_count = 9
review_case_negative_query_count = 9
review_case_graded_answerable_coverage = graded answerable / 50
review_case_binary_answerable_coverage = binary answerable / 50
```

세 코퍼스 모델 성능은 각각의 전용 qrels로 독립 산출한다. 같은 모델의 3코퍼스 평균은 각 코퍼스 점수의 단순 macro average로 별도 표기하되, 코퍼스마다 graded/binary answerable Query 수가 다를 수 있음을 함께 표시한다. 더 엄격한 직접 비교가 필요하면 세 정답지 모두 `relevance >= 2` 정답이 있는 공통 Query 교집합 점수도 함께 계산한다.

```text
심의사례 점수 = review_case_qrels_v1.jsonl
인정기준 점수 = fault_standard_qrels_v1.jsonl
판례 점수 = precedent_qrels_v1.jsonl
3코퍼스 macro = 각 코퍼스의 primary metric을 독립 산출한 뒤 세 점수의 평균
공통-answerable 점수 = 세 코퍼스 모두 정답이 있는 query_id 교집합
```

### 12.5 통계적 불확실성

50개 질의의 평균 차이가 작을 수 있으므로 질의 단위 paired bootstrap 1,000회를 수행한다.

보고 항목:

```text
모델별 평균 지표
95% bootstrap confidence interval
기준 모델 대비 paired difference
accident_group별 지표
difficulty별 지표
승패가 뒤집히는 query 목록
```

---

## 13. 속도, 비용 및 RunPod 실행 설계

### 13.1 데이터 크기가 GPU 선택에 미치는 영향

이번 코퍼스는 904청크, 임베딩 입력 본문 약 31.97만 자, 원본 JSONL 약 1.19MB다. 벡터 원시 저장량도 모델당 다음 정도다.

```text
6개 모델 native 차원 합계 = 10,240
904 chunks x 10,240 dimensions x 4 bytes
= 약 35.3 MiB/repeat raw document vectors
3회 = 약 105.9 MiB raw document vectors
```

따라서 파일 크기나 전체 청크 수 때문에 고사양 GPU가 필요한 실험이 아니다. **VRAM은 전체 데이터 용량보다 모델 크기, 한 청크의 최대 token 길이, batch size로 결정**된다. 이번 작업 시간은 실제 embedding 연산보다 모델 다운로드와 Python 환경 설치가 더 큰 비중을 차지할 가능성이 높다.

### 13.2 RunPod GPU 추천

2026-07-15 RunPod 공식 Pods 가격 페이지 표시값 기준이다. 실제 가격과 재고는 지역, Cloud 유형, 시점에 따라 달라질 수 있으므로 Pod 생성 직전에 다시 확인한다. [RunPod GPU 가격](https://www.runpod.io/pricing), [RunPod GPU 종류와 VRAM](https://docs.runpod.io/references/gpu-types)

| 용도 | GPU | VRAM | 현재 표시 가격 | 판정 |
|---|---|---:|---:|---|
| 기본 권장 | `A40` | 48GB | 약 $0.44/hr | Qwen3-4B를 최대 모델로 하는 로컬 모델 4개를 순차 실행하는 기본 후보 |
| 재고 대안 | 동급 48GB GPU | 48GB | 배포 시 확인 | A40 재고가 없을 때 가격·VRAM 재승인 후 사용 |
| 속도 우선 | `RTX 4090` | 24GB | 약 $0.69/hr | 다운로드 이후 연산을 빨리 끝내고 싶을 때 |
| 과사양 | `A100/H100` | 80GB 이상 | $1.39/hr 이상 | 이번 904청크 실험에는 불필요 |

최종 권장안:

```text
기본 실행:
Community Cloud A40 48GB 1장 또는 동급 48GB GPU

데이터 정책상 Community Cloud 사용이 어려운 경우:
동일 VRAM의 Secure Cloud Pod 선택
```

심의사례 PDF는 공개 자료이고 이번 실험 파일에는 사용자 사고 원문이나 개인정보를 올리지 않으므로 Community Cloud로 시작할 수 있다. 향후 실제 사용자 query나 비공개 정답지를 올리는 경우에는 Secure Cloud 또는 사내 실행 환경을 사용한다. RunPod는 Pods를 분 단위로 과금하고 공식 PyTorch template을 제공한다. [RunPod Pods 개요](https://docs.runpod.io/pods/overview)

### 13.3 기존 OJH Pod 보호와 공통 Pod 인계 원칙

> [!CAUTION]
> RunPod Pods 목록에 이미 존재하는 **`SKN27-3T-OJH`는 OJH 작업 전용 보호 대상**이다. 심의사례 임베딩 A/B 실험에서는 이 Pod를 절대 사용하거나 변경하지 않는다. 목록에서 이름을 확인하는 것 외에는 해당 행, 상세 화면, 더보기 메뉴를 열지 않는다.

`SKN27-3T-OJH`에 대해 금지하는 작업은 다음과 같다.

```text
- Connect, Web Terminal, SSH, Jupyter 접속
- 로그 열람, 파일 업로드, 명령 실행
- Start, Stop, Restart, Reset, Redeploy
- GPU, template, 환경변수, container disk 설정 변경
- 기존 Pod volume 또는 network volume 연결·분리·재사용
- Clone, Edit, Terminate, Delete
```

공통 Pod는 새로 만드는 것이 기본이 아니다. 공통 계획 11.2의 우선순위대로 `SKN27-embedding-ab-*` 등 임베딩 A/B용 기존 Pod가 있으면 사용자에게 Start와 JupyterLab 열기를 요청하여 그 Pod를 사용한다. 기존 임베딩 Pod가 없고 보호 대상 `SKN27-3T-OJH`만 있을 때에만 `00_preflight_orchestrator`가 신규 Pod를 생성한다. 기존 Pod의 GPU 불가·migration·GPU 변경은 사용자 확인 전 자동으로 처리하지 않는다. 이전 Track B vector·검색·점수는 재사용하지 않고, Track A 결과 경로를 새로 만든다.

`00_preflight_orchestrator`만 위 선택 분기와 필요 시 신규 Pod 생성을 수행한다. 모델별 작업 채팅은 manifest에 등록된 공통 Pod를 인계받아 세 코퍼스를 순차 실행하며, 이 문서는 그중 `batch_02_review_case`의 입력과 검증을 규정한다. 모델 채팅은 Pod를 새로 만들거나 종료하지 않는다. 재사용·신규 여부와 무관하게 Pod Stop, Terminate, Delete는 결과 회수와 SHA 검증 후 사용자 확인 없이는 수행하지 않는다.

신규 리소스 식별 규칙:

```text
Pod name: SKN27-3T-EMBED-AB-ALL-<작업자이니셜>-<YYYYMMDD>
예시: SKN27-3T-EMBED-AB-ALL-HR-20260715
금지 이름: SKN27-3T-OJH 또는 OJH가 포함된 이름
Container disk: 신규 생성
Pod volume: 신규 40GB 이상 생성
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

### 13.4 권장 Pod 구성

```text
GPU count: 1
GPU: A40 48GB 기본, 재고가 없으면 동급 48GB GPU 재승인
Template: RunPod 공식 PyTorch template
Container disk: 30GB 이상
Volume disk: 40GB 이상
Network volume: 이번 일회성 실험에는 불필요
Python: 3.11 권장
CUDA/PyTorch: 선택한 template의 호환 조합 사용
실행 방식: 모델 한 개씩 load -> encode -> 저장 -> unload
```

로컬 모델 4개를 동시에 VRAM에 올리지 않는다. 모델 한 개를 로드한 상태에서 세 코퍼스를 순차 batch 처리하고, 코퍼스별·repeat별 결과를 분리 저장한 뒤 Python 객체를 제거하고 CUDA cache를 비운다. OpenAI 모델 2개는 로컬에서 별도로 실행한다.

권장 패키지 최소 조건:

```text
torch
transformers>=4.51.0
sentence-transformers>=2.7.0
FlagEmbedding
accelerate
pandas
pyarrow
numpy
```

Qwen3 모델 카드는 `transformers>=4.51.0`, `sentence-transformers>=2.7.0`을 요구한다. FlashAttention 2는 선택사항이다. 현재 최대 청크가 짧고 전체 건수가 작으므로 설치 실패 가능성을 늘리면서까지 첫 실행에 강제하지 않는다. 기본 SDPA로 성공한 뒤 필요할 때만 적용한다.

### 13.5 모델별 시작 batch 설정

token length audit가 끝난 뒤 실제 max token에 맞게 조정한다.

| 모델 | dtype | 시작 batch | max_length 원칙 | OOM 시 |
|---|---|---:|---|---|
| Qwen3 0.6B | fp16 또는 bf16 | 64 | audit 최대값보다 큰 1024 또는 2048 | 32, 16으로 감소 |
| BGE-M3 | fp16 | 64 | audit 최대값보다 큰 1024 또는 2048 | 32, 16으로 감소 |
| multilingual-e5-large | fp16 | 64 | 512 고정 | 32, 16으로 감소 |

코퍼스가 작으므로 큰 batch로 최대 처리량을 만드는 것이 목적은 아니다. 같은 모델의 batch size는 document embedding 전체에서 고정하고, 재시도 시 manifest에 변경 이력을 남긴다.

### 13.6 RunPod 예상 시간과 예산

RunPod 시간과 비용은 심의사례 904개만의 별도 Pod 예산이 아니라 로컬 모델 4개와 세 코퍼스 전체를 3회 처리하는 공통 experiment로 관리한다. 비용 상한은 반복당 timed benchmark 후 사용자 승인값으로 고정한다.

| Pod | 1시간 | 2시간 | 용도 |
|---|---:|---:|---|
| A40 | 약 $0.44 | 약 $0.88 | 기본 권장 |
| 동급 48GB GPU | 배포 시 확인 | 배포 시 확인 | A40 재고 대안 |
| RTX 4090 | 약 $0.69 | 약 $1.38 | 속도 우선 |

위 계산은 GPU Pod 시간만 단순 환산한 값이며 storage 비용은 별도다. 심의사례 작업의 완료 조건은 자기 모델의 904개 문서와 심의사례용 query 50개를 저장·검증하는 것이지만, 이때 Pod를 종료하지 않는다. 같은 모델의 판례 배치와 다음 모델 작업까지 완료된 뒤 공통 오케스트레이터가 실제 청구액을 manifest에 기록하고 종료한다.

### 13.7 OpenAI API 예상 비용

`embedding_text_v1`의 정확한 token 수는 OpenAI tokenizer audit와 API 응답의 `usage.total_tokens`로 확정한다. 현재 31.97만 자를 기준으로 0.2M~0.5M input token 범위를 계획값으로 잡으면 다음 정도다.

| 모델 | 공식 현재 단가/1M token | 0.2M 예상 | 0.5M 예상 |
|---|---:|---:|---:|
| `text-embedding-3-small` | $0.02 | 약 $0.004 | 약 $0.010 |
| `text-embedding-3-large` | $0.13 | 약 $0.026 | 약 $0.065 |

따라서 OpenAI 두 모델의 document embedding 비용은 이번 데이터 규모에서 모델 선택을 제한할 수준이 아니다. 다만 운영비 비교에서는 초기 904개 생성비와 향후 사용자 query 1,000건 비용을 분리한다.

### 13.8 모델별 별도 채팅과 병렬 허용 범위

| 작업 채팅 | model_key | 실행 위치 | 심의사례 작업 |
|---|---|---|---|
| `00_preflight_orchestrator` | 공통 준비 | 로컬 | 904개 snapshot·adapter·manifest 검증, 신규 Pod 생성과 최종 종료 |
| `01_openai_small` | `openai_small_native_1536` | 로컬 API | 심의사례 document 904 + query 50 × 3회 |
| `02_openai_large` | `openai_large_native_3072` | 로컬 API | 심의사례 document 904 + query 50 × 3회 |
| `03_qwen3_06b` | `qwen3_06b_native_1024` | 공통 RunPod | Qwen instruction으로 document 904 + query 50 × 3회 |
| `04_qwen3_4b` | `qwen3_4b_native_2560` | 공통 RunPod | 동일 instruction으로 document 904 + query 50 × 3회 |
| `05_bge_m3` | `bge_m3_dense_native_1024` | 공통 RunPod | dense only document 904 + query 50 × 3회 |
| `06_e5_large` | `e5_large_native_1024` | 공통 RunPod | `passage:`/`query:` adapter로 document 904 + query 50 × 3회 |
| `07_integrate_evaluate` | 통합 평가 | 로컬 pgvector | 18개 model-repeat 결과 평가·집계·보고 |

별도 채팅은 **모델별 책임 분리**를 뜻하며 GPU 모델을 동시에 실행한다는 뜻이 아니다. 무료 준비 단계의 read-only audit과 문서 검토는 병렬로 할 수 있지만, 공유 코드를 수정하는 작업은 `00_preflight_orchestrator`만 수행한다. `code_bundle_sha`와 `requirements_lock_sha`가 동결된 뒤 모델 채팅은 코드를 수정하지 않고 자기 output 경로에만 쓴다.

OpenAI small과 large는 서로 다른 API lane이라 기술적으로 병렬 실행할 수 있으나 세 정식 repeat 모두 비용·재시도·로그 추적을 위해 순차 실행한다. Qwen 2개, BGE, E5는 공통 GPU 하나를 공유하므로 `runpod_execution_lock.json`을 획득한 채 반드시 순차 실행한다. lock이 `active`이거나 model_key·task owner가 다르면 Pod에 접속하거나 명령을 실행하지 않는다.

모델 채팅에서 결함을 발견하면 부분 산출물을 최종 파일로 승격하지 않고 중단한다. 공통 코드를 고쳐야 한다면 orchestrator가 runner version과 code bundle SHA를 올리고, 영향을 받은 모델·코퍼스 batch를 처음부터 다시 실행한다.

### 13.9 RunPod 실행 순서

```text
1. 공통 Query, 심의사례 corpus snapshot, embedding_text_v1과 SHA를 로컬에서 동결
2. 코드, requirements, corpus, query만 전송하고 DB 비밀번호, OpenAI API key, qrels는 제외
3. 공통 오케스트레이터가 생성·검증한 `SKN27-3T-EMBED-AB-ALL-*` Pod manifest 확인
4. 자기 model lock을 획득하고 다른 모델이 실행 중이 아님을 확인
5. 같은 모델의 `batch_01_fault_standard` 완료 상태와 산출물 hash 확인
6. 모델을 유지한 채 `batch_02_review_case` 904개 document vectors 생성
7. 같은 모델·심의사례 adapter로 query 50개 vectors 생성
8. count, dimension, NaN/Inf, norm, hash 검증 후 corpus_key/model_key 경로에 원자 저장
9. 같은 모델 채팅이 판례 계획을 읽고 `batch_03_precedent`를 계속 실행하며 Pod와 모델을 임의 종료하지 않음
10. 세 코퍼스 완료 후 model unload와 lock 해제, 다음 모델 채팅으로 인계
11. 로컬 통합 작업에서 pgvector schema에 적재하고 심의사례 qrels로 평가
12. 로컬 모델 4개·세 코퍼스·전체 3회가 모두 끝난 뒤에만 공통 오케스트레이터가 신규 Pod와 volume 종료
```

RunPod에서는 벡터 생성만 하고 pgvector 평가와 Ground Truth 채점은 로컬에서 수행한다. 이렇게 하면 DB를 외부에 노출하지 않고 모든 모델 결과에 동일한 평가 코드를 적용할 수 있다.

### 13.10 기록할 성능과 비용 지표

| 항목 | 기록 단위 |
|---|---|
| 모델 다운로드 시간 | 초/분 |
| 모델 초기 로딩 시간 | 초 |
| document embedding 총시간 | 초/분 |
| document 처리량 | chunks/sec, tokens/sec |
| query embedding warm p50/p95 | ms |
| query embedding cold start | ms |
| exact DB search p50/p95 | ms |
| API 또는 GPU 총비용 | USD와 실행 시점 환산 원화 |
| 벡터 및 index 저장공간 | MB |
| 최대 GPU 메모리 | GB |
| 실패, OOM, 재시도 건수 | 건 |

HNSW 평가는 품질 모델이 2개 이하로 좁혀진 뒤 진행한다.

```text
HNSW Recall@10 against exact Top-10
index build time
index size
search p50/p95
```

---

## 14. 실험 실행 단계

### Phase 0. 데이터와 정답지 준비

1. 구조화 청크 904개 snapshot과 hash를 만든다.
2. `embedding_text_v1`을 생성하고 hash를 동결한다.
3. 공통 `common_fault_queries_v1.jsonl`의 연속 50개 query_id와 SHA를 검증하고 `query_manifest.annotation_status=approved`를 확인한다.
4. 승인된 qrels 89행이 모두 `adjudication_status=approved`이고 SHA가 `093f70b78484c8d9b4989801debca52e1aae5debbfa9e1788285bd8cae0c6c1f`인지 확인한다.
5. qrels의 `adjudication_status`와 `label_source`는 승인·검수 이력이므로 제거하거나 수정하지 않는다.
6. 공유 runner, requirements lock, run state와 output 덮어쓰기 방지 테스트를 구현한다.
7. 후보별 token length audit를 수행하고 E5 overflow 및 winner 자격을 확정한다.
8. OpenAI key 존재·native 차원 smoke, 로컬 pgvector extension·모델별 차원 table 생성 권한을 확인한다.
9. common query·심의사례 corpus·승인 qrels manifest를 `run_group_id`의 eval snapshot으로 복사하고 SHA를 재검증한다.

1~9가 모두 통과하기 전에는 OpenAI 전체 유료 호출이나 RunPod Deploy를 시작하지 않는다. 정답지 내용 변경이 필요해지면 승인본을 덮어쓰지 않고 새 Ground Truth version과 SHA를 만든다.

### Phase 1. 10개 smoke 실험

1. 현재 작성된 사고군별 파일럿 10개를 기술 smoke 입력으로 재사용한다.
2. 공통 6개 후보 모두 document/query 벡터 수와 native 차원을 검증한다.
3. exact 검색과 case dedup이 동일하게 동작하는지 확인한다.
4. qrels와 리포트 생성 코드의 오류를 수정한다.

smoke 결과로 모델을 탈락시키지 않는다. 파이프라인 검증에만 사용한다.

### Phase 2. 정식 50개 평가

1. 동결된 50개 query를 공통 6개 후보로 임베딩한다.
2. 모델별 exact cosine 후보를 생성한다.
3. 사례 중복 제거 후 Top-10을 평가한다.
4. 전체, accident_group별, difficulty별, expected_chunk_types별 지표를 계산한다.
5. paired bootstrap과 오류 분석을 수행한다.

### Phase 3. 운영성 평가

1. 품질 상위 2개 모델을 선정한다.
2. 동일 HNSW 파라미터로 인덱스를 생성한다.
3. exact 대비 Recall@10과 지연을 측정한다.
4. 비용과 운영 난이도를 포함해 최종 모델을 결정한다.

---

## 15. 모델 선정 규칙

최종 판단 순서는 다음과 같다.

1. R2 이상 정답 보유 32개 Query의 `Primary Case nDCG@10`이 가장 높은 모델을 확인한다.
2. `Case Hit@1`, `Case Hit@5`, `Case MRR@10`에서 치명적인 열세가 없는지 확인한다.
3. accident_group별·difficulty별 성능이 한쪽으로 크게 무너지지 않는지 확인한다.
4. 95% 신뢰구간이 크게 겹치는 후보는 품질 동급으로 본다.
5. 동급 후보 중 query latency, 총비용, 운영 난이도, 라이선스를 비교한다.
6. 최종 1개 모델과 장애 시 대체할 1개 후보를 기록한다.

권장 품질 방어선:

```text
최고 모델 대비 Case Hit@5 차이 <= 0.03
특정 accident_group 또는 difficulty의 Case nDCG@10 급락 없음
document/query vector 누락 0
HNSW Recall@10 against exact >= 0.98
```

50개 질의에서도 차이가 작고 신뢰구간이 넓다면 승자를 억지로 확정하지 않는다. 오류 유형을 분석한 뒤 희소 사고유형 중심으로 다음 query version을 추가한다.

---

## 16. 결과 보고서 구조

최종 결과 문서는 다음 순서로 작성한다.

```text
1. 실험 목적과 한 줄 결론
2. 전처리와 청크 품질 요약
3. corpus/embedding_text/query/qrels 버전
4. 모델과 입력 adapter
5. RunPod 또는 API 실행환경
6. 전체 정량 점수표
7. accident_group별 점수표
8. difficulty별 점수표
9. 비용과 지연 비교
10. 대표 성공 사례
11. 모델별 실패 사례
12. chunk_type 편향 및 E5 truncation 분석
13. Ground Truth 변경 이력
14. 최종 모델 선정 및 운영 권고
15. 후속 input ablation/hybrid/reranker 실험 항목
```

모델 결과 보고서에는 최소한 다음 식별자를 남긴다.

```text
run_group_id
corpus_key = review_case
corpus_version
embedding_text_version
embedding_text_hash
query_set_version
ground_truth_version
model_key
embedding_model
embedding_revision
embedding_dim
query_adapter_version
document_adapter_version
query_adapter_hash
document_adapter_hash
runtime_gpu
runtime_dtype
runtime_library_versions
distance_metric
top_k
case_dedup_rule
git_commit
code_bundle_sha
requirements_lock_sha
```

---

## 17. 권장 산출물

```text
etl/fault_cases/evaluation/common/embedding_ab/v1/
  common_fault_query_schema_v1.json
  common_fault_queries_v1.jsonl
  query_manifest.json

etl/fault_cases/evaluation/review_case/embedding_ab/v1/
  pilot/
    qrels_review_cases_pilot_v1.jsonl
    pilot_manifest.json
    pilot_labeling_report.md
  ground_truth/
    review_case_qrels_v1.jsonl
    ground_truth_manifest.json
    labeling_report.md
    qrels_explanation.md
    README.md
  labeling_guide.md
  README.md

etl/fault_cases/artifacts/embedding_ab_shared/track_a_6models_native_3repeats/run_<experiment_group_id>/repeat_<NN>/
  00_input/
    common/queries.jsonl
    common/query_manifest.json
    corpora/review_case/
      documents.jsonl
      corpus_manifest.json
  00_manifest/
    run_group_manifest.json
    run_state.json
    runpod_resource_manifest.json
    runpod_execution_lock.json
    model_manifests/<model_key>.json
    eval_snapshots/review_case/
      queries.jsonl
      qrels.jsonl
      ground_truth_manifest.json
  01_token_audit/<model_key>/review_case/token_length_audit.json
  02_vectors/<model_key>/review_case/
    document_embeddings.parquet
    query_embeddings.parquet
    artifact_manifest.json
    failures.jsonl
  03_retrieval/review_case/<model_key>/
    raw_top50.jsonl
    primary_top10.jsonl
    retrieval_manifest.json
  04_metrics/review_case/
    scores.csv
    query_details.jsonl
    bootstrap.json
    cost_latency.json
    error_analysis.csv
    cosine_similarity_summary.csv
    cosine_similarity_query_details.jsonl
```

세 코퍼스 통합 최종 문서는 아래 두 파일이며 공통 계획 14장의 이름과 내용 계약을 그대로 사용한다.

```text
run_<experiment_group_id>/05_report/pgvector_3코퍼스_임베딩_모델_AB_스코어_비교표.md
run_<experiment_group_id>/05_report/pgvector_3코퍼스_임베딩_모델_AB_분석_리포트.md
run_<experiment_group_id>/05_report/corpora/review_case/corpus_result.md
```

---

## 18. 완료 체크리스트

```text
[ ] review_case_chunks 904개 snapshot 및 hash 동결
[ ] source_chunks 285개 제외 확인
[ ] embedding_text_v1 904개 생성 및 hash 동결
[ ] 공통 6개 후보 token length audit 완료
[ ] E5 512 token overflow와 winner 자격 기록
[x] 공통 query 입력 스키마와 common_fault_queries_v1.jsonl 50개 인수
[x] 공통 query 연속 50개, query_id, version, hash 검증
[x] 공통 Query를 심의사례 쪽에서 수정하지 않았으며 query SHA가 동일한지 확인
[x] 사고군별 파일럿 10개 심의사례 qrels draft 작성
[x] 파일럿 판정을 50개 전체 원문 검수 결과로 승계하고 q01 수정 이력 기록
[x] 파일럿 10개와 나머지 40개를 포함한 qrels draft 89줄 작성
[x] manifest query_ids 50개를 100% 커버하는 판정 행 작성
[x] has_relevant_document 41 / no_relevant_document 9 상태 전수 확인
[x] graded coverage 82%, binary coverage 64%, 관련 판정 80건, 서로 다른 정답 review_case_id 71건 집계
[x] 사고군 10종 건수·비율과 difficulty 25/21/4 비율 검증
[x] document/chunk ID 참조와 중복 판정 없음 검증
[x] 누락 8건 추가, 반대 방향 1건 제외, relevance 9건 재조정
[x] q12 직접 사례 복구, 반대 방향 2건 제외, relevance 6건 재조정
[x] expected_chunk_types를 주 청크 유형 하나로 정리
[x] Query 1~50번별 문제·정답·원문 근거·등급 이유·오답 포인트 해설집 작성
[x] 최종 판정 검수 결과의 사용자 수용과 approved SHA 기록
[ ] fault_common_queries_v1 공통 소유자 동결
[x] review_case_qrels_v1 89행 모두 `adjudication_status=approved`
[x] qrels SHA `093f70b7...c6c1f`와 ground_truth_manifest 일치
[ ] 공유 runner와 requirements.lock 구현
[ ] run_group_id, run_state, model lock과 output 덮어쓰기 방지 테스트 통과
[ ] 모델별 작업 채팅이 공통 계획과 세 코퍼스 계획을 모두 읽었는지 확인
[ ] OpenAI small 1,536 / large 3,072차원 확인(`dimensions` 축소 인자 미사용)
[ ] `SKN27-3T-OJH` 접속·변경·복제·종료 금지 확인
[ ] 기존 임베딩 A/B Pod 확인 결과와 `resource_origin=reused|new`를 manifest로 확인
[ ] 기존 Pod면 사용자 Start·JupyterLab 열기 후 사용, 없으면 신규 Pod name/ID/volume ID를 manifest에 기록
[ ] RunPod GPU/라이브러리/dtype preflight 완료
[ ] 로컬 모델 revision 및 입력 adapter manifest 저장
[ ] 모델별 document vector 904개 확인
[ ] 모델별 query vector 50개 확인
[ ] model_key/corpus_key/adapter_hash 혼합 0건 확인
[ ] pgvector exact cosine 결과 생성
[ ] review_case_id 기준 case dedup 적용
[ ] 32개 Query Primary Case Hit@1/5, MRR@10, nDCG@10 계산
[ ] R1-only 9개 near-miss와 no-relevant 9개 false-positive 진단
[ ] 41개 Query Graded Coverage nDCG@10을 보조 지표로 계산
[ ] accident_group/difficulty/chunk_type/reference_chart/ratio 보조 지표 계산
[ ] paired bootstrap 1,000회 수행
[ ] 품질 상위 2개 HNSW 운영성 평가
[ ] 비용 및 지연 기록
[ ] 심의사례 산출물 검증 후 같은 모델 채팅이 Pod와 model을 유지해 판례 배치를 계속 실행
[ ] RunPod 5개 모델·세 코퍼스·전체 3회 완료 후 결과 SHA를 확인하고 Pod 종료 여부를 사용자에게 확인
[ ] `SKN27-3T-OJH` 상태가 변경되지 않았음을 최종 확인
[ ] 최종 결과 보고서 작성
[ ] 운영 테이블 반영 여부 별도 승인
```

---

## 19. 팀 공유용 요약

현재 심의사례는 472쪽 PDF에서 226건을 분리하고 필수 섹션과 비율을 구조화한 뒤, 사례당 의미 단위 4종으로 총 904청크를 생성했다. fatal flag, 빈 청크, 중복 ID, DB 건수 불일치는 모두 0이다. 임베딩 실험에서는 원본 청크를 바꾸지 않고 구조화 메타데이터를 한 번만 붙인 `embedding_text_v1`을 공통 본 실험 6개 후보에 동일하게 적용한다.

심의사례, 인정기준, 판례는 정식 평가에서 동일한 사용자 사고 Query 50개와 `query_id`를 공유한다. 기존 100개에서 사고군·난이도 비율을 유지해 50개를 층화 선정한 뒤 `fault_common_q01`부터 `fault_common_q50`까지 연속 재번호했다. 각 코퍼스는 공통 Query 문장을 수정하지 않고 자기 코퍼스 안에서만 정답을 판정한 전용 qrels를 별도로 만든다.

심의사례 Ground Truth는 `review_case_id`를 1차 정답으로 삼는다. 같은 사례의 4개 청크 중 어떤 청크가 검색되어도 사례 검색 자체는 정답이며, 질문 의도에 맞는 `chunk_type`을 찾았는지는 보조 지표로 평가한다. 참고기준 번호와 결정비율은 유용한 검증값이지만 단독 정답으로 사용하지 않는다.

현재 `ground_truth/`에는 유일한 정답 원본인 qrels 89줄과 1~50번 문제별 풀이를 담은 `qrels_explanation.md`가 있다. qrels 89행은 모두 `adjudication_status=approved`이며 SHA `093f70b7...c6c1f`가 manifest에 동결돼 있으므로 이 필드와 승인본을 수정하지 않는다. 41개 Query에 관련 심의사례 80건이 연결됐고 9개는 `no_relevant_document`이며, 서로 다른 정답 심의사례는 71건이다. relevance 분포는 `3/2/1 = 40/19/21`이다. R2 이상 직접 정답이 있는 32개를 주 모델 선정 분모로 사용하고, R1-only 9개와 no-relevant 9개는 각각 near-miss와 false-positive 진단으로 분리한다. 사고군 분포는 `16/14/10/16/8/6/8/12/6/4%`, 난이도는 `easy 50% / medium 42% / hard 8%`다.

정답지 작성은 반드시 `공통 Query 동결 -> 심의사례 후보 수집 -> 관련도 판정 또는 no_relevant_document -> qrels 갱신 -> SHA 검증 -> 승인 버전 동결 -> 전 모델 공통 평가` 순서로 진행한다. 심의사례 모델 점수는 심의사례 qrels만으로 계산하고, 세 코퍼스 결과를 독립 산출한 뒤 같은 모델의 macro average를 별도로 계산한다.

공통 본 실험은 6개 모델을 세 repeat로 나누어 전체 실행한다. OpenAI 두 모델은 로컬에서 순차 실행하고, Qwen 0.6B/4B·BGE-M3·E5는 공통 오케스트레이터가 생성한 RunPod를 model lock으로 순차 공유한다. 각 model-repeat는 인정기준 277개, 심의사례 904개, 판례 8,334개를 순서대로 새로 처리하며 이전 repeat vector를 재사용하지 않는다. 어떤 경우에도 기존 `SKN27-3T-OJH`는 접속·변경·복제·종료하지 않는다.
