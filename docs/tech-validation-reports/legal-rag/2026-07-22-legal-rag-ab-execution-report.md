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

## 실행 업데이트 — `legal-ab-010-ragas`

유효한 OpenAI 키와 Python 3.13 평가 환경에서 같은 corpus snapshot과 공개 법률 20개 질의로 A/B를 다시 실행했다. 두 backend 모두 20개 질의를 처리했고, 시드 메타데이터와 출처 메타데이터도 모두 확인됐다.

| 지표 | PostgreSQL lexical | pgvector |
| --- | ---: | ---: |
| Recall@1 / Recall@3 / Recall@5 | 0.35 / 0.40 / 0.45 | 0.50 / 0.75 / 0.80 |
| MRR | 0.385000 | 0.620833 |
| nDCG@5 | 0.400889 | 0.666173 |
| no-result rate | 0.00 | 0.10 |
| p50 / p95 latency | 377 / 719 ms | 900 / 1,142 ms |
| metadata complete rate | 1.00 | 1.00 |

pgvector는 검색 정확도 지표에서 lexical보다 높았지만, no-result rate와 p95 latency gate를 통과하지 못했다. 따라서 pgvector 우선 전환은 하지 않는다.

RAGAS 20건 × 두 backend 실행은 현재 `ragas_execution_failed`로 끝나 지표를 남기지 못했다. 공개 법률 1건의 최소 재현에서는 네 metric이 실제로 실행되는 것을 확인했지만, 이는 전체 평가의 대체 근거가 아니다. 다음 작업은 batch 실패의 안전한 오류 분류와 대표 질의별 실패 격리이며, 그 전까지 RAGAS gate는 `not_evaluated`를 유지한다.

## Issue #285 구현 검증

2026-07-22에 배치 실패 격리 계약을 구현하고 로컬 회귀 테스트를 수행했다. `run_ragas()`는 각 공개 법률 질의를 독립적으로 생성·평가하며, 한 질의의 실패나 빈 context는 다음 질의를 중단시키지 않는다. 질의 결과에는 `query_id`, `backend`, `status`, 안전한 `error_code`, `latency_ms`만 남기며, 예외 원문·질문·답변·context·키 값은 남기지 않는다.

모든 질의가 성공하고 `context_precision`, `context_recall`, `faithfulness`, `answer_relevancy`가 모두 유한한 0~1 값일 때만 backend aggregate가 `evaluated`와 metric을 반환한다. 하나라도 실패·누락·NaN·범위 밖이면 aggregate는 `not_evaluated` / `incomplete_ragas_evidence`이며 metric을 반환하지 않는다. 빈 context는 외부 API를 호출하지 않고 `no_ragas_contexts`로 기록한다.

`test/test_legal_rag_evaluation.py` 및 `test/test_legal_rag_evaluation_environment.py`의 로컬 계약 테스트 32개가 통과했다. 이는 구현 계약 검증일 뿐 실제 OpenAI/RAGAS 20건 × 두 backend 재실행은 아직 수행하지 않았으므로, `legal-ab-010-ragas`의 RAGAS 결과와 gate 상태는 계속 `not_evaluated`다.
