# Auth token lifecycle - 2026-06-30

## Basis

- Issue: #106
- Previous backend boundary: #100
- Previous frontend login flow: #105
- Session policy source: `docs/architecture/auth-session-policy-2026-06-28.md`

## Implemented endpoints

- `POST /api/auth/refresh/`
  - Requires a valid app Bearer JWT.
  - Reissues an app Bearer JWT for the same `auth_session_id`.
  - Keeps `auth_sessions.status` as `active`.
  - Records `auth_token_refreshed` in `auth_events` and `history_events`.
- `POST /api/auth/logout/`
  - Requires a valid app Bearer JWT.
  - Marks `auth_sessions.status` as `revoked` and sets `revoked_at`.
  - Returns `client_action.clear_access_token=true` and `clear_google_profile=true`.
  - Records `auth_logout_completed` in `auth_events` and `history_events`.

## MVP policy

Refresh currently requires a still-valid app JWT. The backend does not store a
separate long-lived refresh token, and it does not silently refresh expired
access tokens. Logout revokes the persisted `auth_session`, but already issued
stateless JWTs remain structurally decodable until clients clear them or a
future auth layer checks `auth_sessions.status` on every protected request.

## Frontend contract

`ChatbotMockFlow` stores the app Bearer token in `localStorage`, calls
`/api/auth/refresh/` to rotate it, and calls `/api/auth/logout/` to clear
local token/profile state before reloading the guest subject.
