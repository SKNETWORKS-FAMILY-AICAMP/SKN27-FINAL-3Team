# History API Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the existing canonical history endpoint to a shadow OpenAPI contract while preserving response compatibility and blocking foreign `job_id` reads.

**Architecture:** Keep `history_events()` as the runtime endpoint. Add a compatibility-preserving Pydantic DTO and RouteSpec; a route-specific OpenAPI security override documents App JWT or signed guest credential without changing existing routes. Reuse analysis-job ownership metadata before listing a `job_id` query.

**Tech Stack:** Django, Pydantic v2, pytest, Django `TestCase`, OpenAPI 3.2 YAML.

## Global Constraints

- Do not alter `/api/mock/history/`, repositories, migrations, retention behavior, or frontend code.
- `X-Guest-Id` is never standalone authority; `X-Guest-Credential` remains header-only proof.
- Preserve the `limit=100` fallback for missing, invalid, and non-positive values.
- Keep existing route security output unchanged unless a route declares an explicit security override.
- Include the already-approved PR #275 C-1 evidence and complete only H's history API item.

---

## File map

| File | Change | Responsibility |
| --- | --- | --- |
| `app/contracts/history.py` | Create | Stable, additive public history response DTOs |
| `app/contracts/api_route_specs.py` | Modify | History route, query/header parameters, explicit OR security metadata |
| `app/contracts/openapi_v1.py` | Modify | Render route security override and guest credential security scheme |
| `backend/chatbot/views.py` | Modify | Authorize a canonical `job_id` filter before listing events |
| `test/test_history_api_contract.py` | Create | Route/DTO/OpenAPI static contract regression |
| `backend/chatbot/test_history_api_contract.py` | Create | HTTP identity, ownership, and limit regression |
| `test/test_openapi_v1_generation.py` | Modify | Preserve route-specific security assertions |
| `docs/api/openapi-v1.yaml` | Regenerate | Checked-in OpenAPI output |
| `docs/ops/project-readiness-master-checklist.md` | Modify | Record PR #275 C-1 evidence and #274 H completion |

## Task 1: Add the `job_id` ownership regression and minimal runtime guard

**Files:**
- Create: `backend/chatbot/test_history_api_contract.py`
- Modify: `backend/chatbot/views.py:612-667`

**Interfaces:**
- Consumes: `get_analysis_job_access_metadata(job_id)`, `_authorize_session_query(session_id, payload, resource_type=...)`, and `_object_access_denied_response(request, access)`.
- Produces: `GET /api/history/?job_id=<foreign>` returns the existing `object_access_denied` 403 envelope before history filtering.

- [x] **Step 1: Write the failing foreign-job test.**

```python
def test_other_users_job_history_is_denied(self) -> None:
    response = self.other_client.get("/api/history/?job_id=job_history_owner")

    self.assertEqual(response.status_code, 403, response.content)
    self.assertEqual(response.json()["error"]["code"], "object_access_denied")
```

Create an owner `ChatSession` and `AnalysisJob(job_id="job_history_owner")` in `setUp`; issue App JWTs with the established `issue_access_token()` and `AuthSession` pattern from `backend/chatbot/test_mypage_api_contract.py`.

- [x] **Step 2: Run test to verify the current failure.**

```powershell
python backend/manage.py test chatbot.test_history_api_contract.HistoryApiContractTests.test_other_users_job_history_is_denied -v 1
```

Expected: 200 because `job_id` is currently only a repository filter.

- [x] **Step 3: Write the minimum runtime guard.**

Before `_authorize_history_query()`, read `request.GET.get("job_id")`. For an existing job, use its existing session metadata and return `_object_access_denied_response()` when `_authorize_session_query(..., resource_type="history")` is denied. A missing job remains on the current empty-list path.

```python
job_id = request.GET.get("job_id")
if job_id:
    metadata = get_analysis_job_access_metadata(job_id)
    if metadata is not None:
        access = _authorize_session_query(
            str(metadata.get("session_id") or ""),
            identity_payload,
            resource_type="history",
        )
        if not access["allowed"]:
            return _object_access_denied_response(request, access)
```

- [x] **Step 4: Add owner-job and other-session cases.**

```python
def test_owner_job_history_is_allowed(self) -> None:
    self.assertEqual(self.owner_client.get("/api/history/?job_id=job_history_owner").status_code, 200)

def test_other_session_is_denied(self) -> None:
    response = self.other_client.get("/api/history/?session_id=ses_history_owner")
    self.assertEqual(response.status_code, 403, response.content)
```

- [x] **Step 5: Run the runtime module.**

```powershell
python backend/manage.py test chatbot.test_history_api_contract chatbot.test_guest_credential_boundary -v 1
```

Expected: selected tests pass; raw guest ID remains 401 and header-proved guest history remains 200.

## Task 2: Promote the stable DTO and route specification

**Files:**
- Create: `app/contracts/history.py`
- Modify: `app/contracts/api_route_specs.py`
- Create: `test/test_history_api_contract.py`
- Modify: `test/test_api_route_specs.py`

**Interfaces:**
- Consumes: current JSON keys emitted by `history_events()`.
- Produces: `HISTORY_API_ROUTE_SPECS`, `HistoryListResponse`, and an `API_ROUTE_SPECS` entry for `GET /api/history/`.

- [x] **Step 1: Write failing static contract tests.**

```python
assert spec.response_model is contracts.HistoryListResponse
assert spec.security_requirements == ({"bearerAuth": ()}, {"guestCredentialAuth": ()})
assert ("GET", "/api/history/") not in deferred
assert set(parameters) == {
    ("X-Guest-Credential", "header"), ("X-Guest-Id", "header"),
    ("session_id", "query"), ("user_id", "query"), ("guest_id", "query"),
    ("job_id", "query"), ("event_type", "query"), ("limit", "query"),
}
```

- [x] **Step 2: Run test to verify it fails.**

```powershell
python -m pytest -q test/test_history_api_contract.py
```

Expected: `HISTORY_API_ROUTE_SPECS` and `app.contracts.history` are absent and history remains deferred.

- [x] **Step 3: Write the minimum DTO and route implementation.**

Define `HistoryPublicModel` with `ConfigDict(extra="allow")`. Require stable event/list fields only and type nested runtime data as `dict[str, Any]`. Add `security_requirements: tuple[dict[str, tuple[str, ...]], ...] = ()` to `RouteSpec`; reject combining it with `auth_required` or `auth_optional`. Register history with `auth_required=False`, `auth_optional=False`, and `({"bearerAuth": ()}, {"guestCredentialAuth": ()})`.

- [x] **Step 4: Run route tests.**

```powershell
python -m pytest -q test/test_history_api_contract.py test/test_api_route_specs.py
```

Expected: all selected tests pass.

## Task 3: Render exact OpenAPI security and generated artifact

**Files:**
- Modify: `app/contracts/openapi_v1.py`
- Modify: `test/test_openapi_v1_generation.py`
- Modify: `docs/api/openapi-v1.yaml` (generated)

**Interfaces:**
- Consumes: `RouteSpec.security_requirements`.
- Produces: `security: [{bearerAuth: []}, {guestCredentialAuth: []}]` and a header `apiKey` `guestCredentialAuth` scheme.

- [x] **Step 1: Add a failing OpenAPI assertion.**

```python
history = document["paths"]["/api/history/"]["get"]
assert history["security"] == [{"bearerAuth": []}, {"guestCredentialAuth": []}]
assert document["components"]["securitySchemes"]["guestCredentialAuth"] == {
    "type": "apiKey", "in": "header", "name": "X-Guest-Credential"
}
```

- [x] **Step 2: Run it and verify failure.**

```powershell
python -m pytest -q test/test_openapi_v1_generation.py -k history
```

Expected: `/api/history/` is absent from OpenAPI v1.

- [x] **Step 3: Render explicit security without changing legacy output.**

Update `_security_requirements()` to return `spec.security_requirements` before falling back to `auth_required` or `auth_optional`. Add `guestCredentialAuth` beside `bearerAuth`. Update the general OpenAPI security loop so history has the OR assertion while all existing path families retain their expectations.

- [x] **Step 4: Regenerate and validate the artifact.**

```powershell
python scripts/generate_openapi_v1.py
python scripts/generate_openapi_v1.py --check
python -m pytest -q test/test_openapi_v1_generation.py
```

Expected: `OpenAPI v1 is current` and all OpenAPI tests pass.

## Task 4: Finalize checklist and run regressions

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `docs/superpowers/plans/2026-07-21-history-api-contract.md`

**Interfaces:**
- Consumes: verified PR #275 RAG isolation evidence and #274 test results.
- Produces: retained C-1 evidence and completed H history API contract item.

- [x] **Step 1: Update only approved checklist rows.**

Keep the PR #275 RAG failed/partial regression row already added. Replace `- [ ] 히스토리 API 계약` with a completed #274 entry describing shadow OpenAPI, App JWT/guest credential boundary, and owner/session/job regression coverage. Do not edit C-2, H common errors, or I items.

- [x] **Step 2: Run focused checks.**

```powershell
python -m pytest -q test/test_history_api_contract.py test/test_api_route_specs.py test/test_openapi_v1_generation.py
python backend/manage.py test chatbot.test_history_api_contract chatbot.test_guest_credential_boundary -v 1
```

Expected: all selected tests pass.

- [ ] **Step 3: Run complete regression and review the diff.**

```powershell
python -m pytest -q --timeout=30 -p no:cacheprovider
git diff --check
git status -sb
```

Expected: full suite passes, whitespace check is clean, and the diff is limited to planned files plus generated OpenAPI and checklist rows.

- [ ] **Step 4: Commit and push implementation.**

```powershell
git add app/contracts/history.py app/contracts/api_route_specs.py app/contracts/openapi_v1.py backend/chatbot/views.py backend/chatbot/test_history_api_contract.py test/test_history_api_contract.py test/test_api_route_specs.py test/test_openapi_v1_generation.py docs/api/openapi-v1.yaml docs/ops/project-readiness-master-checklist.md docs/superpowers/plans/2026-07-21-history-api-contract.md
git commit -m "test: promote history API contract"
git push origin test/274-history-api-contract
```

## Plan self-review

- [x] Issue #274's DTO, query, authentication, raw guest, user/guest/session/job ownership, generated OpenAPI, and checklist requirements map to Tasks 1-4.
- [x] The job guard is limited to `history_events()` and reuses existing metadata; repository and sidecar changes are absent.
- [x] Explicit security avoids anonymous OpenAPI access while routes that do not opt in keep their current output.
- [x] C-2, H common errors, and I operational items have no task and remain untouched.
