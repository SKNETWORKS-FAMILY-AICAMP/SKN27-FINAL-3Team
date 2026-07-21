# 비회원 guest credential 서버 검증 경계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 원본 `guest_id`만으로 기존 비회원 신원·세션·Google 결합을 재개할 수 없도록, 서버 서명 guest credential을 발급·검증하고 정상 전환 흐름은 유지한다.

**Architecture:** guest credential은 app JWT와 issuer·audience·type·파생 HMAC 키가 분리된 독립 JWT다. Django 요청 경계는 app JWT 또는 guest credential을 먼저 검증하고, 검증된 claim만 `auth_context`에 넣는다. 프런트엔드는 credential을 기존 guest 상태와 함께 보관하고 전용 header로만 보낸다.

**Tech Stack:** Python 3.13, Django, PyJWT HS256, Pydantic DTO, React, localStorage, pytest/Django TestCase.

## Global Constraints

- `issue/objection-report-generation` 브랜치·구현은 수정하지 않는다.
- app JWT 형식·Google provider 검증·DB migration·credential revocation·HttpOnly Cookie 전환은 변경하지 않는다.
- credential은 `X-Guest-Credential` header로만 받고, body/query/`auth_context`/`X-Guest-Id`는 신원 증명이 아니다.
- credential 원문은 응답 재반환, DB metadata, AuthEvent/history, worker payload, fingerprint, logger에 남기지 않는다.
- 기존 응답 계약은 필드를 호환성 있게 추가하고 인증 오류는 `auth_error.v1`를 유지한다.
- #256 완료와 #258 진행 상태는 구현 PR에 포함해 `docs/ops/project-readiness-master-checklist.md`에서 갱신한다.

## 파일 구조

- Create: `app/services/guest_credential_service.py` — 발급·검증과 전용 claim/키 경계.
- Modify: `app/services/auth_session_service.py`, `app/contracts/auth_session.py`, `app/contracts/api_route_specs.py`.
- Modify: `backend/chatbot/views.py`, `backend/chatbot/repositories.py`.
- Modify: `app/web/apiClient.js`, `app/web/authSession.js`, `app/web/FrontendAppShell.jsx`.
- Modify: `app/security/pii_masking.py`, `docs/ops/project-readiness-master-checklist.md`.
- Test: `test/test_guest_credential_service.py`, `test/test_auth_session_service.py`, `test/test_frontend_auth_session_contract.py`, `test/test_api_route_specs.py`, `test/test_pii_masking.py`, `backend/chatbot/test_guest_credential_boundary.py`, `backend/chatbot/test_guest_login_session_ownership_e2e.py`, `backend/chatbot/test_operational_log_privacy.py`.

---

### Task 1: 전용 guest credential과 auth 계약

**Files:**
- Create: `app/services/guest_credential_service.py`
- Modify: `app/services/auth_session_service.py:16-159`
- Modify: `app/contracts/auth_session.py:79-89`
- Modify: `app/contracts/api_route_specs.py:408-565`
- Test: `test/test_guest_credential_service.py`, `test/test_auth_session_service.py`, `test/test_api_route_specs.py`

**Interfaces:**
- Produces: `issue_guest_credential(guest_id, *, now=None) -> tuple[str, dict[str, Any]]`, `decode_guest_credential(token) -> tuple[bool, dict[str, Any]]`.
- Produces: `create_guest_session(payload, *, guest_credential=None)` 및 `get_current_auth_subject(..., guest_credential=None)`.

- [ ] **Step 1: 발급·검증 실패 테스트를 작성한다.**

```python
def test_guest_credential_cannot_be_reused_as_an_app_jwt():
    token, claims = issue_guest_credential("gst_owner")

    assert decode_guest_credential(token)[0] is True
    assert claims["sub"] == "gst_owner"
    assert decode_access_token(token) == (False, {"reason": "not_app_jwt"})


def test_expired_and_tampered_credentials_return_only_safe_reasons():
    expired, _ = issue_guest_credential("gst_owner", now=FIXED_PAST)

    assert decode_guest_credential(expired) == (False, {"reason": "expired_guest_credential"})
    assert decode_guest_credential(f"{expired}x") == (False, {"reason": "invalid_guest_credential"})
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest test/test_guest_credential_service.py -q --timeout=30`

Expected: `guest_credential_service` 모듈이 없어 FAIL.

- [ ] **Step 3: 최소 발급·검증 구현을 작성한다.**

```python
GUEST_CREDENTIAL_ISSUER = "skn27-guest-credential"
GUEST_CREDENTIAL_AUDIENCE = "skn27-guest-session"
GUEST_CREDENTIAL_TYPE = "guest_credential"

def issue_guest_credential(guest_id: str, *, now: datetime | None = None) -> tuple[str, dict[str, Any]]:
    issued_at = now or _now()
    claims = {
        "iss": GUEST_CREDENTIAL_ISSUER,
        "aud": GUEST_CREDENTIAL_AUDIENCE,
        "typ": GUEST_CREDENTIAL_TYPE,
        "sub": _normalize_guest_id(guest_id),
        "jti": f"gcr_{uuid4().hex}",
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=GUEST_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(claims, _guest_credential_secret(), algorithm="HS256"), claims
```

`_guest_credential_secret()`은 app JWT secret 원문에 `b"skn27-guest-credential.v1"` HMAC-SHA256을 적용한다. app JWT의 `decode_access_token()`은 수정하지 않는다.

- [ ] **Step 4: guest session과 DTO·route spec을 확장한다.**

```python
def create_guest_session(payload=None, *, guest_credential=None):
    valid, claims = decode_guest_credential(guest_credential or "")
    guest_id = str(claims["sub"]) if valid else f"gst_{uuid4().hex}"
    session_id = _text((payload or {}).get("session_id")) if valid else None
    credential, _ = issue_guest_credential(guest_id)
    issued_at = _now()
    return {
        "auth_state": "guest",
        "guest": {"guest_id": guest_id, "status": "active"},
        "subject": {"subject_id": f"guest:{guest_id}", "subject_type": "guest"},
        "session_binding": {"session_id": session_id, "can_bind_to_chat_session": bool(session_id)},
        "guest_credential": credential,
    }
```

`GuestSessionResponse`에는 `guest_credential: str`을 추가한다. `X-Guest-Credential`을 route spec에 추가하고, `X-Guest-Id`는 단독 인증 불가라고 명시한다.

- [ ] **Step 5: 단위·계약 테스트를 통과시키고 커밋한다.**

Run: `python -m pytest test/test_guest_credential_service.py test/test_auth_session_service.py test/test_api_route_specs.py -q --timeout=30`

Expected: PASS; 임의 ID 재사용·JWT 교차 사용·만료/변조가 거부된다.

```powershell
git add app/services/guest_credential_service.py app/services/auth_session_service.py app/contracts/auth_session.py app/contracts/api_route_specs.py test/test_guest_credential_service.py test/test_auth_session_service.py test/test_api_route_specs.py
git commit -m "feat: add signed guest credential boundary"
```

### Task 2: Django 요청 신원 경계와 세션 결합

**Files:**
- Modify: `backend/chatbot/views.py:193-579, 605-1218, 2167-2237, 2439-2549`
- Modify: `backend/chatbot/repositories.py:850-862, 1168-1234, 4965-5190`
- Create: `backend/chatbot/test_guest_credential_boundary.py`
- Modify: `backend/chatbot/test_guest_login_session_ownership_e2e.py`

**Interfaces:**
- Consumes: Task 1의 `get_current_auth_subject(..., guest_credential=...)`.
- Produces: `_request_identity_or_error(request, payload=None, *, session_id=None) -> tuple[dict[str, object], JsonResponse | None]`.
- Produces: `guest_session_binding_error(guest_id, session_id) -> str`.

- [ ] **Step 1: raw ID 우회와 Google provider 선차단 테스트를 작성한다.**

```python
def test_raw_guest_id_cannot_write_a_bound_guest_session(self):
    owner = self.create_guest_session_with_credential()
    response = Client(HTTP_X_GUEST_ID=owner["guest_id"]).post(
        "/api/chat/messages/",
        {"session_id": owner["session_id"], "user_text": "hello"},
        content_type="application/json",
    )
    self.assertEqual(response.status_code, 401)
    self.assertEqual(self.resource_snapshot(), owner["snapshot"])


def test_invalid_guest_credential_blocks_google_before_provider_call(self):
    with patch("chatbot.views._create_google_code_login") as provider:
        response = self.post_google_code(guest_credential="tampered")
    self.assertEqual(response.status_code, 401)
    provider.assert_not_called()
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest backend/chatbot/test_guest_credential_boundary.py -q --timeout=30`

Expected: raw `X-Guest-Id`가 아직 수용되므로 FAIL.

- [ ] **Step 3: 공통 request identity helper를 도입한다.**

```python
def _request_identity_or_error(request, payload=None, *, session_id=None):
    body = dict(payload or {})
    status, auth_payload = _get_current_auth_subject(
        authorization_header=request.headers.get("Authorization"),
        guest_id=_requested_guest_id(request, body),
        guest_credential=request.headers.get("X-Guest-Credential"),
        session_id=session_id or body.get("session_id"),
    )
    if status >= 400:
        return {}, _auth_error_response(request, auth_payload, status=status)
    return _payload_from_verified_subject(body, auth_payload), None
```

모든 chat/file/job/history/report와 guest 결합 Google 경로는 리소스 조회, DB 쓰기, worker enqueue, history 기록, provider 호출 전에 오류를 반환한다. `_payload_with_request_identity()`의 raw `X-Guest-Id` fallback은 삭제한다.

- [ ] **Step 4: 결합을 fail-closed로 만든다.**

```python
def guest_session_binding_error(*, guest_id: str, session_id: str | None) -> str:
    access = get_chat_session_access_metadata(session_id)
    if access is None:
        return ""
    if access["owner_id"] or not access["guest_id"]:
        return "guest_session_binding_denied"
    if access["guest_id"] != guest_id:
        return "guest_session_binding_denied"
    return ""
```

유효 credential이 없으면 `guest_session()`은 body의 기존 `guest_id`·`session_id`를 버리고 새 guest만 만든다. 이미 존재하지만 unbound/다른 guest/로그인 사용자 소유 세션은 덮어쓰지 않는다.

- [ ] **Step 5: Google code 결합에는 검증된 guest만 쓴다.**

```python
identity, error_response = _request_identity_or_error(request, body, session_id=body.get("session_id"))
if error_response is not None:
    return error_response
binding_error = _google_code_session_binding_error(
    {**body, "guest_id": verified_guest_id_from(identity)}
)
```

guest 결합 요청만 credential을 요구하고, 일반 Google 로그인은 유지한다. mismatch·already-owned는 기존 403 reason을 보존한다.

- [ ] **Step 6: E2E를 통과시키고 커밋한다.**

Run: `python -m pytest backend/chatbot/test_guest_credential_boundary.py backend/chatbot/test_guest_login_session_ownership_e2e.py -q --timeout=30`

Expected: PASS; 정상 guest → Google → Case 승격은 유지되고, 복제/변조/만료는 상태를 바꾸지 못한다.

```powershell
git add backend/chatbot/views.py backend/chatbot/repositories.py backend/chatbot/test_guest_credential_boundary.py backend/chatbot/test_guest_login_session_ownership_e2e.py
git commit -m "feat: verify guest identity at request boundary"
```

### Task 3: 프런트엔드 보관·header 전송·새 시작

**Files:**
- Modify: `app/web/apiClient.js:198-208`
- Modify: `app/web/authSession.js:190-233`
- Modify: `app/web/FrontendAppShell.jsx:185-327`
- Modify: `test/test_frontend_auth_session_contract.py`

**Interfaces:**
- Consumes: `guest_credential` 응답 필드와 `guest_credential_*` auth reason.
- Produces: `buildRequestHeaders({ authToken, guestId, guestCredential, authSessionId })`, `persistAuthSession({ guestId, guestCredential })`.

- [ ] **Step 1: 브라우저 계약 테스트를 작성한다.**

```python
def test_guest_credential_is_persisted_and_sent_only_in_a_header():
    client = read_text(ROOT / "app" / "web" / "apiClient.js")
    auth = read_text(ROOT / "app" / "web" / "authSession.js")

    assert '"X-Guest-Credential": guestCredential' in client
    assert "guestCredential" in auth
    assert '"guest_credential"' not in client
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest test/test_frontend_auth_session_contract.py -q --timeout=30`

Expected: `guestCredential` 상태와 header가 없어 FAIL.

- [ ] **Step 3: header와 저장 상태를 추가한다.**

```javascript
export function buildRequestHeaders({ authToken, guestId, guestCredential, authSessionId } = {}, options = {}) {
  return {
    ...(options.includeContentType ? { "Content-Type": "application/json" } : {}),
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...(guestId ? { "X-Guest-Id": guestId } : {}),
    ...(guestCredential ? { "X-Guest-Credential": guestCredential } : {}),
    ...(authSessionId ? { "X-Auth-Session-Id": authSessionId } : {}),
  };
}
```

`persistAuthSession`과 `readStoredAuthSession`은 `guest_credential`을 함께 처리한다. credential은 body/query에 절대 넣지 않는다.

- [ ] **Step 4: bootstrap과 Google 결합을 변경한다.**

```javascript
const guest = await api.createGuestSession({ guest_id: guestId, session_id: sessionId }, identity);
const nextGuestCredential = guest?.guest_credential || "";
setGuestCredential(nextGuestCredential);
persistAuthSession({ guestId: nextGuestId, guestCredential: nextGuestCredential });

if (isGuestCredentialError(error)) {
  clearGuestSessionState();
  return bootstrapGuestSession(nextRoute);
}
```

credential 오류는 과거 guest ID·session ID를 먼저 지운 뒤 guest-session endpoint만 호출한다. `previewLoggedInUi`는 raw guest ID로 보호 API를 호출하지 않는 UI preview로 제한한다.

- [ ] **Step 5: 프런트엔드 테스트를 통과시키고 커밋한다.**

Run: `python -m pytest test/test_frontend_auth_session_contract.py -q --timeout=30`

Expected: PASS; credential은 저장·header 전송만 된다.

```powershell
git add app/web/apiClient.js app/web/authSession.js app/web/FrontendAppShell.jsx test/test_frontend_auth_session_contract.py
git commit -m "feat: send guest credential from web client"
```

### Task 4: 비밀 비노출, 회귀, 체크리스트

**Files:**
- Modify: `app/security/pii_masking.py:28-74`
- Modify: `test/test_pii_masking.py`, `backend/chatbot/test_operational_log_privacy.py`, `test/test_api_route_specs.py`
- Modify: `docs/ops/project-readiness-master-checklist.md`

**Interfaces:**
- Consumes: 실제 guest credential과 AuthEvent/history/worker 경로.
- Produces: canonical 및 WSGI header key 마스킹, #258 진행 상태가 반영된 checklist.

- [ ] **Step 1: credential 원문 비노출 테스트를 작성한다.**

```python
def test_guest_credential_is_masked_for_canonical_and_wsgi_header_keys():
    credential = "<signed guest credential>"
    masked = sanitize_pii({"guest_credential": token, "HTTP_X_GUEST_CREDENTIAL": token})
    assert masked == {"guest_credential": MASK_TOKEN, "HTTP_X_GUEST_CREDENTIAL": MASK_TOKEN}
```

Django 테스트는 실제 guest 요청 뒤 AuthEvent, history, worker metadata, request fingerprint, logger에 credential 문자열이 없는지 확인한다.

- [ ] **Step 2: 실패를 확인한다.**

Run: `python -m pytest test/test_pii_masking.py backend/chatbot/test_operational_log_privacy.py -q --timeout=30`

Expected: 명시 credential key 마스킹이 없어 FAIL.

- [ ] **Step 3: 마스킹·route spec·checklist를 갱신한다.**

```python
SECRET_FIELD_KEYS |= {"guest_credential", "x_guest_credential", "http_x_guest_credential"}
```

`X-Guest-Credential`을 resource/auth route spec에 명시하고, #256은 `[x] … #256 / PR #257`, #258은 `[~]`로 갱신한다. PR 생성 직전 검증 완료 시에만 #258을 `[x] … #258 / PR #<번호>`로 바꾼다.

- [ ] **Step 4: 관련 테스트와 전체 회귀를 실행한다.**

Run: `python -m pytest test/test_guest_credential_service.py test/test_auth_session_service.py test/test_frontend_auth_session_contract.py test/test_api_route_specs.py test/test_pii_masking.py backend/chatbot/test_guest_credential_boundary.py backend/chatbot/test_guest_login_session_ownership_e2e.py backend/chatbot/test_operational_log_privacy.py -q --timeout=30`

Expected: PASS.

Run: `python -m pytest -q --timeout=30`

Expected: PASS; legacy raw guest-ID fixture가 실패하면 guest-session endpoint와 header credential helper를 사용하도록 같은 테스트에서 교체한 뒤 재실행한다.

- [ ] **Step 5: 최종 변경을 커밋한다.**

```powershell
git add app/security/pii_masking.py test/test_pii_masking.py backend/chatbot/test_operational_log_privacy.py test/test_api_route_specs.py docs/ops/project-readiness-master-checklist.md
git commit -m "test: guard guest credential privacy boundary"
```

## Self-Review

- Spec coverage: Task 1은 claim·키·호환 응답, Task 2는 요청 경계·session binding·Google 선검증, Task 3은 browser state/header, Task 4는 비밀 비노출·checklist·회귀를 구현한다.
- Placeholder scan: `TBD`, `TODO`, “적절한 처리”, “나중에 구현”을 쓰지 않았고 각 task에 실행 명령과 기대 결과를 적었다.
- Type consistency: Task 1의 `guest_credential`과 `guest_credential=` 입력을 Task 2가 사용하고, Task 3이 동일 값을 `X-Guest-Credential`으로 전송하며, Task 4가 원문 비저장을 검증한다.
