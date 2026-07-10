# hi20260204-maker 개발 트러블슈팅 정리

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-07-09 |
| 작성 기준 | 2026-06-19부터 2026-07-09까지의 문서, 이슈 흐름, Git commit/PR 흐름 |
| 담당 계정 | `hi20260204-maker` |
| 현재 브랜치 | `feature/local-google-login-fallback` |
| 핵심 범위 | PM 문서화, Supervisor/API 계약, auth/session, upload/scan, worker progress, report 저장/다운로드, RAG adapter 연결, demo hardening |

## 1. 전체 요약

초기 트러블은 "아직 정해지지 않은 것을 구현 기준처럼 쓰면 안 된다"는 문제였다. 그래서 `#22` Agent 결과 schema, `#29` Supervisor routing, `#27` 이의신청서 생성 조건, `#40` 통합 시나리오에서 확정/검증 필요/보류를 분리했다.

중반 이후에는 실제 MVP spine을 연결하면서 문제가 바뀌었다. `guest -> login -> upload -> scan -> async worker -> report -> history/mypage` 흐름에서 session 유지, 로그인 gate, scan gate, worker progress, report payload/download 계약이 계속 충돌했다. 이를 API 계약, 프론트 상태, 테스트로 고정했다.

후반에는 mock-only demo를 실서비스 후보 구조로 끌어올리는 문제가 남았다. Google authorization code flow, file scan, object storage adapter, RAG smoke, report PDF/이의신청서 산출물을 붙였지만, 실제 운영 credential, real S3, real LLM, production DB, 법률 안전장치 검증은 별도 release gate로 남겼다.

## 2. 기간별 흐름

| 기간 | 주요 문제 | 처리 방향 |
|---|---|---|
| 2026-06-19 ~ 2026-06-22 | 담당자별 schema, routing, 시나리오가 아직 없는데 구현 범위가 먼저 커짐 | PM 문서에서 확정/검증 필요/보류를 분리하고 협업 의존성 표 작성 |
| 2026-06-29 ~ 2026-07-03 | auth/session, report/storage, worker, RAG smoke가 한 흐름으로 이어지지 않음 | canonical mock API와 DB 저장 경계를 만들고 MVP spine 연결 |
| 2026-07-06 ~ 2026-07-07 | 데모 흐름은 있으나 리포트가 기획의 문서형 리포트와 다름 | `fine_notice`, `fault_ratio` 리포트 타입 계약과 section order 정리 |
| 2026-07-08 ~ 2026-07-09 | Google login fallback, report PDF, 이의신청서 산출물, local RAG 연결의 마감 이슈 | 로컬 mock login 기본값, gated report action, objection form download, adapter smoke 보강 |

## 3. 상세 트러블슈팅

### TS-01. 미확정 schema/routing을 확정 구현처럼 쓰는 문제

| 구분 | 내용 |
|---|---|
| 증상 | Agent별 input/output, node code, evidence metadata가 정해지기 전에 화면/API 구현 기준으로 사용될 위험이 있었다. |
| 원인 | OCR, 법률 RAG, 과실비율, Vision 담당 산출물이 아직 분리되어 있었고 PM 문서가 먼저 필요한 상태였다. |
| 해결 | `#22`, `#27`, `#29`, `#40`, `#41`에서 공통 envelope, routing rule, 이의신청서 입력 조건, 통합 시나리오, guardrail을 문서화했다. 확정되지 않은 항목은 `검증 필요` 또는 `보류`로 표기했다. |
| 재발 방지 | 담당자 산출물 없이 PM이 최종 enum, 모델, endpoint, 법률 문구를 확정하지 않는다는 원칙을 남겼다. |
| 근거 | `docs/hi20260204-maker-issue-action-detail-2026-06-19.md`, `docs/hi20260204-maker-collaboration-dependencies-2026-06-22.md` |

### TS-02. Google 로그인과 Google 데이터 접근 권한이 섞이는 문제

| 구분 | 내용 |
|---|---|
| 증상 | 로그인에 필요한 `openid email profile`과 Drive/Photos/Sheets 같은 데이터 접근 scope가 한 흐름으로 섞일 가능성이 있었다. |
| 원인 | 초기 구현에서는 "Google 로그인"과 "Google API 접근 권한"의 저장 경계가 명확하지 않았다. |
| 해결 | Authorization Code Flow로 전환했다. 프론트는 code만 받고, 백엔드가 token endpoint에서 교환한다. 서비스 JWT와 Google token을 분리하고 `social_accounts`, `oauth_connections` 저장 경계를 만들었다. |
| 재발 방지 | 최초 로그인 scope는 최소화하고, Drive/Photos 등은 기능을 누를 때 추가 scope를 요청하는 정책으로 고정했다. |
| 근거 | `docs/architecture/google-auth-code-flow-2026-07-01.md`, `backend/README.md` |

### TS-03. 로컬 Google login이 실제 credential 없이는 막히는 문제

| 구분 | 내용 |
|---|---|
| 증상 | 발표/로컬 데모에서 Google Cloud credential이나 실제 popup redirect 설정이 없으면 로그인 흐름이 끊길 수 있었다. |
| 원인 | 실제 OAuth flow와 로컬 mock flow가 같은 버튼/상태에서 안정적으로 분기되지 않았다. |
| 해결 | 로컬에서는 `GOOGLE_AUTH_ALLOW_MOCK=1` 기반 `mock_google_code:*` 흐름을 기본으로 사용하도록 조정했다. 프론트도 repo root env를 읽고 local mock login fallback을 사용할 수 있게 했다. |
| 재발 방지 | 실제 OAuth mock-off smoke는 production readiness의 별도 항목으로 남기고, 로컬 데모는 mock code flow로 반복 가능하게 유지한다. |
| 근거 | commit `7abb35e Use local mock Google login by default`, `06f5876 Load frontend Google env from repo root` |

### TS-04. guest에서 로그인 후 `session_id`가 끊기는 문제

| 구분 | 내용 |
|---|---|
| 증상 | 비회원으로 상담을 시작한 뒤 업로드 시점에 로그인하면 기존 상담 session과 로그인 session이 분리될 수 있었다. |
| 원인 | guest identity, auth session, chat session의 역할이 섞여 있었고 프론트에서 `authSession`을 하위 화면으로 안정적으로 전달하지 못했다. |
| 해결 | `guest_id`, `auth_session_id`, `session_id`를 분리하고 Google code login 요청에 기존 `guest_id`, `session_id`를 함께 전달했다. 챗봇 화면에도 auth session prop을 넘겼다. |
| 재발 방지 | MVP demo checklist에서 "Google mock login 후 original `session_id` retained"를 명시했고, frontend auth session contract 테스트로 고정했다. |
| 근거 | `docs/issues/68-mvp-demo-checklist-2026-07-06.md`, commit `10a28f8 Pass auth session into chat screen`, `3b05601 Connect MVP auth session spine` |

### TS-05. 파일 scan 전 첨부가 Agent 입력으로 들어가는 문제

| 구분 | 내용 |
|---|---|
| 증상 | 업로드된 파일이 검사 전이거나 반려 상태인데도 Agent input package에 들어갈 수 있었다. |
| 원인 | 파일 업로드 metadata 저장과 Agent handoff 사이에 scan 상태 gate가 없었다. |
| 해결 | `file_scan_result.v1`, file scan command, scan status 전환, Agent attachment scan gate를 추가했다. `scan_status != clean` 또는 ready가 아닌 파일은 blocked attachment로 분리했다. |
| 재발 방지 | demo checklist에 pending/rejected scan blocked state를 추가했고, clean 파일만 Agent input에 들어가는 테스트를 유지한다. |
| 근거 | `docs/architecture/guest-production-hardening-implementation-plan-2026-07-02.md`, commit `65b108f Gate agent execution on file scan state` |

### TS-06. async worker 진행 상태가 화면에 보이지 않는 문제

| 구분 | 내용 |
|---|---|
| 증상 | 채팅 메시지를 보낸 뒤 worker가 queued/running/success 중 어디에 있는지 사용자가 확인하기 어려웠다. |
| 원인 | chat response, analysis job, progress cache, frontend polling의 계약이 분리되어 있었다. |
| 해결 | chat message를 worker queue로 보내고, `progress_state`를 job detail에서 조회하도록 연결했다. 프론트는 worker progress polling으로 상태를 갱신한다. |
| 재발 방지 | `queued`, `running`, `success`, `partial`, `failed` 상태를 명시하고, Redis miss 시 PostgreSQL fallback을 기준 저장소로 유지한다. |
| 근거 | commit `78a043f Queue chat messages through worker progress`, `2c2b01f Poll worker progress from job detail`, `backend/README.md` |

### TS-07. 리포트가 기획의 2종 문서형 리포트와 맞지 않는 문제

| 구분 | 내용 |
|---|---|
| 증상 | `fine_notice`, `fault_ratio` 제목은 있었지만 `fault_ratio`가 generic section으로 fallback되어 화면설계의 "사고 과실비율 분석 리포트"와 맞지 않았다. |
| 원인 | reporting payload가 공통 저장/다운로드 중심으로 먼저 구현되어 타입별 section contract가 늦게 고정됐다. |
| 해결 | `fine_notice_objection`, `fault_ratio_analysis` 리포트 타입을 1차 구현 범위로 고정하고, 타입별 section order와 필수 표시 항목을 문서화했다. |
| 재발 방지 | download body와 frontend workbench가 `report_type`, `screen_id`, `quality`, `sections` 계약을 바라보도록 테스트를 추가한다. |
| 근거 | `docs/reporting-implementation-alignment-2026-07-07.md`, commit `4ff42cc Cover report payload download sections` |

### TS-08. report 저장/다운로드 권한과 object storage 경계 문제

| 구분 | 내용 |
|---|---|
| 증상 | guest가 report preview, save, download를 어디까지 할 수 있는지 정책이 흔들렸고, 저장소도 metadata-only URI 중심이었다. |
| 원인 | 데모에서는 빠른 preview가 필요했지만 실서비스에서는 저장/다운로드가 개인정보와 비용 리스크를 만든다. |
| 해결 | guest는 preview 중심, save/download는 로그인 필요 정책으로 정리했다. report metadata는 DB에 저장하고 object storage adapter envelope을 통해 storage URI, object key, access decision을 추적했다. |
| 재발 방지 | report action을 `preview/save/download`로 분리하고, download 시 owner check와 header metadata를 확인한다. |
| 근거 | `docs/architecture/guest-production-hardening-implementation-plan-2026-07-02.md`, `backend/README.md`, commit `54242f5 Enforce guest policy on MVP endpoints`, `e2af0c5 Add objection form downloads and gated reporting flow` |

### TS-09. 제출 문서/이의신청서 산출물이 리포트와 분리되지 않는 문제

| 구분 | 내용 |
|---|---|
| 증상 | 분석 리포트와 실제 제출용 이의신청서 초안의 역할이 섞여 사용자가 "제출 가능한 문서"로 오해할 수 있었다. |
| 원인 | 초기 리포트는 text download와 payload summary 중심이었고, 제출 문서 section이 별도 gate로 강조되지 않았다. |
| 해결 | 이의신청서 생성 agent와 PDF template renderer를 추가하고, 제출 문서 section을 UI에서 강조했다. 다운로드/제출 관련 action은 로그인 및 검토 필요 상태를 통과하도록 gated flow로 묶었다. |
| 재발 방지 | 분석 리포트, 제출 문서, PDF/DOCX 산출물을 phase로 분리하고, 성공 보장/자동 제출 표현을 금지한다. |
| 근거 | commit `baa3f1d Highlight submission document report sections`, `e2af0c5 Add objection form downloads and gated reporting flow` |

### TS-10. mock-only Agent와 실제 adapter 연결 사이의 간극

| 구분 | 내용 |
|---|---|
| 증상 | 화면은 동작하지만 실제 법률 RAG, 과실비율 RAG, text ML case search와 연결되지 않으면 발표 이후 구현 신뢰도가 떨어진다. |
| 원인 | canonical mock API가 먼저 만들어졌고, 각 Agent는 별도 브랜치/담당 흐름에서 개발됐다. |
| 해결 | Agent adapter envelope을 강화하고, law ground sync adapter, text ML case search adapter, fault ratio knowledge agent를 순차적으로 연결했다. smoke command와 readiness 문서로 mock/fallback 여부를 노출했다. |
| 재발 방지 | Agent output은 `node_name`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations` envelope을 지켜야 한다. |
| 근거 | commit `4192aee Strengthen agent adapter envelope`, `7330f15 Add text ML case search sync adapter`, `59083c5 Connect fault ratio knowledge agent`, `be17195 Connect law ground sync adapter` |

### TS-11. 법률 RAG/GraphRAG가 자연어 변형에 약한 문제

| 구분 | 내용 |
|---|---|
| 증상 | Neo4j hint graph나 사전 매핑에만 의존하면 등록되지 않은 자연어 표현에서 검색이 실패하거나 근거가 빈약해질 수 있었다. |
| 원인 | 법령/판례 검색은 정확한 조문 키와 자연어 semantic query가 함께 필요하지만 초기 설계는 graph hint 중심이었다. |
| 해결 | PostgreSQL + pgvector와 Neo4j knowledge graph를 함께 사용하는 구조로 정리하고, regex 추출, graph expansion, LLM fallback, smoke fixture를 분리했다. |
| 재발 방지 | 법률 근거는 최신성, source reference, limitation을 함께 노출하고, RAG 연결 전에는 "최신성 확인 필요"를 숨기지 않는다. |
| 근거 | `docs/final_architecture_review.md`, `docs/github-activity-2026-06-29-to-2026-07-05.md`, commit `afd890e Add legal RAG smoke fixture` |

### TS-12. Docker compose/env 병합과 로컬 실행값 불일치

| 구분 | 내용 |
|---|---|
| 증상 | docker compose, backend env, frontend env, Google auth 설정이 서로 다른 기본값을 볼 수 있었다. |
| 원인 | 기능별 브랜치가 빠르게 머지되면서 `.env.example`, compose service, frontend env loading 위치가 계속 바뀌었다. |
| 해결 | compose merge cleanup을 수행하고, frontend가 repo root env를 읽도록 조정했다. local auth proxy defaults와 mock Google login 기본값도 정리했다. |
| 재발 방지 | `.env.example`, `.env.production.example`, `docs/ops/production-env.md`, `docker-compose.yml` 변경은 함께 검토한다. |
| 근거 | commit `d6ab854 Fix docker compose merge cleanup`, `42ed2a9 Fix local auth proxy defaults`, `06f5876 Load frontend Google env from repo root` |

### TS-13. "데모 가능"과 "실서비스 가능"이 섞이는 문제

| 구분 | 내용 |
|---|---|
| 증상 | MVP는 브라우저 데모가 가능해졌지만 운영 보안, real OAuth, real storage, real LLM, production DB, 관측성은 아직 같은 수준이 아니었다. |
| 원인 | 중간발표 목적의 mock/canonical API와 실서비스 release gate가 한 문서 안에서 같이 논의됐다. |
| 해결 | `Guest Production Hardening Implementation Plan`에서 phase별로 현재 상태와 production gap을 분리했다. file scan, mock_s3 local binary write, slot smoke validator는 일부 완료했고 real credential smoke는 남겼다. |
| 재발 방지 | `check_production_readiness --fail-on-error` 통과 전에는 실서비스 가능으로 표현하지 않는다. local dev에서는 mock/fallback 항목을 warn/fail로 명확히 드러낸다. |
| 근거 | `docs/architecture/guest-production-hardening-implementation-plan-2026-07-02.md`, `docs/deployment-readiness-review-2026-06-22.md` |

## 4. 현재까지 얻은 운영 원칙

| 원칙 | 이유 |
|---|---|
| 미확정 항목은 `검증 필요`로 남긴다. | 화면/API 구현자가 문서 초안을 확정 계약으로 오해하지 않게 한다. |
| guest, auth session, chat session은 분리한다. | 로그인 전후에도 상담 흐름을 유지하면서 저장/다운로드 권한을 통제하기 위해서다. |
| scan 전 파일은 Agent 입력으로 넘기지 않는다. | 개인정보, 악성 파일, 잘못된 증거 입력 리스크를 줄이기 위해서다. |
| report는 preview/save/download action을 분리한다. | 데모 UX와 개인정보/소유권 정책을 동시에 맞추기 위해서다. |
| 법률/과실비율 결과는 단정하지 않는다. | RAG/AI 결과가 법률 판단이나 제출 성공 보장처럼 보이면 안 된다. |
| mock/fallback은 숨기지 않는다. | 발표 데모와 실서비스 readiness를 구분하기 위해서다. |

## 5. 남은 트러블과 다음 액션

| 남은 이슈 | 현재 상태 | 다음 액션 |
|---|---|---|
| 실제 Google OAuth code exchange | local mock flow 중심 | `GOOGLE_AUTH_ALLOW_MOCK=0` 환경에서 popup code exchange smoke 실행 |
| 실제 S3/object storage | `mock_s3` local binary write 또는 adapter 경계 | `OBJECT_STORAGE_PROVIDER=s3` credential 환경에서 binary write smoke 실행 |
| 실제 LLM slot filling | validator와 smoke 경계 일부 구현 | `SUPERVISOR_LLM_ENABLED=1`에서 `--require-used --require-slot-state` 검증 |
| production PostgreSQL/pgvector | 로컬/문서/일부 readiness 중심 | migration, extension, introspection을 production env에서 확인 |
| 법률 안전장치 | 면책/한계 문구는 있음, 근거 추적/오답 대응은 미완 | source trace, retrieval event, feedback/정정 프로세스 추가 |
| PDF/DOCX 제출 문서 | PDF/template flow 시작 | 제출용 문서의 최종 문구 검수와 DOCX/PDF phase 분리 |

## 6. 회귀 검증 명령

```powershell
python backend\manage.py test chatbot.tests.ChatbotMockApiTests.test_mvp_e2e_demo_spine_upload_worker_report_history
python backend\manage.py test chatbot
python -m pytest test\test_frontend_auth_session_contract.py test\test_agent_node_service.py test\test_chatbot_mock_service.py
npm --prefix app\web run build
git diff --check
```

선택 smoke:

```powershell
python backend\manage.py load_legal_rag_smoke_fixture --replace --format text --smoke-query school-zone-smoke
python backend\manage.py check_production_readiness --format text
python backend\manage.py smoke_file_scan --require-clean
python backend\manage.py smoke_object_storage --require-binary
python backend\manage.py smoke_supervisor_llm --require-slot-state
```

## 7. 발표용 한 문단

이번 개발의 핵심 트러블은 단순 버그보다 "흐름의 경계"였다. 처음에는 담당자별 Agent schema와 Supervisor routing이 확정되지 않아 문서에서 검증 필요 항목을 분리했고, 이후에는 guest 로그인, 파일 업로드, scan gate, worker progress, 리포트 저장/다운로드가 하나의 사용자 여정에서 끊기지 않도록 연결했다. 현재는 브라우저 데모가 가능한 MVP spine을 확보했고, 실서비스 전환을 위해 real OAuth, S3, LLM, production DB, 법률 안전장치 검증을 release gate로 남겨둔 상태다.
