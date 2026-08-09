# Phase 0-B Baseline Gates Receipt
## Phase 0 C/G characterization completion

- Initial approved base: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- Dev synchronization / PR #400 merge-base: `e245d17074b2a957a45d1e6250e7b8f7c44e859e`
- P400 reviewed merge commit: `2cbec1ed2e2ee198d0b10b8a6687a2bd787ba893`
- C verified-behavior commit: `1ed561ab1a9b2de9b0d043d0ec9e0b27890e598e`
- G verified-behavior commit: `2f41fff12a36d6108d9b928e796a9b2f3ffaad3d`
- C/G blocking selector commit: `d98ae619d32eac5c491d3b5872003d46ad464f95`

| Command | Exit code | Result |
|---|---:|---|
| `python backend/manage.py test chatbot.test_phase_00_ocr_law_flow --verbosity 2` | 0 | PASS: 4 tests |
| `python backend/manage.py test chatbot.test_phase_00_report_lifecycle --verbosity 2` | 0 | PASS: 4 tests |
| C law-node assertion mutation probe | 1 | Expected FAIL: `law_ground_search` assertion detected mutation |
| G report-owner assertion mutation probe | 1 | Expected FAIL: report owner provenance assertion detected mutation |

C uses only document classification, OCR, and legal-RAG provider doubles. G uses only text pgvector and legal-RAG provider doubles. Neither test patches submission/routing/planning/enqueue/worker/report/auth/download code, creates `AgentResult`/`AnalysisDisplayResult`/`Report` directly, or uses `/api/mock/` as evidence. G creates its report only through the production case -> fact version -> queue -> worker lifecycle.

The stale-report assertion starts with that worker-created report, confirms it through the public endpoint, then changes its already-persisted reporting input in the isolated test database. The real public download boundary recomputes the fingerprint and rejects the stale confirmation; no report, authorization, or download function is patched.

Known full-collection and platform items remain `PREEXISTING_BASELINE_DEBT` and are `NOT_INTRODUCED_BY_PR_399`: the cv2/pypdf collection debt and Windows EICAR portability observation. They are not represented as C/G characterization success or as a new PR regression.

| Additional local verification | Exit code | Result |
|---|---:|---|
| expanded Phase 0 Django selector | 0 | PASS: 13 tests |
| `chatbot.test_queued_followup_state_persistence` | 0 | PASS: 7 tests |
| `chatbot.test_analysis_job_queue` | 0 | PASS: 34 tests |
| production contract/artifact pytest selector | 0 | PASS: 53 tests |
| `test/test_phase_00_compose_probe.py` | 0 | PASS: 7 tests |
| follow-up service pytest + Django OCR follow-up module | 0 | PASS: 8 + 8 tests with their respective runners |
| `manage.py check`, OpenAPI check, frontend-route check, ruff, Compose shell syntax | 0 | PASS |
| frontend `node --test ./*.test.js` / `npm run build` | 0 | PASS: 155 tests / production build |
| local Terraform sequence | 1 | NOT_RUN: `terraform` is not installed on this Windows host; this is a local tool limitation, not an application baseline failure. The Ubuntu CI Terraform gate remains authoritative. |

The combined plain-pytest command against the Django `test_chat_session_followup_ocr_confirmation.py` module failed only because that runner does not configure `DJANGO_SETTINGS_MODULE`; the same module passes with `python backend/manage.py test`. This is a runner-selection observation, not a production failure or a test change request.

## Remote CI evidence for the C/G behavior head

- Behavior head: `d98ae619d32eac5c491d3b5872003d46ad464f95`
- `production-gate` Run: `31317365628` — `success`
- `offline-verification` Job: `93254668908` — `success`
- `compose-integration` Job: `93255063276` — `success`
- `regression-signal` Run: `31317365643` is tracked independently on the same behavior head.

The successful offline job includes `Phase 0 core user-flow characterization gate`, `Queued follow-up state regression`, contract/artifact checks, OpenAPI/route drift checks, ruff, frontend tests/build, Terraform validation, and `Docker build and import smoke`. The successful Compose job includes the integration gate and artifact upload. Downloaded artifact `phase-00-compose-evidence` reported `status=pass`, database/cache/ClamAV/Neo4j ready, backend live/ready true, and both agent-worker and file-scan-worker consumed work.

This receipt records the last behavior-bearing C/G CI head. The final PR head after this evidence-only documentation commit is authoritative in PR metadata; no repeated documentation-only commit is made merely to self-reference that later CI run.

## Base and scope

- Base: `198efeba3cabacc3a977cfcaf2f8d7e06fd47104`
- Working branch: `refactor/phase-00-baseline-gates`
- Permitted changes: refactoring documentation, tests, Compose gate scripts, and `production-gate.yml` only.
- No production runtime module, Dockerfile, root Compose file, dependency metadata, migration, or API contract is changed.

## Local deterministic evidence

| Command | Result |
|---|---|
| `python backend/manage.py test chatbot.test_phase_00_core_user_flows chatbot.test_file_quarantine.FileQuarantinePipelineTests.test_multipart_registration_writes_only_to_quarantine chatbot.test_consultation_v2.ConsultationCaseApiTests.test_fact_confirmation_precedes_real_worker_queue --verbosity 1` | PASS: 5 tests |
| `python -m pytest test/test_phase_00_compose_probe.py -q` | PASS: 6 tests |
| `bash -n scripts/refactoring/run_phase_00_compose_gate.sh` | PASS |
| `git diff --check` | PASS |

The test runner initially rejected two incorrectly transcribed existing class names. Those selectors were corrected to the code-defined `ConsultationCaseApiTests`; this was not an application baseline failure.

## Docker evidence boundary

| Scope | Result | Evidence |
|---|---|---|
| D1 image build/import | PASS | Existing `production-gate` Run 30861528733, Job 91844345278; equivalent approved-base tree |
| D2 Compose integration | PENDING_CI | new blocking `compose-integration` job invokes `scripts/refactoring/run_phase_00_compose_gate.sh` and uploads `tmp/phase-00-compose-evidence/` |

Local D2 was not invoked because the local Docker daemon is unavailable. This is an environment limitation, not a passing result and not an application baseline failure.

## Unverified boundaries

- D2 service integration awaits the first GitHub Actions execution.
- External provider calls and operating AWS infrastructure are deliberately outside the provider-free Phase 0 gate.
- C's persisted OCR-to-law-search path and G's generated-report-to-confirmation path have only supporting existing tests; their missing production characterization coverage is recorded in the verification matrix and must not be represented as a pass.
