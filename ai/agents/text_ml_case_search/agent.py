"""RAG-backed adapter for text accident case search.

The full ML service can replace this module later as long as it keeps the
AgentAdapterInput -> AgentAdapterOutput contract stable.
"""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.services.legal_rag_service import search_legal_rag


CASE_SOURCE_TYPE = "review_case"
FALLBACK_CASE_ID = "case_text_ml_heuristic_001"


def run_text_ml_case_search(
    agent_input: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    query_text = _case_query(agent_input)
    node = context.get("node") if isinstance(context.get("node"), dict) else {}

    knowledge_output = _run_fault_ratio_knowledge_agent(
        agent_input=agent_input,
        node=node,
        query_text=query_text,
    )
    if knowledge_output:
        return knowledge_output

    if not query_text:
        return _output(
            agent_input=agent_input,
            node=node,
            status="failed",
            summary="text_ml_case_search needs accident context or query text before case search.",
            structured_result=_structured_result(
                query_text="",
                cases=[],
                retrieval=_empty_retrieval("empty_query"),
                agent_input=agent_input,
                fallback_used=False,
            ),
            evidence=[],
            limitations=["No query_text or accident_context was available for case search."],
        )

    retrieval = search_legal_rag(query_text, top_k=3, source_type=CASE_SOURCE_TYPE)
    cases = _cases_from_retrieval(retrieval)
    fallback_used = False
    status = "success"
    limitations: list[str] = []

    if not cases:
        fallback_used = True
        status = "partial"
        cases = [_heuristic_case(query_text)]
        limitations.append(
            "No review_case RAG chunks were available; returned a heuristic case candidate."
        )

    structured_result = _structured_result(
        query_text=query_text,
        cases=cases,
        retrieval=retrieval,
        agent_input=agent_input,
        fallback_used=fallback_used,
    )
    evidence = _evidence_from_cases(cases, retrieval)

    return _output(
        agent_input=agent_input,
        node=node,
        status=status,
        summary=_summary(cases, fallback_used),
        structured_result=structured_result,
        evidence=evidence,
        limitations=limitations
        + [
            "This adapter does not assert a fixed numeric fault ratio.",
            "Similar cases are supporting references and require factual/legal review.",
        ],
    )


def _output(
    *,
    agent_input: dict[str, Any],
    node: dict[str, Any],
    status: str,
    summary: str,
    structured_result: dict[str, Any],
    evidence: list[dict[str, Any]],
    limitations: list[str],
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": node.get("node_name") or "Text ML case search",
        "node_code": "text_ml_case_search",
        "node_type": node.get("node_type") or "agent",
        "owner": node.get("owner") or "leejaegang27",
        "status": status,
        "summary": summary,
        "structured_result": structured_result,
        "evidence": evidence,
        "next_actions": next_actions
        or [
            "show_similar_case_candidates",
            "request_blackbox_scene_photo_or_insurance_record",
        ],
        "limitations": limitations,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _run_fault_ratio_knowledge_agent(
    *,
    agent_input: dict[str, Any],
    node: dict[str, Any],
    query_text: str,
) -> dict[str, Any] | None:
    try:
        from etl.fault_cases.src.agents.text_ml_case_search.agent import (
            run_text_ml_case_search as run_fault_ratio_agent,
        )
    except Exception:
        return None

    etl_input = _etl_agent_input(agent_input, query_text)
    if not etl_input["query_text"]:
        return None

    es_client, adapter_notes = _optional_elasticsearch_client()
    try:
        raw_output = (
            run_fault_ratio_agent(etl_input, es_client=es_client)
            if es_client is not None
            else run_fault_ratio_agent(etl_input)
        )
    except Exception as exc:
        raw_output = None
        adapter_notes.append(
            f"fault_ratio_knowledge_agent_error:{exc.__class__.__name__}"
        )

    if not isinstance(raw_output, dict):
        return None

    structured_result = _knowledge_structured_result(raw_output, query_text)
    evidence = _knowledge_evidence(raw_output)
    limitations = [
        str(item)
        for item in raw_output.get("limitations", []) + adapter_notes
        if str(item)
    ]
    return _output(
        agent_input=agent_input,
        node=node,
        status=_knowledge_status(raw_output.get("status")),
        summary=_knowledge_summary(raw_output, evidence=evidence),
        structured_result=structured_result,
        evidence=evidence,
        next_actions=[
            str(item)
            for item in raw_output.get("next_actions", [])
            if str(item)
        ]
        or [
            "show_similar_case_candidates",
            "request_blackbox_scene_photo_or_insurance_record",
        ],
        limitations=limitations
        or [
            "The fault-ratio knowledge agent returned without additional limitations."
        ],
    )


def _etl_agent_input(agent_input: dict[str, Any], query_text: str) -> dict[str, Any]:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    return {
        "session_id": agent_input.get("session_id") or "unknown_session",
        "message_id": agent_input.get("message_id") or "unknown_message",
        "job_id": agent_input.get("job_id") or "unknown_job",
        "node_code": "text_ml_case_search",
        "query_text": query_text,
        "raw_user_text": _text(context.get("raw_user_text")) or _text(agent_input.get("user_text")),
        "vision_evidence": _vision_evidence(agent_input),
        "ocr_evidence": _dict_or_none(context.get("ocr_evidence")),
        "insurer_claim": _insurer_claim(agent_input),
        "required_outputs": agent_input.get("required_inputs")
        or [
            "normalized_description",
            "issue_tags",
            "similar_cases",
            "evidence",
            "ratio_range_label",
            "recommended_evidence",
        ],
    }


def _optional_elasticsearch_client() -> tuple[Any | None, list[str]]:
    if not _truthy(os.getenv("TEXT_ML_CASE_SEARCH_SYNC_USE_ES", "")):
        return None, [
            "TEXT_ML_CASE_SEARCH_SYNC_USE_ES is not enabled; ran fault-ratio agent without Elasticsearch RAG."
        ]

    try:
        from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import (
            get_elasticsearch_client,
            ping_elasticsearch,
        )

        client = get_elasticsearch_client()
        if not ping_elasticsearch(client):
            return None, [
                "Elasticsearch ping failed; ran fault-ratio agent without Elasticsearch RAG."
            ]
        return client, ["Elasticsearch RAG was enabled for text_ml_case_search."]
    except Exception as exc:
        return None, [
            f"Elasticsearch RAG unavailable for text_ml_case_search:{exc.__class__.__name__}"
        ]


def _knowledge_structured_result(
    raw_output: dict[str, Any],
    query_text: str,
) -> dict[str, Any]:
    structured = deepcopy(raw_output.get("structured_result") or {})
    similar_cases = structured.get("similar_cases")
    if not isinstance(similar_cases, list):
        similar_cases = []
    structured["similar_cases"] = [_case_with_source_ref(item) for item in similar_cases]
    structured["top_cases"] = deepcopy(structured["similar_cases"])
    structured.setdefault("query_text", query_text)
    structured.setdefault("normalized_description", query_text)
    structured.setdefault("ratio_range_label", "")
    structured.setdefault("recommended_evidence", [])
    structured.setdefault("evidence_tags", [])
    structured["reliability_score"] = _knowledge_reliability_score(
        structured,
        raw_output.get("evidence"),
    )
    structured.setdefault("retrieval", {})
    if isinstance(structured["retrieval"], dict):
        structured["retrieval"].setdefault("adapter_source", "fault_ratio_knowledge_agent")
        structured["retrieval"].setdefault(
            "source_summary",
            structured.get("source_summary") if isinstance(structured.get("source_summary"), dict) else {},
        )
    limitations = structured.get("limitations")
    structured["limitations"] = limitations if isinstance(limitations, list) else []
    return structured


def _case_with_source_ref(value: Any) -> dict[str, Any]:
    case = deepcopy(value) if isinstance(value, dict) else {}
    source_reference = case.get("source_reference") or case.get("source_ref") or case.get("chunk_id")
    if source_reference:
        case.setdefault("source_reference", source_reference)
        case.setdefault("source_ref", source_reference)
    if "reliability_score" not in case and "score" in case:
        case["reliability_score"] = _case_score(case.get("score"))
    return case


def _knowledge_evidence(raw_output: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = raw_output.get("evidence")
    if not isinstance(evidence, list):
        return []
    return [deepcopy(item) for item in evidence if isinstance(item, dict)]


def _knowledge_reliability_score(
    structured_result: dict[str, Any],
    evidence: Any,
) -> float | None:
    raw_score = structured_result.get("reliability_score")
    if isinstance(raw_score, (int, float)):
        return round(float(raw_score), 4)

    scores = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        score = item.get("confidence") or item.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _knowledge_status(status: Any) -> str:
    value = str(status or "partial")
    return value if value in {"success", "partial", "failed"} else "partial"


def _knowledge_summary(
    raw_output: dict[str, Any],
    *,
    evidence: list[dict[str, Any]],
) -> str:
    status = _knowledge_status(raw_output.get("status"))
    if status == "success":
        return f"Fault-ratio knowledge agent returned {len(evidence)} evidence item(s)."
    if status == "failed":
        missing_fields = raw_output.get("missing_fields") or []
        return f"Fault-ratio knowledge agent failed; missing fields: {', '.join(missing_fields) or 'unknown'}."
    return "Fault-ratio knowledge agent prepared issue tags and evidence recommendations without live RAG evidence."


def _structured_result(
    *,
    query_text: str,
    cases: list[dict[str, Any]],
    retrieval: dict[str, Any],
    agent_input: dict[str, Any],
    fallback_used: bool,
) -> dict[str, Any]:
    evidence_tags = _evidence_tags(agent_input, query_text)
    return {
        "normalized_description": query_text,
        "query_text": query_text,
        "accident_type_candidates": _accident_type_candidates(query_text),
        "issue_tags": _issue_tags(query_text),
        "evidence_tags": evidence_tags,
        "similar_cases": deepcopy(cases),
        "top_cases": deepcopy(cases),
        "reliability_score": _reliability_score(cases),
        "ratio_range_label": "Fault ratio is not fixed; review issues and evidence first.",
        "recommended_evidence": _recommended_evidence(evidence_tags),
        "retrieval": _retrieval_metadata(retrieval, fallback_used=fallback_used),
        "limitations": [
            "Fault ratio is not finalized by this result.",
            "Case similarity is advisory until source facts are reviewed.",
        ],
    }


def _case_query(agent_input: dict[str, Any]) -> str:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    slot_state = (
        agent_input.get("slot_state") if isinstance(agent_input.get("slot_state"), dict) else {}
    )
    upstream_results = (
        agent_input.get("upstream_results")
        if isinstance(agent_input.get("upstream_results"), dict)
        else {}
    )

    parts: list[str] = []
    _append_text(parts, agent_input.get("user_text"))
    for key in (
        "query_text",
        "accident_context",
        "road_context",
        "movement_context",
        "raw_user_text",
        "conversation_summary",
    ):
        _append_text(parts, context.get(key))

    supervisor_handoff = context.get("supervisor_handoff")
    if isinstance(supervisor_handoff, dict):
        for package in supervisor_handoff.get("agent_input_packages") or []:
            if not isinstance(package, dict) or package.get("node_code") != "text_ml_case_search":
                continue
            payload = package.get("payload") if isinstance(package.get("payload"), dict) else {}
            for key in ("query_text", "accident_context", "road_context", "movement_context"):
                _append_text(parts, payload.get(key))

    slots = slot_state.get("slots") if isinstance(slot_state.get("slots"), dict) else {}
    for key in ("accident_context", "road_context", "movement_context", "query_text"):
        _append_slot(parts, slots.get(key))

    vision_result = upstream_results.get("vision_media_analysis")
    if isinstance(vision_result, dict):
        structured = vision_result.get("structured_result")
        if isinstance(structured, dict):
            for key in ("scene_summary", "observations", "accident_scene_candidates"):
                _append_text(parts, structured.get(key))

    return " ".join(_dedupe(parts))[:1200].strip()


def _append_slot(parts: list[str], value: Any) -> None:
    if isinstance(value, dict) and "value" in value:
        _append_text(parts, value.get("value"))
        return
    _append_text(parts, value)


def _append_text(parts: list[str], value: Any) -> None:
    text = _text(value)
    if text:
        parts.append(text)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return " ".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        preferred = [
            "value",
            "text",
            "summary",
            "description",
            "query_text",
            "accident_context",
            "road_context",
            "movement_context",
        ]
        values = [_text(value.get(key)) for key in preferred if key in value]
        return " ".join(item for item in values if item)
    return str(value).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _vision_evidence(agent_input: dict[str, Any]) -> list[dict[str, Any]]:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    direct = context.get("vision_evidence")
    if isinstance(direct, list):
        return [deepcopy(item) for item in direct if isinstance(item, dict)]

    upstream_results = (
        agent_input.get("upstream_results")
        if isinstance(agent_input.get("upstream_results"), dict)
        else {}
    )
    vision_result = upstream_results.get("vision_media_analysis")
    if not isinstance(vision_result, dict):
        return []

    structured = vision_result.get("structured_result")
    if not isinstance(structured, dict):
        return []

    evidence = []
    for key in ("observations", "key_frames", "detected_objects", "accident_scene_candidates"):
        value = structured.get(key)
        if isinstance(value, list):
            evidence.extend(
                {"source_reference": f"vision_media_analysis.{key}", "description": _text(item)}
                for item in value
                if _text(item)
            )
        elif _text(value):
            evidence.append(
                {"source_reference": f"vision_media_analysis.{key}", "description": _text(value)}
            )
    if _text(structured.get("scene_summary")):
        evidence.append(
            {
                "source_reference": "vision_media_analysis.scene_summary",
                "description": _text(structured.get("scene_summary")),
            }
        )
    return evidence


def _insurer_claim(agent_input: dict[str, Any]) -> dict[str, Any] | None:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    claim = _dict_or_none(context.get("insurer_claim"))
    if claim:
        return claim

    slot_state = (
        agent_input.get("slot_state") if isinstance(agent_input.get("slot_state"), dict) else {}
    )
    slots = slot_state.get("slots") if isinstance(slot_state.get("slots"), dict) else {}
    claim_slot = slots.get("insurer_claim") or slots.get("claimed_ratio")
    if isinstance(claim_slot, dict):
        claim_text = claim_slot.get("value") or claim_slot.get("text")
    else:
        claim_text = claim_slot
    if not _text(claim_text):
        return None
    return {
        "claimed_ratio": _text(claim_text),
        "reason_text": _text(slots.get("insurer_claim_reason")),
        "source_type": "slot_state",
        "source_text": _text(claim_text),
    }


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return deepcopy(value) if isinstance(value, dict) else None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _cases_from_retrieval(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    for index, item in enumerate(retrieval.get("results") or [], start=1):
        if not isinstance(item, dict):
            continue
        source_ref = _text(item.get("source_reference")) or f"review_case_{index:03d}"
        cases.append(
            {
                "case_id": source_ref,
                "title": _text(item.get("title"))
                or _text(item.get("source_name"))
                or f"Similar accident case {index}",
                "summary": _text(item.get("summary"))
                or "Retrieved case chunk requires source review.",
                "reliability_score": _case_score(item.get("score")),
                "source_type": _text(item.get("source_type")) or CASE_SOURCE_TYPE,
                "source_ref": source_ref,
            }
        )
    return cases


def _heuristic_case(query_text: str) -> dict[str, Any]:
    return {
        "case_id": FALLBACK_CASE_ID,
        "title": "Heuristic intersection/contact accident candidate",
        "summary": (
            "Use this as a placeholder candidate until review_case RAG data or the "
            "dedicated text ML agent is available."
        ),
        "reliability_score": 0.42 if query_text else 0.0,
        "source_type": CASE_SOURCE_TYPE,
        "source_ref": FALLBACK_CASE_ID,
    }


def _case_score(raw_score: Any) -> float:
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return 0.5
    if score > 1:
        score = score / 10
    return round(min(0.95, max(0.1, score)), 4)


def _reliability_score(cases: list[dict[str, Any]]) -> float:
    scores = [
        float(case.get("reliability_score"))
        for case in cases
        if isinstance(case.get("reliability_score"), (int, float))
    ]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def _issue_tags(query_text: str) -> list[str]:
    lowered = query_text.lower()
    tags = []
    keyword_tags = [
        (
            ("intersection", "signal", "crossroad", "\uad50\ucc28\ub85c", "\uc2e0\ud638"),
            "intersection_signal",
        ),
        (
            ("lane", "merge", "change", "\ucc28\uc120", "\uc9c4\uc785", "\ud569\ub958"),
            "lane_or_merge",
        ),
        (
            ("rear", "stop", "sudden", "\ucd94\ub3cc", "\uae09\uc815\uac70", "\uc815\ucc28"),
            "sudden_stop_or_rear_end",
        ),
        (
            (
                "pedestrian",
                "crosswalk",
                "school zone",
                "\ubcf4\ud589\uc790",
                "\ud6a1\ub2e8\ubcf4\ub3c4",
                "\uc5b4\ub9b0\uc774\ubcf4\ud638\uad6c\uc5ed",
            ),
            "pedestrian_or_school_zone",
        ),
        (
            ("accident", "collision", "contact", "\uc0ac\uace0", "\ucda9\ub3cc", "\uc811\ucd09"),
            "contact_or_collision",
        ),
    ]
    for keywords, tag in keyword_tags:
        if any(keyword in lowered for keyword in keywords):
            tags.append(tag)
    return tags or ["fault_ratio_review"]


def _accident_type_candidates(query_text: str) -> list[str]:
    lowered = query_text.lower()
    if any(keyword in lowered for keyword in ("lane", "merge", "change", "\ucc28\uc120", "\ud569\ub958")):
        return ["lane_change_contact", "merge_collision"]
    if any(keyword in lowered for keyword in ("rear", "stop", "sudden", "\ucd94\ub3cc", "\uae09\uc815\uac70")):
        return ["rear_end_collision", "sudden_stop_dispute"]
    if any(
        keyword in lowered
        for keyword in (
            "pedestrian",
            "crosswalk",
            "school zone",
            "\ubcf4\ud589\uc790",
            "\ud6a1\ub2e8\ubcf4\ub3c4",
            "\uc5b4\ub9b0\uc774\ubcf4\ud638\uad6c\uc5ed",
        )
    ):
        return ["pedestrian_crossing", "school_zone_incident"]
    return ["intersection_contact", "side_entry_collision"]


def _evidence_tags(agent_input: dict[str, Any], query_text: str) -> list[str]:
    tags = []
    lowered = query_text.lower()
    if any(keyword in lowered for keyword in ("blackbox", "dashcam", "video", "\ube14\ub799\ubc15\uc2a4", "\uc601\uc0c1")):
        tags.append("blackbox")
    if any(keyword in lowered for keyword in ("photo", "image", "scene", "\uc0ac\uc9c4", "\ud604\uc7a5")):
        tags.append("scene_photo")
    if "insurance" in lowered or "\ubcf4\ud5d8" in lowered:
        tags.append("insurance_record")

    for attachment in agent_input.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        purpose = _text(attachment.get("purpose")).lower()
        content_type = _text(attachment.get("content_type") or attachment.get("mime_type")).lower()
        if any(keyword in purpose for keyword in ("blackbox", "dashcam", "video")) or content_type.startswith("video/"):
            tags.append("blackbox")
        if "photo" in purpose or content_type.startswith("image/"):
            tags.append("scene_photo")
        if "insurance" in purpose:
            tags.append("insurance_record")

    return _dedupe(tags) or ["blackbox", "scene_photo", "insurance_record"]


def _recommended_evidence(evidence_tags: list[str]) -> list[str]:
    label_by_tag = {
        "blackbox": "original blackbox or dashcam video",
        "scene_photo": "scene photos including lane, signal, and impact position",
        "insurance_record": "insurance claim or accident reception record",
    }
    return [label_by_tag[tag] for tag in evidence_tags if tag in label_by_tag]


def _evidence_from_cases(
    cases: list[dict[str, Any]],
    retrieval: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "source_type": case.get("source_type") or CASE_SOURCE_TYPE,
            "title": case.get("title") or "Similar case candidate",
            "source_reference": case.get("source_ref") or case.get("case_id"),
            "metadata": {
                "case_id": case.get("case_id"),
                "retrieval_backend": retrieval.get("backend"),
                "retrieval_status": retrieval.get("status"),
            },
            "confidence": case.get("reliability_score"),
        }
        for case in cases
    ]


def _retrieval_metadata(retrieval: dict[str, Any], *, fallback_used: bool) -> dict[str, Any]:
    metadata = {
        key: retrieval.get(key)
        for key in (
            "contract_version",
            "status",
            "backend",
            "query",
            "top_k",
            "result_count",
            "latency_ms",
            "error_code",
            "fallback_from",
            "attempted_backends",
            "embedding",
            "sql_tables",
        )
        if key in retrieval
    }
    metadata["source_type"] = CASE_SOURCE_TYPE
    metadata["fallback_used"] = fallback_used
    return metadata


def _empty_retrieval(status: str) -> dict[str, Any]:
    return {
        "contract_version": "legal_rag_search.v1",
        "status": status,
        "backend": "none",
        "query": "",
        "top_k": 0,
        "result_count": 0,
        "latency_ms": 0,
        "results": [],
        "error_code": status,
    }


def _summary(cases: list[dict[str, Any]], fallback_used: bool) -> str:
    if fallback_used:
        return "Prepared a heuristic similar-case candidate while RAG case data is unavailable."
    return f"Retrieved {len(cases)} similar case candidate(s) for the accident context."
