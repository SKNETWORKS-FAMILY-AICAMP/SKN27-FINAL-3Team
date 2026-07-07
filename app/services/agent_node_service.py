"""Mock Agent/Node registry and execution envelopes for integration tests."""

from __future__ import annotations

import base64
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.agent_adapter_contract import (
    build_adapter_context,
    build_agent_adapter_input,
    build_agent_adapter_contract,
)
from app.services.attachment_mock_service import resolve_attachment_references
from app.services.legal_rag_service import search_legal_rag

try:
    from chatbot.object_storage import read_object_bytes, storage_reference_from_uri
except Exception:  # pragma: no cover - keeps CLI-only mock service imports decoupled from Django.
    read_object_bytes = None
    storage_reference_from_uri = None


NODE_REGISTRY: dict[str, dict[str, Any]] = {
    "input_context_validation": {
        "order": 10,
        "node_name": "입력 컨텍스트 검증 노드",
        "node_code": "input_context_validation",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "description": "사용자 명령문, 첨부 목적, 입력 modality를 정리하고 필수 입력 누락을 확인한다.",
        "required_inputs": ["user_text|attachments"],
        "produces": ["input_summary", "routing_hints", "missing_fields"],
        "handoff_to": ["fine_notice_analysis", "text_ml_case_search", "vision_media_analysis"],
        "status": "mock_ready",
    },
    "fine_notice_analysis": {
        "order": 20,
        "node_name": "고지서 OCR·과태료/범칙금 분석 노드",
        "node_code": "fine_notice_analysis",
        "node_type": "agent",
        "owner": "workzion2",
        "description": "고지서 이미지나 설명에서 위반 내용, 관할 기관, 의견제출 기한 후보를 추출한다.",
        "required_inputs": ["attachments[purpose=fine_notice]|user_text"],
        "produces": ["fine_notice_analysis", "notice_fields", "required_documents"],
        "handoff_to": ["law_ground_search", "objection_report_generation"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["mock", "sync"],
    },
    "law_ground_search": {
        "order": 30,
        "node_name": "법률 근거 검색 노드",
        "node_code": "law_ground_search",
        "node_type": "agent",
        "owner": "techshin31",
        "description": "법령, 시행령, 규칙, 판례 근거 후보를 검색해 Supervisor 병합용 근거를 만든다.",
        "required_inputs": ["law_code|violation_text|search_query"],
        "produces": ["matched_laws", "source_ref", "applicability_limit"],
        "handoff_to": ["agent_result_validation", "objection_report_generation"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["mock", "sync"],
    },
    "text_ml_case_search": {
        "order": 40,
        "node_name": "텍스트 ML/판례·사례 검색 노드",
        "node_code": "text_ml_case_search",
        "node_type": "agent",
        "owner": "leejaegang27",
        "description": "사고 설명을 정규화하고 유사 사고 유형, 쟁점 태그, 사례 후보를 반환한다.",
        "required_inputs": ["query_text|accident_context"],
        "produces": ["accident_type_candidates", "similar_cases", "reliability_score"],
        "handoff_to": ["law_ground_search", "agent_result_validation"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["mock", "sync"],
    },
    "vision_media_analysis": {
        "order": 50,
        "node_name": "영상·이미지 분석 노드",
        "node_code": "vision_media_analysis",
        "node_type": "agent",
        "owner": "ohjuheecode",
        "description": "사진/영상에서 사고 장면 후보, 객체, 품질 이슈를 추출해 텍스트 분석 노드에 넘긴다.",
        "required_inputs": ["attachments[purpose=accident_scene|evidence]"],
        "produces": ["key_frames", "scene_summary", "quality_issues"],
        "handoff_to": ["text_ml_case_search", "agent_result_validation"],
        "status": "mock_contract_only",
        "adapter_modes": ["mock"],
    },
    "objection_report_generation": {
        "order": 60,
        "node_name": "이의신청서 생성/리포트 노드",
        "node_code": "objection_report_generation",
        "node_type": "agent",
        "owner": "hi20260204-maker",
        "description": "고지서 분석, 법률 근거, 사용자 사실관계를 조합해 이의신청서 초안과 리포트 action을 만든다.",
        "required_inputs": ["notice_analysis_result", "law_ground_result", "user_facts"],
        "produces": ["objection_draft", "attachment_list", "report_actions"],
        "handoff_to": ["agent_result_validation", "final_response_merge"],
        "status": "mock_contract_only",
        "adapter_modes": ["mock"],
    },
    "agent_result_validation": {
        "order": 70,
        "node_name": "Agent 결과 최종 검증 노드",
        "node_code": "agent_result_validation",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "description": "Agent 결과 envelope, evidence, limitations를 검증하고 최종 병합 가능 여부를 표시한다.",
        "required_inputs": ["agent_results"],
        "produces": ["validation_summary", "rejected_results", "merge_ready"],
        "handoff_to": ["final_response_merge", "missing_input_question"],
        "status": "mock_ready",
    },
}


def list_agent_nodes() -> list[dict[str, Any]]:
    """Return the current Agent/Node registry in execution-friendly order."""

    return [
        _node_with_adapter_contract(NODE_REGISTRY[node_code])
        for node_code in sorted(NODE_REGISTRY, key=lambda code: NODE_REGISTRY[code]["order"])
    ]


def get_agent_node(node_code: str) -> dict[str, Any]:
    return _node_with_adapter_contract(NODE_REGISTRY.get(node_code, _unknown_node(node_code)))


def execute_mock_node(payload: dict[str, Any]) -> dict[str, Any]:
    payload = resolve_attachment_references(payload)
    node_code = _payload_node_code(payload)
    execution_status = str(payload.get("execution_status") or payload.get("mock_status") or "success")
    result_status = _normalize_result_status(execution_status)
    node = get_agent_node(node_code)
    agent_input = _agent_input(payload, node)
    execution_id = f"exec_{uuid4().hex[:12]}"
    execution_mode = _requested_execution_mode(payload)
    adapter_context = build_adapter_context(
        execution_id=execution_id,
        execution_mode=execution_mode if _should_use_sync_adapter(node_code, execution_mode) else "mock",
        node=node,
        plan_step=payload.get("plan_step"),
    )

    if _should_use_sync_adapter(node_code, execution_mode):
        return _execute_sync_node(
            payload=payload,
            node=node,
            agent_input=agent_input,
            adapter_context=adapter_context,
            execution_id=execution_id,
        )

    return {
        "execution_id": execution_id,
        "execution_mode": "mock",
        "job_id": payload.get("job_id"),
        "node_code": node_code,
        "node": node,
        "adapter_context": adapter_context,
        "agent_input": agent_input,
        "agent_output": build_agent_output(
            node_code=node_code,
            payload=payload,
            result_status=result_status,
            execution_status=execution_status,
        ),
        "created_at": _now_iso(),
    }


def execute_mock_plan(analysis_plan: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    payload = resolve_attachment_references(payload)
    executions = []
    upstream_results = deepcopy(payload.get("upstream_results", {}))
    for step in analysis_plan.get("steps", []):
        step_payload = deepcopy(payload)
        step_payload.update(
            {
                "analysis_plan_id": analysis_plan.get("plan_id"),
                "session_id": analysis_plan.get("session_id") or payload.get("session_id"),
                "message_id": analysis_plan.get("message_id") or payload.get("message_id"),
                "node_code": step.get("node_code"),
                "execution_status": step.get("status", "success"),
                "execution_mode": step.get("execution_mode") or payload.get("execution_mode"),
                "adapter_mode": step.get("adapter_mode") or payload.get("adapter_mode"),
                "required_inputs": step.get("required_inputs", []),
                "depends_on": step.get("depends_on", []),
                "plan_step": step,
                "upstream_results": deepcopy(upstream_results),
            }
        )
        if isinstance(step.get("context"), dict):
            step_context = deepcopy(payload.get("context") if isinstance(payload.get("context"), dict) else {})
            step_context.update(deepcopy(step["context"]))
            step_payload["context"] = step_context
        execution = execute_mock_node(step_payload)
        execution["plan_step"] = deepcopy(step)
        executions.append(execution)
        upstream_results[execution["node_code"]] = deepcopy(execution["agent_output"])

    return {
        "execution_mode": _plan_execution_mode(executions),
        "job_id": payload.get("job_id"),
        "plan_id": analysis_plan.get("plan_id"),
        "session_id": analysis_plan.get("session_id") or payload.get("session_id"),
        "message_id": analysis_plan.get("message_id") or payload.get("message_id"),
        "executions": executions,
        "status_counts": _status_counts(executions),
        "completed_node_codes": [
            item["node_code"]
            for item in executions
            if item["agent_output"]["status"] == "success"
        ],
        "limitations": [
            "중간발표용 mock 실행 결과이며 실제 LangGraph, RAG, OCR, ML, LLM 호출 결과가 아닙니다."
        ],
        "created_at": _now_iso(),
    }


def build_agent_output(
    *,
    node_code: str,
    payload: dict[str, Any],
    result_status: str,
    execution_status: str,
) -> dict[str, Any]:
    node = get_agent_node(node_code)
    return {
        "session_id": payload.get("session_id"),
        "message_id": payload.get("message_id"),
        "job_id": payload.get("job_id"),
        "node_name": node["node_name"],
        "node_code": node["node_code"],
        "node_type": node["node_type"],
        "owner": node["owner"],
        "status": result_status,
        "execution_status": execution_status,
        "summary": _summary_for_node(node_code, result_status),
        "structured_result": _structured_result_for_node(node_code, payload, result_status),
        "evidence": _evidence_for_node(node_code, result_status),
        "next_actions": _next_actions_for_node(node_code, result_status),
        "limitations": _limitations_for_node(node_code, result_status, execution_status),
        "created_at": _now_iso(),
    }


def _payload_node_code(payload: dict[str, Any]) -> str:
    agent_input = payload.get("agent_input")
    if isinstance(agent_input, dict) and agent_input.get("node_code"):
        return str(agent_input["node_code"])
    return str(payload.get("node_code") or "unknown_node")


def _agent_input(payload: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    nested_agent_input = payload.get("agent_input") if isinstance(payload.get("agent_input"), dict) else {}
    return build_agent_adapter_input(
        analysis_plan_id=payload.get("analysis_plan_id"),
        job_id=payload.get("job_id"),
        session_id=payload.get("session_id"),
        message_id=payload.get("message_id"),
        node=node,
        user_text=payload.get("user_text"),
        attachments=payload.get("attachments", []),
        context=_agent_context(payload, node),
        slot_state=payload.get("slot_state") or nested_agent_input.get("slot_state") or {},
        required_inputs=payload.get("required_inputs") or node["required_inputs"],
        depends_on=payload.get("depends_on", []),
        upstream_results=payload.get("upstream_results", {}),
    )


def _agent_context(payload: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    context = deepcopy(payload.get("context") if isinstance(payload.get("context"), dict) else {})
    if node.get("node_code") != "law_ground_search":
        return context

    query_context = context.get("query") if isinstance(context.get("query"), dict) else {}
    if query_context.get("raw_text") or query_context.get("search_query"):
        return context

    query = _law_ground_query(payload)
    if query:
        context["query"] = {
            "raw_text": query,
            "search_query": query,
        }
    return context


def _node_with_adapter_contract(node: dict[str, Any]) -> dict[str, Any]:
    node_copy = deepcopy(node)
    node_copy["adapter_contract"] = build_agent_adapter_contract(node_copy)
    return node_copy


def _requested_execution_mode(payload: dict[str, Any]) -> str:
    requested = str(payload.get("execution_mode") or payload.get("adapter_mode") or "").strip().lower()
    if requested in {"sync", "real", "live", "agent"}:
        return "sync"
    return "mock"


def _should_use_sync_adapter(node_code: str, execution_mode: str) -> bool:
    return execution_mode == "sync" and node_code in {
        "fine_notice_analysis",
        "law_ground_search",
        "text_ml_case_search",
    }


def _execute_sync_node(
    *,
    payload: dict[str, Any],
    node: dict[str, Any],
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
    execution_id: str,
) -> dict[str, Any]:
    try:
        agent_output = _run_sync_adapter(agent_input, adapter_context)
        adapter_error = None
    except Exception as exc:  # pragma: no cover - defensive production boundary.
        agent_output = _adapter_error_output(
            node=node,
            agent_input=agent_input,
            exc=exc,
        )
        adapter_error = {
            "error_code": exc.__class__.__name__,
            "message": str(exc),
        }

    result = {
        "execution_id": execution_id,
        "execution_mode": "sync",
        "job_id": payload.get("job_id"),
        "node_code": node["node_code"],
        "node": node,
        "adapter_context": adapter_context,
        "agent_input": agent_input,
        "agent_output": agent_output,
        "created_at": _now_iso(),
    }
    if adapter_error:
        result["adapter_error"] = adapter_error
    return result


def _run_sync_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    node_code = str(agent_input.get("node_code") or "")
    if node_code == "fine_notice_analysis":
        return _run_fine_notice_analysis_adapter(agent_input, adapter_context)
    if node_code == "law_ground_search":
        return _run_law_ground_search_adapter(agent_input, adapter_context)
    if node_code == "text_ml_case_search":
        return _run_text_ml_case_search_adapter(agent_input, adapter_context)
    raise RuntimeError(f"sync_adapter_unregistered:{node_code}")


def _run_fine_notice_analysis_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    from ai.agents.fine_notice_analysis.graph import graph

    state = _fine_notice_state(agent_input)
    result = graph.invoke(state)
    raw_output = (
        result.get("agent_results", {}).get("fine_notice_analysis")
        if isinstance(result, dict)
        else None
    )
    if not isinstance(raw_output, dict):
        raw_output = {
            "status": _normalize_result_status(str(result.get("ocr_status") or "partial")),
            "summary": "fine_notice_analysis returned without an agent_results envelope.",
            "structured_result": _fine_notice_structured_result(result if isinstance(result, dict) else {}),
            "evidence": [],
            "next_actions": ["check_fine_notice_agent_output"],
            "limitations": ["The real fine_notice_analysis graph did not return a complete envelope."],
        }
    return _complete_adapter_output(
        raw_output,
        node=adapter_context["node"],
        agent_input=agent_input,
        adapter_trace={
            "adapter": "ai.agents.fine_notice_analysis.graph",
            "execution_mode": "sync",
            "source_status": raw_output.get("status"),
            "input_source": state.get("_input_source"),
        },
    )


def _run_law_ground_search_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    from ai.agents.law_ground_search import run_law_ground_search

    raw_output = run_law_ground_search(agent_input, adapter_context)
    if not isinstance(raw_output, dict):
        raw_output = {
            "status": "partial",
            "summary": "law_ground_search returned without an AgentAdapterOutput envelope.",
            "structured_result": {
                "law_provisions": [],
                "matched_laws": [],
            },
            "evidence": [],
            "next_actions": ["check_law_ground_search_agent_output"],
            "limitations": ["The law_ground_search adapter did not return a dictionary."],
        }
    return _complete_adapter_output(
        raw_output,
        node=adapter_context["node"],
        agent_input=agent_input,
        adapter_trace={
            "adapter": "ai.agents.law_ground_search.run_law_ground_search",
            "execution_mode": "sync",
            "source_status": raw_output.get("status"),
            "input_source": "agent_input.context",
        },
    )


def _run_text_ml_case_search_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    from ai.agents.text_ml_case_search import run_text_ml_case_search

    raw_output = run_text_ml_case_search(agent_input, adapter_context)
    if not isinstance(raw_output, dict):
        raw_output = {
            "status": "partial",
            "summary": "text_ml_case_search returned without an AgentAdapterOutput envelope.",
            "structured_result": {
                "similar_cases": [],
                "top_cases": [],
                "reliability_score": 0,
            },
            "evidence": [],
            "next_actions": ["check_text_ml_case_search_agent_output"],
            "limitations": ["The text_ml_case_search adapter did not return a dictionary."],
        }
    return _complete_adapter_output(
        raw_output,
        node=adapter_context["node"],
        agent_input=agent_input,
        adapter_trace={
            "adapter": "ai.agents.text_ml_case_search.run_text_ml_case_search",
            "execution_mode": "sync",
            "source_status": raw_output.get("status"),
            "input_source": "agent_input",
        },
    )


def _fine_notice_state(agent_input: dict[str, Any]) -> dict[str, Any]:
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    notice_image = context.get("notice_image")
    notice_mime_type = context.get("notice_mime_type")
    input_source = "context"

    if not notice_image:
        for attachment in agent_input.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            if attachment.get("purpose") != "fine_notice":
                continue
            notice_image = _attachment_base64(attachment)
            notice_mime_type = attachment.get("content_type") or attachment.get("mime_type")
            input_source = "attachment"
            if notice_image:
                break

    return {
        "notice_image": notice_image,
        "notice_mime_type": notice_mime_type or "image/jpeg",
        "agent_results": {},
        "_input_source": input_source if notice_image else "missing",
    }


def _attachment_base64(attachment: dict[str, Any]) -> str | None:
    for key in ("content_base64", "data_base64", "base64"):
        value = attachment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    storage_uri = str(attachment.get("storage_uri") or "")
    object_storage_bytes = _attachment_object_storage_bytes(attachment, storage_uri)
    if object_storage_bytes is not None:
        return base64.b64encode(object_storage_bytes).decode("ascii")

    if not storage_uri.startswith("mock://uploads/"):
        return None

    relative_path = storage_uri.removeprefix("mock://uploads/")
    file_path = Path(os.environ.get("MOCK_UPLOAD_ROOT", "backend/media/mock_uploads")) / relative_path
    if not file_path.exists() or not file_path.is_file():
        return None
    return base64.b64encode(file_path.read_bytes()).decode("ascii")


def _attachment_object_storage_bytes(attachment: dict[str, Any], storage_uri: str) -> bytes | None:
    if read_object_bytes is None:
        return None
    object_storage = attachment.get("object_storage")
    if isinstance(object_storage, dict) and object_storage.get("storage_uri"):
        return read_object_bytes(object_storage)
    if storage_reference_from_uri is None or not storage_uri.startswith("s3://"):
        return None
    reference = storage_reference_from_uri(
        storage_uri,
        resource_type="uploaded_file",
        resource_id=str(attachment.get("attachment_id") or ""),
        filename=str(attachment.get("filename") or attachment.get("original_filename") or ""),
        content_type=str(attachment.get("content_type") or attachment.get("mime_type") or ""),
        size_bytes=attachment.get("size_bytes"),
    )
    return read_object_bytes(reference)


def _fine_notice_structured_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "ocr_status",
        "ocr_error",
        "fine_type",
        "notice_stage",
        "law_code",
        "violation_text",
        "violation_datetime",
        "violation_location",
        "fine_amount",
        "opinion_deadline",
        "issuing_authority",
        "vehicle_number",
        "missing_fields",
        "format_errors",
    }
    return {key: result.get(key) for key in allowed if key in result}


def _complete_adapter_output(
    raw_output: dict[str, Any],
    *,
    node: dict[str, Any],
    agent_input: dict[str, Any],
    adapter_trace: dict[str, Any],
) -> dict[str, Any]:
    source_status = str(raw_output.get("status") or "partial")
    structured_result = deepcopy(raw_output.get("structured_result") or {})
    structured_result = _normalize_adapter_structured_result(
        structured_result,
        node_code=node["node_code"],
        adapter_trace=adapter_trace,
    )
    structured_result.setdefault("adapter_trace", adapter_trace)
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": raw_output.get("node_name") or node["node_name"],
        "node_code": node["node_code"],
        "node_type": node["node_type"],
        "owner": node["owner"],
        "status": _adapter_result_status(source_status),
        "execution_status": source_status,
        "summary": raw_output.get("summary") or _summary_for_node(node["node_code"], _adapter_result_status(source_status)),
        "structured_result": structured_result,
        "evidence": deepcopy(raw_output.get("evidence") or []),
        "next_actions": deepcopy(raw_output.get("next_actions") or []),
        "limitations": _adapter_limitations(raw_output, adapter_trace),
        "created_at": raw_output.get("created_at") or _now_iso(),
    }


def _adapter_result_status(status: str) -> str:
    if status in {"success", "partial", "failed"}:
        return status
    if status in {"degraded"}:
        return "partial"
    if status in {"rejected", "blocked", "skipped"}:
        return "failed"
    return "partial"


def _adapter_limitations(raw_output: dict[str, Any], adapter_trace: dict[str, Any]) -> list[str]:
    limitations = [str(item) for item in raw_output.get("limitations") or [] if str(item)]
    adapter = str(adapter_trace.get("adapter") or "")
    if "fine_notice_analysis" in adapter:
        marker = "fine_notice_analysis real adapter is connected through Supervisor sync execution mode."
    elif "text_ml_case_search" in adapter:
        marker = "text_ml_case_search sync adapter is connected through the RAG-backed case-search port."
    else:
        marker = "Sync adapter is connected through Supervisor sync execution mode."
    if marker not in limitations:
        limitations.append(marker)
    if "text_ml_case_search" in adapter and not os.getenv("TEXT_ML_CASE_SEARCH_SYNC_USE_ES", "").strip():
        es_marker = "TEXT_ML_CASE_SEARCH_SYNC_USE_ES is not enabled; ran fault-ratio agent without Elasticsearch RAG."
        if es_marker not in limitations:
            limitations.append(es_marker)
    if "fine_notice_analysis" in adapter and adapter_trace.get("input_source") == "missing":
        limitations.append("No fine_notice attachment image was available for OCR.")
    return limitations


def _normalize_adapter_structured_result(
    structured_result: dict[str, Any],
    *,
    node_code: str,
    adapter_trace: dict[str, Any],
) -> dict[str, Any]:
    structured = deepcopy(structured_result) if isinstance(structured_result, dict) else {}
    structured.setdefault("adapter_trace", adapter_trace)
    if node_code == "text_ml_case_search":
        retrieval = structured.get("retrieval") if isinstance(structured.get("retrieval"), dict) else {}
        retrieval.setdefault("adapter_source", "fault_ratio_knowledge_agent")
        retrieval.setdefault("source_type", "review_case")
        structured["retrieval"] = retrieval
        structured.setdefault("similar_cases", [])
        structured.setdefault("top_cases", deepcopy(structured.get("similar_cases") or []))
        structured.setdefault("ratio_range_label", "Fault ratio is not fixed; review issues and evidence first.")
        structured.setdefault("recommended_evidence", [])
    return structured


def _adapter_error_output(
    *,
    node: dict[str, Any],
    agent_input: dict[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    adapter_trace = _adapter_error_trace(node["node_code"], agent_input, exc)
    structured_result = _normalize_adapter_structured_result(
        {
            "error_code": exc.__class__.__name__,
            "error_message": str(exc),
        },
        node_code=node["node_code"],
        adapter_trace=adapter_trace,
    )
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": node["node_name"],
        "node_code": node["node_code"],
        "node_type": node["node_type"],
        "owner": node["owner"],
        "status": "failed",
        "execution_status": "adapter_error",
        "summary": f"{node['node_code']} sync adapter failed before returning a usable envelope.",
        "structured_result": structured_result,
        "evidence": [],
        "next_actions": ["fallback_to_mock_or_retry_adapter"],
        "limitations": ["Sync adapter exception was normalized for Supervisor result validation."],
        "created_at": _now_iso(),
    }


def _adapter_error_trace(node_code: str, agent_input: dict[str, Any], exc: Exception) -> dict[str, Any]:
    adapter_by_node = {
        "fine_notice_analysis": "ai.agents.fine_notice_analysis.graph",
        "law_ground_search": "ai.agents.law_ground_search.run_law_ground_search",
        "text_ml_case_search": "ai.agents.text_ml_case_search.run_text_ml_case_search",
    }
    if node_code == "fine_notice_analysis":
        input_source = "attachment" if _has_fine_notice_attachment(agent_input) else "missing"
    elif node_code == "law_ground_search":
        input_source = "agent_input.context"
    else:
        input_source = "agent_input"
    return {
        "adapter": adapter_by_node.get(node_code, f"unregistered:{node_code}"),
        "execution_mode": "sync",
        "source_status": "adapter_error",
        "input_source": input_source,
        "error_code": exc.__class__.__name__,
    }


def _has_fine_notice_attachment(agent_input: dict[str, Any]) -> bool:
    return any(
        isinstance(attachment, dict) and attachment.get("purpose") == "fine_notice"
        for attachment in agent_input.get("attachments") or []
    )


def _plan_execution_mode(executions: list[dict[str, Any]]) -> str:
    modes = {str(execution.get("execution_mode") or "mock") for execution in executions}
    if not modes or modes == {"mock"}:
        return "mock"
    if modes == {"sync"}:
        return "sync"
    return "hybrid"


def _normalize_result_status(status: str) -> str:
    return {
        "success": "success",
        "partial": "partial",
        "pending": "partial",
        "running": "partial",
        "blocked": "partial",
        "failed": "failed",
        "skipped": "failed",
    }.get(str(status), "success")


def _status_counts(executions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"success": 0, "partial": 0, "failed": 0}
    for execution in executions:
        status = execution["agent_output"]["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts


def _summary_for_node(node_code: str, status: str) -> str:
    if status == "failed":
        return "mock 실행에서 필수 입력 또는 선행 결과가 부족한 것으로 처리했습니다."
    if status == "partial":
        return "mock 실행 결과 일부 정보가 부족해 Supervisor 추가 확인이 필요합니다."
    return {
        "input_context_validation": "입력 텍스트와 첨부 목적을 정리하고 라우팅 힌트를 만들었습니다.",
        "fine_notice_analysis": "고지서 정보와 이의신청 선행 입력을 mock 분석했습니다.",
        "law_ground_search": "관련 법령 근거 후보를 mock 검색했습니다.",
        "text_ml_case_search": "사고 설명 기반 쟁점과 유사 사례 후보를 mock 정리했습니다.",
        "vision_media_analysis": "이미지/영상 장면 후보와 품질 이슈를 mock 분석했습니다.",
        "objection_report_generation": "고지서 분석과 법률 근거를 바탕으로 이의신청서 초안 구조를 mock 생성했습니다.",
        "agent_result_validation": "Agent 결과 envelope와 limitations를 mock 검증했습니다.",
    }.get(node_code, "등록되지 않은 노드의 mock 결과입니다.")


def _structured_result_for_node(
    node_code: str,
    payload: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    attachments = payload.get("attachments", [])
    if status == "failed":
        return {"reason": "missing_or_skipped_input", "received_inputs": sorted(payload.keys())}

    if node_code == "input_context_validation":
        return {
            "has_user_text": bool(payload.get("user_text")),
            "attachment_count": len(attachments),
            "modalities": _input_modalities(payload),
            "attachment_purposes": _attachment_purposes(payload),
            "routing_hints": _routing_hints(payload),
            "missing_fields": [] if payload.get("user_text") or attachments else ["user_text|attachments"],
        }

    if node_code == "fine_notice_analysis":
        return {
            "notice_fields": {
                "notice_type": "traffic_fine_notice",
                "agency": "mock agency",
                "payment_deadline": "사용자 고지서 원문 확인 필요",
            },
            "ocr_status": "mock_completed",
            "ocr_confidence": 0.82,
            "missing_fields": [] if status == "success" else ["user_facts"],
            "disposition_stage": "opinion_submission_or_objection_review",
            "required_documents": ["고지서 원본", "이의신청 사유", "관련 증빙"],
        }

    if node_code == "law_ground_search":
        rag_search = search_legal_rag(_law_ground_query(payload), top_k=3)
        if rag_search.get("results"):
            return {
                "matched_laws": [
                    {
                        "law_name": item.get("source_name") or item.get("title"),
                        "article": item.get("article") or item.get("section_ref") or "source_chunk",
                        "summary": item.get("summary"),
                        "source_reference": item.get("source_reference"),
                        "source_url": item.get("source_url"),
                        "effective_date": item.get("effective_date"),
                        "score": item.get("score"),
                    }
                    for item in rag_search["results"]
                ],
                "applicable_conditions": ["RAG 근거는 사용자 사실관계와 처분 문구 확인 후 적용 여부를 판단해야 합니다."],
                "exceptions": [],
                "retrieval_quality": rag_search.get("backend") or "django_rag_tables",
                "retrieval": _retrieval_metadata(rag_search),
            }
        return {
            "matched_laws": [
                {
                    "law_name": "도로교통법",
                    "article": "mock_article",
                    "summary": "실제 조문 조회 전 연결 확인용 mock 근거입니다.",
                }
            ],
            "applicable_conditions": ["고지서 또는 사고 유형 확인 후 적용 가능성 검토"],
            "exceptions": [],
            "retrieval_quality": "mock_only",
            "retrieval": _retrieval_metadata(rag_search),
        }

    if node_code == "text_ml_case_search":
        return {
            "normalized_description": payload.get("user_text") or "mock accident description",
            "accident_type_candidates": ["intersection_no_signal", "side_entry_collision"],
            "issue_tags": ["선진입", "일시정지", "시야 제한"],
            "evidence_tags": ["blackbox", "scene_photo", "insurance_record"],
            "similar_cases": [
                {
                    "case_id": "case_mock_001",
                    "title": "신호 없는 교차로 접촉사고",
                    "reliability_score": 0.78,
                }
            ],
            "reliability_score": 0.71,
        }

    if node_code == "vision_media_analysis":
        return {
            "key_frames": [{"frame_id": "frame_mock_001", "timestamp": "00:00:03"}],
            "scene_summary": "차량 접근 방향과 교차로 상황 후보를 mock 감지했습니다.",
            "detected_objects": ["vehicle", "road", "lane"],
            "accident_scene_candidates": ["intersection_contact"],
            "confidence_label": "mock_medium",
            "quality_issues": ["실제 Vision 모델 미연결"],
        }

    if node_code == "objection_report_generation":
        return {
            "recipient_agency": "mock agency",
            "document_title": "이의신청서 초안",
            "case_summary": "고지서 내용과 사용자 사실관계를 결합한 mock 요약입니다.",
            "grounds": ["사실관계 보완 후 제출 문구 확정 필요"],
            "attachment_list": ["고지서", "사용자 증빙"],
            "disclaimer": "제출 가능성 또는 처분 취소를 보장하지 않습니다.",
        }

    if node_code == "agent_result_validation":
        return {
            "checked_contract_fields": [
                "node_name",
                "node_code",
                "status",
                "summary",
                "structured_result",
                "evidence",
                "next_actions",
                "limitations",
            ],
            "rejected_results": [],
            "merge_ready": status == "success",
        }

    return {"node_code": node_code, "mock_result": "unregistered node"}


def _retrieval_metadata(rag_search: dict[str, Any]) -> dict[str, Any]:
    return {
        key: rag_search.get(key)
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
        if key in rag_search
    }


def _evidence_for_node(node_code: str, status: str) -> list[dict[str, Any]]:
    if status == "failed":
        return []

    evidence_map: dict[str, list[dict[str, Any]]] = {
        "fine_notice_analysis": [
            _evidence("user_uploaded_file", "고지서 첨부 mock", "att_mock_001", {"ocr_status": "mock_completed"}, 0.82),
            _evidence("fine_rule", "과태료 분석 rule mock", "fine_rule_mock_001", {"rule_version": "mock"}, 0.7),
        ],
        "law_ground_search": [
            _evidence("law", "도로교통법 관련 조항 mock", "law_mock_001", {"jurisdiction": "KR"}, 0.64)
        ],
        "text_ml_case_search": [
            _evidence("review_case", "과실비율 심의사례 mock", "case_mock_001", {"case_type": "intersection"}, 0.78)
        ],
        "vision_media_analysis": [
            _evidence("vision_result", "영상·이미지 분석 mock", "vision_mock_001", {"confidence_label": "mock_medium"}, 0.61)
        ],
        "objection_report_generation": [
            _evidence("user_uploaded_file", "제출 첨부 mock", "att_mock_001", {"file_type": "notice"}, None)
        ],
    }
    return deepcopy(evidence_map.get(node_code, []))


def _evidence(
    source_type: str,
    title: str,
    source_reference: str,
    metadata: dict[str, Any],
    confidence: float | None,
) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "title": title,
        "source_reference": source_reference,
        "metadata": metadata,
        "confidence": confidence,
    }


def _next_actions_for_node(node_code: str, status: str) -> list[str]:
    if status == "failed":
        return ["필수 입력 재확인", "Supervisor 추가 질문"]
    if status == "partial":
        return ["부족 입력 보완", "limitations 확인 후 다음 노드 보류"]
    return {
        "input_context_validation": ["Supervisor routing 실행"],
        "fine_notice_analysis": ["법률 근거 검색", "사용자 사실관계 보완"],
        "law_ground_search": ["근거 카드 병합", "리포트 근거 반영"],
        "text_ml_case_search": ["유사 사례 후보 표시", "추가 증거 요청"],
        "vision_media_analysis": ["텍스트 ML/판례·사례 검색 노드에 장면 요약 전달"],
        "objection_report_generation": ["초안 검토", "리포트 저장/다운로드"],
        "agent_result_validation": ["Supervisor 최종 응답 병합"],
    }.get(node_code, ["노드 adapter 등록 확인"])


def _limitations_for_node(node_code: str, status: str, execution_status: str) -> list[str]:
    limitations = []
    if execution_status in {"blocked", "skipped", "running", "pending"}:
        limitations.append(f"plan step 상태가 `{execution_status}`라 실제 실행 대신 mock envelope만 생성했습니다.")
    if status == "failed":
        limitations.append("필수 입력 또는 선행 node 결과가 없어 결과 근거로 사용하지 않습니다.")
    if status == "partial":
        limitations.append("일부 입력 또는 근거가 부족해 단정 표현 없이 표시해야 합니다.")

    node_limitations = {
        "law_ground_search": "실제 법령 원문, 최신 판례, MCP 조회 결과가 아닙니다.",
        "text_ml_case_search": "과실비율 수치를 확정하지 않고 쟁점/유사 사례 후보만 제공합니다.",
        "vision_media_analysis": "실제 Vision/DL 모델이 연결되지 않은 mock 결과입니다.",
        "objection_report_generation": "이의신청서 제출 가능성이나 처분 취소 가능성을 보장하지 않습니다.",
    }
    if node_code in node_limitations:
        limitations.append(node_limitations[node_code])
    return limitations or ["중간발표용 mock Agent 결과입니다."]


def _input_modalities(payload: dict[str, Any]) -> list[str]:
    modalities = ["text"] if payload.get("user_text") else []
    for attachment in payload.get("attachments", []):
        attachment_type = _modality_for_attachment_type(attachment.get("type"))
        if attachment_type and attachment_type not in modalities:
            modalities.append(attachment_type)
    return modalities


def _law_ground_query(payload: dict[str, Any]) -> str:
    agent_input = payload.get("agent_input") if isinstance(payload.get("agent_input"), dict) else {}
    direct_query = (
        payload.get("search_query")
        or payload.get("violation_text")
        or agent_input.get("search_query")
        or agent_input.get("violation_text")
    )
    if direct_query:
        return str(direct_query)

    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    supervisor = (
        context.get("supervisor_handoff")
        if isinstance(context.get("supervisor_handoff"), dict)
        else {}
    )
    packages = supervisor.get("agent_input_packages") if isinstance(supervisor.get("agent_input_packages"), list) else []
    for package in packages:
        if not isinstance(package, dict) or package.get("node_code") != "law_ground_search":
            continue
        package_payload = package.get("payload") if isinstance(package.get("payload"), dict) else {}
        query = package_payload.get("search_query") or package_payload.get("violation_text")
        if query:
            return str(query)

    return str(payload.get("user_text") or "")


def _attachment_purposes(payload: dict[str, Any]) -> list[str]:
    purposes = []
    for attachment in payload.get("attachments", []):
        purpose = attachment.get("purpose") or "unknown"
        if purpose not in purposes:
            purposes.append(purpose)
    return purposes


def _routing_hints(payload: dict[str, Any]) -> list[str]:
    text = str(payload.get("user_text") or "")
    purposes = _attachment_purposes(payload)
    hints = []
    if "fine_notice" in purposes or "고지서" in text or "이의신청" in text:
        hints.append("fine_notice_analysis")
    if "accident_scene" in purposes or "과실" in text or "사고" in text:
        hints.append("text_ml_case_search")
    if {"accident_scene", "evidence"} & set(purposes):
        hints.append("vision_media_analysis")
    return hints or ["fine_notice_analysis"]


def _modality_for_attachment_type(attachment_type: Any) -> str | None:
    if attachment_type in {"pdf", "document", "file", "text"}:
        return "document"
    return str(attachment_type) if attachment_type else None


def _unknown_node(node_code: str) -> dict[str, Any]:
    return {
        "order": 999,
        "node_name": "미등록 노드",
        "node_code": node_code,
        "node_type": "unknown",
        "owner": "unassigned",
        "description": "아직 registry에 등록되지 않은 노드입니다.",
        "required_inputs": [],
        "produces": [],
        "handoff_to": [],
        "status": "unregistered",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
