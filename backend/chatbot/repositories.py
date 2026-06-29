"""Repository helpers for canonical API persistence boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from django.db import transaction

from app.services.attachment_mock_service import (
    register_attachment as register_mock_attachment,
)
from chatbot.models import (
    AgentResult,
    AgentResultStatus,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobEvent,
    AnalysisJobStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    MessageRole,
    Report,
    ReportStatus,
    ReportType,
    UploadedFile,
    UploadedFileStatus,
)


def register_uploaded_file(
    payload: dict[str, Any],
    upload_file: Any | None = None,
) -> dict[str, Any]:
    """Register a canonical file upload and persist its metadata in Django DB.

    The byte/object storage path still goes through the mock local storage
    service until the object-storage adapter is introduced.
    """

    attachment = register_mock_attachment(payload, upload_file=upload_file)
    owner_id = _owner_id(payload)
    return persist_uploaded_file_metadata(attachment, owner_id=owner_id, raw_payload=payload)


def persist_uploaded_file_metadata(
    attachment: dict[str, Any],
    *,
    owner_id: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = _get_or_create_session(attachment.get("session_id"), owner_id=owner_id)
    metadata = _metadata_snapshot(attachment, raw_payload=raw_payload)

    with transaction.atomic():
        uploaded_file, _created = UploadedFile.objects.update_or_create(
            attachment_id=_text(attachment.get("attachment_id")),
            defaults={
                "owner_id": owner_id or (session.owner_id if session else ""),
                "session": session,
                "purpose": _text(attachment.get("purpose")) or "unknown",
                "file_type": _text(attachment.get("type")),
                "original_filename": _text(attachment.get("original_filename")),
                "content_type": _text(attachment.get("content_type")),
                "size_bytes": _positive_int_or_none(attachment.get("size_bytes")),
                "storage_uri": _text(attachment.get("storage_uri")),
                "privacy_risk": True,
                "status": _model_status(attachment.get("status")),
                "scan_status": "not_started",
                "agent_handoff": attachment.get("agent_handoff") or {},
                "metadata": metadata,
            },
        )

    return uploaded_file_to_api(uploaded_file)


def list_uploaded_files(session_id: str | None = None) -> list[dict[str, Any]]:
    queryset = UploadedFile.objects.select_related("session").order_by("-created_at")
    if session_id:
        queryset = queryset.filter(session__session_id=session_id)
    return [uploaded_file_to_api(uploaded_file) for uploaded_file in queryset]


def get_uploaded_file(attachment_id: str) -> dict[str, Any] | None:
    uploaded_file = (
        UploadedFile.objects.select_related("session")
        .filter(attachment_id=attachment_id)
        .first()
    )
    if uploaded_file is None:
        return None
    return uploaded_file_to_api(uploaded_file)


def persist_chat_message_analysis_boundary(
    payload: dict[str, Any],
    chat_response: dict[str, Any],
) -> dict[str, Any]:
    """Persist the canonical chat message and its analysis-job boundary."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(chat_response.get("session_id"), owner_id=owner_id)
    if session is None:
        raise ValueError("chat_response must include session_id")

    message_id = _text(chat_response.get("message_id"))
    analysis_plan = chat_response.get("analysis_plan") or {}
    progress = chat_response.get("progress") or {}
    job_id = _analysis_job_id(payload, chat_response)

    with transaction.atomic():
        message, _message_created = ChatMessage.objects.update_or_create(
            message_id=message_id,
            defaults={
                "session": session,
                "role": MessageRole.USER,
                "content": _message_content(payload),
                "routing_intent": _text(chat_response.get("routing_intent")),
                "metadata": {
                    "source": "canonical_chat_message",
                    "analysis_job_id": job_id,
                    "mock_scenario": chat_response.get("mock_scenario"),
                    "mock_status": payload.get("mock_status"),
                    "response_status": chat_response.get("status"),
                    "attachments": chat_response.get("attachments", []),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "raw_payload": _safe_payload(payload),
                },
            },
        )
        job, _job_created = AnalysisJob.objects.update_or_create(
            job_id=job_id,
            defaults={
                "session": session,
                "message": message,
                "owner_id": owner_id or session.owner_id,
                "routing_intent": _text(chat_response.get("routing_intent")),
                "mock_scenario": _text(chat_response.get("mock_scenario")),
                "status": _analysis_job_status(chat_response.get("status")),
                "active_node": _text(progress.get("active_node")),
                "progress_message": _text(progress.get("message")),
                "analysis_plan_id": _text(analysis_plan.get("plan_id")),
                "status_counts": _analysis_plan_status_counts(analysis_plan),
                "metadata": {
                    "source": "canonical_chat_message",
                    "analysis_plan": analysis_plan,
                    "assistant_message": chat_response.get("assistant_message"),
                    "case_status": chat_response.get("case_status"),
                    "cards": chat_response.get("cards", []),
                    "pending_questions": chat_response.get("pending_questions", []),
                    "report_links": chat_response.get("report_links", []),
                    "attachments": chat_response.get("attachments", []),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "limitations": chat_response.get("limitations", []),
                },
            },
        )
        _upsert_initial_job_event(job, progress=progress)

    return {
        "message_id": message.message_id,
        "job_id": job.job_id,
        "session_id": session.session_id,
    }


def persist_analysis_job_execution(
    payload: dict[str, Any],
    job_payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a canonical analysis job and its agent execution outputs."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(job_payload.get("session_id"), owner_id=owner_id)
    if session is None:
        raise ValueError("job_payload must include session_id")

    message_id = _text(job_payload.get("message_id"))
    job_id = _text(job_payload.get("job_id"))
    if not job_id:
        raise ValueError("job_payload must include job_id")

    chat_response = job_payload.get("chat_response") or {}
    analysis_plan = job_payload.get("analysis_plan") or chat_response.get("analysis_plan") or {}
    progress = {
        "active_node": job_payload.get("active_node"),
        "message": job_payload.get("progress_message"),
    }

    with transaction.atomic():
        message = None
        if message_id:
            message, _message_created = ChatMessage.objects.update_or_create(
                message_id=message_id,
                defaults={
                    "session": session,
                    "role": MessageRole.USER,
                    "content": _message_content(payload),
                    "routing_intent": _text(job_payload.get("routing_intent")),
                    "metadata": {
                        "source": "canonical_analysis_job",
                        "analysis_job_id": job_id,
                        "mock_scenario": job_payload.get("mock_scenario"),
                        "response_status": job_payload.get("status"),
                        "attachments": job_payload.get("attachments", []),
                        "attachment_resolution": job_payload.get("attachment_resolution", {}),
                        "raw_payload": _safe_payload(payload),
                    },
                },
            )

        job, _job_created = AnalysisJob.objects.update_or_create(
            job_id=job_id,
            defaults={
                "session": session,
                "message": message,
                "owner_id": owner_id or session.owner_id,
                "routing_intent": _text(job_payload.get("routing_intent")),
                "mock_scenario": _text(job_payload.get("mock_scenario")),
                "status": _analysis_job_status(job_payload.get("status")),
                "active_node": _text(job_payload.get("active_node")),
                "progress_message": _text(job_payload.get("progress_message")),
                "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
                "status_counts": job_payload.get("status_counts") or {},
                "metadata": {
                    "source": "canonical_analysis_job",
                    "analysis_plan": analysis_plan,
                    "assistant_message": chat_response.get("assistant_message"),
                    "case_status": chat_response.get("case_status"),
                    "cards": chat_response.get("cards", []),
                    "pending_questions": chat_response.get("pending_questions", []),
                    "report_links": chat_response.get("report_links", []),
                    "attachments": job_payload.get("attachments", []),
                    "attachment_resolution": job_payload.get("attachment_resolution", {}),
                    "limitations": job_payload.get("limitations", []),
                },
            },
        )
        _upsert_initial_job_event(job, progress=progress, source="canonical_analysis_job")
        agent_results = _persist_agent_results(job, job_payload.get("node_execution") or {})

    return {
        "backend": "postgresql",
        "tables": [AnalysisJob._meta.db_table, AgentResult._meta.db_table],
        "analysis_job_table": AnalysisJob._meta.db_table,
        "agent_results_table": AgentResult._meta.db_table,
        "agent_results_saved": len(agent_results),
        "agent_result_ids": [result.result_id for result in agent_results],
        "node_codes": [result.node_code for result in agent_results],
        "status": "saved",
    }


def persist_analysis_display_result(result_payload: dict[str, Any]) -> dict[str, Any]:
    """Persist the canonical Supervisor display snapshot for an analysis job."""

    job_id = _text(result_payload.get("job_id"))
    if not job_id:
        return _display_result_persistence_skipped("missing_job_id")

    job = AnalysisJob.objects.filter(job_id=job_id).first()
    if job is None:
        return _display_result_persistence_skipped("analysis_job_not_found")

    display_result, _created = AnalysisDisplayResult.objects.update_or_create(
        display_result_id=_display_result_id(job.job_id),
        defaults={
            "job": job,
            "assistant_message": _dict_or_empty(result_payload.get("assistant_message")),
            "progress": _list_or_empty(result_payload.get("progress")),
            "cards": _list_or_empty(result_payload.get("cards")),
            "pending_questions": _list_or_empty(result_payload.get("pending_questions")),
            "attachments": _list_or_empty(result_payload.get("attachments")),
            "report_links": _list_or_empty(result_payload.get("report_links")),
            "limitations": _list_or_empty(result_payload.get("limitations")),
        },
    )

    return {
        "backend": "postgresql",
        "table": AnalysisDisplayResult._meta.db_table,
        "display_result_id": display_result.display_result_id,
        "status": "saved",
    }


def persist_report_action(
    payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a canonical report action as report metadata."""

    report_id = _text(report_payload.get("report_id"))
    if not report_id:
        return _report_persistence_skipped("missing_report_id")

    owner_id = _owner_id(payload)
    job = AnalysisJob.objects.filter(job_id=_text(payload.get("job_id"))).first()
    session = job.session if job else _get_or_create_session(payload.get("session_id"), owner_id=owner_id)
    display_result = _display_result_for_job(job)

    report, _created = Report.objects.update_or_create(
        report_id=report_id,
        defaults={
            "owner_id": owner_id or (job.owner_id if job else "") or (session.owner_id if session else ""),
            "session": session,
            "job": job,
            "display_result": display_result,
            "report_type": _report_type(payload.get("report_type")),
            "status": _report_status(report_payload.get("status")),
            "title": _report_title(payload, report_payload),
            "storage_uri": _text(payload.get("storage_uri")) or f"mock://reports/{report_id}",
            "content_summary": _report_content_summary(display_result, report_payload),
            "content": {
                "format": _text(payload.get("format")) or "mock_text",
                "action": _text(payload.get("action")) or "save",
                "case_id": report_payload.get("case_id"),
                "download_url": report_payload.get("download_url"),
            },
            "metadata": {
                "source": "canonical_report_action",
                "action": _text(payload.get("action")) or "save",
                "mock_status": report_payload.get("status"),
                "limitations": report_payload.get("limitations", []),
                "object_storage_status": "mock_placeholder",
                "raw_payload": _safe_payload(payload),
            },
        },
    )

    return {
        "backend": "postgresql",
        "table": Report._meta.db_table,
        "report_id": report.report_id,
        "status": "metadata_saved",
        "storage_uri": report.storage_uri,
        "object_storage": "mock_placeholder",
    }


def get_report_download_metadata(report_id: str) -> dict[str, Any] | None:
    report = (
        Report.objects.select_related("session", "job", "display_result")
        .filter(report_id=report_id)
        .first()
    )
    if report is None:
        return None

    storage_uri = report.storage_uri or f"mock://reports/{report.report_id}"
    storage_backend = _storage_backend(storage_uri)
    return {
        "report_id": report.report_id,
        "filename": f"{report.report_id}.txt",
        "content_type": "text/plain; charset=utf-8",
        "storage_uri": storage_uri,
        "storage_backend": storage_backend,
        "status": report.status,
        "body": _report_download_body(report, storage_backend=storage_backend),
    }


def uploaded_file_to_api(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata or {}
    checks = dict(metadata.get("checks") or {})
    checks.setdefault("metadata_repository", UploadedFile._meta.db_table)
    limitations = list(metadata.get("limitations") or [])
    session_id = (
        uploaded_file.session.session_id
        if uploaded_file.session_id
        else metadata.get("session_id")
    )
    filename = metadata.get("filename") or Path(uploaded_file.original_filename).name

    attachment = {
        "attachment_id": uploaded_file.attachment_id,
        "session_id": session_id,
        "message_id": metadata.get("message_id"),
        "purpose": uploaded_file.purpose,
        "type": uploaded_file.file_type,
        "original_filename": uploaded_file.original_filename,
        "filename": filename,
        "content_type": uploaded_file.content_type,
        "size_bytes": uploaded_file.size_bytes or 0,
        "storage_uri": uploaded_file.storage_uri,
        "status": uploaded_file.status,
        "created_at": uploaded_file.created_at.isoformat(),
        "checks": checks,
        "agent_handoff": uploaded_file.agent_handoff or {},
        "limitations": limitations,
        "persistence": {
            "backend": "postgresql",
            "table": UploadedFile._meta.db_table,
            "status": "metadata_saved",
        },
    }
    return {key: value for key, value in attachment.items() if value is not None}


def _get_or_create_session(session_id: Any, *, owner_id: str) -> ChatSession | None:
    normalized_session_id = _text(session_id)
    if not normalized_session_id:
        return None

    session, _created = ChatSession.objects.get_or_create(
        session_id=normalized_session_id,
        defaults={
            "owner_id": owner_id,
            "status": ChatSessionStatus.ACTIVE,
            "metadata": {"created_by": "canonical_file_upload"},
        },
    )
    if owner_id and not session.owner_id:
        session.owner_id = owner_id
        session.save(update_fields=["owner_id", "updated_at"])
    return session


def _metadata_snapshot(
    attachment: dict[str, Any],
    *,
    raw_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "session_id": attachment.get("session_id"),
        "message_id": attachment.get("message_id"),
        "filename": attachment.get("filename"),
        "mock_status": attachment.get("status"),
        "checks": attachment.get("checks") or {},
        "limitations": attachment.get("limitations") or [],
        "raw_payload": _safe_payload(raw_payload or {}),
    }


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _owner_id(payload: dict[str, Any]) -> str:
    return _text(payload.get("owner_id") or payload.get("user_id"))


def _message_content(payload: dict[str, Any]) -> str:
    return _text(payload.get("user_text") or payload.get("message") or payload.get("content"))


def _analysis_job_id(payload: dict[str, Any], chat_response: dict[str, Any]) -> str:
    explicit_job_id = _text(payload.get("job_id"))
    if explicit_job_id:
        return explicit_job_id
    message_id = _text(chat_response.get("message_id"))
    if message_id.startswith("msg_"):
        return f"job_{message_id.removeprefix('msg_')}"
    return f"job_{message_id}"


def _analysis_job_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in AnalysisJobStatus}:
        return status_text
    if status_text == "pending":
        return AnalysisJobStatus.RUNNING
    return AnalysisJobStatus.RUNNING


def _analysis_plan_status_counts(analysis_plan: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    steps = analysis_plan.get("steps") or []
    for step in steps:
        if not isinstance(step, dict):
            continue
        status = _text(step.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _upsert_initial_job_event(
    job: AnalysisJob,
    *,
    progress: dict[str, Any],
    source: str = "canonical_chat_message",
) -> None:
    status = job.status
    active_node = _text(progress.get("active_node"))
    message = _text(progress.get("message")) or "canonical chat message에서 분석 job 경계를 생성했습니다."
    first_event = job.events.order_by("created_at").first()
    if first_event is None:
        AnalysisJobEvent.objects.create(
            job=job,
            status=status,
            active_node=active_node,
            message=message,
            metadata={"source": source},
        )
        return

    first_event.status = status
    first_event.active_node = active_node
    first_event.message = message
    first_event.metadata = {"source": source}
    first_event.save(update_fields=["status", "active_node", "message", "metadata"])


def _persist_agent_results(
    job: AnalysisJob,
    node_execution: dict[str, Any],
) -> list[AgentResult]:
    executions = node_execution.get("executions") or []
    agent_results = []
    for index, execution in enumerate(executions, start=1):
        if not isinstance(execution, dict):
            continue

        agent_output = execution.get("agent_output") or {}
        if not isinstance(agent_output, dict):
            continue

        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        if not node_code:
            continue

        agent_result, _created = AgentResult.objects.update_or_create(
            result_id=_agent_result_id(job.job_id, node_code, index),
            defaults={
                "job": job,
                "node_code": node_code,
                "node_name": _text(agent_output.get("node_name")),
                "status": _agent_result_status(agent_output.get("status")),
                "summary": _text(agent_output.get("summary")),
                "structured_result": _dict_or_empty(agent_output.get("structured_result")),
                "evidence": _list_or_empty(agent_output.get("evidence")),
                "next_actions": _list_or_empty(agent_output.get("next_actions")),
                "limitations": _list_or_empty(agent_output.get("limitations")),
                "raw_output": _agent_result_raw_output(execution, agent_output),
            },
        )
        agent_results.append(agent_result)
    return agent_results


def _agent_result_id(job_id: str, node_code: str, index: int) -> str:
    readable_id = f"res_{job_id}_{index}_{node_code}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{index}:{node_code}".encode("utf-8")).hexdigest()[:16]
    return f"res_{digest}_{index}"


def _display_result_id(job_id: str) -> str:
    readable_id = f"disp_{job_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:20]
    return f"disp_{digest}"


def _display_result_for_job(job: AnalysisJob | None) -> AnalysisDisplayResult | None:
    if job is None:
        return None
    try:
        return job.display_result
    except AnalysisDisplayResult.DoesNotExist:
        return None


def _agent_result_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in AgentResultStatus}:
        return status_text
    if status_text in {"pending", "running", "blocked"}:
        return AgentResultStatus.PARTIAL
    return AgentResultStatus.SUCCESS


def _agent_result_raw_output(
    execution: dict[str, Any],
    agent_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source": "mock_node_execution",
        "execution_id": execution.get("execution_id"),
        "execution_mode": execution.get("execution_mode"),
        "adapter_context": execution.get("adapter_context") or {},
        "plan_step": execution.get("plan_step") or {},
        "agent_output": agent_output,
        "created_at": agent_output.get("created_at") or execution.get("created_at"),
    }


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _display_result_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "table": AnalysisDisplayResult._meta.db_table,
        "status": "skipped",
        "reason": reason,
    }


def _report_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "table": Report._meta.db_table,
        "status": "skipped",
        "reason": reason,
    }


def _report_type(value: Any) -> str:
    report_type = _text(value)
    if report_type in {choice.value for choice in ReportType}:
        return report_type
    return ReportType.OBJECTION_DRAFT


def _report_status(value: Any) -> str:
    status = _text(value)
    if status in {choice.value for choice in ReportStatus}:
        return status
    if status in {"downloaded", "report_saved", "saved", "success"}:
        return ReportStatus.READY
    if status == "failed":
        return ReportStatus.FAILED
    return ReportStatus.READY


def _report_title(payload: dict[str, Any], report_payload: dict[str, Any]) -> str:
    return (
        _text(payload.get("title"))
        or _text(report_payload.get("title"))
        or _text(payload.get("action"))
        or "report"
    )


def _report_content_summary(
    display_result: AnalysisDisplayResult | None,
    report_payload: dict[str, Any],
) -> str:
    if display_result and isinstance(display_result.assistant_message, dict):
        summary = _text(display_result.assistant_message.get("summary"))
        if summary:
            return summary
        answer = _text(display_result.assistant_message.get("answer"))
        if answer:
            return answer[:500]
    return f"Mock report action result: {_text(report_payload.get('status')) or 'ready'}"


def _storage_backend(storage_uri: str) -> str:
    if storage_uri.startswith("mock://"):
        return "mock_placeholder"
    if storage_uri.startswith("s3://"):
        return "object_storage"
    if storage_uri.startswith("file://"):
        return "local_file"
    return "unknown"


def _report_download_body(report: Report, *, storage_backend: str) -> str:
    lines = [
        f"Report metadata download for {report.report_id}",
        f"status: {report.status}",
        f"storage_backend: {storage_backend}",
        f"storage_uri: {report.storage_uri}",
    ]
    if report.job_id:
        lines.append(f"job_id: {report.job.job_id}")
    if report.display_result_id:
        lines.append(f"display_result_id: {report.display_result.display_result_id}")
    if report.content_summary:
        lines.append("")
        lines.append(report.content_summary)
    return "\n".join(lines) + "\n"


def _model_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in UploadedFileStatus}:
        return status_text
    if status_text == "metadata_registered":
        return UploadedFileStatus.UPLOADED
    return UploadedFileStatus.UPLOADED


def _positive_int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
