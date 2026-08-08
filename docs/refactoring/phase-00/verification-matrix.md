# Phase 0 Verification Matrix

- 기준 SHA: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- 작성 기준일: 2026-08-08

| 흐름 | 보호 테스트 | 실제 production 경계 | patch 범위 | DB 검증 | CI blocking | 신규 test |
|---|---|---|---|---|---|---|
| A guest → Google → resume | `test_phase_00_guest_login_promotes_only_its_session` | guest/auth/session/resume `/api/` | Google `urllib_request.urlopen` | `ChatSession` owner/auth metadata | core user-flow gate | 추가 |
| B upload → scan → classify → OCR | `test_multipart_registration_writes_only_to_quarantine`; Compose file probe | `/api/files/`, upload persistence, file worker | 없음; D2는 실제 ClamAV | `UploadedFile` status/scan metadata | core + Compose gate | classification/OCR canonical gap은 Phase 0-C review input |
| C OCR → follow-up → law search | supporting follow-up tests | follow-up service state | 없음 | existing unit has no DB row | supporting only | canonical persistence gap은 Phase 0-C review input |
| D intake → Case | `ConsultationCaseApiTests::test_fact_confirmation_precedes_real_worker_queue` | Case/fact/job `/api/` | 없음 | `Case`, `ConfirmedFactVersion`, `AnalysisJob`, `AgentWorkItem` | core user-flow gate | 불필요 |
| E facts → job → worker → result | `test_phase_00_internal_worker_plan_persists_once` | enqueue/claim/worker/persistence | 없음 | `AnalysisJob`, `AgentWorkItem`, `AgentResult` | core + Compose gate | 추가 |
| F stale lease → re-run | `test_phase_00_stale_internal_work_is_reclaimed_once` | stale requeue/claim/worker | 없음 | work attempt/status, one `AgentResult` | core user-flow gate | 추가 |
| G report → confirm → download | `test_owner_download_exposes_only_public_document_headers` | report confirmation/download `/api/` | 없음 | `Report` fixture | supporting only | generation-to-download gap은 Phase 0-C review input |

The core gate does not classify `/api/mock/`, sidecar-only, source-text, or orchestration-fixture tests as a production characterization pass. D2 evidence is required separately because D1 Docker build/import does not exercise service integration.
