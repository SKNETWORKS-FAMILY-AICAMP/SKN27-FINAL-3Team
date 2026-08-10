# Phase 0 State Ownership Baseline

This is a runtime baseline, not a target architecture. It records the observed owner, duplicated representations, and the read/write routes that must remain stable during Phase 0.

| State | Primary persisted location | Duplicated/derived location | Current read path | Current write path |
|---|---|---|---|---|
| identity and session ownership | PostgreSQL: `AuthSession`, `ChatSession` | browser auth/session storage; chat metadata | `/api/auth/resume/`, chat-session repository | `/api/auth/guest-session/`, `/api/auth/google/code/` |
| uploaded file and scan lifecycle | PostgreSQL: `UploadedFile` and metadata | quarantine/clean object storage; message attachment IDs | file repository and attachment gate | `/api/files/`, file scan worker |
| OCR/classification follow-up | PostgreSQL chat-session/message metadata | frontend in-memory/browser UI state | follow-up service and canonical chat read | canonical chat/follow-up path |
| consultation facts and Case | PostgreSQL: `Case`, `ConfirmedFactVersion` | session metadata and request payloads | case/fact repositories | fact confirmation / case-promotion route |
| analysis dispatch and result | PostgreSQL: `AnalysisJob`, `AgentWorkItem`, `AgentResult`, `AgentInvocation` | Redis queue/cache only where configured; worker logs | repository claim/read paths | `enqueue_analysis_job_work`, agent worker |
| report and downloadable document | PostgreSQL: `Report` | report object storage; frontend download state | report API/document-confirmation endpoint | report repository/worker persistence |
| cache/lease coordination | Redis | PostgreSQL work-item fencing fields are durable source for work status | runtime health and worker/repository reads | Redis client and worker coordination |

PostgreSQL is the durable state for the rows named above. Metadata and frontend storage are representations or workflow inputs, not an additional owner. Redis must not be treated as the only durable record of a completed job, file, case, or report.
