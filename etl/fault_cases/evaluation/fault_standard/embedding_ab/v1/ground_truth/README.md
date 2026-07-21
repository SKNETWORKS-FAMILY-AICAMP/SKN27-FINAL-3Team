# 인정기준 Ground Truth

이 폴더는 파일럿과 분리된 인정기준 공통 50개 Query의 정식 Ground Truth 작업 위치다. 공통 질문은 `fault_common_queries_v1`로 고정하며 이 폴더에서 수정하지 않는다.

현재 평가 대상은 `fault_standard_qrels_v1.2.jsonl`이다. q31 구조 수정, q13 최종 판정, 50 Query 커버리지 검증과 manifest 동결을 완료했다.

## 파일

| 파일 | 역할 | 건수 |
|---|---|---:|
| `fault_standard_qrels_v1.jsonl` | 최초 정답 원본. 비교·이력 보존용 | 103줄 |
| `fault_standard_qrels_v1.1.jsonl` | PDF 재검토 피드백을 반영한 중간 이력 | 112줄 |
| `fault_standard_qrels_v1.1_해설.md` | v1.1 라벨링 정책과 수정 이력 | 1개 |
| `fault_standard_qrels_v1.2.jsonl` | 현재 정식 평가 대상. Rule 판정 110행 + q31 무정답 행 1행 | 111줄 / 50 Query |
| `fault_standard_qrels_v1.2_해설.md` | q01~q50을 각각 풀이한 문제집형 해설집 | 50문항 |
| `ground_truth_manifest.json` | v1 query/qrels 건수, 분포, hash와 검수 상태 | 1개 |
| `ground_truth_manifest_v1.1.json` | v1.1 건수, 분포, hash와 검수 상태 | 1개 |
| `ground_truth_manifest_v1.2.json` | 현재 승인본의 query/qrels/해설 SHA와 검증 상태 | 1개 |
| `labeling_report.md` | v1 최초 라벨링 당시 사고유형·난이도 분포와 검수 우선 항목 | 1개 |

## 상태 규칙

```text
structure_complete_qrels_111_rows_50_queries
  -> q13_final_judgment_approved
  -> content_review_complete
  -> ground_truth_manifest_v1.2_created
  -> frozen_for_embedding_ab=true
```

## v1.2 Flat qrels 규칙

- `judgments` 배열을 사용하지 않는다.
- Rule 판정행에는 실제 `rule_id`와 `relevance`가 있으며 판정 1건당 한 줄에 온다.
- hard negative도 별도 행이며 `relevance=0`, `is_hard_negative=true`로 표시한다.
- 판정할 Rule이 전혀 없는 q31도 같은 qrels에 `judgment_status=no_relevant_document`, `negative_control=true` 행으로 저장한다.
- q31 무정답 행에는 `rule_id`와 `relevance`가 없으며 일반 Hit@K·MRR·nDCG가 아니라 별도 abstention/negative-control 평가에 사용한다.
- 별도 Query metadata 파일은 사용하지 않는다.

Hit@K와 MRR의 정답은 `relevance=2`만 사용한다. `relevance=1`은 유사 Rule이며 nDCG 진단에만 사용한다. `relevance=0`은 hard-negative 진단에 사용한다. `query_answerability=no_exact_rule`인 Query는 표준 top-K 지표의 분모에서 분리하고 코퍼스 또는 질문의 정보 공백으로 보고한다.

과실비율 값은 retrieval 정답을 보조 검증하기 위한 annotation이다. `calculation_status`가 `requires_fact_resolution`, `requires_adjustment_review` 또는 `no_exact_rule_in_corpus`이면 최종 과실 숫자를 확정값으로 사용하지 않는다.

v1.2의 문항별 판단과 계산 과정은 `fault_standard_qrels_v1.2_해설.md`를 기준으로 한다. q31을 포함한 공통 질문 50개가 qrels 하나에 모두 존재해야 한다.
