# Google Authorization Code Flow 전환 기록 - 2026-07-01

## 1. 결론

Google 인증은 사용자가 제안한 방식대로 진행한다.

핵심은 로그인과 Google 데이터 접근 권한을 한 덩어리로 묶지 않는 것이다.

- 로그인: `openid email profile`만 요청한다.
- Google Drive, Photos, Sheets 같은 데이터 접근: 사용자가 해당 기능을 누를 때 필요한 scope만 추가 요청한다.
- 프론트는 authorization code만 받고, Google access token과 refresh token은 저장하지 않는다.
- 백엔드가 authorization code를 Google token endpoint에서 교환하고, refresh token은 암호화 또는 암호화 가능 저장 경계 안에 둔다.
- 우리 서비스 JWT와 Google API token은 분리한다.

이 작업은 인증/사용자/연동 저장 경계만 다룬다. `hi20260204-maker`가 맡지 않은 Agent 구현은 건드리지 않는다.

GitHub #68 기록:

- Google Authorization Code Flow 전환 코멘트: https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/68#issuecomment-4850447548
- Google Authorization Code Flow 1차 구현 완료 코멘트: https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team/issues/68#issuecomment-4850567384

## 2. 선택한 방식

초기 로그인은 Google Identity Services의 Authorization Code Flow를 사용한다.

프론트:

- `google.accounts.oauth2.initCodeClient()`를 사용한다.
- scope는 기본 로그인 기준 `openid email profile`로 시작한다.
- `ux_mode`는 popup을 기본으로 사용한다.
- callback에서 받은 `response.code`만 백엔드로 전송한다.
- 요청에는 `X-Requested-With: XmlHttpRequest`를 포함한다.

백엔드:

- `POST /api/auth/google/code/`에서 code를 받는다.
- popup flow에서는 `redirect_uri`를 프론트 origin과 맞춘다.
- Google token endpoint로 code를 교환한다.
- `id_token` 검증 또는 userinfo 조회로 Google `sub`, `email`, `name`, `picture`를 확인한다.
- `users`, `social_accounts`, `oauth_connections`, `auth_sessions`, `auth_events`에 저장한다.
- 우리 서비스용 app JWT를 발급한다.

## 3. Scope 정책

처음부터 넓은 권한을 요청하지 않는다.

| 목적 | Scope | 정책 |
|---|---|---|
| 기본 로그인 | `openid email profile` | 최초 로그인 전용 |
| Drive 이미지 선택 | `https://www.googleapis.com/auth/drive.file` | Google Picker 또는 사용자가 선택한 파일 중심 |
| Drive 전체 읽기 | `https://www.googleapis.com/auth/drive.readonly` | restricted scope라 MVP 기본값에서 제외 |
| Photos 선택 | `https://www.googleapis.com/auth/photospicker.mediaitems.readonly` | Photos Picker API 기준 |
| Sheets 읽기 | `https://www.googleapis.com/auth/spreadsheets.readonly` | 해당 기능을 누를 때만 |
| Calendar 읽기 | `https://www.googleapis.com/auth/calendar.readonly` | 해당 기능을 누를 때만 |

## 4. DB 추가 경계

기존 `users`, `auth_sessions`, `auth_events`에 다음 경계를 추가한다.

### social_accounts

Google 계정 식별용이다.

- `provider = google`
- `provider_user_id = Google sub`
- 한 Google 계정은 하나의 사용자에만 연결한다.

### oauth_connections

Google API 접근 권한 저장용이다.

- `access_token_encrypted`
- `refresh_token_encrypted`
- `token_type`
- `expires_at`
- `granted_scopes`
- `revoked_at`

운영에서는 refresh token을 반드시 안전하게 암호화해야 한다. 현재 구현은 저장 경계를 만들고, 운영 secret 기반 보호를 적용할 수 있게 분리한다.

## 5. API 계약

### POST /api/auth/google/code/

구현 상태: 완료.

현재 endpoint는 다음을 수행한다.

- `X-Requested-With: XmlHttpRequest`가 없는 popup code 요청을 거절한다.
- `GOOGLE_AUTH_ALLOW_MOCK=1`에서는 `mock_google_code:*`로 로컬/테스트 code flow를 검증한다.
- `GOOGLE_AUTH_ALLOW_MOCK=0`에서는 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_POPUP_REDIRECT_URI`를 사용해 Google token endpoint로 code를 교환한다.
- 응답에는 우리 서비스 app JWT만 포함하고, Google access token/refresh token 원문은 포함하지 않는다.
- `social_accounts`, `oauth_connections`, `auth_sessions`, `auth_events`에 저장한다.

요청:

```json
{
  "code": "4/0...",
  "purpose": "LOGIN",
  "redirect_uri": "http://127.0.0.1:5173",
  "guest_id": "gst_...",
  "session_id": "ses_..."
}
```

응답:

```json
{
  "contract_version": "google_auth_code.v1",
  "auth_state": "authenticated",
  "provider": "google",
  "access_token": "우리 서비스 JWT",
  "google": {
    "connected": true,
    "granted_scopes": ["openid", "email", "profile"],
    "purpose": "LOGIN"
  }
}
```

## 6. Google 데이터 가져오기 후속

이번 작업은 로그인 code flow를 먼저 고정한다.

다음 단계에서 기능별 endpoint를 붙인다.

- `GET /api/google/connection/`
- `POST /api/auth/google/code/` with `purpose = GOOGLE_DRIVE_CONNECT`
- `POST /api/google/drive/import-image/`
- `POST /api/auth/google/code/` with `purpose = GOOGLE_PHOTOS_CONNECT`
- `POST /api/google/photos/import-image/`

Drive/Photos/Sheets/Calendar는 기능별 scope를 따로 요청하고, 승인된 scope만 `oauth_connections.granted_scopes`에 저장한다.

## 7. 공식 문서 확인

- Google Identity Services Code Model: https://developers.google.com/identity/oauth2/web/guides/use-code-model
- Google OAuth web server flow: https://developers.google.com/identity/protocols/oauth2/web-server
- Google Drive API scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Google Photos Picker API: https://developers.google.com/photos/picker/guides/get-started-picker

## 8. 1차 구현 검증

- `python backend/manage.py test chatbot`
  - Result: 62 passed
- `python -m pytest test/test_auth_session_mock_service.py test/test_agent_node_service.py`
  - Result: 15 passed
- `python -m pytest --ignore=test/test_fine_notice_ocr.py`
  - Result: 56 passed
- `npm run build` in `app/web`
  - Result: passed
- `python backend/manage.py makemigrations --check --dry-run`
  - Result: No changes detected
- `docker compose config --quiet`
  - Result: passed

Agent ownership guard:

- No non-`hi20260204-maker` Agent implementation was changed.
