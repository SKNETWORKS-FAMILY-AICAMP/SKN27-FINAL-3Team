# 공통 사용자 사고 query 평가셋

이 폴더는 심의사례, 인정기준, 판례 임베딩 모델 A/B에서 공통으로 사용하는 사용자 사고 query 50개의 원본 위치다.

## 파일

| 파일 | 역할 |
|---|---|
| `common_fault_queries_v1.jsonl` | 현재 공통 query 50개이자 세 코퍼스 정식 평가 입력 후보 |
| `common_fault_query_schema_v1.json` | v1 query 레코드 JSON Schema |
| `query_manifest.json` | v1 건수, 분포, hash, 검수 상태 |

## 검색 입력

실제 임베딩 검색에는 다음 필드만 사용한다.

```text
query_text -> agent_input.query_text
```

`raw_user_text`는 사용자가 입력한 원문 형태와 query 정규화 품질을 검토하기 위해 보관한다. 정규화 과정에서 과실 계산에 영향을 주는 사실을 삭제하거나 원문에 없는 도로 폭·진입 순서 등을 추가하면 안 된다. `accident_group`, `participants`, `issue_tags`, `difficulty`는 평가 분포와 실패 원인 분석용 metadata이며 query embedding 본문에 결합하지 않는다.

## 세 코퍼스 사용 규칙

50개 query 모두 다음 세 검색기에 전달한다.

```text
review_case
fault_standard
precedent
```

query 파일에는 정답 문서나 정답 청크 ID를 넣지 않는다. Ground Truth는 같은 `query_id`를 사용해 코퍼스별로 별도 작성한다.

```text
evaluation/review_case/embedding_ab/v1/ground_truth/review_case_qrels_v1.jsonl
evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2.jsonl
evaluation/precedent/embedding_ab/v1/ground_truth/precedent_qrels_v1.jsonl
```

세 정답지는 모두 `common_fault_queries_v1.jsonl`의 `fault_common_q01`~`fault_common_q50`을 사용한다. 인정기준 정답지는 `fault_standard_qrels_v1.2.jsonl`, 심의사례와 판례 정답지는 각 v1 파일을 사용한다. query version을 올릴 때는 일부 정답지만 먼저 전환하지 말고 세 qrels의 호환성 검수와 manifest 갱신을 같은 변경으로 처리한다.

기존 100개에서 50개로 줄일 때 사고군 비율과 난이도를 최대한 유지했다. 선정된 50개는 파일 순서대로 `fault_common_q01`부터 `fault_common_q50`까지 연속 재번호했으며, 세 코퍼스 qrels와 파일럿에도 같은 매핑을 적용했다.

## 현재 상태

- query 50개 층화 선정 완료
- 난이도 `easy 25 / medium 21 / hard 4`
- hard는 전체의 8%이며 `q11`, `q34`, `q38`, `q50`만 사용
- 이륜차 6개, 자전거 1개, 개인형 이동장치 1개 유지
- 실제 인정기준과 심의사례의 사고유형을 참고해 분포 구성
- `annotation_status=approved`
- 인정기준 qrels v1.2 111행/50 Query와 query ID 연결 확인
- 심의사례 qrels v1 89행/50 Query와 query ID 연결 확인
- 판례 qrels v1 58행/50 Query와 query ID 연결 확인
- 세 코퍼스 정답지 작성 완료 후 공통 Query v1 승인·동결 완료

`annotation_status`는 정답지 완성 후 `approved`로 갱신했다. 이후 질문 문장이나 ID를 바꾸려면 새 query version을 만들고 세 코퍼스 qrels를 모두 재검증한다.
