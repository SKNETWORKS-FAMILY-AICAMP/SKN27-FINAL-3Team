# 심의사례 임베딩 평가셋 v1

이 폴더는 사람이 작성하고 Git으로 관리하는 심의사례 임베딩 모델 A/B Ground Truth의 원본 위치다. 세 코퍼스 공통 Query는 이 폴더에 복제하지 않고 `evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl`을 참조한다.

| 경로 | 역할 | 현재 상태 |
|---|---|---|
| `pilot/` | 사고군별 10개 파일럿 qrels와 검수 보고서 | draft |
| `ground_truth/review_case_qrels_v1.jsonl` | 판정별 한 줄인 유일한 정답 원본이자 평가 입력 | 89줄 approved |
| `ground_truth/ground_truth_manifest.json` | query/corpus/정답지 SHA와 검증 상태 | approved |
| `ground_truth/labeling_report.md` | 분포, answerable 현황과 검수 우선순위 | 작성 완료 |
| `ground_truth/qrels_explanation.md` | 1~50번 문제별 정답, 원문 근거, 등급 이유와 오답 포인트 | 작성 완료 |
| `labeling_guide.md` | relevance 및 독립 검수 규칙 | v1 |

루트의 `review_case_eval_queries_v1.jsonl`, `review_case_qrels_v1.jsonl`, `query_manifest.json`은 공통 Query 구조를 확정하기 전에 만든 빈 초기 scaffold다. 정식 입력이나 정답지로 사용하지 않는다.

qrels는 관련 사례 판정마다 한 줄을 사용하므로 행 수가 50보다 많을 수 있지만 공통 Query ID 50개를 모두 커버해야 한다. 사람 검수 시에는 `qrels_explanation.md`와 함께 확인하되 정답 수정은 qrels에서만 수행한다. Recall/MRR에서는 `relevance >= 2`만 정답으로 인정하고 R1은 nDCG와 오차 분석에만 사용한다.

실행 시 이 폴더의 파일을 다음 경로로 복사하고 hash를 기록한다.

```text
etl/fault_cases/artifacts/embedding_ab/review_case/runs/<run_id>/eval_snapshot/
```

실행 snapshot에는 공통 Query, `ground_truth/review_case_qrels_v1.jsonl`과 manifest를 함께 복사한다. `artifacts` 아래 복사본이나 실행 결과를 이 폴더의 원본보다 먼저 수정하지 않는다.
