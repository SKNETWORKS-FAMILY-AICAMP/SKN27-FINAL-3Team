# Phase 1 Mock Consumer Migration

Explicit Mock 소비자는 `app.mock_runtime`와 `config.mock_urls`를 사용한다. canonical API·worker·repository 소비자는 `app.services.attachment_staging_service` 및 `app.services.history_event_contract`만 사용한다.

기존 `app.services/*_mock_service.py` import는 historical test와 local smoke command의 호환 대상으로 남아 있다. canonical production 경로에서는 금지되며, 후속 Legacy Phase에서 남은 compatibility import를 `app.mock_runtime`으로 완전 이관한다.

기본 frontend source와 production bundle은 `/api/mock/`를 호출하지 않는다. public route·authentication·production agent에는 mock enable switch를 추가하지 않는다.
