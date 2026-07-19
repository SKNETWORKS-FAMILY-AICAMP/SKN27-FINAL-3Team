"""Agent/Node registry and runtime execution envelopes."""

from __future__ import annotations

import base64
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.contracts.agent_registry import AgentCapabilityContract
from app.security.pii_masking import sanitize_pii
from app.services.agent_adapter_contract import (
    build_adapter_context,
    build_agent_adapter_input,
    build_agent_adapter_contract,
    validate_adapter_context_envelope,
    validate_agent_input_envelope,
    validate_agent_output_envelope,
)
from app.services.attachment_mock_service import resolve_attachment_references
from app.services.legal_rag_service import search_legal_rag
from app.services.law_ground_contract import (
    normalize_law_evidence,
    normalize_law_structured_result,
)
from app.services.supervisor_control_service import (
    SUPERVISOR_INTERNAL_NODE_CODES,
    run_supervisor_control_node,
)
from app.services.supervisor_execution_input_service import (
    bind_supervisor_plan_step_payload,
    is_ready_supervisor_handoff,
    requires_supervisor_handoff,
)
from app.services.supervisor_routing_service import PUBLIC_AGENT_NODE_CODES


DL_MOCK_NODE_CODES = {"vision_media_analysis"}
REPORTING_NODE_CODE = "objection_report_generation"
TRAFFIC_ACCIDENT_CONFIRMATION_OCR_NODE_CODE = "traffic_accident_confirmation_ocr"
TRAFFIC_ACCIDENT_CONFIRMATION_ATTACHMENT_PURPOSE = "traffic_accident_confirmation"
TRAFFIC_ACCIDENT_CONFIRMATION_REQUIRED_ATTACHMENT = (
    "attachments[purpose=traffic_accident_confirmation, scan_ready]"
)


class SupervisorHandoffValidationError(RuntimeError):
    """Raised before dispatch when a server Supervisor handoff is unusable."""


try:
    from chatbot.object_storage import read_object_bytes, storage_reference_from_uri
except Exception:  # pragma: no cover - keeps CLI-only mock service imports decoupled from Django.
    read_object_bytes = None
    storage_reference_from_uri = None


DL_MOCK_NODE_CODES = {"vision_media_analysis"}


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
        "status": "internal_ready",
    },
    "consultation_fact_state_reducer": {
        "order": 12,
        "node_name": "상담 사실 상태 병합 노드",
        "node_code": "consultation_fact_state_reducer",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "description": "이전 사실과 현재 답변을 출처 단위로 병합하고 충돌 및 누락 필드를 계산한다.",
        "required_inputs": ["conversation_history|facts"],
        "produces": ["facts", "conflicts", "missing_fields"],
        "handoff_to": ["case_promotion_gate"],
        "status": "internal_ready",
    },
    "case_promotion_gate": {
        "order": 14,
        "node_name": "상담 사건 전환 판단 노드",
        "node_code": "case_promotion_gate",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "description": "위험도, 사실 준비도, 인증 및 동의 조건으로 상담의 사건 전환 가능성을 판단한다.",
        "required_inputs": ["consultation_state"],
        "produces": ["decision", "requirements", "automatic_case_creation"],
        "handoff_to": ["final_response_merge"],
        "status": "internal_ready",
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
        "handoff_to": ["law_ground_search", "appeal_decision_flow"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["sync"],
    },
    "law_ground_search": {
        "order": 30,
        "node_name": "법률 근거 검색 노드",
        "node_code": "law_ground_search",
        "node_type": "agent",
        "owner": "techshin31",
        "description": "법령, 시행령, 규칙, 판례 근거 후보를 검색해 Supervisor 병합용 근거를 만든다.",
        "required_inputs": ["law_code|violation_text|search_query"],
        "produces": ["matched_laws", "source_reference", "retrieval", "applicability_limit"],
        "handoff_to": ["appeal_decision_flow", "agent_result_validation", "objection_report_generation"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["sync"],
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
        "adapter_modes": ["sync"],
    },
    "traffic_accident_confirmation_ocr": {
        "order": 45,
        "node_name": "교통사고 사실확인원 OCR 노드",
        "node_code": "traffic_accident_confirmation_ocr",
        "node_type": "agent",
        "owner": "leejaegang27",
        "description": "검증 완료된 교통사고 사실확인원 이미지에서 사고 사실관계 필드를 추출합니다.",
        "required_inputs": [TRAFFIC_ACCIDENT_CONFIRMATION_REQUIRED_ATTACHMENT],
        "produces": ["ocr_evidence", "extracted_fields", "document_check"],
        "handoff_to": ["agent_result_validation", "text_ml_case_search"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["sync"],
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
    "appeal_decision_flow": {
        "order": 55,
        "node_name": "이의신청 가능성 판단 노드",
        "node_code": "appeal_decision_flow",
        "node_type": "agent",
        "owner": "hi20260204-maker",
        "description": "고지서 분석 결과와 사용자 이의 사유를 실제 LangGraph 판단 흐름으로 검토합니다.",
        "required_inputs": ["notice_analysis_result", "user_appeal_reason"],
        "produces": ["appeal_decision", "judgment_status", "guide"],
        "handoff_to": ["objection_report_generation"],
        "status": "sync_adapter_ready",
        "adapter_modes": ["sync"],
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
        "status": "sync_adapter_ready",
        "adapter_modes": ["sync"],
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
        "status": "internal_ready",
    },
    "final_response_merge": {
        "order": 80,
        "node_name": "최종 사용자 응답 병합 노드",
        "node_code": "final_response_merge",
        "node_type": "supervisor_internal",
        "owner": "hi20260204-maker",
        "description": "검증이 승인한 결과만 사용자 응답, 카드, 근거, 한계 및 다음 행동으로 병합한다.",
        "required_inputs": ["agent_result_validation"],
        "produces": ["assistant_message", "cards", "evidence", "limitations"],
        "handoff_to": [],
        "status": "internal_ready",
    },
}

PRODUCTION_AGENT_TIMEOUT_SECONDS = {
    "appeal_decision_flow": 120,
    "fine_notice_analysis": 120,
    "law_ground_search": 30,
    "objection_report_generation": 30,
    "text_ml_case_search": 60,
    "traffic_accident_confirmation_ocr": 120,
}


def list_agent_nodes() -> list[dict[str, Any]]:
    """Return the current Agent/Node registry in execution-friendly order."""

    return [
        _node_with_adapter_contract(NODE_REGISTRY[node_code])
        for node_code in sorted(NODE_REGISTRY, key=lambda code: NODE_REGISTRY[code]["order"])
    ]


def list_public_agent_nodes() -> list[dict[str, Any]]:
    """Return only production-callable Agents under a strict public contract."""

    capabilities = []
    for node_code in sorted(
        _sync_adapter_node_codes(),
        key=lambda code: NODE_REGISTRY[code]["order"],
    ):
        node = _production_node(node_code)
        capability = AgentCapabilityContract(
            node_code=node_code,
            node_name=str(node["node_name"]),
            owner=str(node["owner"]),
            description=str(node["description"]),
            timeout_seconds=PRODUCTION_AGENT_TIMEOUT_SECONDS[node_code],
            required_inputs=list(node.get("required_inputs") or []),
            produces=list(node.get("produces") or []),
            handoff_to=list(node.get("handoff_to") or []),
        )
        capabilities.append(capability.model_dump(mode="json"))
    return capabilities


def get_agent_node(node_code: str) -> dict[str, Any]:
    return _node_with_adapter_contract(NODE_REGISTRY.get(node_code, _unknown_node(node_code)))


def execute_mock_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Compatibility entrypoint; only the DL node may still return mock output."""

    payload = resolve_attachment_references(payload)
    node_code = _payload_node_code(payload)
    if node_code not in DL_MOCK_NODE_CODES:
        return execute_agent_node(payload)

    execution_status = str(payload.get("execution_status") or payload.get("mock_status") or "success")
    result_status = _normalize_result_status(execution_status)
    node = get_agent_node(node_code)
    agent_input = _agent_input(payload, node)
    execution_id = f"exec_{uuid4().hex[:12]}"
    adapter_context = build_adapter_context(
        execution_id=execution_id,
        execution_mode="mock",
        node=node,
        plan_step=payload.get("plan_step"),
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


def execute_agent_node(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one production Agent through a registered synchronous adapter."""

    node_code = _payload_node_code(payload)
    node = _node_with_adapter_contract(_production_node(node_code))
    execution_id = f"exec_{uuid4().hex[:12]}"
    agent_input = _agent_input(payload, node)
    adapter_context = build_adapter_context(
        execution_id=execution_id,
        execution_mode="sync",
        node=node,
        plan_step=payload.get("plan_step"),
    )
    input_validation = validate_agent_input_envelope(
        agent_input,
        expected_node_code=node_code,
    )
    context_validation = validate_adapter_context_envelope(
        adapter_context,
        expected_execution_mode="sync",
    )
    if not input_validation["valid"] or not context_validation["valid"]:
        return _contract_rejected_execution(
            payload=payload,
            node=node,
            agent_input=agent_input,
            adapter_context=adapter_context,
            execution_id=execution_id,
            error_code="agent_input_contract_invalid",
            validation={
                "agent_input": input_validation,
                "adapter_context": context_validation,
            },
        )
    if node_code in SUPERVISOR_INTERNAL_NODE_CODES:
        return _execute_supervisor_internal_node(
            payload=payload,
            node=node,
            agent_input=agent_input,
            adapter_context=adapter_context,
            execution_id=execution_id,
        )
    if node_code not in _sync_adapter_node_codes():
        return {
            "execution_id": execution_id,
            "execution_mode": "sync",
            "job_id": payload.get("job_id"),
            "node_code": node_code,
            "node": node,
            "adapter_context": adapter_context,
            "agent_input": agent_input,
            "agent_output": _unregistered_adapter_output(node=node, agent_input=agent_input),
            "created_at": _now_iso(),
        }
    return _execute_sync_node(
        payload=payload,
        node=node,
        agent_input=agent_input,
        adapter_context=adapter_context,
        execution_id=execution_id,
    )


def execute_agent_plan(analysis_plan: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a canonical plan without fixture or heuristic output fallbacks."""

    executions = []
    upstream_results = _initial_plan_upstream_results(payload)
    supervisor_handoff_state = _supervisor_handoff_state(payload)
    supervisor_handoff: dict[str, Any] = {}
    executable_steps = executable_analysis_plan_steps(
        analysis_plan,
        completed_node_codes=set(upstream_results),
    )
    for step in executable_steps:
        step_payload = _build_plan_step_payload(
            analysis_plan=analysis_plan,
            payload=payload,
            step=step,
            upstream_results=upstream_results,
        )
        _validate_supervisor_step_binding(
            step_payload,
            step=step,
            handoff_state=supervisor_handoff_state,
        )
        if (
            step.get("node_code") == REPORTING_NODE_CODE
            and not _reporting_execution_authorized(
                upstream_results,
                payload=step_payload,
            )
        ):
            continue
        if step.get("node_code") == REPORTING_NODE_CODE:
            supervisor_handoff = _build_supervisor_reporting_handoff(
                upstream_results,
                analysis_plan=analysis_plan,
            )
            context = deepcopy(
                step_payload.get("context")
                if isinstance(step_payload.get("context"), dict)
                else {}
            )
            context["supervisor_handoff"] = deepcopy(supervisor_handoff)
            step_payload["context"] = context
        execution = (
            execute_mock_node(step_payload)
            if step.get("node_code") in DL_MOCK_NODE_CODES
            else execute_agent_node(step_payload)
        )
        execution["plan_step"] = deepcopy(step)
        executions.append(execution)
        upstream_results[execution["node_code"]] = deepcopy(execution["agent_output"])

    limitations = []
    for execution in executions:
        for limitation in execution["agent_output"].get("limitations", []):
            text = str(limitation).strip()
            if text and text not in limitations:
                limitations.append(text)
    if not supervisor_handoff:
        supervisor_handoff = _build_supervisor_reporting_handoff(
            upstream_results,
            analysis_plan=analysis_plan,
        )
    reporting_payload = _build_reporting_payload(
        payload.get("reporting_payload"),
        upstream_results=upstream_results,
        supervisor_handoff=supervisor_handoff,
    )
    execution_mode = _production_plan_execution_mode(executions)
    return {
        "execution_mode": execution_mode,
        "job_id": payload.get("job_id"),
        "plan_id": analysis_plan.get("plan_id"),
        "session_id": analysis_plan.get("session_id") or payload.get("session_id"),
        "message_id": analysis_plan.get("message_id") or payload.get("message_id"),
        "executions": executions,
        "status_counts": _status_counts(executions),
        "completed_node_codes": [
            execution["node_code"]
            for execution in executions
            if execution["agent_output"]["status"] == "success"
        ],
        "supervisor_handoff": supervisor_handoff,
        "reporting_payload": reporting_payload,
        "limitations": limitations,
        "created_at": _now_iso(),
    }


def executable_analysis_plan_steps(
    analysis_plan: dict[str, Any],
    *,
    completed_node_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return only explicitly runnable steps whose dependencies are satisfiable.

    Plans are treated as ordered execution contracts. Unknown or waiting states fail
    closed, and a runnable step is admitted only after every dependency has either
    already completed or appeared earlier in the admitted sequence.
    """

    available = {
        str(node_code).strip()
        for node_code in (completed_node_codes or set())
        if str(node_code).strip()
    }
    selected: list[dict[str, Any]] = []
    for candidate in analysis_plan.get("steps", []):
        if not isinstance(candidate, dict):
            continue
        status = str(candidate.get("status") or "").strip().lower()
        if status not in {"ready", "queued"}:
            continue
        node_code = str(candidate.get("node_code") or "").strip()
        if not node_code or node_code in available:
            continue
        dependencies = {
            str(dependency).strip()
            for dependency in candidate.get("depends_on", [])
            if str(dependency).strip()
        }
        if not dependencies.issubset(available):
            continue
        selected.append(candidate)
        available.add(node_code)
    return selected


def validate_supervisor_plan_handoff(
    analysis_plan: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Reject malformed Supervisor packages before any paid dispatch reservation.

    The runtime repeats this validation before each individual node.  This
    preflight exists only to guarantee malformed server state has no dispatch
    side effect at the queue boundary.
    """

    upstream_results = _initial_plan_upstream_results(payload)
    handoff_state = _supervisor_handoff_state(payload)
    if handoff_state == "absent":
        return
    for step in executable_analysis_plan_steps(
        analysis_plan,
        completed_node_codes=set(upstream_results),
    ):
        if str(step.get("node_code") or "").strip() not in PUBLIC_AGENT_NODE_CODES:
            continue
        step_payload = _build_plan_step_payload(
            analysis_plan=analysis_plan,
            payload=payload,
            step=step,
            upstream_results=upstream_results,
        )
        _validate_supervisor_step_binding(
            step_payload,
            step=step,
            handoff_state=handoff_state,
        )


def _build_plan_step_payload(
    *,
    analysis_plan: dict[str, Any],
    payload: dict[str, Any],
    step: dict[str, Any],
    upstream_results: dict[str, Any],
) -> dict[str, Any]:
    """Create one runtime input from a server plan and current result state."""

    step_payload = deepcopy(payload)
    step_payload.update(
        {
            "analysis_plan_id": analysis_plan.get("plan_id"),
            "session_id": analysis_plan.get("session_id") or payload.get("session_id"),
            "message_id": analysis_plan.get("message_id") or payload.get("message_id"),
            "node_code": step.get("node_code"),
            "execution_mode": "sync",
            "required_inputs": step.get("required_inputs", []),
            "depends_on": step.get("depends_on", []),
            "plan_step": step,
            "upstream_results": deepcopy(upstream_results),
        }
    )
    if isinstance(step.get("context"), dict):
        context = deepcopy(payload.get("context") if isinstance(payload.get("context"), dict) else {})
        context.update(deepcopy(step["context"]))
        step_payload["context"] = context
    return bind_supervisor_plan_step_payload(
        step_payload,
        step=step,
        upstream_results=upstream_results,
    )


def _sync_adapter_node_codes() -> set[str]:
    return {
        "appeal_decision_flow",
        "fine_notice_analysis",
        "law_ground_search",
        "objection_report_generation",
        "text_ml_case_search",
        TRAFFIC_ACCIDENT_CONFIRMATION_OCR_NODE_CODE,
    }


def _production_plan_execution_mode(executions: list[dict[str, Any]]) -> str:
    modes = {str(item.get("execution_mode") or "") for item in executions}
    if modes == {"mock"}:
        return "dl_mock"
    if "mock" in modes:
        return "hybrid"
    return "sync"


def _build_supervisor_reporting_handoff(
    upstream_results: dict[str, Any],
    *,
    analysis_plan: dict[str, Any],
) -> dict[str, Any]:
    analysis_results: dict[str, dict[str, Any]] = {}
    source_node_codes: list[str] = []
    status_counts = {"success": 0, "partial": 0, "failed": 0}
    for node_code, raw_output in upstream_results.items():
        if (
            node_code == REPORTING_NODE_CODE
            or node_code in SUPERVISOR_INTERNAL_NODE_CODES
            or not isinstance(raw_output, dict)
        ):
            continue
        output = raw_output.get("agent_output") if isinstance(raw_output.get("agent_output"), dict) else raw_output
        status = str(output.get("status") or "failed")
        normalized_status = status if status in status_counts else "failed"
        status_counts[normalized_status] += 1
        source_node_codes.append(node_code)
        analysis_results[node_code] = {
            "status": normalized_status,
            "summary": str(output.get("summary") or ""),
            "structured_result": deepcopy(output.get("structured_result") or {}),
            "evidence": deepcopy(output.get("evidence") or []),
            "limitations": deepcopy(output.get("limitations") or []),
        }
    ready_for_reporting = bool(analysis_results) and status_counts["failed"] == 0
    return {
        "contract_version": "supervisor_reporting_handoff.v1",
        "analysis_plan_id": analysis_plan.get("plan_id"),
        "ready_for_reporting": ready_for_reporting,
        "source_node_codes": source_node_codes,
        "status_counts": status_counts,
        "agent_results": analysis_results,
    }


def _build_reporting_payload(
    base_payload: Any,
    *,
    upstream_results: dict[str, Any],
    supervisor_handoff: dict[str, Any],
) -> dict[str, Any]:
    report_output = upstream_results.get(REPORTING_NODE_CODE)
    if not isinstance(report_output, dict):
        return {}
    nested = report_output.get("agent_output")
    if isinstance(nested, dict):
        report_output = nested
    structured = report_output.get("structured_result")
    structured = deepcopy(structured) if isinstance(structured, dict) else {}
    base = deepcopy(base_payload) if isinstance(base_payload, dict) else {}
    source_node_codes = list(supervisor_handoff.get("source_node_codes") or [])
    return {
        **base,
        "contract_version": "reporting_payload.v2",
        "source": "supervisor_agent_result_aggregation",
        "stage": "final" if report_output.get("status") == "success" else "partial",
        "report_type": base.get("report_type") or structured.get("document_variant") or "general",
        "title": structured.get("document_title") or base.get("title") or "Analysis report",
        "summary": report_output.get("summary") or base.get("summary") or "",
        "generated_from_node_codes": source_node_codes,
        "sections": deepcopy(structured.get("form_sections") or []),
        "report_actions": deepcopy(structured.get("report_actions") or []),
        "missing_fields": deepcopy(structured.get("missing_fields") or []),
        "form_data": deepcopy(structured.get("form_data") or {}),
        "document_readiness": deepcopy(structured.get("document_readiness") or {}),
        "quality": {
            "ready_for_reporting": bool(supervisor_handoff.get("ready_for_reporting")),
            "agent_status_counts": deepcopy(supervisor_handoff.get("status_counts") or {}),
        },
    }


def _production_node(node_code: str) -> dict[str, Any]:
    node = deepcopy(NODE_REGISTRY.get(node_code, _unknown_node(node_code)))
    if node_code in SUPERVISOR_INTERNAL_NODE_CODES and node_code in NODE_REGISTRY:
        node["status"] = "internal_ready"
        node["adapter_modes"] = ["sync"]
        return node
    supported = node_code in _sync_adapter_node_codes()
    node["status"] = "sync_adapter_ready" if supported else "unavailable"
    node["adapter_modes"] = ["sync"] if supported else []
    return _node_with_adapter_contract(node)


def _unregistered_adapter_output(
    *,
    node: dict[str, Any],
    agent_input: dict[str, Any],
) -> dict[str, Any]:
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": node.get("node_name"),
        "node_code": node.get("node_code"),
        "node_type": node.get("node_type"),
        "owner": node.get("owner"),
        "status": "failed",
        "execution_status": "failed",
        "summary": "요청한 Agent는 운영 환경에서 사용할 수 없습니다.",
        "structured_result": {
            "error_code": "sync_adapter_unregistered",
            "node_code": node.get("node_code"),
        },
        "evidence": [],
        "next_actions": ["remove_unsupported_capability_or_register_adapter"],
        "limitations": ["The requested Agent has no production adapter."],
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


def _initial_plan_upstream_results(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept persisted upstream state only for non-Supervisor legacy callers."""

    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    if (
        requires_supervisor_handoff(payload)
        or is_ready_supervisor_handoff(context.get("supervisor_handoff"))
    ):
        return {}
    upstream_results = payload.get("upstream_results")
    return deepcopy(upstream_results) if isinstance(upstream_results, dict) else {}


def _supervisor_handoff_state(payload: dict[str, Any]) -> str:
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    if "supervisor_handoff" not in context:
        return "missing_required" if requires_supervisor_handoff(payload) else "absent"
    return "ready" if is_ready_supervisor_handoff(context.get("supervisor_handoff")) else "invalid"


def _validate_supervisor_step_binding(
    payload: dict[str, Any],
    *,
    step: dict[str, Any],
    handoff_state: str,
) -> None:
    node_code = str(step.get("node_code") or "").strip()
    if node_code not in PUBLIC_AGENT_NODE_CODES or handoff_state == "absent":
        return
    if handoff_state != "ready":
        raise SupervisorHandoffValidationError(
            "Supervisor Agent input package handoff is invalid"
        )
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    package = context.get("supervisor_agent_package")
    if not isinstance(package, dict) or package.get("node_code") != node_code:
        raise SupervisorHandoffValidationError(
            "Supervisor Agent input package is unavailable"
        )


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
    return execution_mode == "sync" and node_code in _sync_adapter_node_codes()


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
        agent_output = _normalize_execution_agent_output(
            agent_output,
            node=node,
            agent_input=agent_input,
        )
        output_validation = validate_agent_output_envelope(
            agent_output,
            expected_node_code=node["node_code"],
        )
        if not output_validation["valid"]:
            agent_output = _contract_error_output(
                node=node,
                agent_input=agent_input,
                error_code="agent_output_contract_invalid",
                validation=output_validation,
            )
            adapter_error = {
                "error_code": "agent_output_contract_invalid",
                "message": "Agent output contract validation failed.",
            }
        else:
            adapter_error = None
    except Exception as exc:  # pragma: no cover - defensive production boundary.
        agent_output = _adapter_error_output(
            node=node,
            agent_input=agent_input,
            exc=exc,
        )
        adapter_error = {
            "error_code": exc.__class__.__name__,
            "message": "Sync adapter execution failed.",
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


def _execute_supervisor_internal_node(
    *,
    payload: dict[str, Any],
    node: dict[str, Any],
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
    execution_id: str,
) -> dict[str, Any]:
    try:
        agent_output = run_supervisor_control_node(node["node_code"], agent_input)
        agent_output = _normalize_execution_agent_output(
            agent_output,
            node=node,
            agent_input=agent_input,
        )
        output_validation = validate_agent_output_envelope(
            agent_output,
            expected_node_code=node["node_code"],
        )
        if not output_validation["valid"]:
            agent_output = _contract_error_output(
                node=node,
                agent_input=agent_input,
                error_code="supervisor_output_contract_invalid",
                validation=output_validation,
            )
            adapter_error = {
                "error_code": "supervisor_output_contract_invalid",
                "message": "Supervisor control output contract validation failed.",
            }
        else:
            adapter_error = None
    except Exception as exc:  # pragma: no cover - defensive Supervisor boundary.
        agent_output = _adapter_error_output(
            node=node,
            agent_input=agent_input,
            exc=exc,
        )
        adapter_error = {
            "error_code": exc.__class__.__name__,
            "message": "Supervisor control execution failed.",
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


def _validation_report_ready(upstream_results: dict[str, Any]) -> bool:
    validation = upstream_results.get("agent_result_validation")
    if not isinstance(validation, dict):
        return False
    nested = validation.get("agent_output")
    output = nested if isinstance(nested, dict) else validation
    structured = output.get("structured_result")
    return bool(structured.get("report_ready")) if isinstance(structured, dict) else False


def _reporting_execution_authorized(
    upstream_results: dict[str, Any],
    *,
    payload: dict[str, Any],
) -> bool:
    if _validation_report_ready(upstream_results):
        return True

    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    if context.get("handoff_required") is not True:
        return False
    handoff = (
        context.get("supervisor_reporting_handoff")
        if isinstance(context.get("supervisor_reporting_handoff"), dict)
        else {}
    )
    target = handoff.get("target") if isinstance(handoff.get("target"), dict) else {}
    source = handoff.get("source") if isinstance(handoff.get("source"), dict) else {}
    gate = handoff.get("gate") if isinstance(handoff.get("gate"), dict) else {}
    return bool(
        handoff.get("contract_version") == "supervisor_reporting_handoff.v1"
        and handoff.get("ready_for_reporting") is True
        and target.get("node_code") == REPORTING_NODE_CODE
        and source.get("persistence") == "agent_results"
        and source.get("persisted") is True
        and gate.get("status") == "ready"
        and gate.get("ready_for_reporting") is True
        and isinstance(handoff.get("results"), dict)
    )


def _contract_rejected_execution(
    *,
    payload: dict[str, Any],
    node: dict[str, Any],
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
    execution_id: str,
    error_code: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "execution_id": execution_id,
        "execution_mode": "sync",
        "job_id": payload.get("job_id"),
        "node_code": node["node_code"],
        "node": node,
        "adapter_context": adapter_context,
        "agent_input": agent_input,
        "agent_output": _contract_error_output(
            node=node,
            agent_input=agent_input,
            error_code=error_code,
            validation=validation,
        ),
        "adapter_error": {
            "error_code": error_code,
            "message": "Agent input contract validation failed.",
        },
        "created_at": _now_iso(),
    }


def _normalize_execution_agent_output(
    output: Any,
    *,
    node: dict[str, Any],
    agent_input: dict[str, Any],
) -> dict[str, Any]:
    normalized = deepcopy(output) if isinstance(output, dict) else {}
    defaults = {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": node["node_name"],
        "node_code": node["node_code"],
        "node_type": node["node_type"],
        "owner": node["owner"],
        "status": "failed",
        "summary": "",
        "structured_result": {},
        "evidence": [],
        "next_actions": [],
        "limitations": [],
        "created_at": _now_iso(),
    }
    for key, value in defaults.items():
        normalized.setdefault(key, value)
    return normalized


def _contract_error_output(
    *,
    node: dict[str, Any],
    agent_input: dict[str, Any],
    error_code: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    invalid_fields = sorted(
        {
            str(field)
            for key in ("missing_fields", "invalid_collection_fields")
            for field in (
                validation.get(key, [])
                if isinstance(validation.get(key), list)
                else []
            )
        }
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
        "execution_status": "failed",
        "summary": "Agent 계약 검증을 통과하지 못해 실행 결과를 전달하지 않았습니다.",
        "structured_result": {
            "error_code": error_code,
            "invalid_fields": invalid_fields,
        },
        "evidence": [],
        "next_actions": ["fix_agent_contract_before_retry"],
        "limitations": ["Invalid Agent input or output was rejected at the execution boundary."],
        "created_at": _now_iso(),
    }


def _run_sync_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    node_code = str(agent_input.get("node_code") or "")
    if node_code == "appeal_decision_flow":
        return _run_appeal_decision_flow_adapter(agent_input, adapter_context)
    if node_code == "fine_notice_analysis":
        return _run_fine_notice_analysis_adapter(agent_input, adapter_context)
    if node_code == "law_ground_search":
        return _run_law_ground_search_adapter(agent_input, adapter_context)
    if node_code == "appeal_decision_flow":
        return _run_appeal_decision_flow_adapter(agent_input, adapter_context)
    if node_code == "objection_report_generation":
        return _run_objection_report_generation_adapter(agent_input, adapter_context)
    if node_code == "text_ml_case_search":
        return _run_text_ml_case_search_adapter(agent_input, adapter_context)
    if node_code == TRAFFIC_ACCIDENT_CONFIRMATION_OCR_NODE_CODE:
        return _run_traffic_accident_confirmation_ocr_adapter(agent_input, adapter_context)
    raise RuntimeError(f"sync_adapter_unregistered:{node_code}")


def _run_appeal_decision_flow_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    from ai.agents.appeal_decision_flow import graph

    state = _appeal_decision_state(agent_input)
    result = graph.invoke(state)
    raw_output = (
        result.get("agent_results", {}).get("appeal_judgment")
        if isinstance(result, dict)
        else None
    )
    if not isinstance(raw_output, dict):
        raw_output = {
            "status": "partial",
            "summary": "appeal_decision_flow returned without an appeal judgment envelope.",
            "structured_result": {
                "judgment_status": "input_required",
                "overall_possibility": None,
                "guide": {},
            },
            "evidence": [],
            "next_actions": ["check_appeal_decision_agent_output"],
            "limitations": ["The appeal decision graph did not return a complete envelope."],
        }
    return _complete_adapter_output(
        raw_output,
        node=adapter_context["node"],
        agent_input=agent_input,
        adapter_trace={
            "adapter": "ai.agents.appeal_decision_flow.graph",
            "execution_mode": "sync",
            "source_status": raw_output.get("status"),
            "input_source": "agent_input.context+upstream_results",
        },
    )


def _appeal_decision_state(agent_input: dict[str, Any]) -> dict[str, Any]:
    from ai.agents.appeal_decision_flow.state import AppealJudgmentState

    allowed_fields = set(AppealJudgmentState.__annotations__)
    context = agent_input.get("context") if isinstance(agent_input.get("context"), dict) else {}
    state = {
        key: deepcopy(value)
        for key, value in context.items()
        if key in allowed_fields and value is not None
    }
    upstream_results = (
        agent_input.get("upstream_results")
        if isinstance(agent_input.get("upstream_results"), dict)
        else {}
    )
    fine_notice = upstream_results.get("fine_notice_analysis")
    if isinstance(fine_notice, dict):
        structured_result = fine_notice.get("structured_result")
        if isinstance(structured_result, dict):
            for key, value in structured_result.items():
                if key in allowed_fields and value is not None and key not in state:
                    state[key] = deepcopy(value)
    if not state.get("user_appeal_reason") and agent_input.get("user_text"):
        state["user_appeal_reason"] = str(agent_input["user_text"])
    state["agent_results"] = {}
    return state


def _run_fine_notice_analysis_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    state = _fine_notice_state(agent_input)
    try:
        from ai.agents.fine_notice_analysis.graph import graph

        result = graph.invoke(state)
    except Exception as exc:
        raw_output = {
            "status": "failed",
            "summary": "fine_notice_analysis adapter failed before completing OCR processing.",
            "structured_result": {
                "ocr_status": "failed",
                "ocr_error": "Fine notice analysis failed.",
                "missing_fields": ["notice_image"] if state.get("_input_source") == "missing" else [],
            },
            "evidence": [],
            "next_actions": [
                "check_fine_notice_agent_dependencies",
                "retry_sync_adapter",
            ],
            "limitations": [
                f"fine_notice_analysis adapter dependency error:{exc.__class__.__name__}",
            ],
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


def _run_traffic_accident_confirmation_ocr_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    state, attachment, input_error = _traffic_accident_confirmation_ocr_state(agent_input)
    adapter_trace = {
        "adapter": "etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.graph",
        "execution_mode": "sync",
        "input_source": "canonical_scan_ready_attachment" if attachment else "missing",
    }
    if input_error:
        return _complete_adapter_output(
            {
                "status": "partial",
                "execution_status": "input_required",
                "summary": "교통사고 사실확인원 OCR에는 검사 완료된 이미지 첨부파일이 필요합니다.",
                "structured_result": {
                    "missing_fields": [TRAFFIC_ACCIDENT_CONFIRMATION_REQUIRED_ATTACHMENT],
                    "input_error": input_error,
                    "ocr_evidence": [],
                },
                "evidence": [],
                "next_actions": ["request_scan_ready_traffic_accident_confirmation"],
                "limitations": [
                    "Inline, unresolved, or unscanned attachments are not passed to OCR."
                ],
            },
            node=adapter_context["node"],
            agent_input=agent_input,
            adapter_trace=adapter_trace,
        )

    try:
        from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.graph import graph

        result = graph.invoke(state)
    except Exception as exc:
        return _complete_adapter_output(
            {
                "status": "failed",
                "summary": "교통사고 사실확인원 OCR 처리 중 오류가 발생했습니다.",
                "structured_result": {
                    "ocr_evidence": _traffic_accident_ocr_evidence(attachment),
                    "error_code": exc.__class__.__name__,
                },
                "evidence": _traffic_accident_ocr_evidence_records(attachment),
                "next_actions": ["retry_sync_adapter"],
                "limitations": ["Traffic accident confirmation OCR failed before returning an envelope."],
            },
            node=adapter_context["node"],
            agent_input=agent_input,
            adapter_trace=adapter_trace,
        )

    raw_output = (
        result.get("agent_results", {}).get(TRAFFIC_ACCIDENT_CONFIRMATION_OCR_NODE_CODE)
        if isinstance(result, dict)
        else None
    )
    if not isinstance(raw_output, dict):
        raw_output = {
            "status": "partial",
            "summary": "교통사고 사실확인원 OCR이 표준 결과 형식을 반환하지 않았습니다.",
            "structured_result": {},
            "evidence": [],
            "next_actions": ["check_traffic_accident_confirmation_ocr_output"],
            "limitations": ["The OCR graph did not return a complete envelope."],
        }

    raw_output = deepcopy(raw_output)
    raw_output["structured_result"] = _traffic_accident_ocr_structured_result(
        raw_output.get("structured_result"),
        attachment=attachment,
    )
    raw_output["evidence"] = _traffic_accident_ocr_evidence_records(attachment)
    adapter_trace["source_status"] = raw_output.get("status")
    return _complete_adapter_output(
        raw_output,
        node=adapter_context["node"],
        agent_input=agent_input,
        adapter_trace=adapter_trace,
    )


def _traffic_accident_confirmation_ocr_state(
    agent_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    attachment = next(
        (
            item
            for item in agent_input.get("attachments") or []
            if isinstance(item, dict) and _is_scan_ready_traffic_accident_confirmation(item)
        ),
        None,
    )
    if attachment is None:
        return {}, None, "scan_ready_attachment_required"

    storage_uri = str(attachment.get("storage_uri") or "")
    image_bytes = _attachment_object_storage_bytes(attachment, storage_uri)
    if not image_bytes:
        return {}, attachment, "scan_ready_attachment_unavailable"

    return (
        {
            "document_image": base64.b64encode(image_bytes).decode("ascii"),
            "document_mime_type": str(attachment.get("content_type") or ""),
            "source_filename": str(attachment.get("filename") or ""),
            "agent_results": {},
        },
        attachment,
        None,
    )


def _is_scan_ready_traffic_accident_confirmation(attachment: dict[str, Any]) -> bool:
    storage_uri = str(attachment.get("storage_uri") or "")
    object_storage = attachment.get("object_storage")
    return bool(
        attachment.get("purpose") == TRAFFIC_ACCIDENT_CONFIRMATION_ATTACHMENT_PURPOSE
        and attachment.get("metadata_source") == "canonical_scan_gate"
        and attachment.get("resolution_status") == "scan_ready"
        and attachment.get("status") == "ready"
        and attachment.get("scan_status") == "clean"
        and storage_uri.startswith("s3://")
        and isinstance(object_storage, dict)
        and object_storage.get("resource_type") == "uploaded_file"
        and object_storage.get("status") == "ready"
        and object_storage.get("storage_uri") == storage_uri
    )


def _traffic_accident_ocr_structured_result(
    raw_structured_result: Any,
    *,
    attachment: dict[str, Any],
) -> dict[str, Any]:
    raw = raw_structured_result if isinstance(raw_structured_result, dict) else {}
    allowed_fields = {
        "document_check",
        "page_info",
        "scene_diagram",
        "quality",
        "privacy",
        "extracted_fields",
        "missing_fields",
        "failure_reason",
    }
    structured = sanitize_pii({key: deepcopy(raw[key]) for key in allowed_fields if key in raw})
    structured["ocr_evidence"] = _traffic_accident_ocr_evidence(attachment)
    return structured


def _traffic_accident_ocr_evidence(attachment: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(attachment, dict):
        return []
    return [
        {
            "attachment_id": str(attachment.get("attachment_id") or ""),
            "storage_uri": str(attachment.get("storage_uri") or ""),
            "content_type": str(attachment.get("content_type") or ""),
        }
    ]


def _traffic_accident_ocr_evidence_records(attachment: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = _traffic_accident_ocr_evidence(attachment)
    if not evidence:
        return []
    return [
        {
            "source_type": "user_uploaded_file",
            "title": "교통사고 사실확인원 첨부파일",
            "source_reference": evidence[0]["attachment_id"],
            "metadata": evidence[0],
            "confidence": None,
        }
    ]


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


def _run_objection_report_generation_adapter(
    agent_input: dict[str, Any],
    adapter_context: dict[str, Any],
) -> dict[str, Any]:
    from ai.agents.objection_report_generation import run_objection_report_generation

    raw_output = run_objection_report_generation(agent_input, adapter_context)
    if not isinstance(raw_output, dict):
        raw_output = {
            "status": "partial",
            "summary": "objection_report_generation returned without an AgentAdapterOutput envelope.",
            "structured_result": {
                "document_type": "objection_form",
                "form_sections": [],
                "report_actions": [],
            },
            "evidence": [],
            "next_actions": ["check_objection_report_generation_agent_output"],
            "limitations": ["The objection_report_generation adapter did not return a dictionary."],
        }
    return _complete_adapter_output(
        raw_output,
        node=adapter_context["node"],
        agent_input=agent_input,
        adapter_trace={
            "adapter": "ai.agents.objection_report_generation.run_objection_report_generation",
            "execution_mode": "sync",
            "source_status": raw_output.get("status"),
            "input_source": (
                "agent_input.context.supervisor_reporting_handoff"
                if _dict_context(agent_input).get("handoff_required") is True
                else "agent_input.upstream_results"
            ),
        },
    )


def _dict_context(agent_input: dict[str, Any]) -> dict[str, Any]:
    context = agent_input.get("context")
    return context if isinstance(context, dict) else {}


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
    attachment_id = str(attachment.get("attachment_id") or "")
    if (
        attachment_id
        and storage_uri.startswith("s3://")
        and attachment.get("metadata_source") == "canonical_scan_gate"
    ):
        try:
            from chatbot.file_scan_service import read_scan_ready_attachment_bytes
        except Exception:  # pragma: no cover - CLI-only imports have no Django app.
            return None
        return read_scan_ready_attachment_bytes(
            attachment_id,
            expected_storage_uri=storage_uri,
        )
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
    if "missing_fields" in raw_output and "missing_fields" not in structured_result:
        structured_result["missing_fields"] = deepcopy(raw_output.get("missing_fields") or [])
    structured_result = _normalize_adapter_structured_result(
        structured_result,
        node_code=node["node_code"],
        adapter_trace=adapter_trace,
    )
    structured_result.setdefault("adapter_trace", adapter_trace)
    evidence = deepcopy(raw_output.get("evidence") or [])
    if node["node_code"] == "law_ground_search":
        evidence = normalize_law_evidence(evidence)
    return {
        "session_id": agent_input.get("session_id"),
        "message_id": agent_input.get("message_id"),
        "job_id": agent_input.get("job_id"),
        "node_name": raw_output.get("node_name") or node["node_name"],
        "node_code": node["node_code"],
        "node_type": node["node_type"],
        "owner": node["owner"],
        "status": _adapter_result_status(source_status),
        "execution_status": raw_output.get("execution_status") or source_status,
        "summary": raw_output.get("summary") or _summary_for_node(node["node_code"], _adapter_result_status(source_status)),
        "structured_result": structured_result,
        "evidence": evidence,
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
    if "appeal_decision_flow" in adapter:
        marker = "appeal_decision_flow real graph is connected through Supervisor sync execution mode."
    elif "fine_notice_analysis" in adapter:
        marker = "fine_notice_analysis real adapter is connected through Supervisor sync execution mode."
    elif "text_ml_case_search" in adapter:
        marker = "text_ml_case_search sync adapter is connected through the RAG-backed case-search port."
    elif "objection_report_generation" in adapter:
        marker = "objection_report_generation sync adapter is connected through Supervisor sync execution mode."
    elif "traffic_accident_confirmation_ocr" in adapter:
        marker = "traffic_accident_confirmation_ocr is connected through the canonical scan-ready attachment boundary."
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
    elif node_code == "law_ground_search":
        structured = normalize_law_structured_result(structured)
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
            "error_message": "Sync adapter execution failed.",
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
        "next_actions": ["retry_sync_adapter"],
        "limitations": ["Sync adapter exception was normalized for Supervisor result validation."],
        "created_at": _now_iso(),
    }


def _adapter_error_trace(node_code: str, agent_input: dict[str, Any], exc: Exception) -> dict[str, Any]:
    adapter_by_node = {
        "appeal_decision_flow": "ai.agents.appeal_decision_flow.graph",
        "fine_notice_analysis": "ai.agents.fine_notice_analysis.graph",
        "law_ground_search": "ai.agents.law_ground_search.run_law_ground_search",
        "text_ml_case_search": "ai.agents.text_ml_case_search.run_text_ml_case_search",
        "traffic_accident_confirmation_ocr": "etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr.graph",
    }
    if node_code == "fine_notice_analysis":
        input_source = "attachment" if _has_fine_notice_attachment(agent_input) else "missing"
    elif node_code == "law_ground_search":
        input_source = "agent_input.context"
    elif node_code == TRAFFIC_ACCIDENT_CONFIRMATION_OCR_NODE_CODE:
        input_source = "canonical_scan_ready_attachment"
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
