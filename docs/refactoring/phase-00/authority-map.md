# Phase 0 Runtime Authority Map

Runtime authority is ordered as follows when Phase 0 documents and gates disagree: executable application code and model/repository code; Dockerfile and Compose runtime definitions; CI workflow/package metadata; tests; then explanatory documents.

| Concern | Runtime authority | Supporting documentation | Phase 0 treatment |
|---|---|---|---|
| HTTP routing and auth | `backend/chatbot/urls.py`, `backend/chatbot/views.py` | root README | characterize current `/api/` behavior |
| chat orchestration and follow-up | `app/services/chat_orchestration_service.py`, `app/services/chat_session_followup_service.py` | architecture history/roadmap | no behavioral change |
| supervisor/agent dispatch | `app/services/agent_node_service.py`, `app/services/supervisor_execution_input_service.py`, `app/services/supervisor_routing_service.py` | architecture history/roadmap | use only provider-free internal plan in D2 |
| durable state and work lease | `backend/chatbot/models.py`, `repositories.py`, `case_repository.py` | this baseline | assert actual rows and timestamps |
| container and CI execution | `Dockerfile`, `docker-compose.yml`, `.github/workflows/production-gate.yml` | Compose receipt | D1 remains existing; D2 is added as blocking CI evidence |
| browser shell and local session | `app/web/FrontendAppShell.jsx`, `app/web/authSession.js` | frontend tests | build and existing frontend tests remain blocking |

`README.md`, `docs/README.md`, and `docs/architecture/ddd-mas-history-log-roadmap-2026-06-29.md` are context documents. They are not accepted as proof where runtime behavior differs.
