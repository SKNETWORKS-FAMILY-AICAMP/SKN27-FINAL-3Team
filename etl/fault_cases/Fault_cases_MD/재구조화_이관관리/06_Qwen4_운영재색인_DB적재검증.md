# 단계 6 Qwen 4B 운영 재색인 DB 적재 검증

- 실행 ID: `qwen4_operational_20260721_v2`
- 결과 압축 SHA-256: `20ac68074d9cb7755ac7a8f75cbb8d8c4116f26d2769e400d008d572fbdcc456`
- 상태: **PROMOTED**
- staging schema: `rag_qwen4_stage_perational20260721v2_20ac6807`
- 이전 활성 schema: `rag_qwen4_prev_perational20260721v2_20ac6807`

| DB | 문서 | 청크 | 새 벡터 | 판정 |
|---|---:|---:|---:|---|
| fault_standard_db | 277 | 0 | 277 | PASS |
| review_case_db | 226 | 904 | 904 | PASS |
| precedent_db | 987 | 8,334 | 8,334 | PASS |

기존 시험 벡터에는 append하지 않았으며, 세 DB staging이 모두 통과한 경우에만 활성 schema를 전환한다.

## 독립 재검증

- 활성 `rag_qwen4` 스키마의 문서·청크·벡터 건수를 DB별로 다시 조회해 위 표와 일치함을 확인했다.
- 세 DB의 `vector_dims(embedding) <> 2560` 건수는 모두 `0`이다.
- 세 DB의 모델명·고정 리비전·`l2_normalized` 정규화 계약 불일치 건수는 모두 `0`이다.
- 이전 운영 스키마 `rag_qwen4_prev_perational20260721v2_20ac6807`가 세 DB에 각각 존재함을 확인했다. 따라서 단계 7을 시작하기 전에도 즉시 롤백할 수 있다.
