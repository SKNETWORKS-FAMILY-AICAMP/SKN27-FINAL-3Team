# 심의사례 Ground Truth v1

이 폴더는 공통 사고 Query 50개에 대응하는 심의사례 전용 정답지 원본을 보관한다. `pilot/`은 기준 합의용 10개 초안이고, 이 `ground_truth/` 폴더는 50개 전체 판정본이다.

## 파일

| 파일 | 역할 | 건수 |
|---|---|---:|
| `review_case_qrels_v1.jsonl` | 유일한 정답 원본이자 평가 입력. 사례 판정당 한 줄 | 89줄 |
| `ground_truth_manifest.json` | 입력·코퍼스·정답지 SHA, 건수, 상태와 검증 결과 | 1개 |
| `labeling_report.md` | 분포, answerable 현황, 정답 없음 목록과 검수 우선순위 | 1개 |
| `qrels_explanation.md` | 1~50번 문제별 정답, 원문 근거, 등급 이유와 오답 포인트 | 1개 |

## 상태

현재 버전은 `approved`다. 최종 판정 검수 결과를 데이터 소유자가 수용했으며 qrels와 해설의 SHA-256을 manifest에 고정했다.

승인본의 판정을 직접 덮어쓰지 않는다. 이후 판정이 바뀌면 새 Ground Truth 버전을 만들고 qrels, 해설과 manifest의 SHA를 함께 갱신한다.

## 평가 규칙

- 모델에는 공통 파일의 `query_text`만 입력한다.
- Hit와 MRR은 `relevance >= 2` 정답이 있는 Query 32개를 분모에 포함한다.
- nDCG는 R1~R3 판정이 있는 Query 41개를 graded relevance 대상으로 사용한다.
- `no_relevant_document`는 일반 retrieval 0점으로 넣지 않고 코퍼스 공백으로 별도 집계한다.
- `review_case_id`가 1차 정답이며 `chunk_id`와 단일 `expected_chunk_types`는 청크 진단에 사용한다.
- 사람 검수 시 `qrels_explanation.md`를 사용하지만 별도 정답 원본으로 취급하지 않는다.
