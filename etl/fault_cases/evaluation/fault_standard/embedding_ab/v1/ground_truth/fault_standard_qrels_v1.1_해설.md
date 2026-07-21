# 인정기준 Ground Truth v1.1 해설

## 1. 문서 목적

이 문서는 `fault_standard_qrels_v1.1.jsonl`의 relevance, Rule, variant, 기본과실, 수정요소 및 최종 과실비율을 어떤 원칙으로 판단했는지 설명한다.

v1.1은 기존 `fault_standard_qrels_v1.jsonl`을 삭제하거나 덮어쓰지 않고 별도 파일로 보존한다. 2026-07-16에 전달받은 50개 Query·103개 기존 판정행에 대한 재검토 피드백과 현재 인정기준 전처리 산출물을 대조하여 작성했다.

이 버전은 피드백 반영본이며 아직 두 명의 독립 검수와 최종 adjudication이 끝난 동결본은 아니다.

## 2. 사용한 자료

- 공통 질문지: `evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl`
- 기존 정답지: `fault_standard_qrels_v1.jsonl`
- 2020 비정형 사고 인정기준 전처리 결과
- 2021 PM 대 자동차 비정형 기준 전처리 결과
- 2023 자동차사고 과실비율 인정기준 전처리 결과
- 2025 2차로형 회전교차로 비정형 기준 전처리 결과
- 사용자 제공 PDF 재검토 피드백

원본 PDF 파일은 현재 작업 트리에서 직접 열 수 없는 상태이므로, 페이지 경계 자체는 전처리 metadata와 사용자 제공 검토 결과를 바탕으로 보류 판정했다. 페이지 경계는 동결 전에 원본 PDF로 다시 확인해야 한다.

## 3. v1.1 요약

| 항목 | 값 |
|---|---:|
| 고유 Query | 50개 |
| 전체 flat JSONL 행 | 112행 |
| relevance 2 | 45행 |
| relevance 1 | 12행 |
| relevance 0 | 48행 |
| no-exact 요약행 | 7행 |

relevance 합계가 전체 행보다 7개 적은 이유는 정확한 Rule이 없는 Query마다 `rule_id=null`, `relevance=null`인 요약행을 한 개씩 두었기 때문이다.

정확한 relevance 2 Rule이 없는 Query는 다음과 같다.

```text
q07, q23, q31, q35, q46, q47, q48
```

## 4. relevance 및 no-exact 정책

### relevance 2

사고유형과 핵심 적용조건이 질문에 직접 일치하여 검색 정답으로 사용할 수 있는 Rule이다. 동일 기준이 2020 비정형과 2023 정형 기준에 동시에 존재하면 실제 검색 코퍼스에 두 문서가 모두 있는 경우 두 Rule 모두 relevance 2가 될 수 있다.

단, 하나의 Rule 안에서 세부 variant만 추가 확인하면 되는 경우에는 Rule 자체를 relevance 2로 유지할 수 있다. q17의 `차33-2`가 여기에 해당한다.

### relevance 1

중요한 조건 일부가 일치하여 검색 후보로 유용하지만 질문만으로 직접 적용할 수 없는 Rule이다. 다음 경우가 포함된다.

- 핵심 적용조건이 질문에 없음
- 여러 Rule 중 어느 하나일 수 있으나 차로·신호·시설 구조가 부족함
- 사고 장소나 진행 방향 일부가 다름
- 현 질문에 바로 적용할 수 없지만 사실 확인 후 relevance 2가 될 수 있음

### relevance 0

표면적인 단어는 비슷하지만 신호, 진행 방향, 사고 위치, 당사자 행동 등 핵심 조건이 충돌하는 hard negative다.

### no_relevant_document

v1.1에서 `no_relevant_document`는 “relevance 1 후보조차 없음”이 아니라 다음 의미다.

```text
현재 질문에 relevance 2로 확정할 수 있는 정확한 Rule이 코퍼스에 없음
```

따라서 no-exact Query에도 relevance 1 후보와 relevance 0 hard negative 행이 함께 존재할 수 있다. no-exact Query에는 별도의 요약행을 한 개 두고, 후보 Rule은 각각 flat 행으로 추가한다.

`query_answerability`는 Query 단위 의미를 명확하게 하기 위해 추가했다.

| 값 | 의미 |
|---|---|
| `has_exact_rule` | relevance 2 Rule이 하나 이상 존재 |
| `no_exact_rule` | relevance 2 Rule이 존재하지 않음 |

## 5. 검색 정답과 과실 계산 정답의 분리

정답지 한 행에는 검색 판단과 계산 annotation이 같이 있지만 두 판단은 분리해서 해석한다.

1. `rule_id`, `relevance`: 임베딩 검색 정답
2. `expected_variant_id`: Rule 내부 세부 시나리오 정답
3. `expected_base_ratio`: 적용 가능한 기본 과실
4. `expected_adjustments`: 질문에서 확인된 수정요소
5. `candidate_adjustments`: 사실 확인 후 적용될 수 있는 수정요소
6. `expected_final_ratio`: 모든 필수 사실이 확정된 경우의 최종 과실

### 계산 상태 규칙

| calculation_status | expected_final_ratio | 의미 |
|---|---|---|
| `calculable_from_query` | 숫자 가능 | 지정된 입력 사실만으로 최종 계산 가능 |
| `base_ratio_only` | 반드시 null | 기본비율은 알지만 수정요소 검토가 남음 |
| `requires_fact_resolution` | 반드시 null | variant 또는 핵심 사실이 부족함 |
| `requires_adjustment_review` | 반드시 null | 수정요소 적용 여부가 남음 |
| `no_exact_rule_in_corpus` | 반드시 null | 정확한 Rule이 없어 계산 불가 |

`expected_adjustments`에는 질문에서 확정된 사실만 넣는다. 확인되지 않은 안전표지, 야간, 시야장애 등은 `candidate_adjustments` 또는 `missing_facts`에 둔다.

## 6. raw_user_text와 query_text의 역할

v1.1은 다음 정책을 사용한다.

- 임베딩 검색용 텍스트: `query_text`
- 과실 계산 사실의 우선 근거: `raw_user_text`

`query_text`는 검색에 적합하게 정규화된 문장이지만 법률상 중요한 사실을 삭제해서는 안 된다. q25에서는 `raw_user_text`의 “이유 없이”가 `query_text`에서 사라졌고 이 사실이 최종 과실을 30% 바꾼다.

q25에는 다음 필드를 추가했다.

```json
"calculation_fact_source": "raw_user_text",
"query_normalization_warning": "'이유 없이'가 query_text에서 누락되어 최종 과실을 30% 바꾸는 핵심 사실이 손실됨"
```

향후 공통 질문지를 v1.1 이상으로 올릴 경우 q25의 `query_text`에도 “이유 없는 급정지”를 보존해야 한다. 질문지를 수정하면 판례·심의사례·인정기준이 공유하는 Query hash도 함께 바뀌므로 세 코퍼스 평가 버전을 동시에 갱신해야 한다.

## 7. Query별 수정 해설

### q07 — 부분 관련 2020 비정형 기준 추가

녹색 직진 대 맞은편 적색 우회전을 당사자 조건까지 직접 기술한 Rule은 없으므로 no-exact를 유지했다.

`nontypical_2020_no_01`은 녹색 직진 차량과 우회전 차량의 사고라는 점에서 가깝지만 보행자신호 및 우회전 허용 조건이 확인되지 않아 relevance 1로 추가했다.

### q13 — Rule·비율 유지, 페이지 범위 보류

`차16-3`, A20:B80, 사용자 B=80은 유지했다. 현재 canonical metadata도 298~298로 되어 있어 qrels만 298~301로 변경하지 않았다.

대신 다음 상태를 표시했다.

```json
"source_evidence_review_status": "pending_original_pdf_visual_check"
```

원본 PDF에서 사고상황·표·기본과실 해설이 301페이지까지 이어지는 것이 확인되면 qrels보다 먼저 canonical rule/chunk metadata를 수정해야 한다.

### q17 — 차33-2는 맞지만 variant와 비율 미확정

사용자 유턴 B와 맞은편 우회전 A는 `차33-2`에 직접 일치하므로 relevance 2를 유지했다.

| variant | 조건 | A 우회전 | B 유턴 |
|---|---|---:|---:|
| 가 | 상시유턴구역 | 30 | 70 |
| 나 | 신호유턴 | 80 | 20 |

질문에는 상시유턴인지 신호유턴인지 없으므로 다음 값을 null로 변경했다.

- `expected_variant_id`
- `expected_base_ratio`
- `expected_final_ratio`

### q23 — 단순 옆 차로 통과와 추월 후 진로변경 분리

2020 비정형 14번과 2023 `차47-3`은 모두 버스를 추월한 뒤 버스 앞으로 진로변경하는 상황을 전제로 한다. 질문에는 옆 차로로 통과했다고만 되어 있다.

따라서 두 Rule 모두 relevance 1로 변경하고 q23을 no-exact Query로 전환했다. 버스 앞으로 진로변경했다는 사실이 확인될 때만 A40:B60, 사용자 B=60을 계산한다.

### q25 — 이유 없는 급정지 +30 반영

사용자 후행차는 A, 선행 상대차는 B다.

```text
기본: A100 : B0
B 이유 없는 급정지: B +30
최종: A70 : B30
사용자: 70
상대방: 30
```

수정요소는 `adj_official_2023_차41-1_006`을 참조한다. 이 계산은 `raw_user_text`를 사실 근거로 사용한다.

### q27 — 1차 사고 사용자 과실 +10 반영

2차 추돌에서 후행 상대 추돌차는 A, 1차 사고 후 정지한 사용자 차량은 B다.

```text
기본: A80 : B20
사용자 B의 선행사고 과실: B +10
최종: A70 : B30
사용자: 30
상대방: 70
```

다만 “먼저 발생한 사고에 B의 과실이 있는 경우”라는 조건은 상세 Rule 해설에는 있으나 현재 `adjustment_factors.jsonl`에 독립 factor로 노출되어 있지 않다. 존재하지 않는 adjustment_id를 만들지 않고 `adjustment_id=null`, `source_block_id=block_official_2023_차42-1_005`로 기록했다.

이 항목은 계산기 연결 전에 전처리 adjustment 구조를 보완하거나 해설 기반 alias 규칙을 정의해야 한다.

### q28 — 기본비율만 유지하고 최종비율 null

`차42-1`과 기본 A80:B20은 유지했다. 그러나 다음 사실이 없어 최종비율은 확정하지 않았다.

- 1차 사고에 사용자 차량의 과실이 있었는지
- 정지 후 비상점멸등·안전표지 등 안전조치 여부
- 2차 추돌차량의 회피 가능성

### q35 — 회전교차로 후보 세 개를 relevance 1로 처리

질문에는 회전교차로의 차로 수와 차량별 차로가 없다. 따라서 다음을 모두 relevance 1 후보로 두었다.

- `차54-1`: 1차로형 또는 바깥쪽 회전차로 회전차 대 진입차
- `차54-3`: 안쪽 회전차로 진출차 대 진입차
- `회전-10`: 차로변경억제형 2차로 회전교차로의 특정 진입·진출 구조

`회전-10`의 relevance 2와 A20:B80 확정값은 제거했고 q35를 no-exact Query로 전환했다.

### q39 — 미확정 안전표지를 후보 수정요소로 이동

`차42-3`과 기본 A100:B0은 유지했다. 질문에는 안전표지 미설치 여부가 없으므로 다음 수정요소는 `expected_adjustments`에서 제거했다.

```text
B 안전표지 미설치 +10
```

해당 항목은 `candidate_adjustments`로 이동했고 최종비율은 null로 유지했다.

### q46 — 정확한 Rule 없음, 부분 관련 문서 명시

보행자 녹색 정상 횡단과 우회전 차량을 직접 결합한 Rule이 없어 no-exact를 유지했다.

| Rule | relevance | 판단 |
|---|---:|---|
| 보10 | 1 | 보행자 녹색 정상 횡단은 일치하지만 차량은 적색 직진 |
| 보17 | 1 | 우회전과 보행자 녹색은 유사하지만 횡단보도 밖 10m 이내 |
| 보18 | 0 | 보행자 적색 및 횡단보도 밖 횡단 |

### q47 — 보11은 후보지만 차량 조건 부족

보행자의 녹색 횡단 개시 후 적색 충돌은 `보11`과 일치한다. 하지만 보11은 자동차가 녹색신호에 직진하는 조건을 요구하며 질문에는 차량 신호와 진행 방향이 없다.

엄격한 relevance 정책에 따라 보11을 relevance 1로 변경하고 q47을 no-exact Query로 전환했다. `official_2023_보11_가`는 현재 variants 데이터에 존재하지 않으므로 만들지 않았고 `expected_variant_id=null`을 유지했다.

보행자 Rule의 원문 당사자 키를 보존하면서 계산기의 정규화 역할도 알 수 있도록 다음 필드를 사용한다.

```json
"expected_user_party_key": "차",
"expected_opponent_party_key": "보",
"expected_user_role": "vehicle",
"expected_opponent_role": "pedestrian"
```

### q48 — 보22 relevance 2 제거

질문에는 근처에 횡단보도가 존재한다. `보22`는 횡단보도가 없는 교차로 또는 그 부근 사고를 전제로 하므로 직접 적용할 수 없다. `보20`은 횡단보도 부근 사고이지만 직선도로 기준이다.

따라서 보22와 보20을 relevance 1로 두고 정확한 relevance 2 Rule이 없는 Query로 변경했다. 보13은 횡단보도 위 정상 횡단이므로 relevance 0을 유지했다.

### q49 — 현재 variant 유지

현재 전처리 variants 데이터에는 다음 ID가 실제로 존재한다.

```text
official_2023_거43-2_가
official_2023_거43-2_나
official_2023_거43-2_다
```

q49는 자전거 전용차로 상황이므로 `official_2023_거43-2_나`를 유지했다. Rule·variant 모델을 나중에 단순화한다면 Core와 qrels를 함께 마이그레이션해야 한다.

### q50 — base_ratio_only와 final ratio 정합성 수정

`도표30`, 기본 A70:B30, 사용자 B 매핑은 유지했다. 보도 주행 위반과 진입 속도 등 수정요소 검토가 남아 있으므로 `calculation_status=base_ratio_only`를 유지하고 `expected_final_ratio=null`로 변경했다.

## 8. source_evidence 페이지 경계 정책

기존 metadata에는 한 페이지가 두 Rule에 겹쳐 잡힌 사례가 있다.

```text
차1-1: 148~152
차1-2: 152~155
```

한 PDF 페이지에 이전 Rule의 끝과 다음 Rule의 시작이 함께 있을 수 있으므로 `page_end`를 일괄적으로 1씩 줄이지 않는다. 다음 원칙을 사용한다.

1. 페이지 범위는 사람의 원문 확인을 위한 보조 정보다.
2. 검색평가의 문서 동일성은 `rule_id`를 기준으로 한다.
3. 세부 근거는 가능하면 `chunk_id`와 `block_id`를 사용한다.
4. 한 페이지에 두 Rule이 있어도 chunk가 Rule별로 분리되어 있으면 페이지 중복을 허용한다.
5. 실제 다음 Rule 내용이 이전 Rule chunk에 섞였다면 전처리 chunk부터 수정한다.

q13과 피드백에서 제시된 페이지 경계 사례는 원본 PDF 시각 검수 후 별도 수정한다.

## 9. 임베딩 A/B 평가 사용법

- Hit@K, Recall@K, MRR의 exact 정답: relevance 2만 사용
- nDCG: relevance 2와 relevance 1의 graded relevance 사용
- hard-negative 진단: relevance 0 사용
- no-exact Query: 표준 exact 검색 지표의 분모에서 분리하여 별도 보고

no-exact Query에서 relevance 1 문서가 검색되었다고 해서 exact hit로 계산하면 안 된다. 다만 관련 후보를 상위에 올리는 능력은 nDCG 또는 별도 candidate recall로 진단할 수 있다.

## 10. 동결 전 검증 규칙

다음 조건을 모두 만족한 뒤 최종 Ground Truth로 동결한다.

- 모든 Query가 한 번 이상 등장함
- exact Query에는 relevance 2가 하나 이상 있음
- no-exact Query에는 relevance 2가 없음
- `base_ratio_only`이면 `expected_final_ratio`가 null임
- 숫자형 최종 과실은 사용자+상대방 합계가 100임
- `expected_adjustments`는 입력에서 확정된 사실만 포함함
- `candidate_adjustments`는 최종 계산에 자동 적용하지 않음
- `expected_variant_id`가 전처리 variants에 실제 존재함
- `expected_adjustments.adjustment_id`가 null이 아니라면 전처리 adjustment table에 존재함
- q27처럼 adjustment_id가 null이면 해설 block과 전처리 보완 사유가 기록되어 있음
- source evidence의 Rule·chunk 소속이 일치함
- JSONL이 중첩 `judgments` 배열 없이 Rule 판정당 한 줄인 flat 구조임

## 11. 남은 검수 항목

1. q13 및 겹치는 페이지 경계를 원본 PDF로 시각 확인
2. q27의 선행사고 B 과실 +10을 adjustment factor로 구조화할지 결정
3. q25의 query_text 정규화 문장을 공통 질문지 다음 버전에서 수정
4. q47의 보행자/차량 party key를 평가 코드가 허용하는지 확인
5. 두 명의 독립 검수 후 의견 불일치 항목 adjudication
6. 검수 완료 후 manifest의 `frozen_for_embedding_ab`를 true로 변경

## 12. 버전 판정

```text
fault_standard_qrels_v1
  -> 외부 PDF 재검토 피드백 반영
  -> fault_standard_qrels_v1.1
  -> 원본 PDF 페이지·전처리 구조·평가 코드 검수
  -> independent review
  -> adjudication
  -> frozen for embedding A/B
```

