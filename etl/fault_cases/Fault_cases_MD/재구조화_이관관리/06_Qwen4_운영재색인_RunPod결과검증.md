# 단계 6 RunPod Qwen 4B 결과 수신 검증

- 실행 ID: `qwen4_operational_20260721_v2`
- 결과 압축 SHA-256: `20ac68074d9cb7755ac7a8f75cbb8d8c4116f26d2769e400d008d572fbdcc456`
- 검증 파일 수: `19`
- 운영 DB 변경: **없음**
- 판정: **PASS — staging 적재 가능**

| 코퍼스 | 벡터 수 | 차원 | L2 norm 범위 | 판정 |
|---|---:|---:|---:|---|
| fault_standard | 277 | 2560 | 1.000000~1.000000 | PASS |
| review_case | 904 | 2560 | 1.000000~1.000000 | PASS |
| precedent | 8,334 | 2560 | 1.000000~1.000000 | PASS |

공통 50문항의 코퍼스별 질문 벡터 3종과 인정기준 Complete30 질문 벡터도 동결 입력 ID·instruction 포함 입력 해시 기준으로 전수 검증했다.
