# #56 Django mock API 운영 저장소 전환 설계 초안

| 항목 | 내용 |
|---|---|
| Issue | `#56 django chatbot mock api fixtures` 후속 |
| Scope | mock sidecar 저장소를 PostgreSQL, Redis, object storage로 전환하기 위한 경계 설계 |
| Status | 설계 초안, 구현 없음 |
| 작성일 | 2026-06-28 |

## 1. 이 브랜치에서의 범위

`django-mock-api-integration` 브랜치는 mock API와 운영 후보 `/api/...` surface를 검증하는 브랜치다. 따라서 여기서는 실제 DB model, migration, Redis, object storage client를 추가하지 않는다.

이 문서에서 하는 일:

- 현재 mock 저장 방식과 운영 저장소 책임을 매핑한다.
- API response shape를 유지한 채 내부 저장소를 바꿀 수 있는 전환 순서를 정한다.
- 다음 구현 브랜치에서 확정해야 할 정책과 위험을 분리한다.

이 문서에서 하지 않는 일:

- Django model, migration 작성
- PostgreSQL, Redis, S3 설정 추가
- sidecar 저장 제거
- 실제 JWT 사용자 FK, 권한 검증 구현
- Celery 또는 background worker 도입

## 2. 현재 mock 저장 구조

| 현재 mock 대상 | 현재 위치 | 현재 책임 | 운영 전환 대상 |
|---|---|---|---|
| attachment metadata | `backend/media/mock_uploads/{attachment_id}/metadata.json` 또는 metadata-only sidecar | 업로드 파일의 purpose, type, storage_uri, agent_handoff 보관 | PostgreSQL `uploaded_files` |
| upload binary | `backend/media/mock_uploads/{attachment_id}/...` | 중간발표용 local file 저장 | object storage original object |
| analysis job | `backend/media/mock_analysis_jobs/{job_id}/job.json` | `chat_response`, `analysis_plan`, `node_execution`, `history` 묶음 저장 | PostgreSQL `analysis_jobs`, `agent_results`, `analysis_job_events` |
| analysis progress | job JSON의 `status`, `active_node`, `history` | polling용 진행 상태 | Redis progress cache + PostgreSQL fallback |
| analysis result display DTO | `get_analysis_result(job_id)` 변환 결과 | 화면용 `assistant_message`, `progress`, `cards`, `evidence` 생성 | PostgreSQL 기반 Supervisor display output 또는 service-level DTO |
| report action | `perform_report_action()`의 임시 응답 | 저장/다운로드 action mock | PostgreSQL `reports` + object storage generated report |

## 3. 저장소별 책임 경계

### 3.1 PostgreSQL

PostgreSQL은 영속 저장소와 권한 판단의 기준이다. Redis나 object storage에 값이 있어도 PostgreSQL metadata가 없으면 API는 리소스를 소유한 것으로 보지 않는다.

| Logical table | 핵심 필드 | 책임 |
|---|---|---|
| `chat_sessions` | `session_id`, `owner_id`, `title`, `status`, `created_at`, `updated_at` | 사용자별 상담 묶음과 목록 조회 |
| `messages` | `message_id`, `session_id`, `role`, `content`, `routing_intent`, `created_at` | 사용자/assistant 메시지 이력 |
| `uploaded_files` | `attachment_id`, `owner_id`, `session_id`, `purpose`, `file_type`, `content_type`, `size_bytes`, `storage_uri`, `privacy_risk`, `scan_status`, `created_at` | 파일 metadata, 권한, Agent handoff 기준 |
| `analysis_jobs` | `job_id`, `session_id`, `message_id`, `owner_id`, `routing_intent`, `status`, `active_node`, `progress_message`, `created_at`, `updated_at` | 분석 job 생명주기 기준 |
| `analysis_job_events` | `event_id`, `job_id`, `status`, `active_node`, `message`, `created_at` | 진행 이력과 audit trail |
| `agent_results` | `result_id`, `job_id`, `node_code`, `status`, `summary`, `structured_result`, `evidence`, `next_actions`, `limitations`, `created_at` | Agent 결과 envelope 저장 |
| `analysis_display_results` | `display_result_id`, `job_id`, `assistant_message`, `progress`, `cards`, `pending_questions`, `report_links`, `created_at` | 화면 표시용 Supervisor 병합 결과 캐시 또는 snapshot |
| `reports` | `report_id`, `owner_id`, `job_id`, `display_result_id`, `report_type`, `status`, `storage_uri`, `content_summary`, `created_at` | 리포트 목록, 상세, 다운로드 metadata |

초기 구현에서는 `structured_result`, `evidence`, `assistant_message`, `cards` 같은 변동이 큰 필드는 `JSONField`로 시작한다. Agent별 schema가 안정되면 일부 검색 필드만 별도 column으로 승격한다.

### 3.2 Redis

Redis는 빠른 조회와 짧은 수명의 상태만 담당한다. Redis 값은 언제든 손실될 수 있다고 보고, PostgreSQL에서 재구성 가능해야 한다.

| Redis key | 값 | TTL 후보 | 책임 |
|---|---|---:|---|
| `chat_session_state:{session_id}` | `current_intent`, `pending_questions`, `active_job_id`, `updated_at` | 24h | 다음 메시지 routing 보조 |
| `analysis_job_progress:{job_id}` | `status`, `active_node`, `progress_message`, `updated_at` | 24h | polling 빠른 응답 |
| `analysis_job_lock:{job_id}` | worker lock token | 10m | 중복 실행 방지 |
| `idempotency:{owner_id}:{request_hash}` | `job_id` 또는 `report_id` | 10m | 중복 요청 방지 |
| `rate_limit:{owner_or_session_id}` | `count`, `reset_at` | 정책별 | 과도한 요청 제한 |

API는 Redis miss 시 PostgreSQL의 `analysis_jobs`와 최신 `analysis_job_events`를 읽어 응답한다. Redis에만 존재하는 job/result는 허용하지 않는다.

### 3.3 Object storage

Object storage는 원본 파일과 생성 산출물의 byte 저장소다. DB에는 object 위치와 metadata만 저장한다.

| Object 종류 | key 후보 | DB 연결 |
|---|---|---|
| 원본 업로드 | `uploads/{env}/{owner_id}/{session_id}/{attachment_id}/{safe_filename}` | `uploaded_files.storage_uri` |
| OCR/Vision 파생 산출물 | `derived/{env}/{job_id}/{node_code}/{artifact_id}.json` | `agent_results.evidence[].source_reference` 또는 별도 artifact table |
| 생성 리포트 | `reports/{env}/{owner_id}/{report_id}/{filename}` | `reports.storage_uri` |
| 임시 다운로드 파일 | `tmp/{env}/{owner_id}/{report_id}/{token}` | Redis token 또는 signed URL |

원칙:

- object는 private bucket에 저장한다.
- API는 object key를 직접 공개하지 않고 download endpoint 또는 짧은 만료 signed URL을 반환한다.
- 파일명은 표시용 metadata와 storage key를 분리한다.
- 개인정보가 포함될 수 있는 원본 파일은 DB에 binary로 저장하지 않는다.

## 4. API 동작 유지 원칙

운영 저장소로 바뀌어도 외부 API shape는 현재 mock과 최대한 동일하게 유지한다.

| API | 저장소 전환 후 내부 처리 |
|---|---|
| `POST /api/files/` | object storage 업로드 또는 pre-signed upload 완료 확인 후 `uploaded_files` 생성 |
| `GET /api/files/{attachment_id}/` | `owner_id` 권한 확인 후 metadata 반환 |
| `POST /api/chat/messages/` | `messages` 저장, Supervisor routing, 필요 시 `analysis_jobs` 생성 |
| `POST /api/analysis/jobs/` | DB job 생성, Redis progress 초기화, worker enqueue |
| `GET /api/analysis/jobs/{job_id}/` | Redis progress 우선 조회, miss 시 DB fallback |
| `GET /api/analysis/results/{job_id}/` | `analysis_display_results` 또는 `agent_results` 병합으로 화면 DTO 반환 |
| `POST /api/reports/` | report 생성 요청 저장, 필요 시 worker enqueue |
| `GET /api/reports/{report_id}/download/` | 권한 확인 후 object storage signed download 또는 streaming response |

`/api/mock/...` endpoint는 운영 전환 후에도 회귀 테스트용으로 남길 수 있지만, 실제 저장소를 쓰는 endpoint는 canonical `/api/...`를 기준으로 한다.

## 5. 권한과 소유권 경계

실제 JWT 연결 후 모든 보호 endpoint는 `request.user` 또는 JWT claim에서 `owner_id`를 얻는다.

| 리소스 | 권한 기준 |
|---|---|
| chat session | `chat_sessions.owner_id == request.user.id` |
| message | message가 속한 session owner 기준 |
| uploaded file | `uploaded_files.owner_id == request.user.id`와 session 연결 기준 |
| analysis job | job이 속한 session owner 기준 |
| agent result | result가 속한 job owner 기준 |
| report | `reports.owner_id == request.user.id` |

권한 실패는 현재 auth error envelope와 같은 계열로 `403 forbidden`을 반환한다. 존재하지 않는 리소스와 권한 없는 리소스를 구분해서 노출할지는 운영 정책에서 결정한다.

## 6. Job lifecycle 전환

현재 mock은 job 생성과 node 실행을 동기적으로 처리한다. 운영 전환에서는 다음 흐름을 기준으로 한다.

1. API가 `analysis_jobs` row를 `queued`로 생성한다.
2. Redis `analysis_job_progress:{job_id}`를 `queued`로 설정한다.
3. worker queue에 `job_id`를 넣는다.
4. worker가 `analysis_job_lock:{job_id}`를 잡고 `running`으로 갱신한다.
5. 각 Agent 결과를 `agent_results`에 저장한다.
6. Supervisor가 display output을 병합해 `analysis_display_results`에 저장한다.
7. job status를 `success`, `partial`, `failed` 중 하나로 마감한다.
8. Redis progress를 최종 상태로 갱신하고 TTL을 둔다.

Redis가 없거나 worker가 실패해도 DB에는 최소한 `queued` 또는 `failed` job row와 event가 남아야 한다.

## 7. 구현 브랜치 추천 순서

### 7.1 브랜치 1: persistence foundation

추천 이름: `django-production-storage-foundation`

범위:

- Django models와 migrations 추가
- repository/service abstraction 추가
- mock sidecar service는 유지
- 신규 DB 저장소는 테스트에서만 검증

완료 기준:

- `uploaded_files`, `analysis_jobs`, `agent_results`, `reports` model 생성
- owner/session/job/report FK 또는 식별자 연결
- 권한 검증 helper skeleton
- 기존 mock endpoint 동작 유지

### 7.2 브랜치 2: file object storage integration

추천 이름: `django-object-storage-integration`

범위:

- local/object storage adapter 인터페이스
- object key 정책
- private download flow
- virus scan, privacy scan status는 enum만 먼저 둠

완료 기준:

- `POST /api/files/`가 metadata와 storage_uri를 DB 기준으로 관리
- 다운로드는 권한 확인 뒤에만 가능
- 테스트용 fake storage 제공

### 7.3 브랜치 3: async job progress

추천 이름: `django-analysis-job-queue-integration`

범위:

- Redis progress cache
- worker enqueue 구조
- job event 기록
- Redis miss 시 DB fallback

완료 기준:

- `GET /api/analysis/jobs/{job_id}/`가 Redis/DB 양쪽 경로로 동작
- 중복 실행 lock과 idempotency key 테스트
- 기존 mock plan execution을 worker 함수로 이동 가능

### 7.4 브랜치 4: report persistence

추천 이름: `django-report-persistence`

범위:

- report 생성, 목록, 상세, 다운로드 metadata
- generated report object 저장
- canonical report endpoint 확장

완료 기준:

- `POST /api/reports/`, `GET /api/reports/`, `GET /api/reports/{id}/`, download flow 정리
- fine/fault report type 분리 정책 결정

## 8. 미확정 정책

| 정책 | 선택지 | 결정 전 영향 |
|---|---|---|
| object storage | AWS S3, S3-compatible local/minio, 서버 local storage | `storage_uri`, signed URL, Docker compose 구성이 달라짐 |
| background worker | Celery + Redis, Django-Q, custom worker, 동기 실행 유지 | job status와 retry 정책이 달라짐 |
| 비회원 상담 | 허용, 불허, 임시 session only | owner_id nullable 여부와 TTL 정책이 달라짐 |
| 파일 보관 기간 | 사용자 삭제 전까지, N일 TTL, report 생성 후 정리 | object lifecycle과 DB cleanup 필요 |
| 개인정보 처리 | 업로드 즉시 scan, 분석 전 scan, MVP에서는 metadata만 | `scan_status`, 접근 제한, 삭제 정책 영향 |
| report format | text, PDF, DOCX, HTML | report generator와 object content_type 영향 |

## 9. 다음 구현 전 확인 질문

1. 운영 저장소는 AWS S3를 바로 쓸지, 로컬 개발용 S3-compatible storage를 먼저 둘지?
2. 분석 job은 Celery + Redis로 갈지, Django process 내부 mock worker를 한 단계 더 유지할지?
3. 비회원 상담을 운영에서도 허용할지?
4. 업로드 파일과 생성 리포트의 기본 보관 기간을 어떻게 둘지?
5. `analysis_display_results`를 DB snapshot으로 저장할지, `agent_results`에서 매번 병합할지?

## 10. 현재 결론

이 브랜치에서는 canonical API와 mock contract를 유지한다. 실제 운영 전환은 별도 브랜치에서 PostgreSQL metadata를 먼저 만들고, 그 다음 object storage와 Redis progress를 단계적으로 붙이는 순서가 안전하다.
