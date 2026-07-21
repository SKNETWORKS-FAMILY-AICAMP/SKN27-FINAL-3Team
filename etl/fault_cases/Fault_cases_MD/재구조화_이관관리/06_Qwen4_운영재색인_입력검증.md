# 단계 6 Qwen 4B 운영 재색인 입력 검증

- 실행 ID: `qwen4_operational_20260721_v2`
- 생성 시각(UTC): `2026-07-21T00:12:47+00:00`
- 모델: `Qwen/Qwen3-Embedding-4B`
- 리비전: `5cf2132abc99cad020ac570b19d031efec650f2b`
- 차원: `2560`
- 판정: **RunPod 업로드 가능**

## 코퍼스별 검증 결과

| 코퍼스 | 상위 문서 | 임베딩 단위 | 단계 5 DB 검색 단위 | 판정 |
|---|---:|---:|---:|---|
| fault_standard | 277 | 277 | 277 | PASS |
| review_case | 226 | 904 | 904 | PASS |
| precedent | 987 | 8,334 | 8,334 | PASS |

## 평가자료

- 공통 승인 질문 50개: ID·승인 상태·본문 검증 PASS
- 인정기준 Complete30 질문·정답 30개: ID·입력 해시 검증 PASS
- 세 코퍼스 qrels: 공통 질문 50개 coverage와 실제 문서·청크 연결 검증 PASS
- qrels와 정답지는 RunPod ZIP에 포함하지 않음

## RunPod 번들

- 파일: `qwen4_three_corpus_operational_bundle_qwen4_operational_20260721_v2.zip`
- SHA-256: `ac1da0baeba891b589bbf85e57864c7bc14d814f91b19df137602db757bcc518`
- ZIP CRC·Linux `/` 경로·경로 탈출 검사 PASS
- `.env`, API 키, DB 비밀번호 포함 없음

## 다음 단계

RunPod Jupyter의 `/workspace`에 ZIP을 업로드한 뒤 `실행안내.md`의 단일 명령을 실행한다. 반환 tar.gz는 로컬 검증을 통과하기 전까지 운영 DB에 적재하지 않는다.
