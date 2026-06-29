"""Repository helpers for canonical API persistence boundaries."""

from __future__ import annotations

import hashlib
from datetime import timedelta, timezone as datetime_timezone
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.services.attachment_mock_service import (
    register_attachment as register_mock_attachment,
)
from app.services.history_event_mock_service import (
    build_agent_execution_events,
    build_history_event,
)
from chatbot.models import (
    AgentInvocation,
    AgentInvocationStatus,
    AgentNodeDefinition,
    AgentResult,
    AgentResultStatus,
    AiSession,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobEvent,
    AnalysisJobStatus,
    AuthEvent,
    AuthSession,
    AuthSessionStatus,
    ChatMessage,
    ChatSession,
    ChatSessionStatus,
    CodeGroup,
    CodeItem,
    GuestIdentity,
    GuestIdentityStatus,
    HistoryEvent,
    MessageRole,
    Report,
    ReportStatus,
    ReportType,
    Subscription,
    SubscriptionStatus,
    UsageEvent,
    UsageQuota,
    UserAccount,
    UserAccountStatus,
    UploadedFile,
    UploadedFileStatus,
)

USAGE_POLICY_GROUP_CODE = "usage_quota_policy"
USAGE_POLICY_LIMITS = {
    "anonymous": {
        "chat_message": 2,
        "file_upload": 1,
        "agent_run": 1,
        "report_action": 1,
    },
    "guest": {
        "chat_message": 5,
        "file_upload": 3,
        "agent_run": 3,
        "report_action": 2,
    },
    "free": {
        "chat_message": 100,
        "file_upload": 30,
        "agent_run": 30,
        "report_action": 30,
    },
    "paid": {
        "chat_message": 500,
        "file_upload": 100,
        "agent_run": 120,
        "report_action": 100,
    },
}


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


def list_uploaded_files(
    session_id: str | None = None,
    *,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    queryset = UploadedFile.objects.select_related("session").order_by("-created_at")
    if session_id:
        queryset = queryset.filter(session__session_id=session_id)
    if owner_id is not None:
        queryset = queryset.filter(owner_id=owner_id)
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


def get_uploaded_file_access_metadata(attachment_id: str) -> dict[str, Any] | None:
    uploaded_file = (
        UploadedFile.objects.select_related("session")
        .filter(attachment_id=attachment_id)
        .first()
    )
    if uploaded_file is None:
        return None
    session = uploaded_file.session
    return {
        "type": "uploaded_file",
        "attachment_id": uploaded_file.attachment_id,
        "owner_id": uploaded_file.owner_id or (session.owner_id if session else ""),
        "session_id": session.session_id if session else "",
        "guest_id": _chat_session_guest_id(session),
        "storage_backend": _storage_backend(uploaded_file.storage_uri),
    }


def get_chat_session_access_metadata(session_id: str | None) -> dict[str, Any] | None:
    normalized_session_id = _text(session_id)
    if not normalized_session_id:
        return None
    session = ChatSession.objects.filter(session_id=normalized_session_id).first()
    if session is None:
        return None
    return {
        "type": "chat_session",
        "session_id": session.session_id,
        "owner_id": session.owner_id,
        "guest_id": _chat_session_guest_id(session),
    }


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


def persist_guest_session_identity(
    auth_payload: dict[str, Any],
    *,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the guest identity preview returned by the auth mock contract."""

    guest_payload = _dict_or_empty(auth_payload.get("guest"))
    subject = _dict_or_empty(auth_payload.get("subject"))
    session_binding = _dict_or_empty(auth_payload.get("session_binding"))
    guest_id = _normalize_guest_id(guest_payload.get("guest_id") or subject.get("guest_id"))
    if not guest_id:
        return _auth_persistence_skipped("missing_guest_id")

    subject_id = _text(subject.get("subject_id")) or f"guest:{guest_id}"
    session_id = _text(session_binding.get("session_id"))
    expires_at = _datetime_or_none(guest_payload.get("expires_at"))

    with transaction.atomic():
        guest, _created = GuestIdentity.objects.update_or_create(
            guest_id=guest_id,
            defaults={
                "status": GuestIdentityStatus.ACTIVE,
                "expires_at": expires_at,
                "metadata": {
                    "source": "auth_guest_session",
                    "auth_state": auth_payload.get("auth_state"),
                    "ttl_seconds": guest_payload.get("ttl_seconds"),
                    "policy_status": guest_payload.get("policy_status"),
                    "merge_policy": auth_payload.get("merge_policy") or {},
                    "rate_limit": auth_payload.get("rate_limit") or {},
                },
            },
        )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id="",
            auth_context={
                "auth_state": "guest",
                "subject_id": subject_id,
                "subject_type": "guest",
                "guest_id": guest_id,
                "auth_session_id": None,
            },
        )
        event = _create_auth_event(
            event_type="guest_session_created",
            subject_id=subject_id,
            guest=guest,
            metadata={
                "source": "auth_guest_session",
                "chat_session_id": chat_session.session_id if chat_session else None,
                "raw_payload": _safe_payload(raw_payload or {}),
            },
        )

    return {
        "backend": "postgresql",
        "tables": [
            GuestIdentity._meta.db_table,
            AuthEvent._meta.db_table,
            ChatSession._meta.db_table,
        ],
        "guest_identity_table": GuestIdentity._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "guest_id": guest.guest_id,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def persist_current_auth_subject(
    auth_payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist the current auth subject preview used by canonical APIs."""

    subject = _dict_or_empty(auth_payload.get("subject"))
    subject_id = _text(subject.get("subject_id")) or "anonymous"
    subject_type = _text(subject.get("subject_type")) or "anonymous"
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    auth_session_id = _text(subject.get("auth_session_id"))

    with transaction.atomic():
        user = _get_or_create_user_account(user_id)
        guest = _get_or_create_guest_identity(guest_id)
        auth_session = None
        if auth_session_id:
            auth_session, _created = AuthSession.objects.update_or_create(
                auth_session_id=auth_session_id,
                defaults={
                    "user": user,
                    "guest": guest,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "status": AuthSessionStatus.ACTIVE,
                    "metadata": {
                        "source": "auth_me",
                        "auth_state": auth_payload.get("auth_state"),
                        "verification": _dict_or_empty(auth_payload.get("auth_session")).get(
                            "verification"
                        ),
                        "rate_limit": auth_payload.get("rate_limit") or {},
                        "merge_policy": auth_payload.get("merge_policy") or {},
                    },
                },
            )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id=user_id,
            auth_context={
                "auth_state": auth_payload.get("auth_state"),
                "subject_id": subject_id,
                "subject_type": subject_type,
                "user_id": user_id or None,
                "guest_id": guest_id or None,
                "auth_session_id": auth_session_id or None,
            },
        )
        event = _create_auth_event(
            event_type="auth_me_checked",
            subject_id=subject_id,
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": "auth_me",
                "auth_state": auth_payload.get("auth_state"),
                "chat_session_id": chat_session.session_id if chat_session else None,
            },
        )

    return {
        "backend": "postgresql",
        "tables": [
            UserAccount._meta.db_table,
            GuestIdentity._meta.db_table,
            AuthSession._meta.db_table,
            AuthEvent._meta.db_table,
            ChatSession._meta.db_table,
        ],
        "user_table": UserAccount._meta.db_table,
        "guest_identity_table": GuestIdentity._meta.db_table,
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id if auth_session else None,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def record_usage_event(
    payload: dict[str, Any],
    *,
    scope: str,
    amount: int = 1,
) -> dict[str, Any]:
    """Record and enforce a lightweight subject-scoped usage quota."""

    normalized_amount = max(amount, 1)
    subject = _ai_subject(payload, {})
    subject_id = subject["subject_id"]
    subject_type = subject["subject_type"]
    quota_key = f"rate_limit:{subject_id}:{scope}"
    policy = _usage_policy_for_subject(subject, scope=scope)
    now = timezone.now()

    with transaction.atomic():
        quota, _created = UsageQuota.objects.get_or_create(
            quota_id=_usage_quota_id(subject_id, scope),
            defaults={
                "subject_id": subject_id,
                "scope": scope,
                "limit_count": policy["limit_count"],
                "used_count": 0,
                "reset_at": now + timedelta(days=1),
                "metadata": {
                    "source": "canonical_usage_policy",
                    "subject_type": subject_type,
                    "plan_code": policy["plan_code"],
                    "subscription_id": policy["subscription_id"],
                    "policy_code_item": policy["policy_code_item"],
                    "policy_status": policy["policy_status"],
                    "policy_managed": True,
                },
            },
        )
        if not _created and quota.metadata.get("policy_managed"):
            quota.metadata = {
                **quota.metadata,
                "subject_type": subject_type,
                "plan_code": policy["plan_code"],
                "subscription_id": policy["subscription_id"],
                "policy_code_item": policy["policy_code_item"],
                "policy_status": policy["policy_status"],
            }
            quota.limit_count = policy["limit_count"]
        if quota.reset_at and quota.reset_at <= now:
            quota.used_count = 0
            quota.reset_at = now + timedelta(days=1)

        projected_count = quota.used_count + normalized_amount
        allowed = quota.limit_count == 0 or projected_count <= quota.limit_count
        if allowed:
            quota.used_count = projected_count
        quota.save(update_fields=["limit_count", "used_count", "reset_at", "metadata", "updated_at"])

        usage_event = UsageEvent.objects.create(
            usage_event_id=_usage_event_id(subject_id, scope),
            subject_id=subject_id,
            scope=scope,
            amount=normalized_amount if allowed else 0,
            quota_key=quota_key,
            metadata={
                "source": "canonical_usage_enforcement",
                "status": "allowed" if allowed else "blocked",
                "subject_type": subject_type,
                "plan_code": policy["plan_code"],
                "subscription_id": policy["subscription_id"],
                "policy_code_item": policy["policy_code_item"],
                "limit_count": quota.limit_count,
                "used_count": quota.used_count,
                "requested_amount": normalized_amount,
                "reset_at": quota.reset_at.isoformat() if quota.reset_at else None,
            },
        )

    return {
        "backend": "postgresql",
        "tables": [UsageQuota._meta.db_table, UsageEvent._meta.db_table],
        "quota_table": UsageQuota._meta.db_table,
        "usage_event_table": UsageEvent._meta.db_table,
        "quota_id": quota.quota_id,
        "usage_event_id": usage_event.usage_event_id,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "scope": scope,
        "quota_key": quota_key,
        "plan_code": policy["plan_code"],
        "subscription_id": policy["subscription_id"],
        "policy_code_item": policy["policy_code_item"],
        "policy_status": policy["policy_status"],
        "allowed": allowed,
        "limit_count": quota.limit_count,
        "used_count": quota.used_count,
        "remaining_count": max(quota.limit_count - quota.used_count, 0)
        if quota.limit_count
        else None,
        "reset_at": quota.reset_at.isoformat() if quota.reset_at else None,
        "status": "allowed" if allowed else "blocked",
    }


def record_history_event_record(
    *,
    event_type: str,
    status: str,
    summary: str,
    actor: dict[str, Any] | None = None,
    subject: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    privacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one standard-light history event in PostgreSQL."""

    event_payload = build_history_event(
        event_type=event_type,
        status=status,
        summary=summary,
        actor=actor,
        subject=subject,
        source=source,
        metadata=metadata,
        privacy=privacy,
    )
    return history_event_to_api(_upsert_history_event_payload(event_payload))


def record_agent_history_event_records(
    executions: list[dict[str, Any]],
    *,
    actor: dict[str, Any],
    source: dict[str, Any],
    subject: dict[str, Any],
) -> list[dict[str, Any]]:
    """Persist standard-light history events for Agent execution envelopes."""

    events = []
    for event_payload in build_agent_execution_events(
        executions,
        actor=actor,
        source=source,
        subject=subject,
    ):
        events.append(history_event_to_api(_upsert_history_event_payload(event_payload)))
    return events


def list_history_event_records(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    guest_id: str | None = None,
    job_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read history events from PostgreSQL using the public history filters."""

    queryset = HistoryEvent.objects.all()
    if session_id:
        queryset = queryset.filter(subject_session_id=session_id)
    if user_id:
        queryset = queryset.filter(actor_user_id=user_id)
    if guest_id:
        queryset = queryset.filter(actor_guest_id=guest_id)
    if job_id:
        queryset = queryset.filter(subject_job_id=job_id)
    if event_type:
        queryset = queryset.filter(event_type=event_type)

    rows = list(queryset.order_by("-occurred_at", "-id")[: max(limit, 1)])
    return [history_event_to_api(event) for event in reversed(rows)]


def history_event_to_api(event: HistoryEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "event_version": event.event_version,
        "occurred_at": event.occurred_at.isoformat(),
        "actor": event.actor,
        "subject": event.subject,
        "source": event.source,
        "status": event.status,
        "summary": event.summary,
        "metadata": event.metadata,
        "privacy": event.privacy,
        "created_at": event.created_at.isoformat(),
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
        node_execution = job_payload.get("node_execution") or {}
        agent_results = _persist_agent_results(job, node_execution)
        ai_session = _upsert_ai_session(job, payload=payload, job_payload=job_payload)
        agent_invocations = _persist_agent_invocations(
            job,
            ai_session=ai_session,
            node_execution=node_execution,
            agent_results=agent_results,
        )

    return {
        "backend": "postgresql",
        "tables": [
            AnalysisJob._meta.db_table,
            AgentResult._meta.db_table,
            AiSession._meta.db_table,
            AgentInvocation._meta.db_table,
        ],
        "analysis_job_table": AnalysisJob._meta.db_table,
        "agent_results_table": AgentResult._meta.db_table,
        "ai_session_table": AiSession._meta.db_table,
        "agent_invocations_table": AgentInvocation._meta.db_table,
        "agent_results_saved": len(agent_results),
        "agent_invocations_saved": len(agent_invocations),
        "agent_result_ids": [result.result_id for result in agent_results],
        "agent_invocation_ids": [invocation.invocation_id for invocation in agent_invocations],
        "ai_session_id": ai_session.ai_session_id,
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
        "owner_id": report.owner_id,
        "session_id": report.session.session_id if report.session_id else None,
        "job_id": report.job.job_id if report.job_id else None,
        "filename": f"{report.report_id}.txt",
        "content_type": "text/plain; charset=utf-8",
        "storage_uri": storage_uri,
        "storage_backend": storage_backend,
        "status": report.status,
        "body": _report_download_body(report, storage_backend=storage_backend),
    }


def authorize_report_download_metadata(
    download: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Authorize report metadata download before the object body is returned."""

    resource = {
        "type": "report",
        "report_id": download.get("report_id"),
        "owner_id": download.get("owner_id"),
        "session_id": download.get("session_id"),
        "storage_backend": download.get("storage_backend"),
    }
    return authorize_resource_access(resource, payload)


def access_subject_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    auth_context = _dict_or_empty(payload.get("auth_context"))
    user_id = _owner_id(payload) or _text(auth_context.get("user_id"))
    guest_id = _normalize_guest_id(payload.get("guest_id") or auth_context.get("guest_id"))
    session_id = _text(payload.get("session_id") or auth_context.get("session_id"))
    auth_session_id = _text(payload.get("auth_session_id") or auth_context.get("auth_session_id"))

    if user_id:
        subject_type = "user"
        subject_id = f"user:{user_id}"
    elif guest_id:
        subject_type = "guest"
        subject_id = f"guest:{guest_id}"
    else:
        subject_type = "anonymous"
        subject_id = "anonymous"

    return {
        "subject": {
            "subject_id": subject_id,
            "subject_type": subject_type,
            "user_id": user_id or None,
            "guest_id": guest_id or None,
            "session_id": session_id or None,
            "auth_session_id": auth_session_id or None,
        },
    }


def authorize_resource_access(
    resource: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Authorize a canonical resource using the normalized mock auth subject."""

    subject = access_subject_from_payload(payload)["subject"]
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    session_id = _text(subject.get("session_id"))
    resource_owner_id = _text(resource.get("owner_id"))
    resource_guest_id = _normalize_guest_id(resource.get("guest_id"))
    resource_session_id = _text(resource.get("session_id"))

    allowed = False
    reason = "owner_mismatch"
    if resource_owner_id:
        allowed = bool(user_id and user_id == resource_owner_id)
        reason = "owner_match" if allowed else "owner_mismatch"
    elif resource_guest_id:
        allowed = bool(guest_id and guest_id == resource_guest_id)
        reason = "guest_match" if allowed else "guest_mismatch"
    elif resource_session_id:
        allowed = bool(session_id and session_id == resource_session_id)
        reason = "session_match" if allowed else "session_mismatch"
    else:
        allowed = True
        reason = "legacy_unowned_resource"

    return {
        "contract_version": "object_access.v1",
        "allowed": allowed,
        "reason": reason,
        "subject": subject,
        "resource": {
            key: value
            for key, value in {
                "type": resource.get("type"),
                "report_id": resource.get("report_id"),
                "attachment_id": resource.get("attachment_id"),
                "session_id": resource_session_id or None,
                "owner_id": resource_owner_id or None,
                "guest_id": resource_guest_id or None,
                "storage_backend": resource.get("storage_backend"),
            }.items()
            if value is not None
        },
    }


def get_mycase_summary(
    *,
    session_id: str | None = None,
    owner_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    queryset = (
        AnalysisJob.objects.select_related("session", "message")
        .prefetch_related("events", "agent_results", "agent_invocations", "reports")
        .order_by("-updated_at")
    )
    if session_id:
        queryset = queryset.filter(session__session_id=session_id)
    if owner_id:
        queryset = queryset.filter(owner_id=owner_id)

    jobs = list(queryset[: max(limit, 1)])
    cases = [_case_summary(job) for job in jobs]
    active_statuses = {
        AnalysisJobStatus.QUEUED.value,
        AnalysisJobStatus.RUNNING.value,
        AnalysisJobStatus.PARTIAL.value,
    }
    saved_reports = Report.objects.all()
    if session_id:
        saved_reports = saved_reports.filter(session__session_id=session_id)
    if owner_id:
        saved_reports = saved_reports.filter(owner_id=owner_id)

    return {
        "storage": {
            "backend": "postgresql",
            "tables": [
                ChatSession._meta.db_table,
                ChatMessage._meta.db_table,
                AnalysisJob._meta.db_table,
                AnalysisJobEvent._meta.db_table,
                AgentResult._meta.db_table,
                AiSession._meta.db_table,
                AgentInvocation._meta.db_table,
                AnalysisDisplayResult._meta.db_table,
                Report._meta.db_table,
            ],
        },
        "active_cases": sum(1 for case in cases if case["case_status"] in active_statuses),
        "due_soon_cases": 0,
        "saved_reports": saved_reports.count(),
        "recent_analysis_count": len(cases),
        "cases": cases,
        "limitations": [
            "deadline calculation is not connected yet; due_soon_cases stays 0.",
            "authorization is still mock bearer/guest-shape based.",
        ],
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


def _bind_chat_session_auth_context(
    *,
    session_id: str,
    owner_id: str,
    auth_context: dict[str, Any],
) -> ChatSession | None:
    session = _get_or_create_session(session_id, owner_id=owner_id)
    if session is None:
        return None

    metadata = dict(session.metadata or {})
    existing_auth_context = (
        metadata.get("auth_context")
        if isinstance(metadata.get("auth_context"), dict)
        else {}
    )
    existing_auth_context.update(
        {key: value for key, value in auth_context.items() if value is not None}
    )
    metadata["auth_context"] = existing_auth_context
    metadata.setdefault("created_by", "canonical_auth_session")
    session.metadata = metadata
    if owner_id and not session.owner_id:
        session.owner_id = owner_id
    session.save(update_fields=["owner_id", "metadata", "updated_at"])
    return session


def _chat_session_guest_id(session: ChatSession | None) -> str:
    if session is None:
        return ""
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    auth_context = metadata.get("auth_context") if isinstance(metadata.get("auth_context"), dict) else {}
    return _normalize_guest_id(auth_context.get("guest_id"))


def _create_auth_event(
    *,
    event_type: str,
    subject_id: str,
    metadata: dict[str, Any],
    user: UserAccount | None = None,
    guest: GuestIdentity | None = None,
    auth_session: AuthSession | None = None,
) -> AuthEvent:
    now = timezone.now()
    digest = hashlib.sha1(
        f"{event_type}:{subject_id}:{now.isoformat()}".encode("utf-8")
    ).hexdigest()[:16]
    return AuthEvent.objects.create(
        event_id=f"authevt_{digest}",
        user=user,
        guest=guest,
        auth_session=auth_session,
        event_type=event_type,
        subject_id=subject_id,
        metadata=metadata,
    )


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


def _upsert_ai_session(
    job: AnalysisJob,
    *,
    payload: dict[str, Any],
    job_payload: dict[str, Any],
) -> AiSession:
    subject = _ai_subject(payload, job_payload)
    user = _get_or_create_user_account(subject["user_id"])
    guest = _get_or_create_guest_identity(subject["guest_id"])
    quota_key = subject["quota_key"]

    ai_session, _created = AiSession.objects.update_or_create(
        ai_session_id=_ai_session_id(job.job_id),
        defaults={
            "session": job.session,
            "user": user,
            "guest": guest,
            "owner_id": subject["user_id"] or job.owner_id,
            "status": "active",
            "routing_intent": job.routing_intent,
            "quota_key": quota_key,
            "metadata": {
                "source": "canonical_analysis_job",
                "job_id": job.job_id,
                "subject_id": subject["subject_id"],
                "subject_type": subject["subject_type"],
                "auth_session_id": subject["auth_session_id"],
                "chat_session_id": job.session.session_id,
                "analysis_plan_id": job.analysis_plan_id,
            },
        },
    )
    return ai_session


def _persist_agent_invocations(
    job: AnalysisJob,
    *,
    ai_session: AiSession,
    node_execution: dict[str, Any],
    agent_results: list[AgentResult],
) -> list[AgentInvocation]:
    executions = node_execution.get("executions") or []
    results_by_id = {result.result_id: result for result in agent_results}
    invocations = []

    for index, execution in enumerate(executions, start=1):
        if not isinstance(execution, dict):
            continue

        agent_output = execution.get("agent_output") or {}
        if not isinstance(agent_output, dict):
            continue

        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        if not node_code:
            continue

        result_id = _agent_result_id(job.job_id, node_code, index)
        agent_result = results_by_id.get(result_id)
        agent_node = _upsert_agent_node_definition(execution, agent_output)
        status = _agent_invocation_status(
            agent_output.get("status"),
            execution.get("execution_status") or agent_output.get("execution_status"),
        )

        invocation, _created = AgentInvocation.objects.update_or_create(
            invocation_id=_agent_invocation_id(job.job_id, node_code, index),
            defaults={
                "ai_session": ai_session,
                "job": job,
                "agent_node": agent_node,
                "node_code": node_code,
                "status": status,
                "attempt_no": _positive_int_or_default(execution.get("attempt_no"), default=1),
                "execution_mode": _text(execution.get("execution_mode")),
                "latency_ms": _positive_int_or_none(execution.get("latency_ms")),
                "token_count": _positive_int_or_none(execution.get("token_count")),
                "evidence_count": len(_list_or_empty(agent_output.get("evidence"))),
                "limitation_count": len(_list_or_empty(agent_output.get("limitations"))),
                "retryable": status in {
                    AgentInvocationStatus.FAILED.value,
                    AgentInvocationStatus.RETRYING.value,
                },
                "error_code": _agent_invocation_error_code(agent_output, status),
                "quota_key": ai_session.quota_key,
                "metadata": _agent_invocation_metadata(
                    execution=execution,
                    agent_output=agent_output,
                    agent_result=agent_result,
                ),
            },
        )
        invocations.append(invocation)

    return invocations


def _upsert_agent_node_definition(
    execution: dict[str, Any],
    agent_output: dict[str, Any],
) -> AgentNodeDefinition | None:
    node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
    if not node_code:
        return None

    node = execution.get("node") if isinstance(execution.get("node"), dict) else {}
    adapter_contract = node.get("adapter_contract") if isinstance(node.get("adapter_contract"), dict) else {}
    agent_node, _created = AgentNodeDefinition.objects.update_or_create(
        node_code=node_code,
        defaults={
            "node_name": _text(agent_output.get("node_name") or node.get("node_name") or node_code),
            "node_type": _text(agent_output.get("node_type") or node.get("node_type")) or "agent",
            "owner": _text(agent_output.get("owner") or node.get("owner")),
            "status": _text(node.get("status")) or "mock_ready",
            "contract_version": _text(adapter_contract.get("contract_version")) or "agent_adapter.v1",
            "adapter_key": _text(adapter_contract.get("function_name")),
            "metadata": {
                "source": "mock_node_registry",
                "order": node.get("order"),
                "description": node.get("description"),
                "required_inputs": node.get("required_inputs") or [],
                "produces": node.get("produces") or [],
                "handoff_to": node.get("handoff_to") or [],
            },
        },
    )
    return agent_node


def _agent_result_id(job_id: str, node_code: str, index: int) -> str:
    readable_id = f"res_{job_id}_{index}_{node_code}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{index}:{node_code}".encode("utf-8")).hexdigest()[:16]
    return f"res_{digest}_{index}"


def _ai_session_id(job_id: str) -> str:
    readable_id = f"ais_{job_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:20]
    return f"ais_{digest}"


def _agent_invocation_id(job_id: str, node_code: str, index: int) -> str:
    readable_id = f"ainv_{job_id}_{index}_{node_code}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{index}:{node_code}".encode("utf-8")).hexdigest()[:16]
    return f"ainv_{digest}_{index}"


def _usage_quota_id(subject_id: str, scope: str) -> str:
    readable_id = f"quota_{subject_id.replace(':', '_')}_{scope}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{subject_id}:{scope}".encode("utf-8")).hexdigest()[:20]
    return f"quota_{digest}"


def _usage_event_id(subject_id: str, scope: str) -> str:
    now = timezone.now().isoformat()
    digest = hashlib.sha1(f"{subject_id}:{scope}:{now}".encode("utf-8")).hexdigest()[:20]
    return f"use_{digest}"


def _usage_policy_for_subject(subject: dict[str, str], *, scope: str) -> dict[str, Any]:
    plan_code = _usage_plan_code(subject)
    code_item = _ensure_usage_policy_code_item(plan_code)
    limits = _dict_or_empty(code_item.metadata.get("limits"))
    limit_count = _positive_int_or_none(limits.get(scope))
    if limit_count is None:
        limit_count = _default_usage_limit(plan_code, scope)
    subscription = _active_subscription_for_subject(subject)
    return {
        "plan_code": plan_code,
        "subscription_id": subscription.subscription_id if subscription else None,
        "policy_code_item": f"{USAGE_POLICY_GROUP_CODE}:{code_item.code}",
        "policy_status": _text(code_item.metadata.get("policy_status")) or "seeded_default",
        "limit_count": limit_count,
    }


def _usage_plan_code(subject: dict[str, str]) -> str:
    subject_type = subject["subject_type"]
    if subject_type == "anonymous":
        return "anonymous"
    if subject_type == "guest":
        return "guest"

    subscription = _active_subscription_for_subject(subject)
    if subscription:
        return subscription.plan_code
    user = _get_or_create_user_account(subject["user_id"])
    if user is not None:
        _ensure_default_free_subscription(user)
    return "free"


def _active_subscription_for_subject(subject: dict[str, str]) -> Subscription | None:
    user_id = subject.get("user_id")
    if not user_id:
        return None
    user = _get_or_create_user_account(user_id)
    if user is None:
        return None
    return (
        Subscription.objects.filter(
            user=user,
            status__in=[
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIAL,
                SubscriptionStatus.FREE,
            ],
        )
        .order_by("-updated_at")
        .first()
    )


def _ensure_default_free_subscription(user: UserAccount) -> Subscription:
    subscription_id = f"sub_free_{user.user_id}"
    subscription, _created = Subscription.objects.get_or_create(
        subscription_id=subscription_id,
        defaults={
            "user": user,
            "plan_code": "free",
            "status": SubscriptionStatus.FREE,
            "metadata": {
                "source": "canonical_usage_policy",
                "policy_status": "seeded_default",
            },
        },
    )
    return subscription


def _ensure_usage_policy_code_item(plan_code: str) -> CodeItem:
    group, _created = CodeGroup.objects.get_or_create(
        group_code=USAGE_POLICY_GROUP_CODE,
        defaults={
            "name": "Usage quota policy",
            "description": "Subject plan to API usage quota defaults.",
            "metadata": {"source": "canonical_usage_policy"},
        },
    )
    defaults = USAGE_POLICY_LIMITS.get(plan_code, USAGE_POLICY_LIMITS["anonymous"])
    code_item, created = CodeItem.objects.get_or_create(
        group=group,
        code=plan_code,
        defaults={
            "label": f"{plan_code} usage policy",
            "description": "Seeded API usage policy. 운영 정책 확정 전 기본값입니다.",
            "is_active": True,
            "metadata": {
                "source": "canonical_usage_policy",
                "policy_status": "seeded_default",
                "limits": defaults,
            },
        },
    )
    if created:
        return code_item
    metadata = dict(code_item.metadata or {})
    metadata.setdefault("source", "canonical_usage_policy")
    metadata.setdefault("policy_status", "seeded_default")
    metadata.setdefault("limits", defaults)
    if metadata != code_item.metadata:
        code_item.metadata = metadata
        code_item.save(update_fields=["metadata", "updated_at"])
    return code_item


def _default_usage_limit(subject_type: str, scope: str) -> int:
    policy = USAGE_POLICY_LIMITS.get(subject_type, USAGE_POLICY_LIMITS["anonymous"])
    return policy.get(scope, 10)


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


def _upsert_history_event_payload(event_payload: dict[str, Any]) -> HistoryEvent:
    actor = _dict_or_empty(event_payload.get("actor"))
    subject = _dict_or_empty(event_payload.get("subject"))
    source = _dict_or_empty(event_payload.get("source"))
    occurred_at = _datetime_or_none(event_payload.get("occurred_at")) or timezone.now()

    event, _created = HistoryEvent.objects.update_or_create(
        event_id=_text(event_payload.get("event_id")),
        defaults={
            "event_type": _text(event_payload.get("event_type")),
            "event_version": _text(event_payload.get("event_version")) or "history_event.v1",
            "occurred_at": occurred_at,
            "actor_user_id": _text(actor.get("user_id")),
            "actor_guest_id": _text(actor.get("guest_id")),
            "actor_auth_session_id": _text(actor.get("auth_session_id")),
            "actor_auth_state": _text(actor.get("auth_state")),
            "subject_session_id": _text(subject.get("session_id")),
            "subject_message_id": _text(subject.get("message_id")),
            "subject_job_id": _text(subject.get("job_id")),
            "subject_report_id": _text(subject.get("report_id")),
            "source_surface": _text(source.get("surface")),
            "source_api_path": _text(source.get("api_path")),
            "source_execution_mode": _text(source.get("execution_mode")),
            "source_node_code": _text(source.get("node_code")),
            "status": _text(event_payload.get("status")) or "success",
            "summary": _text(event_payload.get("summary")),
            "actor": actor,
            "subject": subject,
            "source": source,
            "metadata": _dict_or_empty(event_payload.get("metadata")),
            "privacy": _dict_or_empty(event_payload.get("privacy")),
        },
    )
    return event


def _agent_result_status(status: Any) -> str:
    status_text = _text(status)
    if status_text in {choice.value for choice in AgentResultStatus}:
        return status_text
    if status_text in {"pending", "running", "blocked"}:
        return AgentResultStatus.PARTIAL
    return AgentResultStatus.SUCCESS


def _agent_invocation_status(status: Any, execution_status: Any) -> str:
    status_text = _text(status) or _text(execution_status)
    if status_text in {choice.value for choice in AgentInvocationStatus}:
        return status_text
    if status_text == "pending":
        return AgentInvocationStatus.QUEUED
    if status_text == "running":
        return AgentInvocationStatus.RUNNING
    if status_text in {"blocked", "skipped"}:
        return AgentInvocationStatus.PARTIAL
    if status_text in {"error", "failed"}:
        return AgentInvocationStatus.FAILED
    return AgentInvocationStatus.SUCCESS


def _agent_invocation_error_code(agent_output: dict[str, Any], status: str) -> str:
    if status != AgentInvocationStatus.FAILED.value:
        return ""
    return _text(agent_output.get("error_code")) or "mock_agent_failed"


def _agent_invocation_metadata(
    *,
    execution: dict[str, Any],
    agent_output: dict[str, Any],
    agent_result: AgentResult | None,
) -> dict[str, Any]:
    plan_step = execution.get("plan_step") if isinstance(execution.get("plan_step"), dict) else {}
    return {
        "source": "canonical_analysis_job",
        "execution_id": execution.get("execution_id"),
        "agent_result_id": agent_result.result_id if agent_result else None,
        "plan_step": plan_step,
        "adapter_context": execution.get("adapter_context") or {},
        "execution_status": execution.get("execution_status") or agent_output.get("execution_status"),
        "created_at": agent_output.get("created_at") or execution.get("created_at"),
    }


def _ai_subject(payload: dict[str, Any], job_payload: dict[str, Any]) -> dict[str, str]:
    auth_context = _dict_or_empty(payload.get("auth_context")) or _dict_or_empty(
        job_payload.get("auth_context")
    )
    user_id = _text(
        payload.get("owner_id")
        or payload.get("user_id")
        or auth_context.get("user_id")
        or job_payload.get("owner_id")
        or job_payload.get("user_id")
    )
    guest_id = _normalize_guest_id(
        payload.get("guest_id") or auth_context.get("guest_id") or job_payload.get("guest_id")
    )
    auth_session_id = _text(
        payload.get("auth_session_id")
        or auth_context.get("auth_session_id")
        or job_payload.get("auth_session_id")
    )

    if user_id:
        subject_type = "user"
        subject_id = f"user:{user_id}"
    elif guest_id:
        subject_type = "guest"
        subject_id = f"guest:{guest_id}"
    else:
        subject_type = "anonymous"
        subject_id = "anonymous"

    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "user_id": user_id,
        "guest_id": guest_id,
        "auth_session_id": auth_session_id,
        "quota_key": f"rate_limit:{subject_id}:agent_run",
    }


def _get_or_create_user_account(user_id: str) -> UserAccount | None:
    if not user_id:
        return None
    user, _created = UserAccount.objects.get_or_create(
        user_id=user_id,
        defaults={
            "display_name": user_id,
            "status": UserAccountStatus.ACTIVE,
            "metadata": {"source": "canonical_analysis_job"},
        },
    )
    return user


def _get_or_create_guest_identity(guest_id: str) -> GuestIdentity | None:
    if not guest_id:
        return None
    guest, _created = GuestIdentity.objects.get_or_create(
        guest_id=guest_id,
        defaults={
            "status": GuestIdentityStatus.ACTIVE,
            "metadata": {"source": "canonical_analysis_job"},
        },
    )
    return guest


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


def _auth_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "tables": [
            UserAccount._meta.db_table,
            GuestIdentity._meta.db_table,
            AuthSession._meta.db_table,
            AuthEvent._meta.db_table,
        ],
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


def _case_summary(job: AnalysisJob) -> dict[str, Any]:
    display_result = _display_result_for_job(job)
    reports = list(job.reports.order_by("-created_at"))
    latest_report = reports[0] if reports else None
    latest_event = job.events.order_by("-created_at").first()
    agent_results = list(job.agent_results.all())
    agent_invocations = list(job.agent_invocations.all())
    next_actions = _case_next_actions(agent_results)
    limitations = _case_limitations(display_result, agent_results)
    summary = _case_display_summary(display_result)

    return {
        "case_id": job.job_id,
        "job_id": job.job_id,
        "session_id": job.session.session_id,
        "message_id": job.message.message_id if job.message_id else None,
        "title": summary or _case_title(job),
        "case_status": job.status,
        "routing_intent": job.routing_intent,
        "active_node": job.active_node,
        "progress_message": job.progress_message,
        "last_event_at": (latest_event.created_at if latest_event else job.updated_at).isoformat(),
        "analysis_plan_id": job.analysis_plan_id,
        "agent_result_count": len(agent_results),
        "agent_status_counts": _agent_status_counts(agent_results),
        "agent_invocation_count": len(agent_invocations),
        "agent_invocation_status_counts": _agent_invocation_status_counts(agent_invocations),
        "ai_session_ids": _case_ai_session_ids(agent_invocations),
        "display_result_id": display_result.display_result_id if display_result else None,
        "report_count": len(reports),
        "latest_report_id": latest_report.report_id if latest_report else None,
        "latest_report_status": latest_report.status if latest_report else None,
        "next_actions": next_actions,
        "limitations": limitations,
    }


def _case_title(job: AnalysisJob) -> str:
    if job.message_id and job.message.content:
        return job.message.content[:80]
    if job.routing_intent:
        return job.routing_intent
    return job.job_id


def _case_display_summary(display_result: AnalysisDisplayResult | None) -> str:
    if display_result and isinstance(display_result.assistant_message, dict):
        summary = _text(display_result.assistant_message.get("summary"))
        if summary:
            return summary
        answer = _text(display_result.assistant_message.get("answer"))
        if answer:
            return answer[:120]
    if display_result and isinstance(display_result.cards, list):
        for card in display_result.cards:
            if isinstance(card, dict) and card.get("title"):
                return _text(card.get("title"))
    return ""


def _case_next_actions(agent_results: list[AgentResult]) -> list[Any]:
    actions = []
    for result in agent_results:
        for action in result.next_actions or []:
            if action not in actions:
                actions.append(action)
    return actions[:5]


def _case_limitations(
    display_result: AnalysisDisplayResult | None,
    agent_results: list[AgentResult],
) -> list[Any]:
    limitations = []
    if display_result:
        limitations.extend(display_result.limitations or [])
    for result in agent_results:
        limitations.extend(result.limitations or [])

    deduped = []
    for limitation in limitations:
        if limitation not in deduped:
            deduped.append(limitation)
    return deduped[:5]


def _agent_status_counts(agent_results: list[AgentResult]) -> dict[str, int]:
    counts = {AgentResultStatus.SUCCESS: 0, AgentResultStatus.PARTIAL: 0, AgentResultStatus.FAILED: 0}
    for result in agent_results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _agent_invocation_status_counts(agent_invocations: list[AgentInvocation]) -> dict[str, int]:
    counts = {choice.value: 0 for choice in AgentInvocationStatus}
    for invocation in agent_invocations:
        counts[invocation.status] = counts.get(invocation.status, 0) + 1
    return {status: count for status, count in counts.items() if count}


def _case_ai_session_ids(agent_invocations: list[AgentInvocation]) -> list[str]:
    ai_session_ids = []
    for invocation in agent_invocations:
        if not invocation.ai_session_id:
            continue
        ai_session_id = invocation.ai_session.ai_session_id
        if ai_session_id not in ai_session_ids:
            ai_session_ids.append(ai_session_id)
    return ai_session_ids


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


def _positive_int_or_default(value: Any, *, default: int) -> int:
    number = _positive_int_or_none(value)
    if number is None or number == 0:
        return default
    return number


def _datetime_or_none(value: Any):
    text = _text(value)
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=datetime_timezone.utc)
    return parsed


def _normalize_guest_id(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    if text.startswith("gst_"):
        return text
    return f"gst_{text}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
