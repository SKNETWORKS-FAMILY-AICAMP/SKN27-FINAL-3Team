# V6 G0 — FULL-50 데이터 완성도 감사

## 결론

현재 50개 질문과 50개 완료 Facts는 존재하지만, FULL-50 Gold Outcome은 아직 완성되지 않았다.
따라서 V6 A/B/C 본실험은 시작하지 않는다.

## 집계

| 항목 | 건수 |
|---|---:|
| 기준 질문 | 50 |
| 완료 Supervisor Facts | 50 |
| Gold 후보: Rule·mapping·final ratio 보유 | 25 |
| Gold final ratio 미보유 | 24 |
| positive Rule 자체 없음 | 1 |
| Facts에 unknown/null 값 존재 Case | 31 |

## FULL-50 Gate 실패 Case

| Case | 상태 | best qrels Rule | qrels final ratio | Facts unknown 수 |
|---|---|---|---|---:|
| fault_common_q04 | missing_gold_ratio | official_2023_차2-6 | - | 0 |
| fault_common_q07 | missing_gold_ratio | nontypical_2020_no_01 | - | 0 |
| fault_common_q09 | missing_gold_ratio | official_2023_차12-1 | - | 0 |
| fault_common_q11 | missing_gold_ratio | official_2023_차12-2 | - | 0 |
| fault_common_q12 | missing_gold_ratio | official_2023_차15-1 | - | 0 |
| fault_common_q15 | missing_gold_ratio | official_2023_차12-1 | - | 0 |
| fault_common_q17 | missing_gold_ratio | official_2023_차33-2 | - | 2 |
| fault_common_q18 | missing_gold_ratio | official_2023_차11-1 | - | 2 |
| fault_common_q19 | missing_gold_ratio | official_2023_차21-1 | - | 2 |
| fault_common_q22 | missing_gold_ratio | official_2023_차43-3 | {'user': 50, 'opponent': 50} | 2 |
| fault_common_q23 | missing_gold_ratio | nontypical_2020_no_14 | - | 2 |
| fault_common_q24 | missing_gold_ratio | official_2023_차43-1 | - | 2 |
| fault_common_q28 | missing_gold_ratio | official_2023_차42-1 | - | 2 |
| fault_common_q29 | missing_gold_ratio | official_2023_차31-2 | - | 2 |
| fault_common_q31 | no_positive_rule | - | - | 2 |
| fault_common_q35 | missing_gold_ratio | official_2023_차54-1 | - | 0 |
| fault_common_q37 | missing_gold_ratio | official_2023_차43-2 | - | 2 |
| fault_common_q38 | missing_gold_ratio | official_2023_차42-1 | - | 2 |
| fault_common_q39 | missing_gold_ratio | official_2023_차42-3 | - | 2 |
| fault_common_q41 | missing_gold_ratio | official_2023_차12-1 | - | 2 |
| fault_common_q43 | missing_gold_ratio | nontypical_2020_no_21 | - | 2 |
| fault_common_q46 | missing_gold_ratio | official_2023_보10 | - | 2 |
| fault_common_q47 | missing_gold_ratio | official_2023_보11 | - | 2 |
| fault_common_q48 | missing_gold_ratio | official_2023_보20 | - | 2 |
| fault_common_q50 | missing_gold_ratio | pm_auto_2021_도표30 | - | 2 |

## 다음 Gate

G1-LABEL에서 이 목록의 각 Case에 대해 PDF Evidence 기반 Rule·Party mapping·Variant·Adjustment·final ratio를 확정해야 한다.
정확한 PDF Rule이 없는 Case는 비율을 추정하지 않고, FULL-50 유지 방법(추가 Facts 또는 Case 교체)을 사용자에게 보고한다.
