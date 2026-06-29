# End-to-end persona walkthrough

| Item | Value |
|---|---|
| Date | 2026-06-29 |
| Persona owner | `hi20260204-maker` |
| Goal | Validate the whole user journey even when several real Agents are still mock/contract-only |
| Base contract | `docs/api/openapi-v0.yaml` |
| Storage checkpoints | `chat_sessions`, `chat_messages`, `uploaded_files`, `analysis_jobs`, `analysis_job_events`, `agent_results`, `analysis_display_results`, `reports` |

## Persona

The primary persona is a guest user who received a traffic fine notice and wants to know whether an objection draft can be prepared.

This persona intentionally does not require every real Agent to be finished. The journey is valid when the API can create the session, accept evidence metadata, create an analysis job, run the mock plan, persist Agent envelopes, build a display result, save report metadata, and download a report artifact placeholder.

## Why this matters

The project can still prove the product flow before OCR, RAG, image analysis, and external LLM calls are production-ready. The Supervisor and storage protocol become the stable skeleton. Each unfinished Agent can later replace its mock output as long as it keeps the adapter output envelope:

```json
{
  "node_code": "fine_notice_analysis",
  "status": "success",
  "summary": "...",
  "structured_result": {},
  "evidence": [],
  "next_actions": [],
  "limitations": []
}
```

## Happy path

1. Guest identity is created with `POST /api/auth/guest-session/`.
2. Chat session is created with `POST /api/chat/sessions/`.
3. Fine notice metadata is registered with `POST /api/files/`.
4. User message is submitted with `POST /api/chat/messages/`.
5. Analysis job is created with `POST /api/analysis/jobs/`.
6. Agent execution envelopes are persisted to `agent_results`.
7. Display result is fetched with `GET /api/analysis/results/{job_id}/`.
8. Display snapshot is persisted to `analysis_display_results`.
9. Report action is created with `POST /api/reports/`.
10. Report metadata is persisted to `reports`.
11. Download is requested with `GET /api/reports/{report_id}/download/`.
12. Canonical download reads `reports.storage_uri` first and falls back to mock text when using `mock://reports/{report_id}`.
13. My Case progress is checked with `GET /api/mypage/summary/?session_id={session_id}`.
14. History is checked with `GET /api/history/`.

## Storage expectations

| Step | Table | Expected state |
|---|---|---|
| Chat message | `chat_messages` | User content boundary exists for the canonical request |
| Analysis job | `analysis_jobs` | `job_id`, `session`, `message`, `status`, `analysis_plan_id` are saved |
| Job event | `analysis_job_events` | Initial job status is recorded |
| Agent output | `agent_results` | One row per mock plan execution |
| Display output | `analysis_display_results` | One snapshot per analysis job after result fetch |
| Report | `reports` | Metadata row links to job and display result when available |
| Download | `reports.storage_uri` | `mock://reports/{report_id}` until object storage is introduced |
| My Case summary | read model | `analysis_jobs`, `analysis_job_events`, `agent_results`, `analysis_display_results`, and `reports` are summarized for progress display |

## Incomplete Agent policy

The persona should not be blocked because an Agent is not production-ready.

| Agent area | Current acceptable behavior | Later replacement |
|---|---|---|
| Fine notice OCR | Mock structured notice fields and limitations | OCR adapter result |
| Law/RAG search | Mock legal evidence and retrieval-quality limitation | RAG retrieval result with citations |
| Vision/image analysis | Contract-only or mock scene summary | Vision/OCR worker result |
| Objection report generation | Mock report action and text placeholder | Report generation worker + object storage |
| Validation | Mock envelope validation | Supervisor validation with policy checks |

## Persona acceptance checklist

- Canonical `/api/...` paths return `api_surface: canonical_mock` where JSON responses are used.
- Explicit `/api/mock/...` paths remain sidecar-only and do not create PostgreSQL rows.
- Agent outputs are traceable through `agent_results`.
- The screen-facing result is available without exposing raw `analysis_plan`, `node_execution`, or `chat_response` from the result endpoint.
- Report download uses DB metadata when a `reports` row exists.
- My Case progress can be reconstructed from PostgreSQL metadata through `GET /api/mypage/summary/`.
- The response never claims legal success, exact fault ratio, or guaranteed submission outcome.
- Limitations remain visible whenever OCR/RAG/Vision/LLM behavior is mocked.

## Next sequence

1. Replace `mock://reports/{report_id}` with an object storage adapter boundary.
2. Add download authorization rules based on `reports.owner_id`, guest identity, and auth session.
3. Split guest/member/session/rate-limit policy into enforced middleware or service checks.
4. Add due date/deadline calculation to My Case progress.
5. Add persona variants for accident photo, blackbox video, law-only question, and report re-download.
