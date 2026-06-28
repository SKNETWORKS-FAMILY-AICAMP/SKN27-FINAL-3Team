# PostgreSQL ERD 초안

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-28 |
| 대상 브랜치 | `django-production-storage-foundation` |
| 관련 이슈 | `#56`, `#58`, `#68` |
| 구현 상태 | Django model + initial migration foundation 완료, API는 아직 mock sidecar 저장소 사용 |

## 1. 현재 진행 정도

오늘 dev에 올릴 수 있는 Django 백엔드 범위는 다음 상태다.

| 영역 | 상태 | 비고 |
|---|---|---|
| Django 서버 골격 | 완료 | `backend/manage.py`, `config`, `chatbot` app 구성 |
| Canonical API surface | 완료 | `/api/...` 경로가 mock service를 재사용하며 동작 |
| Mock API 회귀 경로 | 완료 | `/api/mock/...` 유지 |
| JWT 실패 envelope | 완료 | `auth_error.v1`, `WWW-Authenticate` header, 401/403 계약 |
| Agent adapter 계약 | 완료 | `agent_adapter.v1`, input/context/output validator |
| PostgreSQL schema foundation | 완료 | Django models + `0001_initial` migration |
| PostgreSQL 실제 저장 연결 | 미완료 | 다음 브랜치에서 repository/service 계층으로 연결 |
| Redis progress cache | 미완료 | DB fallback 정책만 설계 |
| Object storage | 미완료 | `storage_uri` metadata 필드만 준비 |

즉, 팀원이 오늘 dev에서 확인할 수 있는 것은 “Django 서버와 운영 후보 API 경로가 살아 있고, PostgreSQL로 갈 테이블 뼈대가 정해진 상태”다. 아직 실제 API 요청이 PostgreSQL row를 만들지는 않는다.

## 2. ERD

```mermaid
erDiagram
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : contains
    CHAT_SESSIONS ||--o{ UPLOADED_FILES : owns
    CHAT_SESSIONS ||--o{ ANALYSIS_JOBS : starts
    CHAT_SESSIONS ||--o{ REPORTS : groups

    CHAT_MESSAGES ||--o{ ANALYSIS_JOBS : triggers
    ANALYSIS_JOBS ||--o{ ANALYSIS_JOB_EVENTS : records
    ANALYSIS_JOBS ||--o{ AGENT_RESULTS : produces
    ANALYSIS_JOBS ||--|| ANALYSIS_DISPLAY_RESULTS : summarizes
    ANALYSIS_JOBS ||--o{ REPORTS : generates
    ANALYSIS_DISPLAY_RESULTS ||--o{ REPORTS : snapshots

    CHAT_SESSIONS {
        bigint id PK
        varchar session_id UK
        varchar owner_id
        varchar title
        varchar status
        varchar current_intent
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }

    CHAT_MESSAGES {
        bigint id PK
        varchar message_id UK
        bigint session_id FK
        varchar role
        text content
        varchar routing_intent
        jsonb metadata
        timestamptz created_at
    }

    UPLOADED_FILES {
        bigint id PK
        varchar attachment_id UK
        varchar owner_id
        bigint session_id FK
        varchar purpose
        varchar file_type
        varchar original_filename
        varchar content_type
        bigint size_bytes
        varchar storage_uri
        boolean privacy_risk
        varchar status
        varchar scan_status
        jsonb agent_handoff
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }

    ANALYSIS_JOBS {
        bigint id PK
        varchar job_id UK
        bigint session_id FK
        bigint message_id FK
        varchar owner_id
        varchar routing_intent
        varchar mock_scenario
        varchar status
        varchar active_node
        text progress_message
        varchar analysis_plan_id
        jsonb status_counts
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }

    ANALYSIS_JOB_EVENTS {
        bigint id PK
        bigint job_id FK
        varchar status
        varchar active_node
        text message
        jsonb metadata
        timestamptz created_at
    }

    AGENT_RESULTS {
        bigint id PK
        varchar result_id UK
        bigint job_id FK
        varchar node_code
        varchar node_name
        varchar status
        text summary
        jsonb structured_result
        jsonb evidence
        jsonb next_actions
        jsonb limitations
        jsonb raw_output
        timestamptz created_at
    }

    ANALYSIS_DISPLAY_RESULTS {
        bigint id PK
        varchar display_result_id UK
        bigint job_id FK
        jsonb assistant_message
        jsonb progress
        jsonb cards
        jsonb pending_questions
        jsonb attachments
        jsonb report_links
        jsonb limitations
        timestamptz created_at
        timestamptz updated_at
    }

    REPORTS {
        bigint id PK
        varchar report_id UK
        varchar owner_id
        bigint session_id FK
        bigint job_id FK
        bigint display_result_id FK
        varchar report_type
        varchar status
        varchar title
        varchar storage_uri
        text content_summary
        jsonb content
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
    }
```

## 3. 실제 Django table 이름

`backend/chatbot/models.py`에는 ERD와 맞도록 `db_table`을 지정한다.

| Django model | PostgreSQL table | 역할 |
|---|---|---|
| `ChatSession` | `chat_sessions` | 사용자별 상담 session |
| `ChatMessage` | `chat_messages` | 사용자/assistant 메시지 이력 |
| `UploadedFile` | `uploaded_files` | 첨부 metadata와 object storage URI |
| `AnalysisJob` | `analysis_jobs` | 분석 job 생명주기 |
| `AnalysisJobEvent` | `analysis_job_events` | job 진행 event/audit trail |
| `AgentResult` | `agent_results` | 개별 Agent 결과 envelope |
| `AnalysisDisplayResult` | `analysis_display_results` | 화면 표시용 Supervisor 병합 snapshot |
| `Report` | `reports` | 리포트 metadata와 생성 결과 |

## 4. 화면/API 연결

| 화면 영역 | API | PostgreSQL 기준 테이블 |
|---|---|---|
| 챗봇 session 생성/목록 | `POST /api/chat/sessions/`, `GET /api/chat/sessions/` 후보 | `chat_sessions` |
| 챗봇 메시지 입력/이력 | `POST /api/chat/messages/`, `GET /api/chat/sessions/{id}/messages/` 후보 | `chat_messages`, `analysis_jobs` |
| 첨부 자료 | `POST /api/files/`, `GET /api/files/{attachment_id}/` | `uploaded_files` |
| 분석 진행 상태 | `POST /api/analysis/jobs/`, `GET /api/analysis/jobs/{job_id}/` | `analysis_jobs`, `analysis_job_events` |
| 분석 결과 카드 | `GET /api/analysis/results/{job_id}/` | `agent_results`, `analysis_display_results` |
| 리포트 저장/다운로드 | `POST /api/reports/`, `GET /api/reports/{report_id}/download/` | `reports`, `analysis_display_results` |
| 마이페이지/이력 | `GET /api/mypage/summary/`, `GET /api/history/` 후보 | `chat_sessions`, `analysis_jobs`, `reports` 집계 |

## 5. 연결 전 정책

- `owner_id`는 현재 문자열 식별자로 둔다. 실제 JWT 연결 후 `request.user` 또는 JWT claim 기반 FK/owner 정책으로 승격한다.
- API response shape는 저장소 전환 후에도 canonical `/api/...` 기준을 유지한다.
- `analysis_plan`, `node_execution`, `chat_response` 같은 raw debug 묶음은 DB에 저장할 수 있지만, 화면용 `GET /api/analysis/results/{job_id}/`는 display DTO만 반환한다.
- Redis는 빠른 progress cache로만 사용하고, Redis miss 시 PostgreSQL의 `analysis_jobs`와 `analysis_job_events`에서 재구성 가능해야 한다.
- Object storage에는 원본 파일과 생성 리포트 byte를 저장하고, PostgreSQL에는 `storage_uri`와 metadata만 저장한다.

## 6. 다음 구현 순서

1. repository/service 계층을 추가하고 test DB에서 model CRUD를 먼저 검증한다.
2. `POST /api/files/`를 `uploaded_files` 저장으로 전환한다.
3. `POST /api/chat/messages/`에서 `chat_messages`와 `analysis_jobs` 생성 경계를 연결한다.
4. Agent adapter 실행 결과를 `agent_results`에 저장한다.
5. Supervisor display DTO를 `analysis_display_results`로 저장하거나, `agent_results`에서 매번 병합할지 결정한다.
6. `reports`와 object storage download flow를 연결한다.
