# History 운영 정책 업데이트

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-30 |
| 담당 | `hi20260204-maker` |
| 관련 이슈 | `#68` |
| 브랜치 | `history-operating-policy` |
| 정책 버전 | `history_operating_policy.v1` |

## 1. 적용 범위

이번 변경은 canonical `GET /api/history/` 운영 기준을 명확히 한다.
명시적 `/api/mock/history/`는 기존 sidecar JSON 회귀 경로로 유지한다.

적용 대상은 PostgreSQL `history_events` 기반 표준-라이트 이력이다.
사용자 원문, OCR 원문, prompt, reasoning, raw output, raw payload는 history에 저장하지 않는다.

## 2. 보관 기간

| subject | 보관 기간 |
|---|---:|
| anonymous | 1일 |
| guest | 7일 |
| user | 365일 |

canonical history 조회는 요청 subject 유형에 맞는 보관 기간 cutoff를 적용한다.
예를 들어 비회원 `guest`가 조회하면 7일보다 오래된 `history_events`는 응답에서 제외된다.

## 3. 조회 범위

| 주체 | 조회 범위 |
|---|---|
| 회원 | 자기 `user_id` 또는 권한이 맞는 session history |
| 비회원 | 자기 `guest_id` 또는 권한이 맞는 session history |
| 익명 | subject 없이 broad history 조회 불가 |

owner/session/guest guard는 기존 `object_access.v1` 흐름을 재사용한다.

## 4. Metadata 정책

metadata는 allowlist와 sensitive key blocklist를 함께 적용한다.

- 허용 예시: `routing_intent`, `mock_scenario`, `response_status`, `attachment_count`, `status_counts`, `node_code`, `evidence_count`, `limitation_count`, `report_status`
- 차단 예시: `user_text`, `ocr_raw`, `ocr_text`, `prompt`, `reasoning`, `raw_output`, `raw_payload`, `transcript`

허용되지 않거나 민감한 key는 저장 시 제거하고, 제거된 key는 `metadata.metadata_policy.dropped_keys`에 기록한다.

## 5. After-service summary 기준

재상담/애프터서비스 summary는 `history_events`의 표준-라이트 이벤트만 사용한다.

대상 이벤트:

- `chat_message_created`
- `analysis_job_created`
- `agent_call_completed`
- `agent_call_partial`
- `agent_call_failed`
- `report_saved`
- `report_downloaded`

summary 기준은 응답의 `after_service_summary`에 포함한다.
이 값은 원문 복원이 아니라 어떤 종류의 서비스 이력이 있는지 판단하는 기준이다.

## 6. 후속 순서

1. Redis progress cache를 붙이되 PostgreSQL fallback을 유지한다.
2. Object storage adapter를 붙이고 download event 기록을 확장한다.
3. 실제 JWT/account merge/운영 billing 정책이 확정되면 history 조회 범위를 다시 검증한다.
