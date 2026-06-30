# Google auth and app JWT boundary - 2026-06-30

## Conclusion

The first Google login implementation is now a boundary layer, not a full
production OAuth deployment. Canonical `POST /api/auth/login/` accepts a Google
subject, creates or updates `users` and `auth_sessions`, and returns an app
Bearer token. `GET /api/auth/me/` can read that token back into the same
`user_id` and `auth_session_id`.

## Scope

- New endpoint: `POST /api/auth/login/`
- Provider: `google`
- Response contract: `google_auth.v1`
- App token: local HMAC JWT with `sub=user_id` and `jti=auth_session_id`
- Persistence:
  - `users`
  - `guest_identities` when a guest id is supplied
  - `auth_sessions`
  - `auth_events`
  - `chat_sessions.metadata.auth_context`

## Local/dev mode

Local and test runs use `GOOGLE_AUTH_ALLOW_MOCK=1`. In this mode the endpoint
accepts mock Google profile fields such as `google_sub`, `email`, and
`display_name`. This keeps frontend/backend integration testable before a real
Google client id and browser callback are configured.

## Production switch

For production verification:

1. Set `GOOGLE_AUTH_ALLOW_MOCK=0`.
2. Set `GOOGLE_CLIENT_ID`.
3. Install/use `google-auth`.
4. Send the Google Identity Services `credential` or `id_token` to
   `POST /api/auth/login/`.

The endpoint then verifies the Google ID token at the login boundary and still
returns the same app Bearer token shape to the rest of the API.

## Remaining work

1. Frontend Google Identity Services button/callback integration.
2. Refresh/logout endpoints.
3. Explicit guest-to-user merge confirmation UI and endpoint.
4. Secret rotation and production JWT issuer/audience policy.
