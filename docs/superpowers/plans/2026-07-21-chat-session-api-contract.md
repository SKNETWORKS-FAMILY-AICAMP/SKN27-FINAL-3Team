# 채팅 세션 API 계약 구현 계획

**목표:** 기존 `POST /api/chat/sessions/`, `POST /api/chat/messages/`, `POST /api/chat/save-state/`를 바꾸지 않고, 세 경로를 DTO·shadow route registry·OpenAPI·회귀 테스트로 공식화한다.

**핵심 결정:** DTO는 OpenAPI 문서와 정적 계약에만 사용한다. Django view의 입력 검증이나 응답 필터로 연결하지 않는다. 따라서 현재 프런트가 보내는 호환 필드(`auth_context` 포함)와 Worker 폴링에 필요한 응답 필드(`work_item`, `supervisor_execution`, `persistence`)가 사라지지 않는다.

## 범위와 금지 사항

- 경로, UI, Worker/Agent, DB schema/migration, 세션·메시지의 영속 동작, History/MyPage API는 바꾸지 않는다.
- 신원은 기존처럼 헤더에서만 검증한다. `X-Guest-Credential`은 body/query/DTO/응답에 넣지 않고, `X-Guest-Id`는 단독 권한 증명이 아님을 header 설명에 유지한다.
- body의 `user_id`는 기존 view가 신뢰하지 않는다. 새 공개 요청 DTO에도 넣지 않는다.
- 존재하지 않는 세션에 대한 save-state는 현재처럼 `200`과 `conversation_save.status="skipped"`이다.
- `POST /api/chat/messages/`의 `503 supervisor_unavailable`은 오류 봉투가 아니라 기존 채팅 응답 본문을 반환한다. 따라서 `200·202·503`은 모두 `ChatMessageResponse`를 참조한다. 이는 `RouteSpec.success_statuses`가 “성공”이라는 이름을 갖더라도 **동일 응답 본문을 갖는 상태 코드 목록**으로 사용하는 한정된 호환 조치다.

## Task A — 실패하는 정적 계약 테스트부터 작성

**파일**

- 생성: `test/test_chat_session_contract.py`
- 수정: `test/test_api_route_specs.py`
- 수정: `test/test_openapi_v1_generation.py`

1. `test/test_chat_session_contract.py`에 다음을 검증한다.
   - `ChatSessionCreateRequest`, `ChatMessageRequest`, `ChatSaveStateRequest`에는 `user_id`, `guest_credential`가 없다.
   - `ChatMessageRequest`에는 `auth_context`가 없다. 이 필드는 런타임의 레거시 호환 입력일 뿐 공개 문서 계약이 아님을 테스트 이름에 명시한다.
   - 세 DTO는 `extra="forbid"`이므로 `user_id` 또는 `guest_credential`가 든 body를 `model_validate`하면 `ValidationError`가 발생한다. 파일의 import에는 `import pytest`와 `from pydantic import ValidationError`를 모두 둔다.
   - 메시지 요청은 `session_id`, `user_text`, `attachments`, `conversation_history`, `conversation_save_state`, `execution_mode`, `routing_intent`, `case_storage_consent`를 문서화하며, 위 최소 입력을 정상 검증한다.
2. `test/test_api_route_specs.py`에 `CHAT_SESSION_API_ROUTE_SPECS`의 정확히 세 경로를 검증한다.
   - `POST /api/chat/sessions/` → `ChatSessionCreateRequest`/`ChatSessionCreateResponse`
   - `POST /api/chat/messages/` → `ChatMessageRequest`/`ChatMessageResponse`, `success_statuses == (200, 202, 503)`
   - `POST /api/chat/save-state/` → `ChatSaveStateRequest`/`ChatSaveStateResponse`
   - 모든 spec은 `auth_optional=True`이고 request parameter 앞 두 개가 `X-Guest-Credential`, `X-Guest-Id` header이다.
   - 세 경로는 `DEFERRED_ROUTE_SPECS`에 남아 있지 않다.
3. `test/test_openapi_v1_generation.py`에서 생성 문서의 세 operation을 검증한다.
   - 메시지 operation의 response key에 `200`, `202`, `503`이 있고 이 셋 모두 `#/components/schemas/ChatMessageResponse`를 참조한다.
   - security는 `[{},{"bearerAuth":[]}]`이고 header 순서·설명이 guest credential 경계를 유지한다.
   - `$ref`만 있는 requestBody를 직접 검사하지 않고 `components.schemas.ChatSessionCreateRequest.properties` 및 `ChatSaveStateRequest.properties`에서 `user_id`, `guest_credential` 부재를 검사한다.
4. 다음 명령으로 새 테스트가 구현 전 실패하는지 확인한다.

   ```powershell
   D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -p no:timeout -p no:cacheprovider test/test_chat_session_contract.py test/test_api_route_specs.py test/test_openapi_v1_generation.py -q
   ```

   기대 결과는 DTO 모듈 또는 route group 부재로 인한 실패다.

## Task B — 공개 DTO와 shadow route registry 구현

**파일**

- 생성: `app/contracts/chat_session.py`
- 수정: `app/contracts/api_route_specs.py`

1. `app/contracts/chat_session.py`를 작성한다.
   - `ChatContractRequest(BaseModel)`은 `ConfigDict(extra="forbid")`를 사용한다.
   - `ChatSessionCreateRequest`는 body 신원 필드 없이 비어 있는 DTO다.
   - `ChatMessageRequest`와 `ChatSaveStateRequest`에는 Task A에 열거한 공개 요청 필드만 둔다. credential, `user_id`, `auth_context`는 넣지 않는다.
   - `ChatPublicResponseModel(BaseModel)`은 `ConfigDict(extra="allow")`를 사용한다. `ChatMessageResponse`는 최소 `contract_version`, `status`와 선택 필드 `session_id`, `message_id`, `execution_mode`, `work_item`, `supervisor_execution`, `persistence`를 선언한다. 선택 필드를 강제하지 않아 즉시 안내·차단·Worker 대기 등 기존 분기를 모두 표현한다.
   - `ChatSessionCreateResponse`, `ConversationSaveResult`, `ChatSaveStateResponse`를 실제 `create_session` 및 `mark_conversation_save_state` 응답에 맞춰 선언한다. `ConversationSaveResult.status`는 `updated|skipped`이며 `reason`, `session_id`는 선택이다.
   - `ChatApiErrorResponse`는 오류의 공통 `error.code`, `message`, `status`만 선언하고 `extra="allow"`를 사용한다. 인증·rate limit·privacy 오류가 제공하는 추가 공개 메타데이터를 거짓으로 배제하지 않는다.
2. `app/contracts/api_route_specs.py`에 DTO import, `_chat_errors(...)`, `CHAT_SESSION_REQUEST_PARAMETERS`를 추가한다. header tuple은 이미 정의된 `GUEST_CREDENTIAL_HEADER_PARAMETER`, `GUEST_ID_HEADER_PARAMETER`을 그 순서로 재사용한다.
3. `CHAT_SESSION_API_ROUTE_SPECS`를 추가한다.
   - 세 route의 `route_name`, `view_name`은 현재 Django URL의 `canonical-create-chat-session/create_chat_session`, `canonical-submit-chat-message/submit_chat_message`, `canonical-chat-save-state/update_chat_save_state`와 일치시킨다.
   - 모두 `contract_status="shadow"`, `auth_required=False`, `auth_optional=True`, tag `("Chat",)`이다.
   - session 발급은 `request_body_required=False`, `success_status=200`이다.
   - 메시지는 `success_status=200`, `success_statuses=(200, 202, 503)`, response는 `ChatMessageResponse`다. `400`, `401`, `403`, `429`만 `ChatApiErrorResponse` 오류 spec으로 선언한다. `503`을 error spec으로 중복 선언하지 않는다.
   - save-state summary에 unknown session의 `200 + skipped`를 명시하고, 인증/권한 오류는 기존 공개 오류 DTO로만 표현한다.
4. `API_ROUTE_SPECS` 조합에 chat group을 `AUTH_SESSION_API_ROUTE_SPECS` 뒤, file group 앞에 넣는다. `DEFERRED_ROUTE_SPECS`에서는 정확히 세 chat `POST` 항목만 제거한다.
5. Task A 명령을 다시 실행해 통과시킨다.

## Task C — 실제 Django 경로와 생성 OpenAPI를 고정

**파일**

- 생성: `backend/chatbot/test_chat_session_api_contract.py`
- 수정: `docs/api/openapi-v1.yaml` (generator 출력)

1. 새 Django 테스트 파일에 기존 `backend/chatbot/test_consultation_v2.py`의 검증된 `authenticated_client` 구현을 그대로 복사한다. 즉 `issue_access_token`, `UserAccount.objects.get_or_create`, `AuthSession.objects.update_or_create`, `Client(HTTP_AUTHORIZATION=f"Bearer {token}")`를 사용하고, 테스트 클래스에 같은 `APP_JWT_SECRET=TEST_JWT_SIGNING_KEY` override를 적용한다. 임의 bearer 문자열이나 미정의 helper를 쓰지 않는다.
2. 같은 파일에서 다음 실제 요청을 고정한다.
   - 인증 user가 `/api/chat/sessions/`에 body `user_id="usr_spoof"`를 보내도 `200`, `contract_version="chat_session.v1"`, 응답 `user_id`가 인증 user이고 spoof 값이 아님.
   - `/api/chat/messages/`의 즉시 안내 fixture는 `backend/chatbot/test_consultation_v2.py`의 검증된 보행자 질문과 동일한 payload로 호출해 `200`, `status="scope_guidance"`를 확인.
   - queued 경로는 기존 mock scenario 패턴(`mock_scenario="fine_notice"`, `mock_status="success"`, `execution_mode="async_worker"`)을 사용해 `202` 및 `work_item.work_item_id`, `supervisor_execution`, `persistence`, `execution_mode="async_worker"`를 확인한다. 외부 Provider를 호출하지 않는다.
   - 존재하지 않는 session의 `/api/chat/save-state/`는 `200`, `conversation_save.status="skipped"`을 확인한다.
   - `issue_guest_credential("chat-contract")`로 만든 `Client(HTTP_X_GUEST_ID="gst_chat_contract", HTTP_X_GUEST_CREDENTIAL=credential)`이 saved 상태를 요청하면 `403`이고 response text에 credential 문자열이 없다.
   - raw `X-Guest-Id`만 사용한 message 요청은 `401`, `missing_guest_credential`이며 `submit_message`가 호출되지 않는 기존 `test_guest_credential_boundary.py` 테스트도 실행 대상으로 포함한다.
3. 다음을 실행한다.

   ```powershell
   D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe backend\manage.py test chatbot.test_chat_session_api_contract chatbot.test_api_route_specs chatbot.test_guest_credential_boundary -v 1
   D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe scripts\generate_openapi_v1.py --output docs\api\openapi-v1.yaml
   ```

4. Task A의 정적 테스트를 다시 실행해 tracked YAML과 registry가 동기화됐는지 확인한다.

## Task D — 체크리스트와 최종 검증

**파일**

- 수정: `docs/ops/project-readiness-master-checklist.md`

1. 모든 Task A~C 검증이 통과한 경우에만 H의 “채팅 세션·메시지·저장 API 공식 계약 및 회귀 검증” 항목을 완료로 표시하고 `#270`과 shadow OpenAPI·상태 코드·guest/소유권 검증 근거를 적는다. History, MyPage, 공통 오류, OCR 항목은 바꾸지 않는다.
2. 변경 범위를 확인한다.

   ```powershell
   git diff --check origin/dev...HEAD
   git diff --name-only origin/dev...HEAD
   ```

3. 관련 회귀와 전체 검증을 실행한다.

   ```powershell
   D:\dev\project\SKN27-FINAL-3Team\.venv\Scripts\python.exe -m pytest -q --timeout=30 -p no:cacheprovider
   npm run build
   ```

   두 번째 명령의 working directory는 `app/web`이다.
4. 변경을 목적별 커밋으로 나눈다: 정적 계약 테스트, DTO/registry, Django/OpenAPI 검증, 체크리스트. 마지막에 `git push origin test/270-chat-session-api-contract`로 push한다. PR 생성과 병합은 하지 않는다.

## 계획 자체 점검

- 503을 error envelope로 오기재하지 않고 기존 채팅 본문으로 보존한다.
- DTO를 런타임 검증/필터에 연결하지 않아 프런트의 `auth_context` 입력과 Worker polling 필드가 깨지지 않는다.
- body 신원 위조, credential header 경계, unknown save-state의 skipped 동작을 각각 정적·통합 테스트로 고정한다.
- 변경 범위는 계약 DTO, registry, generated OpenAPI, 테스트, 같은 PR의 체크리스트로 한정한다.
