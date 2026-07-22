"""Application service for reading analysis jobs and their public results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal


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

    job = deepcopy(stored_job)
    job["progress_cache"] = deepcopy(load_progress(job_id))
    return AnalysisJobQueryOutcome(kind="detail", payload=job)


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
    composed = compose_response(
        {
            "job_id": job_id,
            "status_counts": deepcopy(job.get("status_counts") or {}),
            "executions": executions,
            "supervisor_state": deepcopy(job.get("supervisor_state") or {}),
            "attachments": deepcopy(job.get("attachments") or []),
        }
    )
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
            "report_links": deepcopy(job.get("report_links") or []),
            "attachments": deepcopy(job.get("attachments") or []),
            "reporting_payload": _project_reporting_payload(job.get("reporting_payload")),
            "supervisor_state": _project_supervisor_state(job.get("supervisor_state")),
            "supervisor_execution": _project_supervisor_execution(
                job.get("supervisor_execution")
            ),
            "work_item": _project_work_item(job.get("work_item")),
            "progress_state": _project_progress_state(job.get("progress_state")),
        }
    )
    return AnalysisJobQueryOutcome(kind="completed", payload=result)


def _project_mapping(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {field: deepcopy(value[field]) for field in fields if field in value}


def _project_reporting_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _project_mapping(value, _REPORTING_PAYLOAD_FIELDS)


def _project_supervisor_state(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    projected = _project_mapping(value, _SUPERVISOR_STATE_FIELDS)
    packages = value.get("agent_input_packages")
    if isinstance(packages, list):
        projected["agent_input_packages"] = [
            {"node_code": item["node_code"]}
            for item in packages
            if isinstance(item, dict) and isinstance(item.get("node_code"), str)
        ]
    return projected


def _project_supervisor_execution(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    projected = _project_mapping(value, _SUPERVISOR_EXECUTION_FIELDS)
    work_item = _project_work_item(value.get("work_item"))
    if work_item is not None:
        projected["work_item"] = work_item
    projected["node_results"] = [
        _project_mapping(item, _NODE_RESULT_FIELDS)
        for item in value.get("node_results", [])
        if isinstance(item, dict)
    ]
    return projected


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
