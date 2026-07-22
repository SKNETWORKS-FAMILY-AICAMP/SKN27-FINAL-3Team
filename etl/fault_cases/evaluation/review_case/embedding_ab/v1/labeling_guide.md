# 심의사례 임베딩 평가셋 라벨링 가이드

## 목표

- 입력 스키마: 1개
- 정식 평가 query: 50개
- Ground Truth qrels: 판정별 1줄, Query ID 50개 전체 커버
- 서로 다른 정답 사례: 60건 이상 권장
- 한 1차 정답 사례당 query: 최대 2개

전체 검색 코퍼스는 심의사례 226건과 구조화 청크 904개다. 정답 사례 다양성 기준은 검색 코퍼스를 줄이는 수가 아니라 query 50개의 정답이 특정 사례에 몰리지 않도록 관리하기 위한 기준이다.

## 작성 순서

1. 공통 `common_fault_queries_v1.jsonl`의 query hash와 50개 ID를 확인한다.
2. Query의 사고 장소, 당사자 유형, 신호, 진행 방향, 충돌 형태와 핵심 쟁점을 분리한다.
3. 구조화 필드와 lexical 후보군으로 심의사례 후보를 넓게 수집한다.
4. 후보 원문과 구조화 document를 대조한다.
5. 모델명과 검색 순위를 보지 않고 `3/2/1/0` 관련도를 판정한다.
6. 유효한 후보가 없으면 근거와 함께 `no_relevant_document`로 판정한다.
7. 판정 결과를 유일한 정답 원본인 qrels에 갱신한다.
8. 두 번째 검수자가 전체 판정을 독립 검수하고 relevance 1·2와 no relevant를 우선 확인한다.
9. Query 커버리지, 중복 판정, ID 참조, 건수와 SHA를 검증해 manifest를 갱신한다.

## relevance

```text
3 = 사고 구조, 차량 행동과 핵심 쟁점이 직접 일치하는 최우선 정답 사례
2 = 핵심 사고 관계는 일치하지만 일부 조건 또는 수정요소가 다른 강한 관련 사례
1 = 상위 사고유형은 유사하고 일부 조건이 참고 가능하지만 이진 검색 정답으로는 쓰지 않는 약한 관련 사례
0 = 표면 키워드만 같거나 방향, 행동, 당사자 유형이 명시적으로 반대인 hard negative
```

## qrels 한 줄 예시

```json
{"query_id":"fault_common_q01","judgment_status":"has_relevant_document","review_case_id":"review_case_2019_008384","review_no":"2019-008384","chunk_id":"review_case_2019_008384_case_overview","relevance":2,"expected_chunk_types":["case_overview"],"reason":"녹색 직진 대 우측도로 적색 직진은 직접 일치하지만 좌회전차로 직진이라는 추가 위반이 존재","adjudication_status":"draft","ground_truth_version":"review_case_qrels_v1"}
```

같은 Query에 관련 사례가 여러 건이면 동일한 `query_id`로 여러 행을 둔다. 유효한 정답이 없으면 `no_relevant_document` 상태 행을 한 줄 둔다. 사람 검수 시에는 qrels를 `query_id`별로 그룹화한 임시 뷰를 사용한다.

`expected_chunk_types`는 `chunk_id`의 주 청크 유형 하나만 둔다. 방향, 행동과 당사자 유형처럼 과실 판단을 바꾸는 핵심 조건이 명시적으로 반대인 사례는 qrels 정답에서 제외하고 hard negative 후보로 관리한다. 진행 형태는 같지만 신호의 법적 성격이나 수정요소가 달라 참고 가치만 있는 사례는 R1로 둘 수 있다.

Recall/MRR 이진 평가에서는 `relevance >= 2`만 정답으로 인정한다. R1은 nDCG의 낮은 gain과 오차 분석에만 사용하며, R1만 있는 Query는 Recall/MRR 분모에서 제외한다.

## 금지사항

- 모델 검색 결과를 먼저 보고 정답 사례를 선정하지 않는다.
- 참고기준 번호만 같다는 이유로 정답 처리하지 않는다.
- 결정비율만 같다는 이유로 정답 처리하지 않는다.
- 차대차 Query에 차대이륜차·보행자·자전거·PM 사례를 당사자 유형 확인 없이 연결하지 않는다.
- 특정 모델에만 유리하게 query 또는 qrels를 수정하지 않는다.
- 검수 없이 `adjudication_status`를 `approved`로 바꾸지 않는다.
