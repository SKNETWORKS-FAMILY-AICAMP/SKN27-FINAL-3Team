# 법령 RAG A/B·RAGAS 실행 준비 및 결과 보고서

## 결론

Issue #282는 PostgreSQL lexical ↔ pgvector A/B와 RAGAS를 **동일한 법령 corpus·동일한 임베딩 공간에서만** 실행하도록 하는 실행 경계를 구현했다. 2026-07-22 현재 실제 비교 점수는 생성하지 않았다. 평가 전용 `.env.rag-eval`과 검증된 법령 seed가 없으므로, 도구는 안전하게 `not_ready`를 기록했고 pgvector 우선 전환 판정은 계속 차단된다.

## 왜 이 구성이 필요한가

| 구성 | 이 작업에서의 역할 | 없을 때의 문제 |
| --- | --- | --- |
| PostgreSQL lexical | 같은 법령 DB에서의 기준선 | 벡터 검색 품질 저하를 비교할 기준이 없다. |
| pgvector | 같은 `law_chunks`의 의미 기반 검색 후보 | 키워드 일치가 약한 질의의 검색 차이를 측정할 수 없다. |
| embedding space 검증 | provider/model/dimension이 동일한지 확인 | 서로 다른 벡터 공간을 A/B로 오인할 수 있다. |
| corpus preflight | 테이블·행 수·embedding 공간·chunk ID snapshot 확인 | 빈 DB 또는 다른 seed의 결과를 근거로 전환할 수 있다. |
| RAGAS | top-5 근거 기반 생성 답변의 품질 측정 | 검색 순위 지표만으로 근거 충실성을 판단하게 된다. |

Elasticsearch, Neo4j, 판례·심의사례·과실기준 RAG는 이번 실행 범위가 아니다. 법령 RAG만의 PostgreSQL lexical과 pgvector를 비교하므로, 서로 다른 도메인에 저장된 임베딩을 합치거나 기존 운영 검색 우선순위를 바꾸지 않는다.

## 구현 산출물

- `.env.rag-eval.example`: 평가 전용 로컬 환경변수 계약. 실제 `.env.rag-eval`은 Git에서 제외된다.
- `etl/legal/evaluation_environment.py`: 환경변수를 읽고, PostgreSQL 연결 정보·vector 활성화·1024차원 동일 embedding space만 허용한다. 비밀번호와 API 키는 결과 파일에 기록하지 않는다.
- `etl/legal/run_evaluation.py`: Django/DB를 사용하기 전에 환경을 검증하고, `law_chunks`·`law_embeddings`, 행 수, embedding space, chunk ID snapshot을 확인한다.
- `scripts/run-legal-rag-ab-evaluation.ps1`: 필요할 때만 `-StartPostgres`로 로컬 Docker PostgreSQL을 시작하고, seed 적재·Neo4j·Elasticsearch 실행 없이 평가만 호출한다.

## 실제 실행 기록

실행 명령:

```powershell
python -m etl.legal.run_evaluation --env-file .env.rag-eval --run-id issue282-env-preflight-20260722
```

| 항목 | 결과 |
| --- | --- |
| `.env.rag-eval` | 없음 |
| 법령 chunks/embeddings artifact | 없음 |
| preflight | `not_ready` / `evaluation_environment_invalid` |
| PostgreSQL lexical·pgvector A/B | 미실행 |
| RAGAS | 미실행 (`preflight_not_ready`) |
| pgvector 전환 | 불가 (`eligible: false`) |

이 결과는 실패한 품질 평가가 아니라, 준비되지 않은 상태를 점수 없이 분리한 실행 검증 결과다.

## 실제 평가 재개 조건

1. `.env.rag-eval.example`을 `.env.rag-eval`로 복사하고 실제 로컬 PostgreSQL 접속 정보와 동일한 seed/query embedding space를 입력한다.
2. 로컬 PostgreSQL에 검증된 법령 `law_chunks`와 `law_embeddings`를 적재한다. 이 스크립트는 적재를 자동으로 수행하지 않는다.
3. 먼저 A/B만 실행한다.

```powershell
.\scripts\run-legal-rag-ab-evaluation.ps1 -StartPostgres -RunId legal-ab-001
```

4. A/B가 정상적으로 준비된 뒤에만 OpenAI 키가 있는 로컬 환경에서 RAGAS를 별도 실행한다.

```powershell
.\scripts\run-legal-rag-ab-evaluation.ps1 -RunId legal-ab-001-ragas -RunRagas
```

두 실행의 `summary.json`에서 모든 전환 gate가 통과하기 전에는 운영의 pgvector 우선 경로를 바꾸지 않는다.
