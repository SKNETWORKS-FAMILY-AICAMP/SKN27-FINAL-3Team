# #108 Frontend app shell and shared auth/API

## Purpose

Implement the frontend-wide foundation that can be shared by #14, #55, #57,
and #58 while explicitly avoiding #101 fine result screen work.

## Included

- `app/web/apiClient.js`
  - Shared API path joining, query building, JSON request helpers, and auth headers.
  - Auth endpoints: guest session, Google login, current subject, refresh, logout.
  - MVP endpoints: chat messages, report action, My Case summary, history.
- `app/web/authSession.js`
  - Shared local storage keys and helpers for app Bearer token and Google profile.
  - Shared `auth_context` builder.
  - Dev Google profile helper.
- `app/web/FrontendAppShell.jsx`
  - Entry, chatbot, My Case, and History shell routes.
  - Reuses `ChatbotMockFlow` for the existing chatbot UI.
  - Loads My Case and History through the shared API client.
- `app/web/ChatbotMockFlow.jsx`
  - Keeps the existing UI surface.
  - Moves shared API and auth/session behavior into reusable modules.

## Excluded

- #101 fine result screen UI.
- `feat-fine-analysis-detail-view` layout ownership.
- Fine-specific result/detail cards.
- Production Google client id smoke.
- Large bundler/package setup changes.

## Validation

- `test/test_frontend_auth_session_contract.py` verifies the shared auth/API
  endpoints, app shell routes, and #101 exclusion boundary.
