# Phase 2-D8 ResumeLatestConsultation Application Boundary

## Authority

- Repository: `SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team`
- Base: `cbbb1f3afa2002a0d1ae98e5e97ac0a7f8bb0f92`
- Branch: `refactor/phase-02-d8-resume-latest-consultation-use-case`
- RED Head: `1acb9f118bf4834146bba6b728c64eccf15fb5ee`
- GREEN Head: `840cc42947b31c44aad1403b7350656c9734b8e2`
- Verification Runtime Head: `647ad2989bbf45a872d56e79d014441ea0d63d6d`
- PR: `PENDING_DRAFT_CREATION`
- Merge: `NOT_PERFORMED`

이 Receipt는 verification runtime source head를 기록한다. 이어지는 docs-only commit의 미래 SHA를 본문에 self-reference 하지 않는다. Docs Delta Head authority는 Git과 Draft PR metadata에서 확인한다.

## Target and Scope

- Route: `GET /api/auth/resume/`
- View: `auth_resume`
- Application: `app/application/auth/resume_latest_consultation.py`
- Use Case: `ResumeLatestConsultation`

Production source delta는 다음 세 파일로 제한한다.

- `app/application/auth/__init__.py`
- `app/application/auth/resume_latest_consultation.py`
- `backend/chatbot/views.py`

`backend/config/middleware.py`: `NOT_MODIFIED`

Route, HTTP method, public manifest schema, persistence schema/migration, repository semantics, Queue/Worker, Storage/Renderer, Agent/RAG, frontend는 변경하지 않았다.

## RED and GREEN Chronology

- RED command: `python backend/manage.py test chatbot.test_phase_02_resume_latest_consultation_use_case --verbosity 1`
- RED result: `9` tests 중 `test_http_get_requires_the_new_application_seam`만 `AssertionError`
- RED failure: `execute_resume_latest_consultation` called `0` times
- GREEN result: D8 characterization + `test_resume_manifest` `12 tests, OK`
- RED ancestor of GREEN: `YES`
- Classification: `INDEPENDENTLY_PROVABLE`

`auth_resume`는 request identity resolution, 기존 HTTP error mapping, `ResumeLatestConsultationQuery` 생성, Application 실행, JSON serialization만 수행한다.

`execute_resume_latest_consultation`는 authenticated user subject 확인, latest owned `ChatSession` 조회, 그 session의 latest `AnalysisJob` 상세 조회, 기존 `build_resume_manifest` 조합을 담당한다. Application module은 HTTP Request/Response, transaction, 직접 ORM, cache write, Queue/Worker, Storage/Renderer 의존성을 추가하지 않는다.

## Authorization, Selection, and Projection

- authenticated user만 resume manifest를 요청할 수 있다.
- latest session은 authenticated subject의 owner만 기준으로 선택한다.
- foreign session이 더 최신이어도 선택하지 않는다.
- selected session의 latest job만 `latest_analysis`로 사용한다.
- attachment와 report는 selected session 안에서도 owner fence를 다시 적용한다.
- manifest는 existing allow-list projection만 사용한다. `storage_uri`, raw OCR, credential, token, private prompt는 노출하지 않는다.
- session이 없으면 existing empty `resume_manifest.v1` contract를 유지한다.

## Guest Transport / View Contract

`PRESERVE_ACTUAL_EXTERNAL_CONTRACT`

- 실제 external `GET /api/auth/resume/` with valid guest headers는 `JwtAuthMiddleware`에서 View 이전에 `401 auth_required`, reason `missing_token`을 반환한다.
- direct `auth_resume` View guest identity는 `403 login_required.v1`, reason `resume_manifest_requires_authenticated_user`를 유지한다.
- external transport test는 View identity resolver와 `execute_resume_latest_consultation` call이 모두 `0`임을 확인한다.
- direct View test는 기존 login-required response를 확인한다.

`RESUME_GUEST_TRANSPORT_VIEW_CONTRACT_ALIGNMENT`

`DEFERRED_ARCHITECTURAL_OBSERVATION`: middleware transport policy와 View-local guest policy는 서로 다른 layer의 현행 contract다. 이 delta는 `/api/auth/resume/`를 guest allow path로 바꾸지 않았고 `401`을 `403`으로 바꾸지 않았다. 이 정렬은 별도 architecture scope가 필요하다.

## Sensitivity

Verification Runtime Head `647ad2989bbf45a872d56e79d014441ea0d63d6d`에서 `python scripts/refactoring/verify_phase_02_d8_resume_latest_consultation_test_sensitivity.py`는 baseline `0`, source restoration `true`, `working_tree_unchanged: true`를 확인했다.

| Mutation | Direct detection |
| --- | --- |
| `view_application_bypass` | View seam call assertion |
| `latest_owned_session_bypass` | newest foreign session exclusion assertion |
| `latest_job_selection_bypass` | selected session newest job assertion |
| `derived_resource_owner_bypass` | foreign attachment/report exclusion assertion |
| `privacy_manifest_bypass` | `storage_uri` and private projection exclusion assertion |

- exact mutation set: `5`
- each mutation: nonzero `AssertionError`
- stale `PHASE_02_D8_SENSITIVITY_HEAD`: strict equality rejection
- runner contract: `4 passed`
- production gate adds D8 boundary test, negative controls, artifact upload, and `ruff check --select F401 app/application/auth/resume_latest_consultation.py`.

## Local Verification

| Suite | Result |
| --- | --- |
| D8 focused + resume manifest + guest boundary | `24 tests, OK` |
| B1–D7 Application regression | `84 tests, OK` |
| Phase 2 sensitivity/API/OpenAPI/frontend auth contracts | `86 passed` |
| Django check / OpenAPI / frontend route / static / diff | `PASS` |
| frontend `node --test ./*.test.js` | `155 passed` |
| frontend `npm run build` | `PASS` |
| Docker D1 image build + Django check + initialized import smoke | `PASS` |
| Docker Compose D2 | `PASS` |

D1 image: `skn27-phase-02-d8-local`.

D2는 `scripts/refactoring/run_phase_00_compose_gate.sh`를 source 변경 없이 실행했다. Windows Git Bash에서 Python stdout CR을 child-session `python3` wrapper로만 정규화했다. 최종 evidence:

- `gate-summary.json`: `status: pass`
- PostgreSQL, Redis, ClamAV, Neo4j: ready
- backend live/ready: `true`
- agent worker: `status: pass`
- file scan worker: `status: pass`
- `last-step.txt`: `compose-final`
- `cleanup.txt`: `cleanup_success`
- `failed-step.txt`: absent
- final Compose containers/volumes/networks residue: `0`

Windows full Django `python backend/manage.py test chatbot --verbosity 1`는 `548 tests`, `20 errors`였다. D8 focused 및 prior Application regression에는 failure/error가 없다. 전체-suite errors는 이 delta 밖의 local portability observation으로 유지한다.

- `pymupdf._extra` DLL loading
- existing attachment classification adapter import portability

## CI and Deferred Scope

- Draft PR source head CI: `PENDING`
- `production-gate`: `PENDING`
- `offline-verification`: `PENDING`
- `compose-integration`: `PENDING`
- `regression-signal`: `PENDING`
- Production DB audit: `NOT_EXECUTED`
- `RESUME_GUEST_TRANSPORT_VIEW_CONTRACT_ALIGNMENT`: `DEFERRED_ARCHITECTURAL_OBSERVATION`
- Phase 2 remaining boundaries and Phase 3 structural work: out of scope

## Status

- Implementation: `PASS`
- RED chronology: `INDEPENDENTLY_PROVABLE`
- Authorization/selection/projection: `PASS`
- Guest transport decision: `PRESERVE_ACTUAL_EXTERNAL_CONTRACT`
- D1: `PASS`
- D2: `PASS`
- CI: `PENDING_DRAFT_PR`
- Merge: `NOT_PERFORMED`
