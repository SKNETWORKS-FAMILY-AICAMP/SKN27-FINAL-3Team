# Phase 1 Runtime Boundaries

## Canonical Runtime

기본 `config.urls`의 `/api/`는 production repository, queue/worker, `attachment_staging_service`, `history_event_contract`, Local Infrastructure Adapter만 사용한다. `/api/mock/`는 등록하지 않으며 canonical 모듈은 `app.mock_runtime` 또는 Explicit Mock service를 import하지 않는다.

## Explicit Mock Runtime

`app/mock_runtime/**`와 `config.mock_urls`는 test/demo 전용 경계다. 진입하려면 `EXPLICIT_MOCK_RUNTIME_ENABLED=True`, `DEBUG=True`, 그리고 `config.mock_urls`의 명시적 선택이 모두 필요하다. 조건 하나라도 충족하지 않으면 `ImproperlyConfigured`로 fail-closed 한다.

## Local Infrastructure Adapter

`mock_s3`는 Explicit Mock이 아니라 production storage contract의 로컬 구현이다. canonical upload는 `local://attachment-staging/`에서 quarantine object storage handoff를 거친다. 이 URI는 canonical 공개 응답의 mock marker가 아니며, scan-ready 이후에는 canonical object storage URI만 agent handoff에 사용한다.

## Legacy DB Column

`AnalysisJob.mock_scenario` physical column은 이번 Phase에서 제거하지 않는다. migration은 생성하지 않았고 canonical write/read/serialization은 제거했다. physical removal은 production data audit과 보존정책 승인 후 별도 migration PR 또는 Legacy Phase에서 수행한다.
