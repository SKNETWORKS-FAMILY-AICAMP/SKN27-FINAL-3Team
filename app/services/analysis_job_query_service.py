"""Application service for reading analysis jobs and their public results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal


AnalysisQueryKind = Literal["not_found", "detail", "pending", "completed"]
JobLoader = Callable[[str], dict[str, Any] | None]
ProgressLoader = Callable[[str], dict[str, Any] | None]
ResponseComposer = Callable[[dict[str, Any]], dict[str, Any]]


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
                "structured_results": {},
                "evidence": [],
                "limitations": [],
                "work_item": deepcopy(job.get("work_item")),
                "progress_state": deepcopy(job.get("progress_state") or {}),
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
    result = compose_response(
        {
            "job_id": job_id,
            "status_counts": deepcopy(job.get("status_counts") or {}),
            "executions": executions,
            "supervisor_state": deepcopy(job.get("supervisor_state") or {}),
            "attachments": deepcopy(job.get("attachments") or []),
        }
    )
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
            "reporting_payload": deepcopy(job.get("reporting_payload") or None),
            "supervisor_reporting_handoff": deepcopy(
                job.get("supervisor_reporting_handoff") or None
            ),
            "reporting_pipeline": deepcopy(job.get("reporting_pipeline") or None),
            "supervisor_state": deepcopy(job.get("supervisor_state") or None),
            "supervisor_execution": deepcopy(job.get("supervisor_execution") or None),
            "work_item": deepcopy(job.get("work_item")),
            "progress_state": deepcopy(job.get("progress_state") or {}),
        }
    )
    return AnalysisJobQueryOutcome(kind="completed", payload=result)


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
