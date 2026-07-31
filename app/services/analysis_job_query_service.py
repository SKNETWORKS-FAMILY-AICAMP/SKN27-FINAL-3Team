"""Application service for reading analysis jobs and their public results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Callable, Literal

from app.services.attachment_workflow_service import (
    ATTACHMENT_WORKFLOW_STATES,
    build_attachment_workflows,
)
from app.services.analysis_progress_service import build_analysis_progress
from app.services.fact_conflict_service import normalize_fact_conflicts
from app.services.public_law_projection_service import project_public_law_items


AnalysisQueryKind = Literal["not_found", "detail", "pending", "completed"]
JobLoader = Callable[[str], dict[str, Any] | None]
ProgressLoader = Callable[[str], dict[str, Any] | None]
ResponseComposer = Callable[[dict[str, Any]], dict[str, Any]]


_COMPOSED_RESULT_FIELDS = (
    "contract_version",
    "job_id",
    "status",
    "assistant_message",
    "evidence",
    "limitations",
    "next_actions",
    "deadline_guidance",
    "service_scope",
    "cards",
)
_REPORTING_PAYLOAD_FIELDS = (
    "contract_version",
    "stage",
    "report_id",
    "report_type",
    "title",
    "summary",
    "sections",
    "document_cards",
    "document_variant",
    "document_confirmation",
    "report_actions",
    "appeal_gate",
)
_SUPERVISOR_STATE_FIELDS = (
    "contract_version",
    "stage",
    "conversation_summary",
    "collected_facts",
    "missing_fields",
    "next_questions",
    "fact_conflicts",
)
_SUPERVISOR_EXECUTION_FIELDS = (
    "contract_version",
    "status",
    "execution_mode",
    "job_id",
)
_NODE_RESULT_FIELDS = (
    "node_code",
    "status",
    "summary",
    "structured_result",
    "evidence",
    "next_actions",
    "limitations",
)
_WORK_ITEM_FIELDS = (
    "contract_version",
    "work_item_id",
    "job_id",
    "status",
    "attempt_no",
    "max_attempts",
    "next_run_at",
)
_PROGRESS_STATE_FIELDS = (
    "contract_version",
    "state",
    "work_item_status",
    "job_status",
    "attempt_no",
    "max_attempts",
    "retryable",
    "retry_after_seconds",
    "next_run_at",
)
_DETAIL_SCALAR_FIELDS = (
    "contract_version",
    "job_id",
    "session_id",
    "message_id",
    "status",
    "active_node",
    "progress_message",
    "status_counts",
    "assistant_message",
    "cards",
    "pending_questions",
    "conversation_messages",
    "agent_result_count",
    "agent_status_counts",
    "report_count",
    "latest_report_id",
    "latest_report_status",
    "last_event_at",
    "created_at",
    "updated_at",
)
_ASSISTANT_MESSAGE_PAYLOAD_FIELDS = (
    "answer",
    "summary",
    "report_id",
    "report_status",
)
_PUBLIC_PROGRESS_CACHE_FIELDS = (
    "policy_version",
    "backend",
    "key",
    "ttl_seconds",
    "fallback",
    "status",
)
_PUBLIC_PROGRESS_SNAPSHOT_FIELDS = (
    "policy_version",
    "key",
    "cache_role",
    "fallback",
    "job_id",
    "session_id",
    "status",
    "active_node",
    "progress_message",
    "status_counts",
    "updated_at",
    "source_tables",
)
_PUBLIC_ATTACHMENT_FIELDS = ("attachment_id", "purpose", "filename", "scan_status")
_PUBLIC_ATTACHMENT_WORKFLOW_FIELDS = (
    "contract_version",
    "attachment_id",
    "state",
    "next_action",
    "retryable",
    "missing_fields",
    "limitations",
)
_PUBLIC_REPORT_LINK_FIELDS = ("report_id", "action")
_PUBLIC_REPORT_SUMMARY_FIELDS = (
    "report_id",
    "report_type",
    "status",
    "title",
    "content_summary",
    "created_at",
    "updated_at",
)
_PUBLIC_LAW_ITEM_FIELDS = (
    "law_name",
    "source_name",
    "article",
    "article_no",
    "title",
    "article_title",
    "summary",
    "provision_text",
    "source_reference",
    "effective_date",
    "score",
    "retrieval_score",
)
_SAFE_PUBLIC_LIMITATIONS = frozenset(
    {
        "Latest revision may not be reflected.",
        "Final legal review and user confirmation are still required.",
    }
)
_SAFE_PUBLIC_STATUSES = frozenset({"ready", "partial", "empty", "blocked", "failed", "unavailable"})
_SAFE_PUBLIC_BACKENDS = frozenset({"postgres_pgvector", "law retrieval", "legal_ground_search"})
_SAFE_PUBLIC_CONFIDENCE_LABELS = frozenset({"high", "medium", "low", "검토 가능", "추가 자료 필요"})
_SAFE_PUBLIC_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_PUBLIC_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


@dataclass(frozen=True, slots=True)
class AnalysisJobQueryOutcome:
    kind: AnalysisQueryKind
    payload: dict[str, Any]


def load_analysis_job_detail(
    job_id: str,
    *,
    load_job: JobLoader,
    load_progress: ProgressLoader,
) -> AnalysisJobQueryOutcome:
    """Load one job and attach transient progress without mutating storage data."""

    stored_job = load_job(job_id)
    if stored_job is None:
        return AnalysisJobQueryOutcome(kind="not_found", payload={})

    return AnalysisJobQueryOutcome(
        kind="detail",
        payload=_project_analysis_job_detail(stored_job, load_progress(job_id)),
    )


def load_analysis_result(
    job_id: str,
    *,
    load_job: JobLoader,
    compose_response: ResponseComposer,
) -> AnalysisJobQueryOutcome:
    """Return a pending placeholder or compose the persisted production outputs."""

    job = load_job(job_id)
    if job is None:
        return AnalysisJobQueryOutcome(kind="not_found", payload={})

    status = str(job.get("status") or "")
    if status in {"queued", "running"}:
        return AnalysisJobQueryOutcome(
            kind="pending",
            payload={
                "contract_version": "analysis_result.v2",
                "job_id": job_id,
                "status": status,
                "assistant_message": None,
                "evidence": [],
                "limitations": [],
                "work_item": _project_work_item(job.get("work_item")),
                "progress_state": _project_progress_state(job.get("progress_state")),
                "attachment_workflows": _attachment_workflows_for_job(
                    job,
                    job.get("attachment_workflows"),
                ),
                "analysis_progress": build_analysis_progress(job),
            },
        )

    executions = [
        {
            "node_code": item.get("node_code"),
            "agent_output": deepcopy(item),
        }
        for item in job.get("agent_results", [])
        if isinstance(item, dict)
    ]
    composition_input = {
        "job_id": job_id,
        "status_counts": deepcopy(job.get("status_counts") or {}),
        "executions": executions,
        "supervisor_state": deepcopy(job.get("supervisor_state") or {}),
        "attachments": deepcopy(job.get("attachments") or []),
    }
    if job.get("routing_intent"):
        composition_input["routing_intent"] = str(job["routing_intent"])
    composed = compose_response(composition_input)
    result = _project_mapping(composed, _COMPOSED_RESULT_FIELDS)
    # The repository status is the canonical terminal outcome.  Recomputing it
    # from a mixture of successful and failed node rows can incorrectly turn a
    # Supervisor-gated failure into a public "partial" result.
    result["status"] = status
    cards = _merge_display_cards(
        composed_cards=result.get("cards"),
        persisted_cards=job.get("cards"),
    )
    result.update(
        {
            "cards": cards,
            "pending_questions": deepcopy(job.get("pending_questions") or []),
            "report_links": _project_report_links(job.get("report_links")),
            "attachments": _project_attachments(job.get("attachments")),
            "attachment_workflows": _attachment_workflows_for_job(
                job,
                composed.get("attachment_workflows"),
            ),
            "reporting_payload": _project_reporting_payload(job.get("reporting_payload")),
            "supervisor_state": _project_supervisor_state(job.get("supervisor_state")),
            "user_claims": _project_user_claims(job.get("supervisor_state")),
            "supervisor_execution": _project_supervisor_execution(
                job.get("supervisor_execution")
            ),
            "work_item": _project_work_item(job.get("work_item")),
            "progress_state": _project_progress_state(job.get("progress_state")),
        }
    )
    result["analysis_progress"] = build_analysis_progress(
        job,
        composed_result=result,
    )
    return AnalysisJobQueryOutcome(kind="completed", payload=result)


def _project_mapping(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {field: deepcopy(value[field]) for field in fields if field in value}


def _project_analysis_job_detail(
    job: dict[str, Any],
    progress_cache: Any,
) -> dict[str, Any]:
    """Expose only the persisted fields the public restore flow consumes."""

    projected = _project_mapping(job, _DETAIL_SCALAR_FIELDS)
    projected.update(
        {
            "progress_state": _project_progress_state(job.get("progress_state")),
            "progress_cache": _project_public_progress_cache(progress_cache),
            "work_item": _project_work_item(job.get("work_item")),
            "assistant_message_payload": _project_assistant_message_payload(
                job.get("assistant_message_payload")
            ),
            "attachments": _project_attachments(job.get("attachments")),
            "attachment_workflows": _attachment_workflows_for_job(
                job,
                job.get("attachment_workflows"),
            ),
            "report_links": _project_report_links(job.get("report_links")),
            "limitations": _safe_public_limitations(job.get("limitations")),
            "reporting_payload": _project_reporting_payload(job.get("reporting_payload")),
            "supervisor_state": _project_supervisor_state(job.get("supervisor_state")),
            "supervisor_execution": _project_supervisor_execution(
                job.get("supervisor_execution")
            ),
            "reports": _project_report_summaries(job.get("reports")),
        }
    )
    projected["analysis_progress"] = build_analysis_progress(
        job,
        composed_result=projected,
    )
    return projected


def _project_assistant_message_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _project_mapping(value, _ASSISTANT_MESSAGE_PAYLOAD_FIELDS)


def _project_public_progress_cache(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    projected = _project_mapping(value, _PUBLIC_PROGRESS_CACHE_FIELDS)
    snapshot = value.get("snapshot")
    if isinstance(snapshot, dict):
        projected["snapshot"] = _project_mapping(
            snapshot, _PUBLIC_PROGRESS_SNAPSHOT_FIELDS
        )
    return projected


def _project_attachments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        _project_public_scalar_mapping(item, _PUBLIC_ATTACHMENT_FIELDS)
        for item in value
        if isinstance(item, dict)
    ]


def _project_attachment_workflows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    workflows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "").strip()
        next_action = str(item.get("next_action") or "").strip()
        attachment_id = str(item.get("attachment_id") or "").strip()
        if (
            item.get("contract_version") != "attachment_workflow.v1"
            or state not in ATTACHMENT_WORKFLOW_STATES
            or not attachment_id
            or re.fullmatch(r"[a-z_]+", next_action) is None
        ):
            continue
        workflows.append(
            {
                "contract_version": "attachment_workflow.v1",
                "attachment_id": attachment_id,
                "state": state,
                "next_action": next_action,
                "retryable": item.get("retryable") is True,
                "missing_fields": [
                    field.strip()
                    for field in item.get("missing_fields") or []
                    if isinstance(field, str) and field.strip()
                ],
                "limitations": _safe_public_limitations(item.get("limitations")),
            }
        )
    return workflows


def _attachment_workflows_for_job(
    job: dict[str, Any],
    composed_workflows: Any,
) -> list[dict[str, Any]]:
    projected = _project_attachment_workflows(composed_workflows)
    if projected:
        return projected

    structured_results: dict[str, Any] = {}
    for result in job.get("agent_results") or []:
        if not isinstance(result, dict):
            continue
        node_code = str(result.get("node_code") or "").strip()
        structured_result = result.get("structured_result")
        if not node_code or not isinstance(structured_result, dict):
            continue
        existing = structured_results.get(node_code)
        if existing is None:
            structured_results[node_code] = structured_result
        elif isinstance(existing, list):
            existing.append(structured_result)
        else:
            structured_results[node_code] = [existing, structured_result]

    return build_attachment_workflows(
        attachments=[
            item
            for item in job.get("attachments") or []
            if isinstance(item, dict)
        ],
        structured_results=structured_results,
        active_node=str(job.get("active_node") or ""),
        overall_status=str(job.get("status") or ""),
        ocr_confirmation=(
            job.get("ocr_confirmation")
            if isinstance(job.get("ocr_confirmation"), dict)
            else None
        ),
    )


def _project_report_links(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        projected
        for item in value
        if isinstance(item, dict)
        and (projected := _project_public_scalar_mapping(item, _PUBLIC_REPORT_LINK_FIELDS))
    ]


def _project_report_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    reports = []
    for item in value:
        if not isinstance(item, dict):
            continue
        report = _project_public_scalar_mapping(item, _PUBLIC_REPORT_SUMMARY_FIELDS)
        report["report_quality"] = {
            "public_quality_summary": _project_public_quality_summary(
                _dict_or_empty(item.get("report_quality")).get("public_quality_summary")
            )
        }
        reports.append(report)
    return reports


def _project_reporting_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _project_mapping(value, _REPORTING_PAYLOAD_FIELDS)


def _project_supervisor_state(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    projected = _project_mapping(value, _SUPERVISOR_STATE_FIELDS)
    if "fact_conflicts" in value:
        projected["fact_conflicts"] = normalize_fact_conflicts(
            value.get("fact_conflicts")
        )
    packages = value.get("agent_input_packages")
    if isinstance(packages, list):
        projected["agent_input_packages"] = [
            {"node_code": item["node_code"]}
            for item in packages
            if isinstance(item, dict) and isinstance(item.get("node_code"), str)
        ]
    return projected


def _project_user_claims(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, dict):
        return []
    case_evidence = value.get("case_evidence")
    if not isinstance(case_evidence, dict):
        return []
    claims = case_evidence.get("claims")
    if not isinstance(claims, dict):
        return []

    projected: list[dict[str, str | None]] = []
    for field in sorted(claims):
        claim = claims.get(field)
        if not isinstance(field, str) or not field.strip() or not isinstance(claim, dict):
            continue
        value = claim.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        evidence_source = claim.get("evidence_source")
        source_type = (
            evidence_source["source_type"].strip()
            if isinstance(evidence_source, dict)
            and isinstance(evidence_source.get("source_type"), str)
            and evidence_source["source_type"].strip()
            else None
        )
        projected.append(
            {
                "field": field.strip(),
                "value": value.strip(),
                "source_type": source_type,
            }
        )
    return projected


def _project_supervisor_execution(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    projected = _project_mapping(value, _SUPERVISOR_EXECUTION_FIELDS)
    work_item = _project_work_item(value.get("work_item"))
    if work_item is not None:
        projected["work_item"] = work_item
    projected["node_results"] = []
    for item in value.get("node_results", []):
        if not isinstance(item, dict):
            continue
        node = _project_mapping(item, _NODE_RESULT_FIELDS)
        if item.get("node_code") == "law_ground_search":
            if "limitations" in item:
                node["limitations"] = _safe_public_limitations(item.get("limitations"))
            node["structured_result"] = _project_public_law_ground_structured_result(
                item.get("structured_result")
            )
        else:
            node.pop("structured_result", None)
            node.pop("limitations", None)
        projected["node_results"].append(node)
    return projected


def _project_public_quality_summary(value: Any) -> dict[str, Any] | None:
    source = value if isinstance(value, dict) else {}
    source_retrieval = source.get("retrieval")
    fallback_retrieval = source.get("_fallback_retrieval")
    retrieval = {}
    if isinstance(fallback_retrieval, dict):
        retrieval.update(fallback_retrieval)
    if isinstance(source_retrieval, dict):
        retrieval.update(source_retrieval)
    limitations = _safe_public_limitations(source.get("limitations"))
    status = _safe_public_status(source.get("status")) or _safe_public_status(retrieval.get("status")) or "unavailable"
    partial_result = (
        bool(source["partial_result"])
        if "partial_result" in source
        else status == "partial"
    )
    review_required = (
        bool(source["review_required"])
        if "review_required" in source
        else partial_result or bool(limitations)
    )
    result_count = source.get("retrieval", {}).get("result_count") if isinstance(source.get("retrieval"), dict) else None
    if result_count is None:
        result_count = retrieval.get("result_count")
    if not isinstance(result_count, int) or isinstance(result_count, bool):
        result_count = None
    backend = _safe_backend(retrieval.get("backend_label") or retrieval.get("backend"))
    used_fallback = source.get("retrieval", {}).get("used_fallback") if isinstance(source.get("retrieval"), dict) else None
    if used_fallback is None:
        used_fallback = bool(retrieval.get("fallback_from")) or retrieval.get("attempted_backends") == "multiple"
    return {
        "status": status,
        "partial_result": partial_result,
        "review_required": review_required,
        "freshness": _project_public_freshness(
            source.get("freshness") or source.get("_fallback_freshness")
        ),
        "retrieval": {
            "backend_label": backend,
            "result_count": result_count,
            "used_fallback": bool(used_fallback),
        },
        "limitation_count": len(limitations),
        "limitations": limitations,
    }


def project_public_quality_summary(value: Any) -> dict[str, Any] | None:
    """Expose the canonical public quality contract to report DTO projections."""

    return _project_public_quality_summary(value)


def project_public_law_quality_summary(value: Any) -> dict[str, Any] | None:
    """Build the public quality summary from a raw law-ground structured result."""

    structured = _project_public_law_ground_structured_result(value)
    summary = structured.get("public_quality_summary")
    return summary if isinstance(summary, dict) else None


def _project_public_law_ground_structured_result(value: Any) -> dict[str, Any]:
    source = _dict_or_empty(value)
    structured: dict[str, Any] = {
        "matched_laws": project_public_law_items(source),
    }
    if "freshness" in source:
        structured["freshness"] = _project_public_freshness(source.get("freshness"))

    retrieval = _project_public_retrieval(source.get("retrieval"))
    if retrieval:
        structured["retrieval"] = retrieval
    quality_source_raw = source.get("public_quality_summary")
    has_quality_source = isinstance(quality_source_raw, dict)
    freshness = structured.get("freshness")
    if has_quality_source or retrieval or freshness:
        quality_source = dict(quality_source_raw) if has_quality_source else {}
        quality_source["_fallback_retrieval"] = retrieval
        quality_source["_fallback_freshness"] = freshness
        summary = _project_public_quality_summary(quality_source)
        if isinstance(summary, dict):
            structured["public_quality_summary"] = summary
    return structured


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _project_public_law_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    projected: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            projected.append(_project_public_scalar_mapping(item, _PUBLIC_LAW_ITEM_FIELDS))
            continue
        if _is_public_scalar(item):
            projected.append(deepcopy(item))
    return projected


def _project_public_scalar_mapping(value: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: deepcopy(value[field])
        for field in fields
        if field in value and _is_public_scalar(value[field])
    }


def _is_public_scalar(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        return False
    return not any(marker in value for marker in ("://", "\\", "/", "?", "&"))


def _project_public_freshness(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    projected = {
        field: freshness
        for field in ("effective_at", "retrieved_at")
        if (freshness := _safe_public_freshness(value.get(field))) is not None
    }
    limitation = _safe_public_limitation(value.get("limitation"))
    if limitation:
        projected["limitation"] = limitation
    return projected


def _project_public_retrieval(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    projected = _project_public_scalar_mapping(
        value, ("status", "result_count", "retrieved_at", "effective_at")
    )
    backend = _safe_backend(value.get("backend"))
    if backend:
        projected["backend"] = backend
    if "fallback_from" in value:
        projected["fallback_from"] = bool(value.get("fallback_from"))
    if "attempted_backends" in value:
        projected["attempted_backends"] = _public_backend_attempt_status(value.get("attempted_backends"))
    return projected


def _public_backend_attempt_status(value: Any) -> str:
    if not isinstance(value, list):
        return "none"
    return "multiple" if len(value) > 1 else "single" if value else "none"


def _safe_backend(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    backend = value.strip()
    return backend if backend in _SAFE_PUBLIC_BACKENDS else None


def _safe_public_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and _is_public_scalar(value) else None


def safe_public_confidence_label(value: Any) -> str | None:
    return value if isinstance(value, str) and value in _SAFE_PUBLIC_CONFIDENCE_LABELS else None


def _safe_public_status(value: Any) -> str | None:
    return value if isinstance(value, str) and value in _SAFE_PUBLIC_STATUSES else None


def _safe_public_freshness(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _SAFE_PUBLIC_DATE_RE.fullmatch(value) or _SAFE_PUBLIC_DATETIME_RE.fullmatch(value) else None


def _safe_public_limitation(value: Any) -> str | None:
    return value if isinstance(value, str) and value in _SAFE_PUBLIC_LIMITATIONS else None


def _safe_public_limitations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [limitation for item in value if (limitation := _safe_public_limitation(item))]


def safe_public_limitations(value: Any) -> list[str]:
    return _safe_public_limitations(value)


def _project_work_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    projected = _project_mapping(value, _WORK_ITEM_FIELDS)
    if "progress_state" in value:
        projected["progress_state"] = _project_progress_state(value.get("progress_state"))
    return projected


def _project_progress_state(value: Any) -> dict[str, Any]:
    return _project_mapping(value, _PROGRESS_STATE_FIELDS)


def _merge_display_cards(
    *,
    composed_cards: Any,
    persisted_cards: Any,
) -> list[dict[str, Any]]:
    deadline_cards = [
        deepcopy(card)
        for card in composed_cards or []
        if isinstance(card, dict) and card.get("card_type") == "deadline_guidance"
    ]
    stored_cards = [deepcopy(card) for card in persisted_cards or [] if isinstance(card, dict)]
    return deadline_cards + [card for card in stored_cards if card not in deadline_cards]
