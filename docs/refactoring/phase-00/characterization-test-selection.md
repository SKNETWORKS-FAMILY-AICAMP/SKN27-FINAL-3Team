# Phase 0 Characterization Test Selection
## C/G completion (supersedes the earlier C/G gap rows)

| Flow | Characterization module and exact tests | Classification | Live production boundaries | Deterministic doubles | Durable/public assertions |
|---|---|---|---|---|---|
| C | `chatbot.test_phase_00_ocr_law_flow::{test_phase_00_ocr_confirmation_is_attachment_scoped,test_phase_00_short_answer_routes_real_law_worker_and_persists_retrieval,test_phase_00_stale_or_foreign_confirmation_is_rejected,test_phase_00_law_result_exposes_no_private_ocr_or_storage_data}` | BLOCKING_NEW | canonical upload/message/result API, scan worker, queue, worker | classification, OCR, legal-RAG providers only | attachment/session/owner, persisted follow-up state, law result/retrieval event, public redaction |
| G | `chatbot.test_phase_00_report_lifecycle::{test_phase_00_worker_result_creates_versioned_report,test_phase_00_owner_confirms_current_report_document,test_phase_00_confirmed_report_download_is_owner_only,test_phase_00_stale_or_foreign_confirmation_is_rejected}` | BLOCKING_NEW | canonical session/file/case/facts/report APIs, queue, worker | text pgvector and legal-RAG providers only | case/fact/job/work/result/display/report provenance, owner access, confirmation and download |

Neither module patches chat submission, routing, planning, enqueueing, worker execution, report persistence, report authorization, or download behavior. `/api/mock/`, mock-sidecar, and string-only evidence remain excluded from this blocking classification.

- 기준 SHA: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- 작성 기준일: 2026-08-08
- 작성 기준: runtime 코드와 테스트 본문을 읽고 `/api/`·ORM·repository·worker 경계 및 실제 patch 대상을 분류했다. 파일명·함수명만으로 분류하지 않았다.

## Existing tests

| 흐름 | 테스트 | patch 대상 | 실제 통과 경계 | DB 검증 | 분류 | 재사용 여부 |
|---|---|---|---|---|---|---|
| A | `backend/chatbot/test_guest_login_session_ownership_e2e.py::GuestLoginSessionOwnershipE2ETests::test_matching_guest_login_can_promote_all_resources_to_one_case` | `chatbot.views.submit_message`, Google HTTP `urlopen`, Agent adapter | `/api/auth/guest-session/`, `/api/auth/google/code/`, ownership 승격 API | `AuthSession`, `ChatSession`, `AnalysisJob`, `UploadedFile`, `Report`, `Case` | SUPPORTING_ONLY | 승격 후속 리소스 회귀 근거로만 사용; 새 A test가 로그인 전 guest session 생성·Google adapter·resume을 실제 경계로 고정한다. |
| B | `backend/chatbot/test_file_quarantine.py::FileQuarantinePipelineTests::test_multipart_registration_writes_only_to_quarantine` | object-storage adapter `FakeS3Client` | `/api/files/` upload persistence | `UploadedFile` status·scan status·storage metadata | BLOCKING_REUSABLE | object storage만 external adapter로 대체하고 upload/quarantine runtime 경계를 통과한다. scan·분류·OCR 경계는 Compose probe로 보완한다. |
| B | `backend/chatbot/test_attachment_classification_confirmation_flow.py::AttachmentClassificationConfirmationFlowTests::test_confirmation_uses_server_classification_to_route_photo_search` | `chatbot.views.submit_message` | `/api/files/`, `/api/chat/messages/` | `UploadedFile` | SUPPORTING_ONLY | orchestration fixture가 분류 이후 경로를 대체하므로 단독 blocking 근거로 사용하지 않는다. |
| C | `backend/chatbot/test_chat_session_followup_ocr_confirmation.py::ChatSessionFollowupOcrConfirmationTests::test_same_attachment_restores_only_allowed_confirmation_fields` | 없음 | follow-up service 함수 | DB row 없음 | SUPPORTING_ONLY | persistence·canonical endpoint가 없어 새 C test로 보완한다. |
| D | `backend/chatbot/test_consultation_v2.py::ConsultationCaseApiTests::test_fact_confirmation_precedes_real_worker_queue` | 없음 | `/api/cases/`, fact confirmation, case analysis job queue | `Case`, `ConfirmedFactVersion`, `AnalysisJob`, `AgentWorkItem` | BLOCKING_REUSABLE | case 승격 전 거절, confirmation, idempotent queue를 blocking selector에 사용한다. |
| E | `backend/chatbot/test_analysis_job_queue.py::AnalysisJobQueueTests::test_worker_executes_work_item_once_and_skips_terminal_reclaim` | `app.services.agent_node_service.execute_agent_plan` (wrap/mock) | repository queue·worker | `AnalysisJob`, `AgentWorkItem`, `AgentResult`, `AgentInvocation` | SUPPORTING_ONLY | prohibited execution patch가 있어 새 E test 및 Compose probe로 보완한다. |
| F | `backend/chatbot/test_analysis_job_queue.py::AnalysisJobQueueTests::test_stale_lease_cannot_reserve_or_dispatch_a_paid_call` | worker/plan test doubles | repository lease·retry | `AgentWorkItem`, `AgentInvocation` | SUPPORTING_ONLY | lease safety 회귀 근거로만 사용; 새 F test는 실제 no-provider internal plan으로 검증한다. |
| G | `backend/chatbot/test_report_api_contract.py::ReportApiContractTests::test_owner_download_exposes_only_public_document_headers` | 없음 | `/api/reports/<report_id>/document-confirmation/`, download | `Report` fixture row | SUPPORTING_ONLY | Report를 직접 fixture로 만들며 생성 use case를 통과하지 않아 새 G test로 보완한다. |
| A/B/E/G | `backend/chatbot/test_canonical_user_flow_e2e.py::CanonicalUserFlowE2ETests::*` | `chatbot.views.submit_message`, agent graph/provider functions | 여러 canonical `/api/` route | `AgentWorkItem`, `Report` | SUPPORTING_ONLY | fixed chat response가 orchestration을 대체하므로 production characterization의 단독 근거로 사용하지 않는다. |

`/api/mock/`, mock service/sidecar만을 사용하는 테스트와 source 문자열 검사 테스트는 `NOT_APPLICABLE`이며 Phase 0 blocking selector에 포함하지 않는다.

## Coverage gap

| 흐름 | 미검증 경계 | 추가할 테스트 | 실제 production 경계 |
|---|---|---|---|
| A | guest credential → Google code exchange → owner promotion → resume | `test_phase_00_guest_login_promotes_only_its_session` | `/api/auth/guest-session/`, `/api/chat/sessions/`, `/api/auth/google/code/`, `/api/auth/resume/`; Google HTTP adapter만 double |
| B | clean scan 후 server classification confirmation과 OCR follow-up state | `test_phase_00_clean_attachment_requires_matching_confirmation_before_ocr_followup` | `/api/files/`, production scan worker function, classification adapter, persisted attachment metadata/follow-up state |
| C | persisted OCR fields가 canonical follow-up과 law-search plan으로 연결 | `test_phase_00_ocr_followup_is_attachment_scoped_and_routes_law_search` | canonical chat/use-case, server follow-up state, law adapter만 double |
| D | case 승격과 queue의 상태·소유권 | 기존 `test_fact_confirmation_precedes_real_worker_queue` | case API, `ConfirmedFactVersion`, `enqueue_analysis_job_work` |
| E | no-provider plan이 queue → worker claim → AgentResult persistence를 통과 | `test_phase_00_internal_worker_plan_persists_once` | `enqueue_analysis_job_work`, `process_agent_work_items`, `AgentWorkItem`, `AgentResult` |
| F | stale lease 재claim이 중복 결과 없이 terminal 상태로 종료 | `test_phase_00_stale_internal_work_is_reclaimed_once` | production lease/reclaim/retry repository 경계 |
| G | worker-persisted report → confirmation → owner-only download | `test_phase_00_worker_persisted_report_confirms_and_downloads_for_owner_only` | production agent adapters only double, worker persistence, report confirmation/download APIs |

각 신규 테스트는 docstring에 보호 흐름, production 경계, external double, DB/state assertion, Explicit Mock Runtime 미사용 여부를 기록한다. 금지된 orchestration·queue·worker·report repository symbol은 patch하지 않는다.

## Compose worker plan

- 사용할 node: `input_context_validation` (`app.services.supervisor_control_service.SUPERVISOR_INTERNAL_NODE_CODES`).
- 사용 이유: `app.services.agent_node_service.execute_agent_node`이 provider adapter가 아닌 `run_supervisor_control_node`을 실행하는 internal node이며, user text가 있으면 success 결과를 만든다.
- queue 경계: `chatbot.repositories.enqueue_analysis_job_work`으로 `ChatSession`, `AnalysisJob`, `AgentWorkItem`을 생성한다. Reporting node와 provider-capable node는 포함하지 않는다.
- Worker 소비 증거: 별도 `agent-worker` container가 claim한 row의 `attempt_no >= 1`, `started_at`, `completed_at`, terminal `success`, 연결된 `AnalysisJob` terminal status, `AgentResult.node_code == input_context_validation`을 poll한다. probe는 `process_agent_work_item`을 호출하지 않는다.
- 외부 provider 비활성: compose override에서 `SUPERVISOR_LLM_ENABLED=0`, `LEGAL_RAG_VECTOR_ENABLED=0`, `LAW_GROUND_SEARCH_ENABLE_NEO4J=0`, Google/OpenAI/RunPod key 없음으로 실행하며 plan은 provider-capable node를 포함하지 않는다.

## Compose file scan plan

- fixture: 고유 UUID를 포함한 harmless text fixture; 악성 또는 EICAR payload는 사용하지 않는다.
- persistence 경계: backend container에서 existing `smoke_file_scan --phase upload --format json`으로 `UploadedFile`과 production metadata를 생성한다.
- Worker 소비 증거: probe는 scan 함수를 호출하지 않고 Compose PostgreSQL row를 poll한다. 별도 `file-scan-worker`가 `scan_status == clean`, error/retry 없음, ClamAV scanner metadata를 남겨야 한다.
- ClamAV 확인 방식: Compose service healthcheck와 scan result의 scanner metadata를 함께 확인한다. local policy/fake scanner 결과는 D2 PASS 근거로 사용하지 않는다.

## Blocking selector

`production-gate.yml`의 Phase 0 core gate는 이 문서의 `BLOCKING_REUSABLE` 테스트와 신규 `test_phase_00_*` 테스트만 명시적으로 실행한다. Supporting-only와 NOT_APPLICABLE 테스트는 기존 회귀 범위를 유지하되, Phase 0 production characterization의 단독 통과 근거로 사용하지 않는다.
