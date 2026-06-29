# OpenAPI ver0 작성 메모

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-06-28 |
| 대상 파일 | `docs/api/openapi-v0.yaml` |
| 기준 원본 | `C:/Users/Playdata/Downloads/pm-api-json-schema-spec-2026-06-23.pdf`, `docs/pm-api-json-schema-spec-2026-06-23.md` |
| OpenAPI 버전 | `3.2.0` |
| 배포 정리일 | 2026-06-29 |
| 목적 | PM API JSON Schema 초안을 팀원이 같은 계약으로 볼 수 있게 기계 판독 가능한 API 문서로 정리 |

## 1. 작성 원칙

이번 ver0은 PDF만 옮긴 문서가 아니라, 저장소 마크다운에 추가된 구현 메모까지 합쳤다. 다만 모든 항목을 같은 확정도로 취급하지 않는다.

| 구분 | 의미 | OpenAPI 표시 |
|---|---|---|
| 확정 | 현재 Django mock/backend 코드에 있거나, PM 계약에서 안정적인 항목 | `x-contract-status: confirmed` |
| 검토 | 문서나 회의에서는 필요하지만 구현, 담당자 output, 정책 확인이 남은 항목 | `x-contract-status: review_required` |
| 내부메모 | Supervisor 내부 라우팅, mock 개발 편의, 확정 전 구현 힌트 | `x-internal-note` 또는 notes 문서에만 기록 |

## 2. OpenAPI 3.2.0을 쓰는 이유

OpenAPI는 API 계약을 사람이 읽는 문서가 아니라, 프론트엔드, 백엔드, Agent 담당자가 같은 request/response 구조를 도구로 검증할 수 있게 만드는 표준이다.

`3.2.0`을 선택한 이유는 다음과 같다.

- JSON Schema 기반 schema 표현을 자연스럽게 쓸 수 있다.
- API 본문에 `x-contract-status`, `x-review-note` 같은 확장 필드를 넣어도 표준 문서 구조를 깨지 않는다.
- ver0 문서가 이후 mock, Django serializer, 프론트 타입, Agent output validator로 확장되기 좋다.

주의할 점도 있다. 일부 도구는 아직 `3.2.0` 지원이 늦을 수 있다. 만약 Swagger UI, codegen, validator에서 막히면 같은 구조를 유지하고 `openapi: 3.1.0` 호환본을 별도 생성하는 선택지가 있다.

## 3. PDF와 마크다운 차이 반영

| 차이 | PDF | 마크다운/코드 | 반영 |
|---|---|---|---|
| 인증 오류 | 공통 오류 중심 | `auth_error.v1`, `token_invalid`, `token_expired`, `WWW-Authenticate` 추가 | 확정 |
| 비회원/auth subject | 제한적 | `POST /api/auth/guest-session/`, `GET /api/auth/me/`, `X-Guest-Id`, `auth_context` 추가 | 확정 |
| canonical/mock 구분 | 제한적 | `/api/...`가 mock service를 재사용하고 `api_surface=canonical_mock`, `execution_mode=mock` 포함 | 확정 |
| Agent adapter | 제한적 | `agent_adapter.v1`, `adapter_contract`, `run_{node_code}` 계약 추가 | 확정 |
| 히스토리 이벤트 | 후보 | `history_event.v1`, standard-light sidecar, `/api/history/` mock 조회 추가 | 확정 |
| `accident_statement` | 없음 | 첨부 purpose와 테스트에 존재 | 검토 표시 포함 |
| `blackbox_video`, `insurance_record` | 없음 | mock 첨부 service에 존재 | 검토 표시 포함 |
| `damage_image` | 없음 | Vision handoff 내부 매핑 메모 | 내부메모, public enum 미반영 |
| 마이페이지/이력 | 후보로 언급 | 아직 Django endpoint 없음 | 검토 endpoint로 포함 |
| 이의신청서 전용 API | `POST /api/reports/objection-draft/` | 현재 Django route 없음, `/api/reports/` mock action만 있음 | 검토 endpoint로 포함 |

## 4. 현재 확정으로 둔 범위

다음 항목은 현재 코드나 테스트에 근거가 있어 `confirmed`로 두었다.

- `GET /api/health/`
- `POST /api/auth/guest-session/`
- `GET /api/auth/me/`
- `POST /api/chat/sessions/`
- `POST /api/chat/messages/`
- `GET/POST /api/files/`
- `GET /api/files/{attachment_id}/`
- `GET/POST /api/analysis/jobs/`
- `GET /api/analysis/jobs/{job_id}/`
- `GET /api/analysis/results/{job_id}/`
- `GET /api/agents/nodes/`
- `POST /api/agents/nodes/run/`
- `POST /api/agents/plans/run/`
- `POST /api/reports/`
- `GET /api/reports/{report_id}/download/`
- `GET /api/history/`
- 명시적 `/api/mock/...` alias
- `auth_error.v1`
- `history_event.v1`
- `agent_adapter.v1`

## 5. 검토 필요로 둔 범위

다음 항목은 구현 전에 사용자 또는 담당자 확인이 필요하다.

| 항목 | 확인 이유 |
|---|---|
| `GET /api/chat/sessions/` | 화면상 대화 목록은 필요하지만 현재 Django route는 POST만 구현 |
| `GET /api/chat/sessions/{session_id}/messages/` | 메시지 이력 조회 API 필요 여부와 권한 정책 미확정 |
| `GET /api/reports/`, `GET /api/reports/{report_id}/` | 리포트 목록/상세 화면은 필요하지만 현재 다운로드/mock action 중심 |
| `POST /api/reports/objection-draft/` | PDF에는 있지만 현재 Django route 없음 |
| `GET /api/mypage/summary/` | 마이페이지 집계 화면은 필요하지만 현재 Django route 없음 |
| 히스토리 TTL/보관 기간 | `/api/history/` mock 조회는 구현됐지만 비회원 TTL, 회원 보관 기간, DB table 전환은 미확정 |
| 비회원 session 정책 | TTL, rate limit, 파일 보관, 로그인 전후 session merge가 갈림 |
| `accident_statement` 수신 node | 첨부 목적은 존재하지만 실제 담당 node와 output schema가 미확정 |
| `blackbox_video`, `insurance_record` public enum 승격 | mock에는 있지만 PM 상위 API enum으로 확정할지 확인 필요 |
| Agent별 최종 `structured_result` | 담당자 sample output 수신 전까지 PM 초안과 충돌 가능 |

## 6. 내부메모로 둔 범위

`damage_image`는 주희/Vision 쪽 handoff 메모에 가깝다. 그래서 `AttachmentPurpose` public enum에는 넣지 않았다.

현재 처리 기준은 다음과 같다.

- 사용자가 업로드 API에 직접 넣는 public purpose에는 `damage_image`를 노출하지 않는다.
- Supervisor가 내부적으로 Vision node에 넘길 때만 차량 파손 이미지로 매핑할 수 있다.
- 이 매핑을 public API로 승격하려면 Frontend 표시 문구, 저장소 enum, Agent input schema를 함께 확인한다.

## 7. 팀원 전달 기준

팀원에게 공유할 때는 아래 순서로 설명하면 된다.

1. 프론트엔드는 `Chat`, `Files`, `Analysis Results`, `Reports` 태그를 우선 본다.
2. Django 담당자는 `confirmed` endpoint와 `auth_error.v1`을 우선 맞춘다.
3. Agent 담당자는 `Agents`, `AgentAdapterInput`, `AgentAdapterOutput`, 자기 `structured_result` schema를 본다.
4. Supervisor 담당자는 `AnalysisPlan`, `AgentPlanExecution`, `AnalysisResult`를 중심으로 병합 흐름을 본다.
5. `review_required` 항목은 구현하지 않고, 샘플 output 또는 정책 확인 후 다음 버전에서 확정한다.

## 8. 다음 컨펌 후보

OpenAPI ver0 다음 단계에서 바로 결정하면 좋은 항목은 다음과 같다.

| 우선순위 | 선택 항목 | 왜 중요한가 |
|---|---|---|
| 1 | 로그인 방식: JWT only, Django session 병행, OAuth 연동 여부 | `Authorization`, `user_id`, `owner_id`, 비회원 session merge가 달라짐 |
| 2 | 비회원 rate limit 기준 | 히스토리 저장 범위와 abuse 방지가 달라짐 |
| 3 | 히스토리 저장 이벤트 단위 | 멘토님이 강조한 수집/고도화/after-service 설계의 핵심 |
| 4 | Agent 실행 방식: 동기, 비동기 worker, 혼합 | 진행 상태, retry, timeout, Redis/PostgreSQL 책임이 달라짐 |
| 5 | `accident_statement` handoff 수신 node | 사고경위서 OCR/문서 인식 흐름이 정해짐 |
