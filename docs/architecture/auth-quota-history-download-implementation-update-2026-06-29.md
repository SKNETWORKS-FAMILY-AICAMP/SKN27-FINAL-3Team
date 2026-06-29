# Auth, quota, history, download boundary 구현 업데이트

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-29 |
| 담당 | `hi20260204-maker` |
| 관련 이슈 | `#56`, `#57`, `#68` |
| 관련 PR | `#92` |
| 제외 범위 | 실제 OCR/RAG/Vision/LLM latency, token, cost, retry/error 계측 |

## 1. Redis 위치

현재 프로젝트 실행 구성에는 Redis가 들어가 있지 않다.

- `docker-compose.yml`에는 Redis service가 없다.
- `backend/config/settings.py`에는 Django cache 또는 Redis URL 설정이 없다.
- 현재 Redis는 문서상 후보 역할이다. 예시는 `chat_session_state:{session_id}`, `analysis_job_progress:{job_id}` 같은 짧은 TTL 캐시다.
- 현재 기준 저장소는 PostgreSQL이다. 진행도와 로그는 `analysis_jobs`, `analysis_job_events`, `usage_events`, `history_events`에서 복구한다.

## 2. 구현된 범위

| 영역 | 구현 |
|---|---|
| 비회원 identity | `POST /api/auth/guest-session/` 응답을 `guest_identities`, `auth_events`, `chat_sessions.metadata.auth_context`에 저장 |
| 로그인 subject | `GET /api/auth/me/` mock bearer subject를 `users`, `guest_identities`, `auth_sessions`, `auth_events`에 저장 |
| 세션 구분 | chat `session_id`, guest `guest_id`, login `auth_session_id`, member `user_id`를 분리 저장 |
| 사용량 제한 | canonical chat/file/analysis/report 요청에 `usage_quotas`, `usage_events` 기록 |
| 한도 초과 응답 | scope별 quota 초과 시 `rate_limit.v1` 429 반환 |
| history log | canonical `GET /api/history/`는 `history_events` DB 조회, `/api/mock/history/`는 sidecar 유지 |
| 다운로드 권한 | canonical report download에서 `reports.owner_id`와 요청 subject 비교, 불일치 시 `object_access.v1` 403 반환 |
| OpenAPI | `UsageMeter`, `RateLimitErrorEnvelope`, `ObjectAccessErrorEnvelope`, `history_events` storage 반영 |

## 3. API 흐름

1. 사용자가 canonical API를 호출하면 mock auth subject를 먼저 해석한다.
2. 인증 subject는 `user:{user_id}`, `guest:{guest_id}`, `anonymous` 중 하나로 정규화된다.
3. chat/file/analysis/report 요청은 scope별 `usage_events`를 남긴다.
4. quota가 초과되면 실제 mock service를 실행하지 않고 429를 반환한다.
5. 성공한 canonical 요청은 기존 mock 응답을 유지하면서 PostgreSQL persistence와 usage 정보를 함께 반환한다.
6. history는 원문이 아니라 `history_event.v1` 표준-라이트 이벤트만 저장한다.
7. report download는 object body 생성 전에 소유자 권한을 먼저 확인한다.

## 4. 남은 범위

- 실제 JWT 서명 검증과 운영 사용자 모델 연결
- 구독 plan별 quota 숫자 확정
- Redis progress cache 도입 여부 결정
- signed URL 또는 object storage adapter 연결
- history TTL, 보관 기간, 조회 권한 정책 확정
- 실제 OCR/RAG/Vision/LLM 계측 연결
