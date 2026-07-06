# hi20260204-maker 발표 멘트 노트 - 2026-07-02

## 0. 발표 시작 멘트

오늘 업데이트의 핵심은 화면을 더 꾸민 것이 아니라, mock/contract 기반 MVP를 실서비스에 가까운 실행 구조로 바꾸는 작업이었습니다.

제가 설명할 포인트는 네 가지입니다.

1. Supervisor가 사용자 입력을 어떻게 해석하고 Agent 실행 계획으로 바꾸는가
2. Agent 실행을 왜 worker queue로 분리했는가
3. Legal RAG 근거를 어디에 저장하고 어떻게 fallback하는가
4. Google 인증, 토큰 저장, production readiness가 어떤 보안 경계를 만드는가

## 1. 오늘 업데이트 요약

기존 구조는 화면에서 mock 결과를 확인할 수 있는 수준이었습니다.

오늘 작업은 요청을 분류하고, 분석 작업을 DB에 남기고, Agent 실행을 queue로 분리하고, RAG 근거 검색 이벤트를 추적하고, 운영 전 설정을 readiness command로 검증하는 구조로 옮긴 것입니다.

중요한 점은 LLM이나 실제 Agent가 붙어도 프론트가 소비하는 계약은 유지된다는 것입니다. 화면은 내부 raw plan이 아니라 `supervisor_execution.v1`, display DTO, Agent envelope 중심으로 받습니다.

## 2. 전체 플로우 차트 설명

사용자가 상담 입력을 보내면 Django API가 대화 이력과 첨부 metadata를 Supervisor에 넘깁니다.

Supervisor는 intent를 분류하고 필요한 정보가 부족하면 추가 질문을 만들고, 충분하면 Agent input package와 analysis plan을 만듭니다.

그 다음 실행 상태는 `analysis_jobs`, `analysis_job_events`, `ai_sessions`에 저장됩니다. Agent 실행은 API 요청 안에서 끝까지 처리하지 않고 `agent_work_items`에 `queued` 상태로 분리합니다.

worker는 work item을 가져가 `running`으로 바꾸고 Agent envelope를 실행합니다. 결과는 `agent_invocations`, `agent_results`, `analysis_display_results`에 저장됩니다.

이 구조 덕분에 응답 지연, 실패, 재시도, 진행률 표시를 나중에 운영 프로세스로 분리할 수 있습니다.

## 3. 시퀀스 다이어그램 설명

시퀀스에서 강조할 점은 API 응답과 실제 Agent 실행을 분리했다는 점입니다.

초기 응답은 Supervisor 실행 요약과 queue 상태를 알려주고, 실제 실행은 worker가 DB row를 claim해서 처리합니다.

RAG 검색은 먼저 pgvector 경로를 시도합니다. 이 경로는 `law_chunks`, `law_embeddings`를 사용합니다.

pgvector가 꺼져 있거나 테이블이 없거나 연결이 안 되면 Django 런타임의 `rag_chunks`, `source_documents` 기반 lexical fallback으로 내려갑니다.

검색 결과는 단순 문자열로만 쓰고 끝내지 않고 `retrieval_events`에 남깁니다. 이 기록은 리포트 근거 검증, 오류 분석, 검색 품질 개선에 필요합니다.

## 4. RAG 저장 설계 설명

RAG 저장소는 두 계층입니다.

첫 번째는 Django 런타임 테이블입니다. `source_documents`, `rag_chunks`, `retrieval_events`는 서비스 화면, 리포트, 감사 로그에서 직접 쓰는 저장소입니다.

두 번째는 pgvector 기반 법률 ETL 경로입니다. `law_chunks`, `law_embeddings`는 법령 ETL 산출물을 벡터 검색하기 위한 테이블입니다.

그래서 Postgres에 pgvector가 있는 것 자체는 맞습니다. 다만 실서비스 Django 런타임이 그 테이블에 접근 가능한지, ETL이 실제로 적재됐는지, 검색 실패 시 fallback이 기록되는지를 readiness와 테스트로 확인해야 합니다.

## 5. Google 인증과 보안 경계 설명

Google 인증은 Authorization Code Flow로 전환되어 있습니다.

프론트엔드는 `google.accounts.oauth2.initCodeClient()`로 authorization code만 받습니다. Google access token이나 refresh token을 브라우저가 직접 저장하지 않습니다.

백엔드의 `POST /api/auth/google/code/`가 code를 Google token endpoint에서 교환합니다. 이때 popup code 요청에는 `X-Requested-With: XmlHttpRequest` 헤더를 요구합니다.

우리 서비스가 브라우저에 내려주는 `access_token`은 Google token이 아니라 서비스 내부 app JWT입니다. 이 JWT는 `APP_JWT_SECRET` 기반 HMAC 서명으로 발급됩니다.

Google 계정 연결은 `social_accounts`에 저장하고, Google access/refresh token은 `oauth_connections`에 backend-only 보호 문자열로 저장합니다. 응답 JSON에는 Google token 원문이 포함되지 않도록 테스트도 들어가 있습니다.

보안적으로 중요한 운영 설정은 다음입니다.

- `GOOGLE_AUTH_ALLOW_MOCK=0`: 운영에서는 mock Google login 차단
- `APP_AUTH_ALLOW_MOCK_BEARER=0`: 운영에서는 dev mock bearer 차단
- `APP_JWT_SECRET`: app JWT 서명 secret
- `OAUTH_TOKEN_SECRET`: Google OAuth token 보호 secret
- `GOOGLE_CLIENT_SECRET`: backend code exchange용 secret

Readiness command는 이 값들이 mock/default 상태이면 fail을 냅니다.

## 6. Readiness 결과 해석

현재 사용자가 실행한 readiness 결과에서 Django security, Google OAuth, Supervisor LLM, Object Storage는 pass입니다.

실패한 것은 DB 연결입니다. `POSTGRES_HOST=postgres`는 Docker Compose 네트워크 내부에서 쓰는 서비스명입니다.

Windows 호스트에서 `python backend\manage.py ...`를 직접 실행하면 `postgres`라는 호스트명을 해석하지 못하므로 `POSTGRES_HOST=localhost`로 바꿔야 합니다.

DB introspection이 실패했기 때문에 Legal RAG 테이블과 worker queue 테이블 검증도 같이 fail로 내려온 것입니다. 이것은 OAuth나 Supervisor 설정 문제가 아니라 DB 접근 위치 문제입니다.

좋아진 점은 이제 이 문제가 traceback으로 터지지 않고 readiness 리포트로 표현된다는 것입니다.

## 7. 현재 프로젝트에 반영된 업데이트 체크

확인된 반영 사항:

- Supervisor LLM optional adapter가 추가되어 `SUPERVISOR_LLM_ENABLED=1`일 때 LLM planner를 시도하고 실패하면 fallback contract로 돌아갑니다.
- Worker queue 경계가 추가되어 `agent_work_items`가 `queued -> running -> success/failed/retrying` 상태를 가집니다.
- `process_agent_work_items` management command와 API 경계가 생겼습니다.
- Knowledge/RAG Django 테이블 `source_documents`, `rag_chunks`, `retrieval_events`가 추가됐습니다.
- Legal RAG runtime은 pgvector `law_chunks/law_embeddings`를 먼저 시도하고, 실패 시 Django `rag_chunks` fallback으로 내려갑니다.
- Google Authorization Code Flow endpoint `POST /api/auth/google/code/`가 추가됐습니다.
- Google token 원문은 브라우저 응답에서 제외되고, `oauth_connections`에 backend-only 보호 필드로 저장됩니다.
- `social_accounts`는 Google `sub` 기준 계정 연결을 저장합니다.
- app JWT refresh/logout 경계가 있고, auth event/history event로 남깁니다.
- Production readiness command가 Django security, database, Google OAuth, Supervisor LLM, Legal RAG, worker queue, object storage를 통합 점검합니다.
- DB 연결 실패는 traceback이 아니라 readiness fail 리포트로 내려오도록 보강됐습니다.

## 8. 아직 남은 일

남은 작업은 구현이 안 됐다는 뜻보다, 운영 배포 전에 닫아야 할 검증 항목입니다.

- Windows 호스트에서 readiness를 돌릴 때 `.env.production`의 `POSTGRES_HOST`를 `localhost`로 바꿔 DB 포함 점검을 다시 실행해야 합니다.
- 실제 배포/컨테이너 환경에서는 `POSTGRES_HOST=postgres`를 유지해도 됩니다.
- `law_chunks`, `law_embeddings`에 법률 ETL 산출물이 실제로 적재됐는지 확인해야 합니다.
- worker를 management command 1회 실행이 아니라 운영 프로세스나 scheduler로 상시 구동하는 정책이 필요합니다.
- Google Cloud OAuth consent screen, JavaScript origin, redirect URI 설정 후 mock off smoke test를 해야 합니다.
- 실제 Agent 구현은 각 담당자의 output sample을 받아 공통 Agent envelope와 display DTO drift test로 검증해야 합니다.
- token/session 보안은 장기적으로 stateless JWT만 믿지 않고 `auth_sessions.status`를 보호 endpoint마다 확인하는 방향을 검토해야 합니다.

## 9. 마무리 멘트

오늘 작업의 의미는 실서비스에서 필요한 경계가 보이기 시작했다는 점입니다.

Supervisor는 판단과 계획을 담당하고, worker는 실행을 담당하고, RAG는 근거와 검색 이벤트를 남기고, Google 인증은 token 노출을 막는 backend-only 경계로 분리됐습니다.

이제 남은 일은 DB/RAG/worker/OAuth를 실제 운영 환경에서 smoke test로 닫고, 각 Agent 담당자의 실제 구현을 이 계약에 맞춰 연결하는 것입니다.
