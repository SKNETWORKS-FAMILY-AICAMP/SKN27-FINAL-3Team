# Auth ownership guard와 quota policy 업데이트

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-30 |
| 담당 | `hi20260204-maker` |
| 관련 이슈 | `#68` |
| 브랜치 | `auth-ownership-guard` |

## 1. 구현 순서 확인

이번 순서는 다음 기준으로 진행한다.

1. `dev` 최신화 후 `auth-ownership-guard` 브랜치 생성
2. 공통 subject 추출과 resource access guard 정리
3. My Case, file, history, report download 조회 권한 적용
4. quota/subscription 정책 seed와 enforcement 고도화
5. 이후 history 운영 정책, Redis progress cache, object storage adapter 순서로 진행

Redis는 기준 저장소가 아니라 cache다. 권한/소유자/quota가 먼저 잡힌 뒤 `analysis_job_progress:{job_id}`, `chat_session_state:{session_id}` 같은 짧은 TTL cache로 붙이는 방향을 유지한다.

## 2. 권한 guard 기준

실패 응답은 `object_access.v1`의 `object_access_denied`로 통일한다.

| API | 적용 기준 |
|---|---|
| `GET /api/mypage/summary/` | query의 `owner_id`, `user_id`, `session_id`가 요청 subject와 맞는지 확인 |
| `GET /api/files/` | canonical 목록 조회를 요청 subject의 owner 또는 허용된 session으로 제한 |
| `GET /api/files/{attachment_id}/` | `uploaded_files.owner_id` 또는 연결 session 소유권 확인 |
| `GET /api/history/` | `user_id`, `guest_id`, `session_id` filter가 요청 subject와 맞는지 확인 |
| `GET /api/reports/{report_id}/download/` | 기존 report owner guard를 공통 access helper로 정리 |

resource type은 `mypage`, `history`, `uploaded_file`, `uploaded_file_list`, `report`로 구분한다.

## 3. Quota policy 기준

`record_usage_event`는 canonical 사용량 기록 시 아래 테이블을 함께 사용한다.

| 테이블 | 역할 |
|---|---|
| `subscriptions` | 회원의 현재 `plan_code` 확인. 없으면 `free` 기본 구독 seed |
| `code_groups` | `usage_quota_policy` 정책 그룹 seed |
| `code_items` | `anonymous`, `guest`, `free`, `paid` plan별 기본 limit metadata 저장 |
| `usage_quotas` | subject/scope별 현재 사용량과 limit 저장 |
| `usage_events` | allowed/blocked 사용 이벤트 기록 |

초기 seed 기준은 다음과 같다.

| plan | chat_message | file_upload | agent_run | report_action |
|---|---:|---:|---:|---:|
| anonymous | 2 | 1 | 1 | 1 |
| guest | 5 | 3 | 3 | 2 |
| free | 100 | 30 | 30 | 30 |
| paid | 500 | 100 | 120 | 100 |

이 값은 운영 확정 정책이 아니라 MVP seed다. 이후에는 `code_items.metadata.limits`를 운영 정책의 1차 조정 지점으로 사용한다.

## 4. 다음 순서

1. History 운영 정책: TTL, 비회원 만료, 회원 조회 범위, 저장 가능한 metadata 기준, after-service summary 기준
2. Redis progress cache: PostgreSQL fallback 유지
3. Object storage adapter: local/mock adapter, S3 또는 MinIO 후보, signed URL, download event 기록
