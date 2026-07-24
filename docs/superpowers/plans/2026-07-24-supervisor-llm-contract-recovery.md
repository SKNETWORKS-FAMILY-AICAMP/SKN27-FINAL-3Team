# Supervisor LLM Contract Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 운영 Supervisor fallback과 LLM 응답 계약을 일치시켜 실제 chat orchestration의 `invalid_contract` 503을 제거하고 production smoke로 재발을 차단한다.

**Architecture:** 모델은 대화 요약·사실·질문·허용된 node payload만 생성한다. 서버는 production fallback과 `NODE_REGISTRY`를 기준으로 stage, owner, status, missing fields, reporting payload를 주입하고, OpenAI strict JSON Schema와 별도 도메인 검증을 모두 통과한 결과만 사용한다.

**Tech Stack:** Python 3.12, OpenAI Python SDK 2.45, Django management commands, pytest, PowerShell AWS pilot deployment

## Global Constraints

- `supervisor_conversation_state.v2`, `analysis_plan.v2`, `reporting_payload.v2` 외부 계약을 유지한다.
- `owner`, `status`, `missing_fields`, `stage`, `slot_state`, `reporting_payload`를 모델이 결정하지 못하게 한다.
- provider 오류, refusal, schema 오류, domain 오류는 기존 503 fail-closed 정책을 유지한다.
- 로그에는 사용자 원문, 첨부 내용, 모델 전체 응답, API key, OAuth code, private URL을 남기지 않는다.
- `json_object`로 자동 완화하지 않는다.
- OpenAI 또는 embedding 유료 호출을 테스트에서 실행하지 않는다.
- `tmp/build_pilot_precedent_seed.py`, `tmp/pilot-rag-bundle/`, `tmp/pilot-rag-evidence/`, `deploy/aws-pilot/.runtime.env`를 Git에 포함하지 않는다.

---

## File Structure

- Create `app/services/supervisor_llm_contract.py`: Registry 보강, strict response schema 생성, 후보 패키지 검증과 안전한 오류 코드의 단일 책임.
- Modify `app/services/supervisor_llm_service.py`: prompt v2, structured response 요청, refusal 처리, contract helper 연결, 안전 로그.
- Modify `app/services/chat_orchestration_service.py`: OCR 확인 후 추가되는 패키지도 canonical 보강 함수를 통과.
- Modify `test/test_supervisor_llm_service.py`: schema, refusal, owner, reporting, 빈 패키지 단위 회귀.
- Create `test/test_supervisor_production_contract.py`: 실제 `submit_message()`의 라우팅 회귀.
- Modify `backend/chatbot/readiness.py`: readiness metadata를 production runtime smoke로 교체.
- Modify `deploy/aws-pilot/Deploy-Pilot.ps1`: mock smoke를 production runtime smoke로 교체.
- Modify `test/test_aws_pilot_infrastructure.py`: 원격 승격 전 smoke 명령과 순서 계약 검증.
- Modify `docs/ops/project-readiness-master-checklist.md`: P0 원인·수정·검증 증거 기록.
- Modify `docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md`: Supervisor production 계약 검증 결과 기록.

---

### Task 1: Canonical Server-Owned Supervisor Contract

**Files:**
- Create: `app/services/supervisor_llm_contract.py`
- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**
- Consumes: `app.services.agent_node_service.NODE_REGISTRY`, production fallback dict
- Produces: `enrich_supervisor_state(fallback_state: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]`
- Produces: `normalize_candidate_packages(candidate_packages: Any, fallback_packages: Any) -> tuple[list[dict[str, Any]] | None, str | None]`

- [ ] **Step 1: Write failing Registry enrichment tests**

Add tests that use the real Registry and a production-shaped v2 fallback:

```python
from app.services import supervisor_llm_contract as service_contract


def test_enrich_supervisor_state_injects_registry_owner_and_package_fields():
    fallback = {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "agent_execution_ready",
        "missing_fields": [],
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "law_ground_search",
                "status": "ready",
                "required_inputs": ["user_text|attachments"],
                "payload": {"user_text": "school zone", "attachments": []},
            }
        ],
        "reporting_payload": None,
    }

    enriched, error = service_contract.enrich_supervisor_state(fallback)

    assert error is None
    assert enriched is not None
    assert enriched["contract_version"] == "supervisor_conversation_state.v2"
    assert enriched["agent_input_packages"][0]["owner"] == "techshin31"
    assert enriched["agent_input_packages"][0]["missing_fields"] == []
    assert enriched["agent_input_packages"][0]["status"] == "ready"
    assert enriched["reporting_payload"] is None
```

Add a second test asserting that an empty package list with
`stage="need_fact_confirmation"` remains valid and a third test asserting an
unknown node returns `registry_node_missing` without leaking payload text.

- [ ] **Step 2: Run the tests to verify RED**

Run:

```powershell
python -m pytest test/test_supervisor_llm_service.py -k "enrich_supervisor_state" -q
```

Expected: collection or assertion failure because
`app.services.supervisor_llm_contract` and `enrich_supervisor_state` do not exist.

- [ ] **Step 3: Implement the contract helper**

Create these exact public functions:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.agent_node_service import NODE_REGISTRY

AGENT_INPUT_SCHEMA_VERSION = "agent_input_schema.v1"
AGENT_PACKAGE_STATUSES = {"ready", "waiting_for_fields"}


def enrich_supervisor_state(
    fallback_state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    state = deepcopy(fallback_state)
    packages = state.get("agent_input_packages")
    if not isinstance(packages, list):
        return None, "invalid_agent_packages"
    enriched: list[dict[str, Any]] = []
    for raw_package in packages:
        package, error = enrich_agent_package(raw_package)
        if error:
            return None, error
        enriched.append(package)
    state["agent_input_packages"] = enriched
    return state, None


def enrich_agent_package(
    raw_package: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw_package, dict):
        return None, "invalid_agent_package"
    node_code = str(raw_package.get("node_code") or "").strip()
    registry_node = NODE_REGISTRY.get(node_code)
    if not registry_node or not str(registry_node.get("owner") or "").strip():
        return None, "registry_node_missing"
    if not isinstance(raw_package.get("payload"), dict):
        return None, "invalid_agent_payload"
    package = deepcopy(raw_package)
    package["schema_version"] = AGENT_INPUT_SCHEMA_VERSION
    package["owner"] = str(registry_node["owner"])
    package["required_inputs"] = [
        str(item)
        for item in registry_node.get("required_inputs") or []
        if str(item).strip()
    ]
    missing_fields = [
        str(field).strip()
        for field in package.get("missing_fields") or []
        if str(field).strip()
    ]
    package["missing_fields"] = missing_fields
    package["status"] = "waiting_for_fields" if missing_fields else "ready"
    return package, None
```

Implement `normalize_candidate_packages` so it requires exactly the fallback
node set, accepts an empty list when fallback is empty, copies only payload keys
already present in fallback, and calls `enrich_agent_package` after merging.

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run:

```powershell
python -m pytest test/test_supervisor_llm_service.py -k "enrich_supervisor_state or candidate_packages" -q
```

Expected: all selected tests pass without network calls.

- [ ] **Step 5: Commit the canonical contract helper**

```powershell
git add app/services/supervisor_llm_contract.py test/test_supervisor_llm_service.py
git commit -m "fix: canonicalize supervisor agent packages"
```

---

### Task 2: Strict Structured Output and Safe Failure Diagnostics

**Files:**
- Modify: `app/services/supervisor_llm_contract.py`
- Modify: `app/services/supervisor_llm_service.py`
- Modify: `test/test_supervisor_llm_service.py`

**Interfaces:**
- Consumes: enriched fallback state and fallback plan
- Produces: `conversation_response_format(fallback_state: dict[str, Any]) -> dict[str, Any]`
- Produces: `analysis_plan_response_format(fallback_plan: dict[str, Any]) -> dict[str, Any]`
- Produces: `_request_supervisor_json(config, request_payload, response_format) -> dict[str, Any]`

- [ ] **Step 1: Write failing request-format and refusal tests**

Use a fake `OpenAI` client that captures `chat.completions.create` arguments and
returns `choices[0].message.content`. Assert:

```python
assert captured["response_format"]["type"] == "json_schema"
assert captured["response_format"]["json_schema"]["strict"] is True
assert captured["response_format"]["json_schema"]["name"] == "supervisor_conversation_response_v2"
assert captured["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
assert "reporting_payload" not in captured["response_format"]["json_schema"]["schema"]["properties"]
```

Add a refusal fixture whose message has `refusal="policy refusal"` and assert the
service returns failed metadata with reason `provider_refusal`, empty packages,
and no refusal text in logs.

- [ ] **Step 2: Run the tests to verify RED**

Run:

```powershell
python -m pytest test/test_supervisor_llm_service.py -k "structured_output or provider_refusal or safe_validation_log" -q
```

Expected: failures showing current `json_object`, missing response schema, and
missing refusal handling.

- [ ] **Step 3: Implement strict response schemas**

Add schema builders whose root object has `additionalProperties: false`.
Conversation schema required properties are exactly:

```python
[
    "conversation_summary",
    "collected_facts",
    "missing_fields",
    "next_questions",
    "agent_input_packages",
]
```

Each candidate package contains exactly `node_code` and `payload`. Restrict
`node_code` with an enum derived from fallback packages. Use `minItems=0` and
`maxItems=0` when fallback packages are empty; otherwise require the exact
fallback count. Do not include owner, status, stage, slot state, contract
version, or reporting payload in the model schema.

Build each payload object schema recursively from its matching fallback
payload. Every object level uses `additionalProperties: false`; scalar values
use their fallback JSON type plus `null` only when the fallback value is null.
Attachment arrays expose only `attachment_id`. Schema validation therefore
cannot introduce a payload key that the fallback normalizer would later drop.

Analysis plan schema allows only fallback node codes and candidate fields that
the existing normalizer already bounds:

```python
[
    "routing_intent",
    "input_summary",
    "required_inputs",
    "pending_questions",
    "agent_input_packages",
    "steps",
    "blocked_reason",
]
```

- [ ] **Step 4: Wire provider request and safe diagnostics**

Change `_request_supervisor_json` to accept the selected response format and
call:

```python
response = client.chat.completions.create(
    model=config["model"],
    temperature=config["temperature"],
    response_format=response_format,
    messages=[
        {"role": "system", "content": request_payload["system"]},
        {"role": "user", "content": json.dumps(request_payload["user"], ensure_ascii=False)},
    ],
)
message = response.choices[0].message
if str(getattr(message, "refusal", "") or "").strip():
    raise SupervisorProviderError("provider_refusal")
```

Introduce `SupervisorProviderError` carrying only an allowlisted reason code.
Add `logger.warning("supervisor_llm_failed reason=%s", reason)` and never log
candidate data or exception text. Upgrade prompt constants to
`supervisor_conversation_prompt.v2` and `supervisor_analysis_plan_prompt.v2`,
explicitly describing array shapes and server-owned fields.

- [ ] **Step 5: Run targeted tests to verify GREEN**

Run:

```powershell
python -m pytest test/test_supervisor_llm_service.py -q
```

Expected: all Supervisor LLM unit tests pass and no API call occurs.

- [ ] **Step 6: Commit strict output handling**

```powershell
git add app/services/supervisor_llm_contract.py app/services/supervisor_llm_service.py test/test_supervisor_llm_service.py
git commit -m "fix: enforce strict supervisor structured output"
```

---

### Task 3: Production Chat Orchestration Regression

**Files:**
- Modify: `app/services/chat_orchestration_service.py`
- Create: `test/test_supervisor_production_contract.py`
- Modify: `test/test_chat_orchestration_service.py`

**Interfaces:**
- Consumes: `enrich_agent_package`, real `submit_message(payload, routing_intent_override=...)`
- Produces: production chat responses that are not `supervisor_unavailable` for valid structured candidates

- [ ] **Step 1: Write failing four-route production regression**

Parametrize the real service call:

```python
@pytest.mark.parametrize(
    ("routing_intent", "user_text"),
    [
        ("general_consultation", "교통 관련 일반 상담이 필요해"),
        ("traffic_law_search", "어린이보호구역 정차 관련 법령을 찾아줘"),
        ("fine_notice_procedure", "과태료 고지서를 받은 뒤 절차를 알려줘"),
        ("fine_notice_analysis", "과태료 고지서 내용을 분석해줘"),
    ],
)
def test_production_submit_message_accepts_registry_enriched_llm_candidate(
    monkeypatch,
    routing_intent,
    user_text,
):
    monkeypatch.setenv("SUPERVISOR_LLM_ENABLED", "1")
    monkeypatch.setenv("SUPERVISOR_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("SUPERVISOR_LLM_MODEL", "gpt-test")
    monkeypatch.setattr(
        supervisor_llm_service,
        "_request_supervisor_json",
        lambda _config, request_payload, _response_format: candidate_from_request(request_payload),
    )

    response = submit_message(
        {"session_id": f"ses_{routing_intent}", "user_text": user_text, "attachments": []},
        routing_intent_override=routing_intent,
    )

    assert response["status"] != "supervisor_unavailable"
    assert response["supervisor_state"]["llm"]["status"] == "used"
    for package in response["supervisor_state"]["agent_input_packages"]:
        assert package["owner"]
        assert isinstance(package["missing_fields"], list)
```

`candidate_from_request` returns only the model-owned fields defined in Task 2
and uses node codes found in the request fallback.

- [ ] **Step 2: Write failing edge-path tests**

Add:

- `accident_initial_consultation` preserves empty packages and
  `need_more_input` or `need_fact_confirmation`.
- Fine-notice OCR confirmation adds `law_ground_search` and
  `appeal_decision_flow`, each with Registry owner and list `missing_fields`.
- A malicious candidate owner field is rejected by strict schema fixture or
  ignored by normalizer and never reaches the final state.

- [ ] **Step 3: Run the tests to verify RED**

Run:

```powershell
python -m pytest test/test_supervisor_production_contract.py test/test_chat_orchestration_service.py -q
```

Expected: current production paths fail with `supervisor_unavailable` or lack
canonical fields on OCR-added packages.

- [ ] **Step 4: Integrate canonical enrichment**

In `build_supervisor_state_with_optional_llm`, enrich fallback before building
the request. Preserve fallback-owned `scenario`, `stage`,
`conversation_turn_count`, `slot_state`, contract version, and reporting
payload in `_normalize_llm_state`.

In `_apply_ocr_confirmation_to_supervisor_state`, pass both server-added
packages through `enrich_agent_package` and fail the state closed with
`registry_node_missing` if enrichment fails.

- [ ] **Step 5: Run production regressions to verify GREEN**

Run:

```powershell
python -m pytest test/test_supervisor_production_contract.py test/test_chat_orchestration_service.py test/test_supervisor_execution_input_service.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit production orchestration integration**

```powershell
git add app/services/chat_orchestration_service.py app/services/supervisor_llm_service.py test/test_supervisor_production_contract.py test/test_chat_orchestration_service.py
git commit -m "fix: align production supervisor orchestration"
```

---

### Task 4: Production Runtime Smoke Deployment Gate

**Files:**
- Modify: `backend/chatbot/readiness.py`
- Modify: `deploy/aws-pilot/Deploy-Pilot.ps1`
- Modify: `test/test_aws_pilot_infrastructure.py`
- Modify: `backend/chatbot/test_supervisor_conversation_runtime_smoke.py`

**Interfaces:**
- Consumes: existing `smoke_supervisor_conversation_runtime`
- Produces: promotion command that verifies public chat, production Supervisor,
  queue, worker, persistence, and report before symlink promotion

- [ ] **Step 1: Write failing deployment contract tests**

Assert the normal promotion segment contains:

```python
expected = (
    "smoke_supervisor_conversation_runtime --allow-paid-provider-call "
    "--require-llm-used --require-real-agent-results "
    "--require-persisted-handoff --require-report "
    "--fine-notice-fixture-s3-uri '$FineNoticeSmokeS3Uri' --format json"
)
assert expected in deploy
assert "smoke_supervisor_llm --require-used" not in normal_promotion_segment
assert "smoke_non_dl_analysis_reporting_pipeline --allow-paid-provider-call" not in normal_promotion_segment
assert deploy.index(expected) < deploy.index("ln -sfn `$RELEASE_DIR /opt/skn27-pilot/current")
```

Assert readiness metadata reports:

```python
assert result["metadata"]["production_smoke"] == (
    "smoke_supervisor_conversation_runtime --require-llm-used"
)
```

- [ ] **Step 2: Run deployment tests to verify RED**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py backend/chatbot/test_supervisor_conversation_runtime_smoke.py -k "supervisor or normal_promotion" -q
```

Expected: deployment script and readiness still reference
`smoke_supervisor_llm`, and normal promotion still runs the separate non-DL
paid smoke.

- [ ] **Step 3: Replace mock smoke with production runtime smoke**

Update the remote normal-promotion command to use the exact expected command
from Step 1. Remove both the mock-only Supervisor smoke and the separate
provider-capable non-DL smoke from this segment because the production runtime
smoke covers public chat, queue, Worker, real results, persisted handoff, and
report in one provider-capable execution. Reuse the already validated
`FineNoticeSmokeS3Uri`; do not add a second fixture or second paid provider
call.

Change readiness metadata key from `mock_off_smoke` to `production_smoke` and
point it at `smoke_supervisor_conversation_runtime --require-llm-used`.

- [ ] **Step 4: Run deployment tests to verify GREEN**

Run:

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py backend/chatbot/test_supervisor_conversation_runtime_smoke.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the deployment gate**

```powershell
git add backend/chatbot/readiness.py deploy/aws-pilot/Deploy-Pilot.ps1 test/test_aws_pilot_infrastructure.py backend/chatbot/test_supervisor_conversation_runtime_smoke.py
git commit -m "fix: gate pilot promotion on production supervisor smoke"
```

---

### Task 5: Full Verification and Release Evidence

**Files:**
- Modify: `docs/ops/project-readiness-master-checklist.md`
- Modify: `docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md`

**Interfaces:**
- Consumes: test and build outputs from Tasks 1-4
- Produces: auditable P0 closure evidence and a PR-ready branch

- [ ] **Step 1: Run focused Supervisor suites**

```powershell
python -m pytest test/test_supervisor_llm_service.py test/test_supervisor_production_contract.py test/test_chat_orchestration_service.py test/test_supervisor_execution_input_service.py backend/chatbot/test_supervisor_conversation_runtime_smoke.py -q
```

Expected: zero failures and no external provider calls.

- [ ] **Step 2: Run backend and deployment regression suites**

```powershell
python -m pytest test/test_aws_pilot_infrastructure.py test/test_runtime_worker_and_registry_contract.py backend/chatbot/test_production_hardening.py -q
```

Expected: zero failures.

- [ ] **Step 3: Run production configuration and frontend gates**

```powershell
npm --prefix app/web run build -- --configLoader runner
docker compose -f deploy/aws-pilot/docker-compose.pilot.yml config --quiet
```

Expected: Vite build succeeds and Compose config exits 0. These commands must
not start AWS resources or call OpenAI.

- [ ] **Step 4: Record exact evidence**

Update the checklist and verification report with:

- root cause: production fallback/validator impossible contract
- fix: server-owned Registry enrichment and strict JSON Schema
- route evidence: four production `submit_message()` branches plus two edge paths
- deployment evidence: production runtime smoke before symlink promotion
- residual risk: `openai_compatible` providers must support strict schema
- live provider smoke: pending until the already approved AWS deployment stage

- [ ] **Step 5: Run final diff and secret checks**

```powershell
git diff --check
git status --short
git diff --name-only origin/dev...HEAD
```

Expected: only planned source, test, deployment, and documentation files are
included. Private `tmp/` artifacts remain untracked and unstaged.

- [ ] **Step 6: Commit release evidence**

```powershell
git add docs/ops/project-readiness-master-checklist.md docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md
git commit -m "docs: record supervisor P0 recovery evidence"
```

- [ ] **Step 7: Publish and open the PR**

```powershell
git push -u origin feat-supervisor-contract-p0
gh pr create --base dev --head feat-supervisor-contract-p0 --title "fix: recover production Supervisor LLM contract" --body-file docs/superpowers/reports/2026-07-23-release-readiness-integration-verification.md
```

Expected: a ready-for-review PR targeting `dev`. Merge only after required CI
checks pass; then resume AWS deployment from merged `dev`.
