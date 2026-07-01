# Service protocol and persona strategy

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 작성자 | `hi20260204-maker` 중심 실행 메모 |
| 기준 문서 | `docs/api/openapi-v0.yaml`, `docs/api/openapi-persona-hi20260204-maker-2026-06-29.md`, `docs/architecture/auth-session-policy-2026-06-28.md`, `docs/architecture/history-event-design-2026-06-28.md`, `docs/architecture/ddd-mas-history-log-roadmap-2026-06-29.md`, `docs/postgresql-erd-2026-06-28.md` |
| 목적 | 로그인/비회원/히스토리/구독/ERD/OpenAPI/Agent 실행 방식을 하나의 실행 전략으로 묶는다. |
| 제외 | MCP, 외부 유료 API 실호출, 실제 RAG/LLM/이미지 생성 비용 발생 작업 |

## 1. 지금 해야 하는 것

현재 가장 안전한 순서는 아래다.

1. OpenAPI v0를 프로토콜 기준으로 둔다.
2. 로그인 세션, 비회원 식별자, 채팅/사건 세션을 분리한다.
3. 모든 분석 흐름은 `chat_session -> chat_message -> analysis_job -> agent_results -> analysis_display_result -> report -> history_event`로 연결한다.
4. 비회원과 회원의 rate limit, 보관 정책, 구독제 확장 지점을 처음부터 schema에 남긴다.
5. Agent 호출과 피드백은 디버깅 가능한 로그로 남기되, reasoning 전문은 저장하지 않는다.
6. 첫 시연은 핵심 persona 하나로 제한하고, 그 persona에서 어떤 입력이 어떤 output으로 바뀌는지 끝까지 보여준다.

기능을 넓히는 것보다 `ID`, `상태`, `로그`, `근거`, `출력`이 이어지는 구조를 먼저 고정하는 편이 낫다.

## 2. ID와 세션 분리

로그인 구현에서 가장 중요한 기준은 아래 네 ID를 섞지 않는 것이다.

| ID | 의미 | 예시 | 저장/전달 |
|---|---|---|---|
| `user_id` | 로그인 회원 계정 | `usr_...` | JWT claim, user table 후보 |
| `guest_id` | 비회원 브라우저/기기 단위 | `gst_...` | cookie/local storage, guest identity 후보 |
| `auth_session_id` | 로그인 유지/토큰 세션 | `auth_...` | JWT `jti`, auth session 후보 |
| `session_id` | 채팅/사건/상담 흐름 | `ses_...` | `chat_sessions.session_id` |

`session_id`는 로그인 세션이 아니다. 한 사용자는 여러 상담 `session_id`를 가질 수 있고, 비회원 상담은 로그인 후 사용자 확인을 거쳐 계정에 병합한다.

## 3. 히스토리 전략

히스토리는 단순 채팅 로그가 아니라 애프터서비스와 디버깅을 위한 이벤트 타임라인이다.

| 단계 | 저장 대상 | 목적 |
|---|---|---|
| MVP 최소 | session, job, report 상태 | 화면 복구와 현재 진행도 표시 |
| 표준-라이트 | Agent 호출, 실패, partial, report action, auth/session 이벤트 | 디버깅, 애프터서비스, 품질 점검 |
| 상세 | 사용자 원문, OCR 원문, 모델 출력 전문, RAG source 전문 | 별도 동의/마스킹/보관 기간 확정 후 |

현재 추천은 표준-라이트다. 사용자 원문, OCR 원문, Agent reasoning 전문은 기본 저장하지 않는다. 대신 아래처럼 구조화 요약만 남긴다.

| 저장 필드 | 저장 이유 |
|---|---|
| `event_type` | 어떤 일이 일어났는지 |
| `actor.user_id`, `actor.guest_id`, `actor.auth_session_id` | 누가 어떤 로그인 상태로 썼는지 |
| `subject.session_id`, `job_id`, `report_id` | 어느 사건/분석/리포트인지 |
| `source.api_path`, `node_code`, `execution_mode` | 어떤 API/Agent에서 발생했는지 |
| `status`, `summary`, `missing_fields`, `evidence_count`, `limitation_count` | 디버깅과 애프터서비스에 필요한 최소 정보 |

## 4. 구독제와 rate limit

구독제를 바로 구현하지 않더라도 rate limit과 entitlement 개념은 초기에 남겨야 한다.

| 사용자 유형 | 무료 허용 | 제한 또는 유료화 후보 |
|---|---|---|
| 비회원 | 일반 교통 질문, 짧은 상담 session, 제한적 history | 파일 업로드 수, Agent 실행 횟수, report 저장/다운로드 |
| 무료 회원 | 상담 이력 저장, 기본 리포트, 제한적 첨부 | 고해상도 파일, 반복 분석, 긴 history 보관 |
| 구독 회원 | 더 많은 Agent 실행, report 보관, 사건 재상담, 우선 처리 | 외부 API/RAG 고비용 호출, 대용량 영상 |

rate limit key는 아래 기준으로 설계한다.

| 대상 | key 후보 |
|---|---|
| 비회원 채팅 | `rate_limit:guest:{guest_id}:chat_message` |
| 회원 채팅 | `rate_limit:user:{user_id}:chat_message` |
| 파일 업로드 | `rate_limit:subject:{subject_id}:file_upload` |
| Agent 실행 | `rate_limit:subject:{subject_id}:agent_run` |
| report 생성 | `rate_limit:subject:{subject_id}:report_generate` |

## 5. ERD 도메인 분리

현재 PostgreSQL foundation은 운영형 MVP로 적절하다. 이후 고도화는 아래 도메인으로 나누는 것이 좋다.

| 도메인 | 주요 테이블 후보 | 책임 |
|---|---|---|
| User/Auth/Billing | `users`, `guest_identities`, `auth_sessions`, `subscriptions`, `usage_quotas`, `billing_events` | 로그인, 비회원, 구독, rate limit |
| Case/Chat | `chat_sessions`, `chat_messages`, `case_status_events` | 상담방, 사건 상태, 내 사건 진행도 |
| AI Orchestration | `analysis_jobs`, `analysis_job_events`, `agent_results`, `analysis_display_results`, `agent_feedback_events` | Supervisor, Agent 실행, 결과 병합, 디버깅 |
| Evidence/File/OCR/Image | `uploaded_files`, `ocr_results`, `image_analysis_results`, `media_frames`, `evidence_items` | 고지서, 사고 장면, 이미지/OCR 전처리 |
| Report | `reports`, `report_versions`, `report_download_events` | 이의신청서, 분석 리포트, 다운로드 |
| Knowledge/RAG | `source_documents`, `rag_chunks`, `retrieval_events`, `law_sources`, `case_sources` | 법령/판례/사례 근거와 재현성 |
| History/After-service | `history_events`, `follow_up_cases` | 애프터서비스, 재상담, 운영 분석 |

초기에는 하나의 Django app 안에서 시작해도 된다. 복잡도가 커질 때 DDD 기준으로 bounded context를 나누고, 필요하면 MSA로 분리한다. Agent 실행 구조는 여러 Agent를 Supervisor가 조율하는 MAS로 본다.

## 6. OpenAPI를 프로토콜 기준으로 쓰는 법

OpenAPI는 단순 문서가 아니라 팀 전체 프로토콜이다.

| 쓰임 | 기준 |
|---|---|
| Frontend | 화면이 어떤 request/response를 기대하는지 |
| Backend | canonical `/api/...`와 mock alias가 어떤 shape를 유지하는지 |
| Supervisor | `analysis_plan`, `AnalysisResult`, Agent 실행 순서 |
| Agent | `AgentAdapterInput`, `AgentAdapterOutput`, node별 `structured_result` |
| QA | `confirmed`와 `review_required` 분리, 회귀 테스트 |

핵심 API는 아래 흐름만 먼저 잡는다.

```text
POST /api/auth/guest-session/
GET  /api/auth/me/
POST /api/chat/sessions/
POST /api/files/
POST /api/chat/messages/
POST /api/analysis/jobs/
GET  /api/analysis/jobs/{job_id}/
POST /api/agents/plans/run/
GET  /api/analysis/results/{job_id}/
POST /api/reports/
GET  /api/reports/{report_id}/download/
GET  /api/mypage/summary/
GET  /api/history/
```

report 목록/상세, 이의신청서 전용 API는 `review_required`로 유지하고 정책 확정 후 다음 버전에 넣는다.

### 6.1 참고 자료 배포 방식

팀원에게는 OpenAPI 원본만 던지지 않는다. 아래 세트를 함께 뿌린다.

| 파일 | 역할 |
|---|---|
| `docs/api/openapi-v0.yaml` | 기계 판독 가능한 API 계약 원본 |
| `docs/api/openapi-v0-distribution-guide.md` | 담당자별 확인 순서 |
| `docs/api/openapi-v0-notes.md` | PDF/마크다운/구현 차이와 검토 기준 |
| `docs/api/openapi-persona-hi20260204-maker-2026-06-29.md` | PM/Django/Supervisor/QA persona 실행 범위 |
| `docs/architecture/service-protocol-persona-strategy-2026-06-29.md` | 로그인/히스토리/구독/ERD/Agent 실행 전략 |

마지막 산출물에서도 "OpenAPI를 기준 프로토콜로 두고, confirmed/review_required를 나누어 구현했다"는 설명을 넣는다.

## 7. Agent 실행 방식

추천은 혼합 방식이다.

| 구간 | 방식 | 이유 |
|---|---|---|
| 입력 검증, `analysis_plan` 생성 | 동기 | 사용자가 즉시 진행 가능 여부를 알아야 함 |
| 짧은 mock Agent 실행 | 동기 가능 | 중간 발표와 local 개발 속도 |
| OCR, 이미지/영상, RAG, 외부 API, LLM | 비동기 worker | 비용, timeout, 재시도, 진행도 표시 필요 |
| 화면 표시 DTO 조회 | polling 또는 event stream 후보 | `GET /api/analysis/jobs/{job_id}`와 `GET /api/analysis/results/{job_id}`로 시작 |

개발 중에는 비용이 드는 API를 바로 붙이지 않는다. mock 또는 local worker session을 별도로 띄우고, 운영 전환 때 API key/RunPod/worker를 붙인다.

### 7.1 개발용 worker/session 원칙

실제 OCR, Vision, RAG, frontier model API는 상용화 전까지 비용이 발생한다. 그래서 개발 중에는 아래처럼 분리한다.

| 환경 | 실행 방식 |
|---|---|
| local demo | Django mock API와 fixture만 사용 |
| local worker 실험 | 별도 command/session으로 worker를 띄워 API 서버와 분리 |
| RunPod 실험 | 인증/queue/timeout 검증용 최소 함수만 연결 |
| production 후보 | API key, queue, retry, quota, billing 기준이 확정된 뒤 연결 |

즉, 화면/API 개발자는 비용이 드는 외부 호출을 기다리지 않고 mock contract로 붙고, Agent 담당자는 별도 worker session에서 샘플을 만든 뒤 `AgentAdapterOutput`만 맞춘다.

## 8. 내 사건 진행도

내 사건 화면의 현재 진행도는 `analysis_jobs`, `analysis_job_events`, `agent_results`, `analysis_display_results`, `reports`, `history_events`에서 재구성한다.

| 상태 | 기준 데이터 |
|---|---|
| 상담 시작 | `chat_sessions.status` |
| 입력 보완 필요 | `analysis_jobs.status=partial`, `pending_questions` |
| 분석 진행 중 | `analysis_jobs.status=running`, `active_node` |
| Agent 일부 실패 | `agent_results.status=partial/failed`, `limitations` |
| 결과 표시 가능 | `analysis_display_results` 존재 |
| report 생성 가능 | `report_links` 또는 `reports.status=ready` |
| 재상담 가능 | `history_events`와 이전 `analysis_display_results` 요약 |

## 9. 이미지/OCR/사고 장면 샘플

이미지 생성이나 실제 Vision 모델은 초기에 어렵다. 따라서 사고 장면 정리에는 샘플 코드와 rule이 필요하다.

1차 샘플은 실제 모델이 아니라 아래 구조를 검증하는 mock/fixture로 시작한다.

| 구성 | 예시 |
|---|---|
| 입력 | 사고 사진 또는 블랙박스 frame metadata |
| 전처리 | 파일 type, 크기, privacy risk, frame timestamp |
| rule | 번호판/얼굴 노출 주의, 흐림/야간/가림 품질 한계, 증거 후보 source_ref |
| 출력 | `observations`, `detected_objects`, `evidence_candidates`, `privacy_redaction_required`, `limitations` |

사고장면 품질 rule 후보:

| rule | 처리 |
|---|---|
| 장면이 흐림 | `status=partial`, `limitations`에 품질 한계 기록 |
| timestamp 없음 | frame 순서만 사용하고 `source_ref`에 내부 frame id 기록 |
| 번호판/얼굴 가능성 | `privacy_redaction_required=true` |
| 충돌 전후 구간 불명확 | 추가 설명 또는 추가 파일 요청 |
| 단일 사진만 있음 | 과실 판단이 아니라 장면 관찰 요약만 반환 |

## 10. 왜 RAG가 필요한가

프론티어 모델만으로 답하면 빠르지만, 교통 법령/판례/심의사례/고지서 근거를 재현하기 어렵다. RAG는 아래 이유로 필요하다.

| 이유 | 설명 |
|---|---|
| 근거 추적 | 법령 조항, 판례, 사례, 고지서 OCR source를 `source_ref`로 연결 |
| 최신성 관리 | 법령/행정 기준은 바뀔 수 있으므로 source 갱신 주기와 retrieval event가 필요 |
| 단정 방지 | 모델 답변이 아니라 근거와 한계를 분리해 표시 |
| 재현성 | 왜 이런 답변이 나왔는지 추후 history/event로 확인 |
| 비용 제어 | 프론티어 모델에는 요약/판단 보조만 맡기고, 검색은 RAG index로 처리 |

프론티어 모델은 최종 자연어 요약, 추가 질문 생성, 사용자 친화적 설명에 강하다. RAG는 근거 검색과 검증에 강하다. 둘을 분리해야 법률 단정과 hallucination 위험을 줄일 수 있다.

## 11. Agent 호출/피드백 로그

Agent 호출은 반드시 추적 가능해야 한다.

| 로그 | 저장 |
|---|---|
| 호출 시작 | `agent_call_started` |
| 호출 완료 | `agent_call_completed` |
| 일부 성공 | `agent_call_partial`, `missing_fields`, `limitations` |
| 실패 | `agent_call_failed`, `error_code`, `retryable` |
| 결과 검증 실패 | `agent_result_validation_failed` |
| 사용자 피드백 | `agent_feedback_events` 후보 |

디버깅에는 ReAct/tool trace가 도움이 될 수 있지만, reasoning 전문 저장은 기본 금지한다. 저장 가능한 것은 tool name, node_code, status, latency, evidence count, limitation count, retry count, error code 정도다.

## 12. 핵심 persona 시나리오

1차 시연 persona는 다음처럼 둔다.

| 항목 | 내용 |
|---|---|
| persona | 비회원으로 고지서 사진을 올리고 이의신청 가능성을 확인하려는 운전자 |
| 진입 | guest session 발급 후 chat session 생성 |
| 입력 | "이 고지서 이의신청서 만들 수 있나요?" + 고지서 이미지 metadata |
| 분석 | input 검증 -> 고지서 OCR mock -> 법령 근거 mock -> 이의신청서 생성 가능성 확인 |
| 출력 | OCR 요약, 감경/이의 가능성, 필요 증거, 유의사항, report action |
| 히스토리 | guest_id, session_id, job_id, node_code, report action 이벤트 기록 |
| 후속 | 로그인 시 "이 상담을 내 사건에 저장" 확인 후 병합 |

예상 output:

```json
{
  "assistant_message": "고지서 정보와 법령 근거를 기준으로 이의신청 가능성을 검토했습니다. 결과는 참고용이며 제출 성공을 보장하지 않습니다.",
  "progress": [
    {"label": "입력 확인", "status": "done"},
    {"label": "고지서 분석", "status": "done"},
    {"label": "법령 근거 확인", "status": "done"},
    {"label": "리포트 준비", "status": "waiting"}
  ],
  "cards": [
    {"card_type": "fine_notice", "title": "고지서 요약"},
    {"card_type": "law_ground", "title": "관련 근거"},
    {"card_type": "objection_report", "title": "이의신청서 초안 준비"}
  ],
  "limitations": [
    "실제 법률 판단이 아니며 제출 성공을 보장하지 않습니다.",
    "OCR 결과는 사용자가 최종 확인해야 합니다."
  ]
}
```

## 13. 산출물에서 설명할 메시지

마지막 산출물에서는 아래처럼 설명한다.

- OpenAPI를 팀 공통 프로토콜로 잡았다.
- 로그인/비회원/채팅 세션을 분리해 개인정보와 rate limit 기준을 명확히 했다.
- 히스토리는 채팅 로그가 아니라 애프터서비스와 디버깅을 위한 이벤트로 설계했다.
- Agent는 공통 adapter contract로 호출하고, 결과는 Supervisor가 display DTO로 병합한다.
- RAG는 법령/판례/사례 근거 추적을 위해 쓰고, 프론티어 모델은 사용자 친화적 요약과 추가 질문에 쓴다.
- 비용이 드는 외부 API/이미지/LLM 호출은 개발 중 mock 또는 별도 worker session으로 분리한다.

## 14. 추후 고도화

시스템이 복잡해지면 도메인 기반으로 나눈다. DDD 기준 bounded context 후보는 다음이다.

| Context | 이후 MSA 분리 후보 |
|---|---|
| Identity/Billing | 로그인, 구독, rate limit |
| Case/Chat | 상담방, 내 사건, 상태 |
| AI Orchestration | Supervisor, Agent, queue |
| Evidence Processing | 파일, OCR, 이미지/영상 |
| Report | 리포트 생성, 다운로드, version |
| Knowledge/RAG | 법령, 판례, 사례, retrieval |
| Observability/History | 이벤트, 디버깅, 피드백 |

이미지 생성이나 사고장면 분석은 여러 persona로 검증해야 한다. 예를 들어 고지서 중심 persona, 사고 사진 중심 persona, 블랙박스 영상 중심 persona, 법령 질문 중심 persona를 나누어 sample output과 실패 case를 비교한다.

## 15. 바로 다음 액션

| 우선 | 작업 | 이유 |
|---:|---|---|
| 1 | DDD/MAS/history log roadmap 확정 | ERD 재분류와 멘토 피드백 반영 |
| 2 | auth/session/rate-limit MVP skeleton | 비회원/회원/구독, AI 호출 비용 기준 |
| 3 | AI session/Agent invocation log skeleton | 누가 어떤 사건에서 어떤 Agent를 호출했는지 추적 |
| 4 | `history_events` DB 전환 여부 결정 | 애프터서비스, 운영 분석, 조회 권한 |
| 5 | 사고 장면 mock sample과 rule 추가 | Vision 비용 없이 품질 기준 검증 |
