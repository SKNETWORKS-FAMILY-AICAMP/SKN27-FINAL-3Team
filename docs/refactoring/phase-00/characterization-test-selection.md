# Phase 0 Characterization Test Selection

## Current authority

This is the current Phase 0 selector record. It supersedes earlier planning
rows that classified C/G as support-only or left D2 as pending.

C/G characterization keeps HTTP, routing, planning, queue, worker,
persistence, authorization, confirmation, rendering, and download boundaries
real. Classification and retrieval dependencies are deterministic
service/pipeline-level doubles whose internal contracts are protected by a
separate blocking service-contract selector.

| Flow | Blocking characterization | Real production boundaries | Deterministic dependency boundary |
|---|---|---|---|
| A | `chatbot.test_phase_00_core_user_flows.Phase00CoreUserFlowTests.test_phase_00_guest_login_promotes_only_its_session` | guest session, Google-code endpoint, authenticated session resume, ownership persistence | Google HTTP adapter |
| B | `chatbot.test_file_quarantine.FileQuarantinePipelineTests.test_multipart_registration_writes_only_to_quarantine`; Compose file-scan probe | `/api/files/`, quarantine/clean persistence, scan worker, document-classification workflow | object-storage test adapter; classification service contract is separately gated |
| C | `chatbot.test_phase_00_ocr_law_flow` including `test_phase_00_replaced_attachment_does_not_reuse_stale_ocr_confirmation` and `test_phase_00_short_answer_routes_real_law_worker_and_persists_retrieval` | canonical upload/message/result APIs, scan, routing, plan, queue, worker, `ChatSession`/`AnalysisJob`/`AgentWorkItem`/`AgentResult`/`RetrievalEvent` persistence | `classify_document_bytes` service-level double; `_call_gpt` OCR provider-call boundary; `search_legal_rag` service-level double |
| D | `chatbot.test_consultation_v2.ConsultationCaseApiTests.test_fact_confirmation_precedes_real_worker_queue` | case API, fact confirmation, case/job binding, queue | none |
| E | `chatbot.test_phase_00_core_user_flows.Phase00CoreUserFlowTests.test_phase_00_internal_worker_plan_persists_once`; Compose agent-worker probe | enqueue, worker claim, result persistence | internal no-provider plan |
| F | `chatbot.test_phase_00_core_user_flows.Phase00CoreUserFlowTests.test_phase_00_stale_internal_work_is_reclaimed_once` | stale lease reclaim, retry, terminal persistence | internal no-provider plan |
| G | `chatbot.test_phase_00_report_lifecycle` including `test_phase_00_worker_result_creates_versioned_report`, owner confirmation, stale confirmation, and owner-only download | authenticated case/facts APIs, queue, worker, report persistence, confirmation, DOCX render/download | `run_unified_pgvector_pipeline` pipeline-level double; `search_legal_rag` service-level double |

No C/G test patches chat submission, routing, planning, queueing, worker
execution, report persistence, report authorization, or download behavior. No
C/G test inserts `AgentResult`, `RetrievalEvent`, `AnalysisDisplayResult`, or
`Report` directly. `/api/mock/`, sidecar-only paths, and string-only checks are
not Phase 0 production characterization evidence.

## Blocking selectors

| Gate | Selector | Purpose |
|---|---|---|
| Phase 0 core user-flow characterization gate | Django selectors in `.github/workflows/production-gate.yml` | A, B quarantine, C, D, E, F, and G production-boundary characterization |
| Phase 0 deterministic service-contract gate | `test/test_attachment_document_classification_adapter.py`, `test/test_legal_rag_service.py`, `etl/fault_cases/src/agents/text_ml_case_search/tests/test_pgvector_unified_retriever.py` | protects deterministic classification, legal-RAG, and pgvector-pipeline internal contracts |
| Phase 0 sensitivity negative controls | `scripts/refactoring/verify_phase_00_test_sensitivity.py` | requires C law-node and G report-owner assertion mutations to fail in temporary test copies |
| Phase 0 Compose integration gate | `scripts/refactoring/run_phase_00_compose_gate.sh` | D2 PostgreSQL, Redis, ClamAV, Neo4j, backend, agent-worker, and file-scan-worker integration |

The sensitivity runner never edits tracked tests. Its success receipt requires
both original tests to exit `0`, both temporary mutants to fail by
`AssertionError`, and an unchanged working tree.
