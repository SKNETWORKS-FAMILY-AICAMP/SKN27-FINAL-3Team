# Phase 1 Mock Persistence Audit

- Local/Test audit: `COMPLETED` (local sqlite의 `analysis_jobs`, `chat_messages`, `uploaded_files`, `reports`, `agent_work_items`, `history_events`는 각 0건; 모든 marker count는 0). `scripts/refactoring/audit_phase_01_mock_persistence.py --format json`은 사용자 원문, token, storage URI를 출력하지 않는다.
- Production DB audit: `NOT_EXECUTED`.
- `AnalysisJob.mock_scenario` physical column removal: `DEFERRED`.
- 이번 Phase의 기준은 canonical 신규 write/read/public serialization에서 `mock_scenario`, `mock_status`, `canonical_mock`, mock sidecar URI를 제거하는 것이다.
