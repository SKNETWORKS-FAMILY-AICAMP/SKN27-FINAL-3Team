# 인정기준 공통 50개 정답지 1차 작성 보고서

작성일: 2026-07-15

## 결과 요약

| 항목 | 결과 |
|---|---:|
| 공통 query coverage | 50 |
| flat qrels 판정 행 | 103 |
| `has_relevant_document` query | 47 |
| `no_relevant_document` query | 3 |
| `relevance=2` 판단 | 49 |
| `relevance=1` 판단 | 4 |
| `relevance=0` hard negative | 47 |
| 서로 다른 exact Rule | 36 |

`relevance=2` 판단이 49건인 이유는 `q06`, `q44`에 2020 비정형 기준과 2023 공식 기준의 의미상 동일 Rule이 함께 존재하기 때문이다. 어느 한쪽을 검색해도 정확한 인정기준을 찾은 것으로 평가한다.

정답 원본은 심의사례와 같은 flat JSONL이다. 정답이 있는 query는 Rule 판정 1건당 한 줄이고, exact Rule이 없는 3개 query는 `no_relevant_document` 한 줄씩만 둔다. `judgments` 중첩 배열은 사용하지 않는다.

## 사고유형 분포

| 사고유형 | 개수 | 비율 |
|---|---:|---:|
| 신호 교차로 | 8 | 16% |
| 무신호 교차로 | 7 | 14% |
| 회전·차로규칙 | 5 | 10% |
| 차로변경·추돌 | 8 | 16% |
| 주차·도로진입 | 4 | 8% |
| 회전교차로 | 3 | 6% |
| 고속도로 | 4 | 8% |
| 이륜차 | 6 | 12% |
| 보행자 | 3 | 6% |
| 자전거·PM | 2 | 4% |
| 합계 | 50 | 100% |

## 난이도 분포

| 난이도 | 개수 | 비율 |
|---|---:|---:|
| easy | 25 | 50% |
| medium | 21 | 42% |
| hard | 4 | 8% |
| 합계 | 50 | 100% |

사고유형과 난이도는 qrels 작성자가 새로 배정한 값이 아니라 동결된 공통 query의 metadata를 그대로 사용했다.

## exact Rule이 없는 3개

| query_id | 사유 | 가장 가까운 Rule |
|---|---|---|
| `fault_common_q07` | 녹색 직진 대 맞은편 적색신호 우회전을 신호조건까지 직접 다룬 Rule 없음 | `official_2023_차5-1` |
| `fault_common_q31` | 양 차량이 주차장 통로에서 서로 다른 방향으로 동시에 후진하는 Rule 없음 | `nontypical_2020_no_19` |
| `fault_common_q46` | 보행자 녹색 횡단보도 정상횡단 대 우회전 차량을 직접 결합한 Rule 없음 | `official_2023_보10`, `official_2023_보13` |

이 3개는 표준 Hit@K, MRR 분모에서 분리하고 `no_relevant_document` 또는 abstention 진단에 사용한다.

## 우선 검수 대상

다음 query는 Rule 검색 정답과 별개로 최종 과실 계산에 필요한 사실이 부족하거나 조정요소 검토가 필요하다.

```text
q11  소로 선진입 인정 여부
q15  우측·좌측 도로 당사자 매핑
q19  두 좌회전 차로 중 사용자 위치
q24  본선차·합류차 당사자 매핑
q35  2025 2차로형 기준 적용 범위
q38  고속도로 주행차로 고장 정차의 조정요소
q39  갓길 안전표지 및 불가피한 주정차 여부
q48  횡단 도로폭과 횡단보도 거리
```

`q25`, `q27`, `q28`, `q50`은 기본비율까지 기록했지만 실제 최종 과실은 추가 조정사실을 확인해야 한다.

## 검수 게이트

1. 검수자 A/B가 서로의 라벨을 보지 않고 `relevance`, 당사자 매핑, 변형 조건을 독립 판정한다.
2. exact Rule 또는 당사자 매핑이 다르면 원문 PDF 페이지를 다시 확인한다.
3. 불일치는 제3 검수자가 adjudication한다.
4. 승인 후 `annotation_status`, manifest hash와 `frozen_for_embedding_ab`를 갱신한다.
5. 승인 전 qrels 결과를 보고 query 문장이나 임베딩 template를 수정하지 않는다.
