# 법률 RAG PostgreSQL lexical ↔ pgvector 실제 A/B 실행 기록

## 결론

2026-07-22에 동일한 공개 법률 질의 20개로 실제 A/B를 실행했다. PostgreSQL lexical은 20개 질의를 모두 처리했지만, pgvector는 OpenAI 질의 임베딩 인증 실패로 20개 모두 `unavailable`이 되었다. 따라서 이번 실행은 pgvector 전환 근거가 아니며, RAGAS도 실행하지 않았다.

## 실행 조건

- 코퍼스: PostgreSQL `law_chunks` 및 `law_embeddings` 97,394건
- 검증된 시드 임베딩 공간: `openai / text-embedding-3-large / 1024`
- 비교 경로: `postgres_lexical` ↔ `postgres_pgvector`
- 질의: 체크인된 `public_law` 20개, 동일 temporal/scope 필터, top-5
- 산출물: 로컬 gitignored `output/law_ingestion/evaluation/legal-ab-005/`

## 결과

| 지표 | PostgreSQL lexical | pgvector | 판정 |
| --- | ---: | ---: | --- |
| 완료 질의 | 20 / 20 | 0 / 20 | 비교 불가 |
| Recall@5 | 0.45 | 0.00 | 불가 |
| MRR | 0.385 | 0.000 | 불가 |
| nDCG@5 | 0.400889 | 0.000000 | 불가 |
| no-result rate | 0.00 | 1.00 | 불가 |
| p50 / p95 latency | 492 / 678 ms | 592 / 824 ms | 전환 근거 아님 |
| metadata complete rate | 1.00 | 0.00 | 불가 |

사전 점검은 `ready`였다. 즉 코퍼스 수, 임베딩 메타데이터, PostgreSQL 연결과 테이블 준비 상태는 통과했다. pgvector 실패의 직접 원인은 `OPENAI_API_KEY`에 대한 OpenAI 401 인증 거절이다.

## 보안 처리

- 실행 산출물에 설정 파일의 정확한 API 키가 포함되지는 않은 것을 로컬 비교로 확인했다.
- 외부 제공자 예외 문구를 `error_code`에 그대로 기록하는 것은 안전하지 않다. 다음 실행부터 평가기에서 401 인증 실패는 `openai_authentication_failed`로만 정규화한다.
- 기존 `legal-ab-005`는 실패 재현 근거로만 로컬 gitignored 경로에 보존하며, Git에 추가하지 않는다.

## 다음 실행 조건

1. 로컬 `.env.rag-eval`의 `OPENAI_API_KEY`를 유효한 키로 교체한다. 키 값은 Git, 보고서, 명령 출력에 기록하지 않는다.
2. 새 run ID로 A/B를 다시 실행한다.
3. 두 backend가 모두 20개 질의를 처리한 경우에만 같은 조건으로 RAGAS를 실행한다.
4. `transition_decision.eligible=true`와 RAGAS gate를 모두 충족하기 전에는 pgvector 우선 전환을 하지 않는다.
