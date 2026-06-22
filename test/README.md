# test

단위, 통합, E2E, 수동 시나리오, fixture 검증 자산을 관리하는 공간이다.

## 하위 폴더 역할

| 폴더 | 역할 |
|---|---|
| `unit/` | 함수, schema, parser 단위 테스트를 둔다. |
| `integration/` | Agent, ETL, storage 계약 간 통합 테스트를 둔다. |
| `e2e/` | 화면, API, Agent를 연결한 자동 E2E 테스트를 둔다. |
| `fixtures/` | 비식별화된 테스트 입력 파일과 작은 샘플을 둔다. |
| `manual_scenarios/` | Cross-MVP 수동 검증 시나리오와 실행 기록을 둔다. |

## 배치 원칙

- 원본 개인정보나 원본 민감 자료는 fixture로 커밋하지 않는다.
- 자동화가 확정되지 않은 통합 흐름은 `manual_scenarios/`에 먼저 기록한다.
- 테스트 데이터는 실제 데이터와 구분 가능한 이름과 metadata를 사용한다.
- 테스트는 `app/`, `ai/`, `etl/`, `storage/`의 책임 경계를 검증한다.
