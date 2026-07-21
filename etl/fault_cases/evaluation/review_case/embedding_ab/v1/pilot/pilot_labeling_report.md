# 심의사례 Ground Truth 파일럿 v1

## 상태

이 파일럿은 relevance 기준을 조정하기 위한 `draft`이며 정식 50개 Ground Truth 중 먼저 검토한 10개다.

```text
공통 Query: 10개
사고그룹: 10개 전체에서 각 1개
난이도: easy 4 / medium 2 / hard 4
has_relevant_document: 8개
no_relevant_document: 2개
양의 judgment: 18행
전체 qrels: 20행
```

## 선정 Query와 판정 요약

| query_id | 사고그룹 | 난이도 | 상태 | 핵심 정답 |
|---|---|---|---|---|
| `fault_common_q01` | 신호 교차로 | easy | relevant | `2018-051544`(3), `2019-008384`(2) |
| `fault_common_q11` | 비신호 교차로 | hard | relevant | `2019-031656`(3), 동시진입·반대 선진입 사례 2건(1) |
| `fault_common_q17` | 유턴/차로규칙 | medium | relevant | 유턴 대 우회전 4건: 3점 2건, 2점 2건 |
| `fault_common_q25` | 추돌 | medium | relevant | `2019-056480`(3), `2019-039292`(3) |
| `fault_common_q30` | 주차장 | easy | relevant | `2018-066885`(3) |
| `fault_common_q34` | 회전교차로 | hard | relevant | `2018-060681`(3), `2019-039702`(2) |
| `fault_common_q38` | 고속도로 | hard | relevant | `2018-045956`(3), `2018-068200`(2) |
| `fault_common_q43` | 자동차-이륜차 | medium | relevant | `2019-045742`(3), `2018-060821`(2) |
| `fault_common_q46` | 자동차-보행자 | easy | no relevant | 보행자 신호를 언급한 차대차 사례는 당사자 유형 불일치로 기각 |
| `fault_common_q50` | 자동차-PM | hard | no relevant | 유사 도로진입 이륜차 사례는 PM과 당사자 유형이 달라 기각 |

## relevance 적용 기준

```text
3 = 사고 구조, 당사자 유형, 차량 행동, 핵심 쟁점이 직접 일치
2 = 핵심 사고 구조는 일치하지만 명시적인 수정요소가 추가됨
1 = 기본 사고 유형은 같지만 선진입, 진행 방향 등 핵심 조건이 다름
0 = 키워드만 유사하거나 당사자 유형과 충돌 관계가 다름
```

0점 후보는 최종 qrels에 넣지 않았다. 모델이 쉽게 혼동할 수 있는 기각 후보와 기각 이유는 아래에 남긴다.

## 주요 기각 후보

| query_id | 후보 | 기각 이유 |
|---|---|---|
| `fault_common_q01` | `2019-022179` | 녹색 직진 대 적색 직진은 유사하지만 상대 당사자가 이륜차 |
| `fault_common_q34` | `2018-047765`, `2019-023315` | 안쪽 차로 진출 차량의 상대가 바깥 차로 회전차량이 아니라 회전교차로 진입차량 |
| `fault_common_q38` | `2018-063611`, `2019-033766` | 주행차로 고장 정차가 아니라 갓길 주정차 사고 |
| `fault_common_q46` | `2018-062943` | 보행자 신호는 수정요소일 뿐 실제 당사자는 차대차 |
| `fault_common_q50` | `2019-015270` | 도로진입 구조는 유사하지만 상대 당사자가 개인형 이동장치가 아니라 이륜차 |

## 사람 검수에서 합의할 항목

1. `q11`에서 동시진입 또는 반대 차량 선진입 사례를 relevance 1로 유지할지 결정한다.
2. `q17`에서 유턴신호 사례와 상시유턴구역 사례를 모두 relevance 3으로 인정할지 결정한다.
3. `q46`, `q50`의 `no_relevant_document`를 정답 없음 탐지용 음성 Query로 승인할지 결정한다.
4. 합의 후 `adjudication_status`와 manifest의 `approved`, `reviewed_by`를 갱신한다.
