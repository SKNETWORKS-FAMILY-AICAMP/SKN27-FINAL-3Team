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

## 실행 업데이트 — `legal-ab-012-ragas-20260722`

평가 전용 `.env.rag-eval`과 동일 corpus snapshot에서 공개 법령 20개 질의를 다시 실행했다. preflight는 `law_chunks`·`law_embeddings` 각각 97,394건, `openai / text-embedding-3-large / 1024` 단일 embedding space로 `ready`였다.

| 지표 | PostgreSQL lexical | pgvector |
| --- | ---: | ---: |
| 처리된 평가 응답 | 20 / 20 | 20 / 20 |
| Recall@5 / MRR / nDCG@5 | 0.45 / 0.385000 / 0.400889 | 0.00 / 0.000000 / 0.000000 |
| no-result / unavailable rate | 0.00 / 0.00 | 1.00 / 1.00 |
| p50 / p95 latency | 454 / 786 ms | 428 / 757 ms |
| metadata complete rate | 1.00 | 0.00 |

pgvector의 20건은 모두 안전한 `openai_authentication_failed`로 기록됐다. RAGAS는 pgvector의 빈 context 20건을 외부 호출 없이 `no_ragas_contexts`로 건너뛰었고, lexical 20건은 각각 `ragas_runtime_unavailable`로 격리됐다. 두 backend aggregate는 모두 `not_evaluated / incomplete_ragas_evidence`이며 RAGAS metric은 생성되지 않았다. 키 값과 예외 원문은 산출물·이 보고서에 기록하지 않는다.

`transition_decision.eligible`는 `false`다. 실패 gate는 retrieval 품질 회귀, pgvector unavailable·metadata 불완전, 그리고 `ragas_not_evaluated`다. 인증이 가능한 평가 전용 OpenAI 키를 로컬에서 교체한 뒤에만 새 run ID로 재실행하며, 그 전까지 pgvector 우선 전환과 C-1 완료 처리는 하지 않는다.

실행기는 Django를 직접 초기화하므로 `requirements-etl.txt`에 `Django==6.0.6`을 명시하고 회귀 테스트로 고정했다. `test/test_legal_rag_evaluation.py`, `test/test_legal_rag_evaluation_environment.py`, `test/test_legal_rag_service.py`의 관련 회귀 58개가 통과했다.

## 실행 업데이트 — `legal-ab-013-ragas-20260722`

평가 전용 키를 교체한 뒤 동일한 corpus snapshot과 공개 법령 20개 질의로 다시 실행했다. preflight는 계속 `ready`였고, PostgreSQL lexical은 20개 질의를 모두 완료했다(Recall@5 0.45, MRR 0.385, nDCG@5 0.401, p50/p95 430/614 ms).

그러나 pgvector 20개는 다시 모두 안전한 `openai_authentication_failed`로 기록됐다. 즉 새 키도 질의 임베딩을 위한 OpenAI 인증을 통과하지 못했다. pgvector는 빈 context로 RAGAS 외부 호출 없이 `no_ragas_contexts`가 됐고, lexical 20개는 `ragas_runtime_unavailable`로 질의별 격리되어 어느 backend도 aggregate metric을 생성하지 못했다.

`transition_decision.eligible`는 계속 `false`다. 새로운 키를 발급하거나 프로젝트·결제·권한이 활성화된 키로 교체한 다음, 새 run ID에서 pgvector의 `openai_authentication_failed`가 0건임을 먼저 확인해야 한다. 그 조건이 충족되기 전에는 pgvector 전환과 C-1 완료 처리를 하지 않는다. 키 값, 예외 원문, 질의·답변·context는 기록하지 않는다.

## 실행 환경 업데이트 — `legal-ab-014` / `legal-ab-015`

키 교체 후 `legal-ab-014-ragas-20260722`와 `legal-ab-015-ragas-20260722`를 재시도했다. `014`는 출력 디렉터리만 만들고 종료됐으며, `015`는 후보와 RAGAS 입력까지만 만들고 `summary.json` 작성 전에 RAGAS 평가 프로세스가 종료됐다. 따라서 두 디렉터리는 완료된 A/B 실행 근거나 전환 gate 판단에 사용하지 않는다.

`015`의 후보 산출물은 키 교체 효과를 제한적으로 확인한다. PostgreSQL lexical은 20개 모두 `ready`이고 pgvector는 18개 `ready`, 2개 `empty`이며 `openai_authentication_failed`는 없다. 하지만 RAGAS 중단으로 backend aggregate와 `transition_decision`이 없으므로 이 수치는 품질 비교·전환 근거가 아니다.

현재 로컬 평가 런타임은 Python 3.14.3뿐이다. 이 환경에서 Hugging Face `Dataset.from_list()`의 fingerprint 직렬화 `TypeError`를 재현했고, 평가기는 RAGAS 0.2.15가 지원하는 `EvaluationDataset.from_list()`를 사용하도록 수정했다. 관련 회귀 59개는 통과했다. 그러나 실제 RAGAS 평가 호출은 Python 프로세스를 종료해 안전한 query ledger나 aggregate를 남기지 못했다.

다음 재실행은 Python 3.13 평가 전용 가상환경에서만 수행한다. 그 환경에서 단일 공개 법령 RAGAS 평가가 summary까지 완주하는 것을 먼저 확인한 뒤, 새 run ID로 20개 질의의 PostgreSQL lexical ↔ pgvector A/B와 RAGAS를 실행한다. 그 전까지 C-1과 pgvector 전환은 보류한다.

## 실행 업데이트 — `legal-ab-016-ragas-20260722`

Python 3.13.14 전용 가상환경에서 RAGAS 0.2.15의 `EvaluationDataset` 스키마(`user_input`, `reference`, `response`, `retrieved_contexts`)로 단일 공개 법령 평가를 먼저 통과한 뒤, 같은 corpus snapshot과 공개 법령 20개 질의의 전체 A/B·RAGAS를 완료했다. preflight는 `ready`였고 `law_chunks`·`law_embeddings`는 각각 97,394건, embedding space는 `openai / text-embedding-3-large / 1024` 단일 공간이었다.

| 지표 | PostgreSQL lexical | pgvector |
| --- | ---: | ---: |
| query count | 20 | 20 |
| completed run count | 20 | 20 |
| Recall@1 | 0.350000 | 0.500000 |
| Recall@3 | 0.400000 | 0.750000 |
| Recall@5 | 0.450000 | 0.800000 |
| MRR | 0.385000 | 0.620833 |
| nDCG@5 | 0.400889 | 0.666173 |
| no-result rate | 0.000000 | 0.100000 |
| unavailable rate | 0.000000 | 0.000000 |
| metadata complete rate | 1.000000 | 1.000000 |
| p50 latency | 595 ms | 1,058 ms |
| p95 latency | 942 ms | 2,826 ms |

lexical RAGAS는 20개 모두 평가돼 `context_precision` 0.654, `context_recall` 0.650, `faithfulness` 0.735, `answer_relevancy` 0.309를 기록했다. pgvector는 18개가 평가됐지만 2개가 빈 context여서 외부 호출 없이 `no_ragas_contexts`로 기록됐다. 엄격한 완전성 계약에 따라 pgvector aggregate는 `not_evaluated / incomplete_ragas_evidence`이며 metric을 만들지 않는다.

`transition_decision.eligible`는 `false`다. pgvector는 검색 정확도 지표가 높지만 no-result rate 0.10, p95 latency 2,826 ms, 그리고 RAGAS aggregate 미생성으로 `no_result_rate_regression`, `p95_latency_regression`, `ragas_not_evaluated` gate를 통과하지 못했다. 따라서 pgvector 우선 전환과 C-1 완료 처리는 하지 않는다.

## 검증·테스트 증적 — `legal-ab-016-ragas-20260722`

### 실행 환경과 의존성 무결성

| 항목 | 확인값 |
| --- | --- |
| Python | 3.13.14 |
| Django | 6.0.6 |
| RAGAS | 0.2.15 |
| datasets | 3.6.0 |
| openai | 2.44.0 |
| langchain-openai | 0.3.35 |
| `pip check` | `No broken requirements found` |
| corpus snapshot | `30b0541ac5d567749daa301930c8c71d292cfa4dfeb07de8bc413fa5ee7e52b0` |
| searchable chunks / embeddings | 97,394 / 97,394 |
| embedding space | `openai / text-embedding-3-large / 1024` |

### 자동화 테스트와 정적 검증

RAGAS 0.2 계약 회귀 테스트를 추가했다. 이 테스트는 구 `datasets.Dataset.from_list()` 사용을 즉시 실패시키고, `EvaluationDataset.from_list()`에 전달하는 각 행이 `user_input`, `reference`, `response`, `retrieved_contexts`로 정확히 변환되는지를 검증한다. 이 계약은 수정 전에는 구 데이터셋 API 사용 때문에 실패했고, RAGAS 0.2 스키마로 교체한 뒤 통과했다.

| 검증 | 명령 또는 범위 | 결과 |
| --- | --- | --- |
| RAGAS 실행·환경·서비스 회귀 | `pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py test/test_legal_rag_service.py --timeout=30 -p no:cacheprovider` | **59 passed in 1.11s** |
| 변경 공백 오류 | `git diff --check` | 통과 (Windows CRLF 변환 안내만 출력, 공백 오류 없음) |
| 단일 공개 법령 RAGAS 사전 검증 | RAGAS 실행부터 summary 생성까지 | 통과; metric 이름 `answer_relevancy`, `context_precision`, `context_recall`, `faithfulness` 확인 |

### 전체 라이브 A/B·RAGAS 실행 증적

`legal-ab-016-ragas-20260722`는 동일 corpus snapshot과 공개 법령 20개 질의로 두 backend를 끝까지 실행했다. 후보 상태는 lexical 20건 `ready`, pgvector 18건 `ready`와 2건 `empty`였다. 인증 실패나 backend unavailable은 없었다.

RAGAS는 생성·판정 모델 모두 `gpt-4o-mini`, judge embedding은 `text-embedding-3-small`을 사용했다. latency는 RAGAS가 실제로 평가한 레코드만 대상으로 계산했다.

| RAGAS 지표 | PostgreSQL lexical | pgvector |
| --- | ---: | ---: |
| query count | 20 | 20 |
| evaluated count | 20 | 18 |
| not-evaluated count | 0 | 2 |
| `no_ragas_contexts` | 0 | 2 |
| aggregate status | `evaluated` | `not_evaluated` |
| aggregate reason | 없음 | `incomplete_ragas_evidence` |
| context precision | 0.653819 | 생성하지 않음 |
| context recall | 0.650000 | 생성하지 않음 |
| faithfulness | 0.735000 | 생성하지 않음 |
| answer relevancy | 0.309416 | 생성하지 않음 |
| evaluated-only p50 latency | 11,878 ms | 13,958 ms |
| evaluated-only p95 latency | 16,341 ms | 19,090 ms |
| evaluated-only mean latency | 12,785.850 ms | 13,974.611 ms |

pgvector RAGAS metric을 공란·0·부분 평균으로 대체하지 않았다. 20건 중 2건이 context 없이 끝난 이상, 완료되지 않은 evidence를 유효 aggregate로 오인하지 않도록 계약상 aggregate를 생성하지 않는 것이 맞다.

### 전환 게이트와 후속 조치

| 게이트 | 현재값 | 통과 기준 | 판정 |
| --- | ---: | ---: | --- |
| no-result 회귀 | 0.100000 | lexical 0.000000 이하 | 실패 |
| p95 검색 latency 회귀 | 2,826 ms | lexical p95의 1.5배 이하 = 1,413 ms 이하 | 실패 |
| pgvector RAGAS 완결성 | 18 / 20 평가 | 20 / 20 평가 및 aggregate 생성 | 실패 |

따라서 `transition_decision.eligible=false`를 유지한다. 다음 작업은 pgvector의 2건 no-result 원인과 p95 지연을 해결하고, 같은 20개 질의를 재실행해 **no-result 0, p95 1,413 ms 이하, RAGAS 20/20 평가 및 aggregate 생성**을 함께 충족하는지 확인하는 것이다. 이 세 조건이 충족되기 전에는 pgvector 우선 전환이나 C-1 완료를 선언하지 않는다.

## 실행 업데이트 — `legal-ab-018-pgvector-gates-20260722`

Issue #289 구현 후 Python 3.13.14 전용 환경에서 같은 공개 법령 20개 질의와 동일 corpus snapshot으로 PostgreSQL lexical ↔ pgvector A/B·RAGAS를 다시 실행했다. preflight는 `ready`였고 searchable chunks와 embeddings는 각각 97,394건, embedding space는 `openai / text-embedding-3-large / 1024` 단일 공간이었다. `legal-ab-017-pgvector-gates-20260722`는 장기 실행 세션이 종료되어 `summary.json`이 없는 부분 산출물만 남았으므로 전환 근거에서 제외한다. 아래 값은 `summary.json`이 생성되고 종료 코드 0으로 끝난 `018`의 측정값이다.

| 지표 | PostgreSQL lexical | pgvector |
| --- | ---: | ---: |
| query count / completed run count | 20 / 20 | 20 / 20 |
| Recall@1 / Recall@3 / Recall@5 | 0.350000 / 0.400000 / 0.450000 | 0.500000 / 0.900000 / 1.000000 |
| MRR / nDCG@5 | 0.385000 / 0.400889 | 0.705833 / 0.780155 |
| no-result rate / unavailable rate | 0.000000 / 0.000000 | 0.000000 / 0.000000 |
| metadata complete rate | 1.000000 | 1.000000 |
| 전체 p50 / p95 latency | 575 ms / 756 ms | 394 ms / 589 ms |

pgvector의 전체 latency phase 증적은 다음과 같다. lexical 경로는 이번 telemetry 대상이 아니므로 각 phase의 count는 0이며, 이를 0 ms로 측정됐다는 뜻으로 해석하지 않는다.

| phase | PostgreSQL lexical (count / p50 / p95 / mean) | pgvector (count / p50 / p95 / mean) |
| --- | ---: | ---: |
| preflight | 0 / 0 / 0 / 0.000 ms | 20 / 6 / 9 / 6.450 ms |
| embedding | 0 / 0 / 0 / 0.000 ms | 20 / 318 / 445 / 421.250 ms |
| vector query | 0 / 0 / 0 / 0.000 ms | 20 / 88 / 125 / 89.800 ms |
| result mapping | 0 / 0 / 0 / 0.000 ms | 20 / 0 / 0 / 0.000 ms |

RAGAS는 생성·판정 모델 `gpt-4o-mini`, judge embedding `text-embedding-3-small`을 사용했다. 두 backend 모두 20개 전부 `evaluated`였고 error code는 모두 없었다.

| RAGAS 지표 | PostgreSQL lexical | pgvector |
| --- | ---: | ---: |
| evaluated / not-evaluated count | 20 / 0 | 20 / 0 |
| aggregate status | `evaluated` | `evaluated` |
| context precision | 0.661944 | 0.811806 |
| context recall | 0.700000 | 0.900000 |
| faithfulness | 0.753333 | 0.840833 |
| answer relevancy | 0.353673 | 0.447695 |
| evaluated-only p50 / p95 / mean latency | 11,065 / 14,997 / 13,126.700 ms | 10,643 / 13,091 / 10,872.450 ms |

| 전환 게이트 | 측정값 | 통과 기준 | 판정 |
| --- | ---: | ---: | --- |
| pgvector no-result | 0.000000 | lexical 0.000000 이하 | 통과 |
| pgvector 전체 p95 latency | 589 ms | 1,413 ms 이하 | 통과 |
| pgvector RAGAS 완결성 | 20 / 20, aggregate 생성 | 20 / 20, aggregate 생성 | 통과 |
| `transition_decision.eligible` | `true` | `true` | 통과 |

자동화 회귀는 `pytest -q test/test_legal_rag_evaluation.py test/test_legal_rag_evaluation_environment.py test/test_legal_rag_service.py --timeout=30 -p no:cacheprovider`로 새 임시 경로에서 실행해 **61 passed in 0.81s**를 확인했다. 이전에 사용한 임시 경로를 재사용한 1회 실행은 pytest의 디렉터리 정리 권한 오류로 setup 4건이 중단됐고, 코드 실패와 구분하기 위해 새 경로에서 재실행했다. `git diff --check`은 CRLF 변환 안내만 출력하고 공백 오류 없이 종료 코드 0이었다.

따라서 이번 유효 실행의 failed gate는 없고, C-1의 법령 RAG PostgreSQL lexical ↔ pgvector 전환 기준 검증을 완료로 갱신한다. 원문 질의·답변·context·API key·예외 전문은 이 보고서와 산출물 요약에 기록하지 않았다.
