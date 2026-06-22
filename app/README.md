# app

사용자 화면, API entrypoint, application service를 관리하는 공간이다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `web/` | 홈, 로그인, 챗봇, 결과/리포트 화면 구현을 둔다. |
| `api/` | 요청/응답 entrypoint, router, controller를 둔다. |
| `services/` | API와 `ai/`, `storage/` 계약을 연결하는 application service를 둔다. |
| `schemas/` | API request/response DTO와 화면 표시용 schema를 둔다. |

## 배치 원칙

- AI 판단 로직은 `ai/`에 둔다.
- 데이터 수집과 전처리 로직은 `etl/`에 둔다.
- 저장소 실행 환경과 DB 계약은 `storage/`에 둔다.
- `app/services/`는 흐름을 조합하되 Agent 내부 구현을 직접 포함하지 않는다.
