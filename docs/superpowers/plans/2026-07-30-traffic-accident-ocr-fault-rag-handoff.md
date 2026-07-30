# Traffic Accident OCR to Fault RAG Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass available traffic-accident-confirmation OCR facts, especially `accident_description`, into `text_ml_case_search` without making OCR a prerequisite for fault-ratio analysis.

**Architecture:** Keep the shared Supervisor envelope unchanged. Add a private mapper in the production `text_ml_case_search` adapter that reads direct `context.ocr_evidence` first and otherwise flattens the traffic OCR node's upstream `structured_result.extracted_fields`. Update accident-analysis plans so OCR executes before fault RAG, while allowing `partial` and `failed` OCR envelopes to flow forward.

**Tech Stack:** Python 3, pytest, existing Supervisor synchronous adapter contract, existing ETL `text_ml_case_search` agent.

## Global Constraints

- OCR is optional and must never block fault-ratio analysis.
- Missing OCR fields remain absent; no inferred facts are created.
- Direct `context.ocr_evidence` takes precedence over upstream OCR.
- `accident_type.value` is flattened to the string `accident_type`.
- Other RAG implementations and the shared `upstream_results` contract are not modified.
- The fault-ratio output schema remains unchanged.

---

### Task 1: Map upstream OCR into the fault-ratio adapter

**Files:**
- Modify: `ai/agents/text_ml_case_search/agent.py`
- Test: `test/test_text_ml_case_search_agent.py`

**Interfaces:**
- Consumes: `agent_input["context"]["ocr_evidence"]` and `agent_input["upstream_results"]["traffic_accident_confirmation_ocr"]["structured_result"]["extracted_fields"]`
- Produces: `_ocr_evidence(agent_input: dict[str, Any]) -> dict[str, Any] | None`
- Produces: an OCR-derived fallback from `_case_query(agent_input)` when no user/query context exists

- [ ] **Step 1: Write failing mapper tests**

Add tests that call the real private boundary helpers:

```python
def test_upstream_traffic_ocr_is_flattened_for_fault_rag() -> None:
    from ai.agents.text_ml_case_search import agent

    payload = {
        "upstream_results": {
            "traffic_accident_confirmation_ocr": {
                "status": "success",
                "structured_result": {
                    "extracted_fields": {
                        "accident_datetime": "2024-08-26 07:20",
                        "accident_location": "충청남도 예산군 삽교읍",
                        "accident_type": {"value": "차대차"},
                        "accident_cause": "진로변경 시 방향지시등 미점등",
                        "accident_description": "1차로 출차 차량과 2차로 진행 차량이 충돌",
                    }
                },
            }
        }
    }

    assert agent._ocr_evidence(payload) == {
        "accident_datetime": "2024-08-26 07:20",
        "accident_location": "충청남도 예산군 삽교읍",
        "accident_type": "차대차",
        "accident_cause": "진로변경 시 방향지시등 미점등",
        "accident_description": "1차로 출차 차량과 2차로 진행 차량이 충돌",
    }
```

Add independent tests proving:

```python
assert agent._ocr_evidence({
    "context": {"ocr_evidence": {"accident_description": "직접 전달 사고내용"}},
    "upstream_results": {
        "traffic_accident_confirmation_ocr": {
            "structured_result": {
                "extracted_fields": {"accident_description": "upstream 사고내용"}
            }
        }
    },
}) == {"accident_description": "직접 전달 사고내용"}
```

and:

```python
assert agent._ocr_evidence({
    "upstream_results": {
        "traffic_accident_confirmation_ocr": {
            "status": "failed",
            "structured_result": {"error_code": "OCRFailure"},
        }
    }
}) is None
```

- [ ] **Step 2: Run mapper tests to verify RED**

Run:

```powershell
python -m pytest test/test_text_ml_case_search_agent.py -q
```

Expected: FAIL because `_ocr_evidence` does not exist and upstream OCR is not mapped.

- [ ] **Step 3: Implement the minimal mapper**

In `ai/agents/text_ml_case_search/agent.py`, add:

```python
OCR_FACT_FIELDS = (
    "accident_datetime",
    "accident_location",
    "accident_cause",
    "accident_description",
)


def _ocr_evidence(agent_input: dict[str, Any]) -> dict[str, Any] | None:
    context = agent_input.get("context")
    if isinstance(context, dict):
        direct = _dict_or_none(context.get("ocr_evidence"))
        if direct is not None:
            return direct

    upstream = agent_input.get("upstream_results")
    if not isinstance(upstream, dict):
        return None
    result = upstream.get("traffic_accident_confirmation_ocr")
    if not isinstance(result, dict) or result.get("status") == "failed":
        return None
    structured = result.get("structured_result")
    if not isinstance(structured, dict):
        return None
    extracted = structured.get("extracted_fields")
    if not isinstance(extracted, dict):
        return None

    mapped = {
        key: extracted[key]
        for key in OCR_FACT_FIELDS
        if _text(extracted.get(key))
    }
    accident_type = extracted.get("accident_type")
    if isinstance(accident_type, dict):
        accident_type = accident_type.get("value")
    if _text(accident_type):
        mapped["accident_type"] = _text(accident_type)
    return mapped or None
```

Replace the ETL input assignment with:

```python
"ocr_evidence": _ocr_evidence(agent_input),
```

- [ ] **Step 4: Add and verify OCR-only query fallback**

Add a failing test:

```python
def test_case_query_uses_ocr_description_when_user_query_is_absent() -> None:
    from ai.agents.text_ml_case_search import agent

    payload = {
        "upstream_results": {
            "traffic_accident_confirmation_ocr": {
                "status": "partial",
                "structured_result": {
                    "extracted_fields": {
                        "accident_description": "회전교차로 1차로 출차 차량과 2차로 진행 차량 충돌",
                        "accident_cause": "진로변경",
                    }
                },
            }
        }
    }

    query = agent._case_query(payload)
    assert "회전교차로 1차로 출차 차량과 2차로 진행 차량 충돌" in query
    assert "진로변경" in query
```

Run the single test and confirm it fails because `_case_query` ignores upstream traffic OCR. Then append the non-empty values returned by `_ocr_evidence(agent_input)` to `_case_query` in this order:

```python
for key in (
    "accident_description",
    "accident_cause",
    "accident_type",
    "accident_location",
    "accident_datetime",
):
    _append_text(parts, ocr_evidence.get(key))
```

- [ ] **Step 5: Run adapter tests to verify GREEN**

Run:

```powershell
python -m pytest test/test_text_ml_case_search_agent.py -q
```

Expected: all tests PASS.

### Task 2: Execute optional OCR before fault RAG in accident plans

**Files:**
- Modify: `app/config/supervisor_routing_policy.v1.json`
- Test: `test/test_chat_orchestration_service.py`
- Test: `test/test_traffic_accident_ocr_runtime.py`

**Interfaces:**
- Consumes: static plan node lists read by `plan_node_codes`
- Produces: ordered plans where OCR precedes `text_ml_case_search` and the latter depends on the OCR execution step

- [ ] **Step 1: Write failing route behavior tests**

For `routing_intent_override="traffic_accident_confirmation_ocr"`, assert:

```python
assert [step["node_code"] for step in response["analysis_plan"]["steps"]] == [
    "input_context_validation",
    "traffic_accident_confirmation_ocr",
    "text_ml_case_search",
    "agent_result_validation",
    "final_response_merge",
]
```

For `routing_intent_override="accident_evidence_analysis"`, assert OCR is immediately before `text_ml_case_search`.

For `routing_intent_override="accident_photo_evidence_analysis"`, assert OCR is immediately before `text_ml_case_search`.

- [ ] **Step 2: Run route tests to verify RED**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py test/test_traffic_accident_ocr_runtime.py -q
```

Expected: FAIL because the current plans do not include both nodes in the required order.

- [ ] **Step 3: Make the minimal policy change**

Update the three plan arrays to contain:

```json
"accident_evidence_analysis": [
  "input_context_validation",
  "vision_media_analysis",
  "traffic_accident_confirmation_ocr",
  "text_ml_case_search",
  "law_ground_search",
  "agent_result_validation",
  "final_response_merge"
]
```

```json
"accident_photo_evidence_analysis": [
  "input_context_validation",
  "traffic_accident_confirmation_ocr",
  "text_ml_case_search",
  "law_ground_search",
  "agent_result_validation",
  "final_response_merge"
]
```

```json
"traffic_accident_confirmation_ocr": [
  "input_context_validation",
  "traffic_accident_confirmation_ocr",
  "text_ml_case_search",
  "agent_result_validation",
  "final_response_merge"
]
```

The runtime admits a dependent step after the preceding node has produced an envelope; it does not require the preceding node's result status to be `success`. Therefore OCR `partial` and `failed` results do not block `text_ml_case_search`.

- [ ] **Step 4: Run route tests to verify GREEN**

Run:

```powershell
python -m pytest test/test_chat_orchestration_service.py test/test_traffic_accident_ocr_runtime.py -q
```

Expected: all tests PASS.

### Task 3: Regression verification

**Files:**
- Verify only; no new production files

**Interfaces:**
- Consumes: completed Task 1 and Task 2 changes
- Produces: evidence that OCR is optional, OCR facts enrich fault RAG, and existing contracts remain intact

- [ ] **Step 1: Run focused integration tests**

```powershell
python -m pytest test/test_text_ml_case_search_agent.py test/test_agent_node_service.py test/test_supervisor_plan_execution.py test/test_chat_orchestration_service.py test/test_traffic_accident_ocr_runtime.py -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run ETL fault-ratio tests**

```powershell
python -m pytest etl/fault_cases/src/agents/text_ml_case_search/tests -q
```

Expected: all tests PASS.

- [ ] **Step 3: Inspect the final diff**

```powershell
git diff --check
git diff -- ai/agents/text_ml_case_search/agent.py app/config/supervisor_routing_policy.v1.json test/test_text_ml_case_search_agent.py test/test_chat_orchestration_service.py test/test_traffic_accident_ocr_runtime.py
```

Expected: no whitespace errors and no modifications to unrelated RAG implementations.
