"""Public semantic progress projection for persisted analysis jobs."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


ANALYSIS_SEMANTIC_STATUSES = frozenset(
    {"queued", "running", "partial", "failed", "needs_input", "success"}
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")
_CONFIRMATION_WORKFLOW_STATES = frozenset(
    {"classified_waiting_confirmation", "ocr_needs_confirmation"}
)
_SEMANTIC_PRESENTATION = {
    "queued": (
        False,
        True,
        "continue_polling",
        "분석 요청이 대기 중입니다. 순서가 되면 자동으로 진행됩니다.",
    ),
    "running": (
        False,
        True,
        "continue_polling",
        "분석이 진행 중입니다. 확인된 결과는 완료되는 대로 표시됩니다.",
    ),
    "needs_input": (
        True,
        False,
        "provide_requested_input",
        "분석을 계속하려면 표시된 확인 항목에 답해 주세요.",
    ),
    "partial": (
        True,
        False,
        "review_partial_result",
        "확인된 결과만 표시했습니다. 한계와 추가 확인 사항을 검토해 주세요.",
    ),
    "failed": (
        True,
        False,
        "review_failure_guidance",
        "분석을 완료하지 못했습니다. 표시된 다음 행동을 확인해 주세요.",
    ),
    "success": (
        True,
        False,
        "review_result",
        "분석이 완료되었습니다.",
    ),
}


def build_analysis_progress(
    job: Mapping[str, Any],
    *,
    composed_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed user-task status independently of worker success."""

    source = job if isinstance(job, Mapping) else {}
    composed = composed_result if isinstance(composed_result, Mapping) else {}
    semantic_status = _semantic_status(source, composed)
    terminal, retryable, next_action, user_message = _SEMANTIC_PRESENTATION[
        semantic_status
    ]
    if semantic_status in {"partial", "failed"} and _explicitly_retryable(
        source, composed
    ):
        retryable = True
        next_action = "retry_polling"

    work_item = source.get("work_item")
    work_item = work_item if isinstance(work_item, Mapping) else {}
    return {
        "contract_version": "analysis_progress.v1",
        "semantic_status": semantic_status,
        "terminal": terminal,
        "retryable": retryable,
        "next_action": next_action,
        "user_message": user_message,
        "job_id": _safe_identifier(source.get("job_id")),
        "correlation_id": _safe_identifier(work_item.get("work_item_id")),
    }


def _semantic_status(
    job: Mapping[str, Any],
    composed: Mapping[str, Any],
) -> str:
    job_status = str(job.get("status") or "").strip().lower()
    work_item = job.get("work_item")
    work_item = work_item if isinstance(work_item, Mapping) else {}
    work_status = str(work_item.get("status") or "").strip().lower()

    if job_status == "queued":
        return "queued"
    if job_status == "running" or work_status in {"running", "retrying"}:
        return "running"
    if _requires_user_input(job, composed):
        return "needs_input"
    if job_status == "failed":
        return "failed"
    if (
        job_status == "partial"
        or _has_items(job.get("limitations"))
        or _has_items(composed.get("limitations"))
        or _has_partial_agent_result(job.get("agent_results"))
    ):
        return "partial"
    if job_status == "success":
        return "success" if _has_user_result(composed) else "partial"
    return "failed"


def _requires_user_input(
    job: Mapping[str, Any],
    composed: Mapping[str, Any],
) -> bool:
    for source in (job, composed):
        if _has_items(source.get("pending_questions")):
            return True
        supervisor_state = source.get("supervisor_state")
        if isinstance(supervisor_state, Mapping) and _has_items(
            supervisor_state.get("fact_conflicts")
        ):
            return True
        workflows = source.get("attachment_workflows")
        if isinstance(workflows, Sequence) and not isinstance(
            workflows, (str, bytes, bytearray)
        ):
            if any(
                isinstance(item, Mapping)
                and str(item.get("state") or "") in _CONFIRMATION_WORKFLOW_STATES
                for item in workflows
            ):
                return True
    return False


def _explicitly_retryable(
    job: Mapping[str, Any],
    composed: Mapping[str, Any],
) -> bool:
    for source in (job, composed):
        work_item = source.get("work_item")
        progress_state = source.get("progress_state")
        if isinstance(work_item, Mapping) and work_item.get("retryable") is True:
            return True
        if (
            isinstance(progress_state, Mapping)
            and progress_state.get("retryable") is True
        ):
            return True
        workflows = source.get("attachment_workflows")
        if isinstance(workflows, Sequence) and not isinstance(
            workflows, (str, bytes, bytearray)
        ):
            if any(
                isinstance(item, Mapping) and item.get("retryable") is True
                for item in workflows
            ):
                return True
    return False


def _has_partial_agent_result(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ) and any(
        isinstance(item, Mapping)
        and str(item.get("status") or "").strip().lower() == "partial"
        for item in value
    )


def _has_user_result(value: Mapping[str, Any]) -> bool:
    assistant = value.get("assistant_message")
    if isinstance(assistant, str) and assistant.strip():
        return True
    if isinstance(assistant, Mapping) and any(
        str(assistant.get(field) or "").strip() for field in ("answer", "summary")
    ):
        return True
    return any(
        _has_items(value.get(field))
        for field in ("structured_results", "cards", "report_links")
    )


def _has_items(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and bool(value)
    )


def _safe_identifier(value: Any) -> str | None:
    identifier = str(value or "").strip()
    return identifier if _IDENTIFIER_RE.fullmatch(identifier) else None
