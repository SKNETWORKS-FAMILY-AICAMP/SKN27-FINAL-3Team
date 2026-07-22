# 법령 RAG 실제 A/B·RAGAS 실행 설계

## 1. 목표

Issue #280에서 만든 평가 도구를 로컬 Docker PostgreSQL/pgvector 환경에서 실제 실행한다. 동일한 공개 법령 corpus snapshot으로 PostgreSQL lexical과 pgvector를 비교하고, 두 backend가 모두 준비됐을 때만 backend별 RAGAS를 실행해 전환 gate의 근거를 만든다.

## 2. 범위와 제외

### 포함

- 로컬 `docker-compose.yml`의 `postgres` 서비스(`pgvector/pgvector:pg16`)를 평가 DB로 사용
- `law_chunks`와 `law_embeddings`의 동일 corpus snapshot 적재 및 사전 검증
- 공개 법령 20개 평가셋의 lexical ↔ pgvector deterministic A/B
- backend별 RAGAS(Context Precision/Recall, Faithfulness, Answer Relevancy)
- aggregate 결과, 실행 시간·비용·실패 reason, 전환 gate를 기술 리포트에 기록
- 평가 전용 환경변수 예시와 사전검사·실행 절차의 자동화

### 제외

- 운영 서비스의 `LEGAL_RAG_VECTOR_ENABLED=0` 기본값 변경
- Elasticsearch, 판례·심의사례·과실기준, 텍스트 ML RAG의 data/index/runtime 변경
- 사용자 대화·OCR·첨부파일의 평가 입력 사용
- pgvector 우선 전환 또는 lexical fallback 제거
- AWS 파일럿 배포·RDS 설정 변경

## 3. 환경 경계

공용 `.env`와 운영 환경은 수정하지 않는다. Git에서 제외되는 `.env.rag-eval`을 평가 프로세스에서만 명시적으로 로드한다. 체크인하는 `.env.rag-eval.example`에는 값이 아닌 변수 이름과 안전한 기본값만 둔다.

| 구분 | 변수 | 원칙 |
| --- | --- | --- |
| 평가 DB | `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | 로컬 Docker `postgres`만 가리킨다. |
| vector query | `LEGAL_RAG_VECTOR_ENABLED=1` 및 query provider/model/dimension | 평가 명령 프로세스에만 적용한다. |
| seed 공간 | `LEGAL_RAG_SEED_EMBEDDING_*` | 실제 적재된 `law_embeddings` metadata와 정확히 일치해야 한다. |
| RAGAS | `OPENAI_API_KEY` | `--run-ragas`일 때만 사용하며 로그·Git에 남기지 않는다. |
| 법령 수집 | `LAW_GO_KR_OC` 또는 `LAW_API_KEY` | 검증된 JSONL artifact가 없을 때만 필요하다. |

`.env.rag-eval`은 `.gitignore` 대상이며, 스크립트는 이 파일이 없거나 필요한 변수·키가 비어 있으면 외부 호출 전 명확한 실패 reason을 반환한다.

## 4. corpus와 embedding 준비

1. 기존 `law_chunks`·`law_embeddings` JSONL artifact와 manifest가 있는지 확인한다.
2. artifact가 있으면 `load_legal_rag_pgvector`로 schema와 두 테이블을 로컬 평가 DB에 적재한다.
3. artifact가 없으면 공개 법령 provider credential을 확인한 뒤에만 수집·embedding·적재를 수행한다. credential이나 수집 결과가 없으면 `not_ready`로 끝내며 fixture나 임의 데이터를 만들지 않는다.
4. 1차 비교는 `intfloat/multilingual-e5-large`, 1024 dimensions, 현재 조문 경계 chunk로 고정한다.
5. table row 수, source type 분포, `embedding_provider/model/dimensions`, corpus snapshot hash를 실행 artifact에 기록한다.

`administrative_rule`·`notice`가 같은 snapshot에 실제 적재되지 않으면, 해당 source family는 이번 결과의 coverage 제한으로 기록한다. 법률 중심 20개 fixture로 그 공백을 완료 처리하지 않는다.

## 5. 실행 흐름

```text
.env.rag-eval 로드
  → Docker postgres readiness
  → artifact/credential 사전검사
  → schema·seed 적재
  → lexical 및 pgvector readiness 확인
  → deterministic A/B (20개, top-5)
  → 두 backend 모두 ready일 때만 backend별 RAGAS
  → aggregate artifact·기술 리포트·전환 gate 기록
```

평가 runner는 기존 `search_legal_rag()`의 운영 fallback 선택기를 사용하지 않는다. 같은 `temporal_basis`, `scope`, `top_k=5`로 `_search_law_chunks_lexical`와 `_search_pgvector`를 각각 호출한다. 따라서 평가가 운영 요청의 backend 우선순위를 바꾸지 않는다.

## 6. RAGAS와 비용 경계

- backend별 최대 20개 공개 법령 질의와 질의별 top-5 context만 사용한다.
- 한 실행에서는 generator, judge, judge embedding model을 고정한다.
- RAGAS 입력에 사용자 PII, OCR 원문, 첨부파일, 인증 값, 세션 식별자를 넣지 않는다.
- API key가 없거나 RAGAS dependency가 준비되지 않았거나 비용 한도를 초과하면 `not_evaluated`를 기록한다.
- RAGAS 결과가 없는 경우 전환 gate는 자동으로 불통과다.

## 7. 전환 판정

pgvector 우선 전환은 이번 Issue의 산출물이 아니다. 다음 gate가 모두 통과한 사실을 리포트로 제시할 때에만 별도 전환 이슈를 제안한다.

- Recall@5: lexical 대비 -2%p 이내
- MRR 및 nDCG@5: 각각 lexical 대비 -0.02 이내
- no-result rate: lexical보다 높지 않음
- p95 latency: lexical의 1.5배 이하
- RAGAS Context Recall 및 Faithfulness: 각각 lexical 대비 -0.03 이내
- top-k: source URL, source reference, 시행일·폐지일 필터 보존
- 두 backend 모두 준비된 실제 결과이며, corpus snapshot·embedding space를 재현 가능하게 기록

하나라도 충족하지 못하면 lexical fallback과 현 운영 설정을 유지한다.

## 8. 테스트와 산출물

- 평가 환경변수 parser, 외부 호출 전 사전검사, artifact metadata 검증은 fixture 기반 단위 테스트로 고정한다.
- 실제 Docker DB 실행은 `integration` 성격으로 분리하고, service가 없으면 통과로 위장하지 않고 `not_ready` artifact를 남긴다.
- 결과 파일은 Git 제외 `output/law_ingestion/evaluation/<run-id>/`에 생성한다.
- Git에 남기는 것은 실행 명령, aggregate 결과, 비용·한계·전환 결론만 포함한 Markdown 기술 리포트다.

## 9. 리스크와 완화

| 리스크 | 완화 |
| --- | --- |
| Docker DB가 없거나 pgvector extension이 없음 | schema·extension·table readiness를 먼저 검사하고 A/B를 시작하지 않는다. |
| seed/query embedding space 불일치 | provider/model/dimensions를 metadata와 비교해 fail-closed 한다. |
| 법령 artifact/API credential 부재 | 임의 corpus를 만들지 않고 `not_ready`로 기록한다. |
| RAGAS 외부 비용·키 노출 | 전용 env, 명시적 `--run-ragas`, 최대 20개 공개 질의, aggregate-only 보고를 사용한다. |
| 운영 설정 오염 | `.env.rag-eval`과 평가 프로세스로만 vector enable을 한정한다. |
