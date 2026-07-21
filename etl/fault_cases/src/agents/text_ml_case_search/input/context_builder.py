from __future__ import annotations

from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.schemas import AgentContext


def build_context(agent_input: dict[str, Any]) -> AgentContext:
    vision_evidence = agent_input.get("vision_evidence")
    if not isinstance(vision_evidence, list):
        vision_evidence = []
    else:
        vision_evidence = [
            _normalize_source_reference_alias(item)
            for item in vision_evidence
            if isinstance(item, dict)
        ]

    required_outputs = agent_input.get("required_outputs")
    if not isinstance(required_outputs, list):
        required_outputs = []

    ocr_evidence = agent_input.get("ocr_evidence")
    if not isinstance(ocr_evidence, dict):
        ocr_evidence = None

    insurer_claim = agent_input.get("insurer_claim")
    if not isinstance(insurer_claim, dict):
        insurer_claim = None
    else:
        insurer_claim = _normalize_source_reference_alias(insurer_claim)

    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_code": agent_input.get("node_code"),
        "query_text": str(agent_input.get("query_text") or "").strip(),
        "raw_user_text": str(agent_input.get("raw_user_text") or "").strip(),
        "vision_evidence": vision_evidence,
        "ocr_evidence": ocr_evidence,
        "insurer_claim": insurer_claim,
        "required_outputs": [str(item) for item in required_outputs],
    }


def _normalize_source_reference_alias(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    if "source_reference" not in normalized and "source_ref" in normalized:
        normalized["source_reference"] = normalized["source_ref"]
    normalized.pop("source_ref", None)
    return normalized
