"""Repository helpers for canonical API persistence boundaries."""

from __future__ import annotations

import hashlib
import base64
import hmac
from datetime import timedelta, timezone as datetime_timezone
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.services.attachment_mock_service import (
    register_attachment as register_mock_attachment,
)
from app.services.history_event_mock_service import (
    SENSITIVE_METADATA_KEYS,
    build_agent_execution_events,
    build_history_event,
)
from chatbot.models import (
    AgentInvocation,
    AgentInvocationStatus,
    AgentNodeDefinition,
    AgentResult,
    AgentResultStatus,
    AgentWorkItem,
    AgentWorkItemStatus,
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
    OAuthConnection,
    RetrievalEvent,
    Report,
    ReportStatus,
    ReportType,
    Subscription,
    SubscriptionStatus,
    SocialAccount,
    UsageEvent,
    UsageQuota,
    UserAccount,
    UserAccountStatus,
    UploadedFile,
    UploadedFileStatus,
)
from chatbot.object_storage import (
    build_report_storage_reference,
    build_upload_storage_reference,
    object_storage_policy,
    storage_reference_from_uri,
    write_object,
    write_object_from_source_uri,
)
from chatbot.progress_cache import (
    progress_cache_policy,
    write_analysis_job_progress,
    write_chat_session_state,
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

HISTORY_POLICY_VERSION = "history_operating_policy.v1"
CONVERSATION_SAVE_POLICY_VERSION = "conversation_save_policy.v1"
CONVERSATION_SAVE_STATES = {"pending", "saved", "session_only"}
HISTORY_RETENTION_DAYS = {
    "anonymous": 1,
    "guest": 7,
    "user": 365,
    "authenticated": 365,
}
HISTORY_METADATA_ALLOWED_KEYS = {
    "action",
    "active_node",
    "analysis_plan_id",
    "attachment_count",
    "card_count",
    "conversation_save_policy",
    "conversation_save_state",
    "error_code",
    "evidence_count",
    "execution_id",
    "execution_status",
    "has_download_url",
    "http_status",
    "is_authenticated",
    "limitation_count",
    "merge_policy",
    "metadata_policy",
    "missing_fields",
    "mock_scenario",
    "mock_status",
    "node_code",
    "node_name",
    "pending_fields",
    "rate_limit_keys",
    "report_status",
    "response_status",
    "routing_intent",
    "session_status",
    "status_counts",
    "subject_type",
    "ttl_seconds",
}
HISTORY_AFTER_SERVICE_EVENT_TYPES = {
    "analysis_job_created",
    "agent_call_completed",
    "agent_call_failed",
    "agent_call_partial",
    "chat_message_created",
    "conversation_saved",
    "report_downloaded",
    "report_saved",
}


def register_uploaded_file(
    payload: dict[str, Any],
    upload_file: Any | None = None,
) -> dict[str, Any]:
    """Register a canonical file upload and persist its metadata in Django DB.

    The mock sidecar remains the local byte source, while the canonical
    metadata exposes the object-storage adapter URI and fallback envelope.
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
    object_storage = build_upload_storage_reference(
        attachment,
        owner_id=owner_id or (session.owner_id if session else ""),
    )
    object_storage_write = write_object_from_source_uri(
        object_storage,
        fallback_payload=attachment,
    )
    object_storage["write_result"] = object_storage_write
    object_storage["status"] = object_storage_write["status"]
    object_storage["writes_binary"] = object_storage_write["writes_binary"]
    object_storage["persistence_state"] = object_storage_write["persistence_state"]
    metadata["source_storage_uri"] = _text(attachment.get("storage_uri"))
    metadata["object_storage"] = object_storage
    metadata["object_storage_write"] = object_storage_write
    agent_handoff = dict(attachment.get("agent_handoff") or {})
    agent_handoff["storage_uri"] = object_storage["storage_uri"]
    agent_handoff["object_storage"] = object_storage

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
                "storage_uri": object_storage["storage_uri"],
                "privacy_risk": True,
                "status": _model_status(attachment.get("status")),
                "scan_status": "not_started",
                "agent_handoff": agent_handoff,
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
    object_storage = _uploaded_file_object_storage(uploaded_file)
    return {
        "type": "uploaded_file",
        "attachment_id": uploaded_file.attachment_id,
        "owner_id": uploaded_file.owner_id or (session.owner_id if session else ""),
        "session_id": session.session_id if session else "",
        "guest_id": _chat_session_guest_id(session),
        "storage_backend": object_storage["backend"],
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


def conversation_save_state_from_payload(
    payload: dict[str, Any],
    *,
    default: str = "saved",
) -> str:
    auth_context = _dict_or_empty(payload.get("auth_context"))
    raw_state = _text(
        payload.get("conversation_save_state")
        or payload.get("save_state")
        or payload.get("save_decision")
        or auth_context.get("conversation_save_state")
        or auth_context.get("save_state")
    ).lower()
    aliases = {
        "": default,
        "defer": "pending",
        "deferred": "pending",
        "pending": "pending",
        "undecided": "pending",
        "save": "saved",
        "saved": "saved",
        "session": "session_only",
        "session_only": "session_only",
        "temporary": "session_only",
        "temp": "session_only",
        "not_saved": "session_only",
        "skip": "session_only",
    }
    normalized = aliases.get(raw_state, raw_state)
    return normalized if normalized in CONVERSATION_SAVE_STATES else default


def mark_conversation_save_state(
    *,
    session_id: str,
    save_state: str,
    owner_id: str = "",
    guest_id: str = "",
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_session_id = _text(session_id)
    normalized_state = conversation_save_state_from_payload(
        {"conversation_save_state": save_state},
        default="pending",
    )
    if not normalized_session_id:
        return _conversation_save_state_result("skipped", normalized_state, reason="missing_session_id")

    session = ChatSession.objects.filter(session_id=normalized_session_id).first()
    if session is None:
        return _conversation_save_state_result("skipped", normalized_state, reason="session_not_found")

    with transaction.atomic():
        session.metadata = _metadata_with_conversation_save_state(
            session.metadata,
            normalized_state,
            raw_payload=raw_payload,
        )
        if normalized_state == "saved" and owner_id and not session.owner_id:
            session.owner_id = owner_id
        session.save(update_fields=["owner_id", "metadata", "updated_at"])

        messages_updated = _update_session_message_save_state(session, normalized_state)
        jobs_updated = _update_session_job_save_state(session, normalized_state, owner_id=owner_id)
        history_events_updated = _update_session_history_save_state(session.session_id, normalized_state)

    session_cache = write_chat_session_state(session)
    return {
        **_conversation_save_state_result("updated", normalized_state),
        "session_id": session.session_id,
        "owner_id": session.owner_id or None,
        "guest_id": guest_id or _chat_session_guest_id(session) or None,
        "chat_messages_updated": messages_updated,
        "analysis_jobs_updated": jobs_updated,
        "history_events_updated": history_events_updated,
        "session_cache": session_cache,
    }


def persist_chat_message_analysis_boundary(
    payload: dict[str, Any],
    chat_response: dict[str, Any],
    *,
    node_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the canonical chat message and its analysis-job boundary."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(chat_response.get("session_id"), owner_id=owner_id)
    if session is None:
        raise ValueError("chat_response must include session_id")

    conversation_save_state = conversation_save_state_from_payload(payload)
    session.metadata = _metadata_with_conversation_save_state(
        session.metadata,
        conversation_save_state,
        raw_payload=payload,
    )
    session.save(update_fields=["metadata", "updated_at"])

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
                    "conversation_save_policy": CONVERSATION_SAVE_POLICY_VERSION,
                    "conversation_save_state": conversation_save_state,
                    "attachments": chat_response.get("attachments", []),
                    "blocked_attachments": chat_response.get("blocked_attachments", []),
                    "attachment_scan_policy": chat_response.get("attachment_scan_policy", {}),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "scan_gate": chat_response.get("scan_gate", {}),
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
                    "blocked_attachments": chat_response.get("blocked_attachments", []),
                    "attachment_scan_policy": chat_response.get("attachment_scan_policy", {}),
                    "attachment_resolution": chat_response.get("attachment_resolution", {}),
                    "scan_gate": chat_response.get("scan_gate", {}),
                    "limitations": chat_response.get("limitations", []),
                    "conversation_save_policy": CONVERSATION_SAVE_POLICY_VERSION,
                    "conversation_save_state": conversation_save_state,
                },
            },
        )
        _upsert_initial_job_event(job, progress=progress)
        agent_results: list[AgentResult] = []
        agent_invocations: list[AgentInvocation] = []
        ai_session: AiSession | None = None
        if node_execution:
            job.status_counts = node_execution.get("status_counts") or job.status_counts
            job.metadata = {
                **_dict_or_empty(job.metadata),
                "supervisor_execution": _node_execution_summary(node_execution),
            }
            job.save(update_fields=["status_counts", "metadata", "updated_at"])
            agent_results = _persist_agent_results(job, node_execution)
            ai_session = _upsert_ai_session(
                job,
                payload=payload,
                job_payload={
                    **chat_response,
                    "job_id": job.job_id,
                    "session_id": session.session_id,
                    "message_id": message.message_id,
                    "owner_id": owner_id or session.owner_id,
                    "auth_context": _dict_or_empty(payload.get("auth_context")),
                },
            )
            agent_invocations = _persist_agent_invocations(
                job,
                ai_session=ai_session,
                node_execution=node_execution,
                agent_results=agent_results,
            )
            retrieval_events_saved = RetrievalEvent.objects.filter(job=job).count()
        else:
            retrieval_events_saved = 0

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(session, latest_job=job)

    return {
        "message_id": message.message_id,
        "job_id": job.job_id,
        "session_id": session.session_id,
        "conversation_save_policy": CONVERSATION_SAVE_POLICY_VERSION,
        "conversation_save_state": conversation_save_state,
        "supervisor_execution": _node_execution_summary(node_execution or {}),
        "agent_results_saved": len(agent_results),
        "agent_invocations_saved": len(agent_invocations),
        "retrieval_events_saved": retrieval_events_saved,
        "ai_session_id": ai_session.ai_session_id if ai_session else None,
        "node_codes": [result.node_code for result in agent_results],
        "progress_cache": progress_cache,
        "session_cache": session_cache,
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
    auth_source = "auth_google_code" if auth_payload.get("contract_version") == "google_auth_code.v1" else "auth_me"
    auth_event_type = "auth_google_code_completed" if auth_source == "auth_google_code" else "auth_me_checked"

    with transaction.atomic():
        user = _get_or_create_user_account(user_id)
        if user is not None:
            _update_user_account_from_auth_payload(user, auth_payload)
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
                    "issued_at": _datetime_or_none(auth_payload.get("issued_at")),
                    "expires_at": _datetime_or_none(auth_payload.get("expires_at")),
                    "revoked_at": None,
                    "metadata": {
                        "source": auth_source,
                        "auth_state": auth_payload.get("auth_state"),
                        "verification": _dict_or_empty(auth_payload.get("auth_session")).get(
                            "verification"
                        ),
                        "google": _safe_google_connection_metadata(auth_payload),
                        "rate_limit": auth_payload.get("rate_limit") or {},
                        "merge_policy": auth_payload.get("merge_policy") or {},
                    },
                },
            )
        google_persistence = _upsert_google_oauth_subject(user, auth_payload)
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
            event_type=auth_event_type,
            subject_id=subject_id,
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": auth_source,
                "auth_state": auth_payload.get("auth_state"),
                "chat_session_id": chat_session.session_id if chat_session else None,
                "google": _safe_google_connection_metadata(auth_payload),
            },
        )

    tables = [
        UserAccount._meta.db_table,
        GuestIdentity._meta.db_table,
        AuthSession._meta.db_table,
        AuthEvent._meta.db_table,
        ChatSession._meta.db_table,
    ]
    for table_name in google_persistence.get("tables", []):
        if table_name not in tables:
            tables.append(table_name)

    return {
        "backend": "postgresql",
        "tables": tables,
        "user_table": UserAccount._meta.db_table,
        "guest_identity_table": GuestIdentity._meta.db_table,
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "social_account_table": google_persistence.get("social_account_table"),
        "oauth_connection_table": google_persistence.get("oauth_connection_table"),
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id if auth_session else None,
        "social_account_id": google_persistence.get("social_account_id"),
        "oauth_connection_id": google_persistence.get("oauth_connection_id"),
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def persist_auth_token_refresh(
    auth_payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    subject = _dict_or_empty(auth_payload.get("subject"))
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    auth_session_id = _text(subject.get("auth_session_id"))
    if not user_id or not auth_session_id:
        return _auth_persistence_skipped("missing_refresh_subject")

    with transaction.atomic():
        user = _get_or_create_user_account(user_id)
        if user is not None:
            _update_user_account_from_auth_payload(user, auth_payload)
        guest = _get_or_create_guest_identity(guest_id)
        auth_session, _created = AuthSession.objects.update_or_create(
            auth_session_id=auth_session_id,
            defaults={
                "user": user,
                "guest": guest,
                "subject_type": "user",
                "subject_id": f"user:{user_id}",
                "status": AuthSessionStatus.ACTIVE,
                "issued_at": _datetime_or_none(auth_payload.get("issued_at")),
                "expires_at": _datetime_or_none(auth_payload.get("expires_at")),
                "revoked_at": None,
                "metadata": {
                    "source": "auth_refresh",
                    "auth_state": auth_payload.get("auth_state"),
                    "verification": _dict_or_empty(auth_payload.get("auth_session")).get("verification"),
                    "refresh_policy": _dict_or_empty(auth_payload.get("auth_session")).get("refresh_policy"),
                    "rate_limit": auth_payload.get("rate_limit") or {},
                },
            },
        )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id=user_id,
            auth_context={
                "auth_state": auth_payload.get("auth_state"),
                "subject_id": f"user:{user_id}",
                "subject_type": "user",
                "user_id": user_id,
                "guest_id": guest_id or None,
                "auth_session_id": auth_session_id,
            },
        )
        event = _create_auth_event(
            event_type="auth_token_refreshed",
            subject_id=f"user:{user_id}",
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": "auth_refresh",
                "auth_state": auth_payload.get("auth_state"),
                "chat_session_id": chat_session.session_id if chat_session else None,
                "expires_at": auth_payload.get("expires_at"),
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
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id,
        "auth_session_status": auth_session.status,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def persist_auth_logout(
    auth_payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    subject = _dict_or_empty(auth_payload.get("subject"))
    user_id = _text(subject.get("user_id"))
    guest_id = _normalize_guest_id(subject.get("guest_id"))
    auth_session_id = _text(subject.get("auth_session_id"))
    if not user_id or not auth_session_id:
        return _auth_persistence_skipped("missing_logout_subject")

    revoked_at = _datetime_or_none(auth_payload.get("revoked_at")) or timezone.now()
    with transaction.atomic():
        user = _get_or_create_user_account(user_id)
        if user is not None:
            _update_user_account_from_auth_payload(user, auth_payload)
        guest = _get_or_create_guest_identity(guest_id)
        auth_session, _created = AuthSession.objects.update_or_create(
            auth_session_id=auth_session_id,
            defaults={
                "user": user,
                "guest": guest,
                "subject_type": "user",
                "subject_id": f"user:{user_id}",
                "status": AuthSessionStatus.REVOKED,
                "revoked_at": revoked_at,
                "metadata": {
                    "source": "auth_logout",
                    "auth_state": "anonymous",
                    "client_action": auth_payload.get("client_action") or {},
                },
            },
        )
        chat_session = _bind_chat_session_auth_context(
            session_id=session_id,
            owner_id=user_id,
            auth_context={
                "auth_state": "guest" if guest_id else "anonymous",
                "subject_id": f"user:{user_id}",
                "subject_type": "user",
                "user_id": user_id,
                "guest_id": guest_id or None,
                "auth_session_id": auth_session_id,
            },
        )
        event = _create_auth_event(
            event_type="auth_logout_completed",
            subject_id=f"user:{user_id}",
            user=user,
            guest=guest,
            auth_session=auth_session,
            metadata={
                "source": "auth_logout",
                "auth_state": "anonymous",
                "chat_session_id": chat_session.session_id if chat_session else None,
                "revoked_at": revoked_at.isoformat(),
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
        "auth_session_table": AuthSession._meta.db_table,
        "auth_events_table": AuthEvent._meta.db_table,
        "chat_session_table": ChatSession._meta.db_table,
        "user_id": user.user_id if user else None,
        "guest_id": guest.guest_id if guest else None,
        "auth_session_id": auth_session.auth_session_id,
        "auth_session_status": auth_session.status,
        "event_id": event.event_id,
        "session_id": chat_session.session_id if chat_session else None,
        "status": "saved",
    }


def _update_user_account_from_auth_payload(
    user: UserAccount,
    auth_payload: dict[str, Any],
) -> None:
    user_payload = _dict_or_empty(auth_payload.get("user"))
    metadata = dict(user.metadata or {})
    changed_fields: list[str] = []

    email = _text(user_payload.get("email"))
    if email and user.email != email:
        user.email = email
        changed_fields.append("email")

    display_name = _text(user_payload.get("display_name"))
    if display_name and user.display_name != display_name:
        user.display_name = display_name
        changed_fields.append("display_name")

    auth_provider = _text(user_payload.get("auth_provider") or auth_payload.get("provider"))
    if auth_provider and user.auth_provider != auth_provider:
        user.auth_provider = auth_provider
        changed_fields.append("auth_provider")

    provider_subject = _text(user_payload.get("provider_subject"))
    if provider_subject and user.provider_subject != provider_subject:
        user.provider_subject = provider_subject
        changed_fields.append("provider_subject")

    for key in ("picture", "policy_status"):
        value = user_payload.get(key)
        if value is not None and metadata.get(key) != value:
            metadata[key] = value
    metadata.setdefault("source", "auth_subject")
    if metadata != user.metadata:
        user.metadata = metadata
        changed_fields.append("metadata")

    if changed_fields:
        user.save(update_fields=[*sorted(set(changed_fields)), "updated_at"])


def _upsert_google_oauth_subject(
    user: UserAccount | None,
    auth_payload: dict[str, Any],
) -> dict[str, Any]:
    if user is None:
        return _google_oauth_persistence_skipped("missing_user")

    google = _dict_or_empty(auth_payload.get("google"))
    social_payload = _dict_or_empty(google.get("social_account"))
    oauth_payload = _dict_or_empty(google.get("oauth_connection"))
    private_tokens = _dict_or_empty(auth_payload.get("_private_oauth_tokens"))
    provider = _text(
        social_payload.get("provider")
        or oauth_payload.get("provider")
        or private_tokens.get("provider")
        or auth_payload.get("provider")
    ).lower()
    if provider != "google":
        return _google_oauth_persistence_skipped("not_google_code_flow")

    provider_user_id = _text(social_payload.get("provider_user_id") or user.provider_subject)
    if not provider_user_id:
        return _google_oauth_persistence_skipped("missing_provider_user_id")

    now = timezone.now()
    social_account_id = f"soc_google_{hashlib.sha256(provider_user_id.encode('utf-8')).hexdigest()[:16]}"
    social_account, _social_created = SocialAccount.objects.update_or_create(
        provider=provider,
        provider_user_id=provider_user_id,
        defaults={
            "social_account_id": social_account_id,
            "user": user,
            "email": _text(social_payload.get("email") or user.email),
            "email_verified": bool(social_payload.get("email_verified")),
            "connected_at": now,
            "metadata": {
                "source": "google_auth_code",
                "policy": "provider_user_id_is_google_sub",
            },
        },
    )
    if not google.get("connected") and not private_tokens:
        return {
            "backend": "postgresql",
            "tables": [SocialAccount._meta.db_table],
            "social_account_table": SocialAccount._meta.db_table,
            "oauth_connection_table": None,
            "social_account_id": social_account.social_account_id,
            "oauth_connection_id": None,
            "status": "saved",
        }

    existing_connection = OAuthConnection.objects.filter(user=user, provider=provider).first()
    granted_scopes = _normalize_scope_text(
        private_tokens.get("granted_scopes")
        or oauth_payload.get("granted_scopes")
        or google.get("granted_scopes")
    )
    access_token = _text(private_tokens.get("access_token"))
    refresh_token = _text(private_tokens.get("refresh_token"))
    access_token_encrypted = (
        _protect_oauth_secret(access_token)
        if access_token
        else (existing_connection.access_token_encrypted if existing_connection else "")
    )
    refresh_token_encrypted = (
        _protect_oauth_secret(refresh_token)
        if refresh_token
        else (existing_connection.refresh_token_encrypted if existing_connection else "")
    )
    connection_id = (
        existing_connection.connection_id
        if existing_connection
        else f"oauth_google_{hashlib.sha256(user.user_id.encode('utf-8')).hexdigest()[:16]}"
    )
    oauth_connection, _oauth_created = OAuthConnection.objects.update_or_create(
        user=user,
        provider=provider,
        defaults={
            "connection_id": connection_id,
            "access_token_encrypted": access_token_encrypted,
            "refresh_token_encrypted": refresh_token_encrypted,
            "token_type": _text(private_tokens.get("token_type")) or "Bearer",
            "expires_at": _datetime_or_none(private_tokens.get("expires_at") or oauth_payload.get("expires_at")),
            "granted_scopes": granted_scopes,
            "revoked_at": _datetime_or_none(oauth_payload.get("revoked_at")),
            "metadata": {
                "source": "google_auth_code",
                "purpose": _text(private_tokens.get("purpose") or google.get("purpose")) or "LOGIN",
                "has_access_token": bool(access_token_encrypted),
                "has_refresh_token": bool(refresh_token_encrypted),
                "token_storage": "backend_only",
                "scope_policy": "incremental_authorization",
            },
        },
    )

    return {
        "backend": "postgresql",
        "tables": [SocialAccount._meta.db_table, OAuthConnection._meta.db_table],
        "social_account_table": SocialAccount._meta.db_table,
        "oauth_connection_table": OAuthConnection._meta.db_table,
        "social_account_id": social_account.social_account_id,
        "oauth_connection_id": oauth_connection.connection_id,
        "status": "saved",
    }


def _safe_google_connection_metadata(auth_payload: dict[str, Any]) -> dict[str, Any]:
    google = _dict_or_empty(auth_payload.get("google"))
    if not google:
        return {}
    return {
        "connected": bool(google.get("connected")),
        "purpose": _text(google.get("purpose")),
        "granted_scopes": _list_or_empty(google.get("granted_scopes")),
        "connection_policy": _text(google.get("connection_policy")),
        "token_storage": _text(_dict_or_empty(google.get("oauth_connection")).get("token_storage")),
    }


def _google_oauth_persistence_skipped(reason: str) -> dict[str, Any]:
    return {
        "backend": "postgresql",
        "tables": [SocialAccount._meta.db_table, OAuthConnection._meta.db_table],
        "social_account_table": SocialAccount._meta.db_table,
        "oauth_connection_table": OAuthConnection._meta.db_table,
        "status": "skipped",
        "reason": reason,
    }


def _normalize_scope_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(_text(item) for item in value if _text(item))
    return " ".join(_text(value).split())


def _protect_oauth_secret(value: str) -> str:
    if not value:
        return ""
    plaintext = value.encode("utf-8")
    secret = _oauth_token_secret().encode("utf-8")
    nonce = hashlib.sha256(f"{timezone.now().timestamp()}:{value}".encode("utf-8")).digest()[:16]
    key_stream = _hmac_stream(secret, nonce, len(plaintext))
    ciphertext = bytes(byte ^ key_stream[index] for index, byte in enumerate(plaintext))
    tag = hmac.new(secret, nonce + ciphertext, hashlib.sha256).digest()[:16]
    return "v1." + base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii").rstrip("=")


def _hmac_stream(secret: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hmac.new(secret, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _oauth_token_secret() -> str:
    return (
        _text(getattr(settings, "OAUTH_TOKEN_SECRET", ""))
        or _text(getattr(settings, "APP_JWT_SECRET", ""))
        or _text(getattr(settings, "SECRET_KEY", ""))
        or "dev-only-change-before-deploy"
    )


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
    event_payload["metadata"] = _history_metadata_snapshot(metadata)
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
    subject_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read history events from PostgreSQL using the public history filters."""

    queryset = HistoryEvent.objects.all()
    retention_days = _history_retention_days(subject_type)
    if retention_days:
        queryset = queryset.filter(occurred_at__gte=timezone.now() - timedelta(days=retention_days))
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

    candidate_rows = list(queryset.order_by("-occurred_at", "-id")[: max(limit, 1) * 3])
    rows = [
        event
        for event in candidate_rows
        if _conversation_is_saved_metadata(event.metadata)
    ][: max(limit, 1)]
    return [history_event_to_api(event) for event in reversed(rows)]


def history_operating_policy(subject_type: str | None = None) -> dict[str, Any]:
    normalized_subject_type = _history_subject_type(subject_type)
    return {
        "policy_version": HISTORY_POLICY_VERSION,
        "storage_policy": "standard_light",
        "retention": {
            "applied_subject_type": normalized_subject_type,
            "applied_days": _history_retention_days(normalized_subject_type),
            "anonymous_days": HISTORY_RETENTION_DAYS["anonymous"],
            "guest_days": HISTORY_RETENTION_DAYS["guest"],
            "user_days": HISTORY_RETENTION_DAYS["user"],
        },
        "query_scope": {
            "member": "own_user_history_only",
            "guest": "own_guest_or_authorized_session_only",
            "anonymous": "history_query_denied_without_subject",
        },
        "metadata_policy": {
            "mode": "allowlist_with_sensitive_key_blocklist",
            "allowed_keys": sorted(HISTORY_METADATA_ALLOWED_KEYS),
            "blocked_keys": sorted(SENSITIVE_METADATA_KEYS),
        },
        "after_service_summary": {
            "source": "history_events_standard_light",
            "eligible_event_types": sorted(HISTORY_AFTER_SERVICE_EVENT_TYPES),
            "excludes": ["user_text", "ocr_raw", "agent_reasoning", "raw_output"],
        },
    }


def build_history_after_service_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    eligible_events = [
        event
        for event in events
        if _text(event.get("event_type")) in HISTORY_AFTER_SERVICE_EVENT_TYPES
    ]
    recent_event_types = []
    for event in eligible_events:
        event_type = _text(event.get("event_type"))
        if event_type and event_type not in recent_event_types:
            recent_event_types.append(event_type)

    return {
        "available": bool(eligible_events),
        "source_event_count": len(eligible_events),
        "source": "history_events_standard_light",
        "summary_basis": recent_event_types[:8],
        "excludes_sensitive_payload": True,
        "status": "ready" if eligible_events else "insufficient_history",
    }


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
                        "blocked_attachments": job_payload.get("blocked_attachments", []),
                        "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                        "attachment_resolution": job_payload.get("attachment_resolution", {}),
                        "scan_gate": job_payload.get("scan_gate", {}),
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
                    "blocked_attachments": job_payload.get("blocked_attachments", []),
                    "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                    "attachment_resolution": job_payload.get("attachment_resolution", {}),
                    "scan_gate": job_payload.get("scan_gate", {}),
                    "limitations": job_payload.get("limitations", []),
                },
            },
        )
        _upsert_initial_job_event(
            job,
            progress=progress,
            source="canonical_analysis_job",
            overwrite_existing=not bool(_text(job_payload.get("work_item_id"))),
        )
        node_execution = job_payload.get("node_execution") or {}
        agent_results = _persist_agent_results(job, node_execution)
        ai_session = _upsert_ai_session(job, payload=payload, job_payload=job_payload)
        agent_invocations = _persist_agent_invocations(
            job,
            ai_session=ai_session,
            node_execution=node_execution,
            agent_results=agent_results,
        )
        retrieval_events_saved = RetrievalEvent.objects.filter(job=job).count()

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(session, latest_job=job)

    return {
        "backend": "postgresql",
        "tables": [
            AnalysisJob._meta.db_table,
            AgentResult._meta.db_table,
            AiSession._meta.db_table,
            AgentInvocation._meta.db_table,
            RetrievalEvent._meta.db_table,
        ],
        "analysis_job_table": AnalysisJob._meta.db_table,
        "agent_results_table": AgentResult._meta.db_table,
        "ai_session_table": AiSession._meta.db_table,
        "agent_invocations_table": AgentInvocation._meta.db_table,
        "retrieval_events_table": RetrievalEvent._meta.db_table,
        "agent_results_saved": len(agent_results),
        "agent_invocations_saved": len(agent_invocations),
        "retrieval_events_saved": retrieval_events_saved,
        "agent_result_ids": [result.result_id for result in agent_results],
        "agent_invocation_ids": [invocation.invocation_id for invocation in agent_invocations],
        "ai_session_id": ai_session.ai_session_id,
        "node_codes": [result.node_code for result in agent_results],
        "progress_cache": progress_cache,
        "session_cache": session_cache,
        "status": "saved",
    }


def enqueue_analysis_job_work(
    payload: dict[str, Any],
    job_payload: dict[str, Any],
    *,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Persist a queued worker item without executing the agent plan inline."""

    owner_id = _owner_id(payload)
    session = _get_or_create_session(job_payload.get("session_id"), owner_id=owner_id)
    if session is None:
        raise ValueError("job_payload must include session_id")

    job_id = _text(job_payload.get("job_id"))
    if not job_id:
        raise ValueError("job_payload must include job_id")

    message_id = _text(job_payload.get("message_id"))
    chat_response = _dict_or_empty(job_payload.get("chat_response"))
    analysis_plan = _dict_or_empty(job_payload.get("analysis_plan") or chat_response.get("analysis_plan"))
    active_node = _text(job_payload.get("active_node")) or _analysis_plan_first_node(analysis_plan)
    progress_message = _text(job_payload.get("progress_message")) or "Agent worker item queued."
    work_item_id = _agent_work_item_id(job_id)

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
                        "source": "canonical_analysis_job_queue",
                        "analysis_job_id": job_id,
                        "mock_scenario": job_payload.get("mock_scenario"),
                        "response_status": AgentWorkItemStatus.QUEUED.value,
                        "attachments": job_payload.get("attachments", []),
                        "blocked_attachments": job_payload.get("blocked_attachments", []),
                        "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                        "attachment_resolution": job_payload.get("attachment_resolution", {}),
                        "scan_gate": job_payload.get("scan_gate", {}),
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
                "status": AnalysisJobStatus.QUEUED.value,
                "active_node": active_node,
                "progress_message": progress_message,
                "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
                "status_counts": _analysis_plan_status_counts(analysis_plan),
                "metadata": {
                    "source": "canonical_analysis_job_queue",
                    "analysis_plan": analysis_plan,
                    "assistant_message": chat_response.get("assistant_message"),
                    "case_status": chat_response.get("case_status"),
                    "cards": chat_response.get("cards", []),
                    "pending_questions": chat_response.get("pending_questions", []),
                    "report_links": chat_response.get("report_links", []),
                    "attachments": job_payload.get("attachments", []),
                    "blocked_attachments": job_payload.get("blocked_attachments", []),
                    "attachment_scan_policy": job_payload.get("attachment_scan_policy", {}),
                    "attachment_resolution": job_payload.get("attachment_resolution", {}),
                    "scan_gate": job_payload.get("scan_gate", {}),
                    "limitations": job_payload.get("limitations", []),
                    "work_queue": {
                        "contract_version": "agent_worker_queue.v1",
                        "work_item_id": work_item_id,
                        "status": AgentWorkItemStatus.QUEUED.value,
                    },
                },
            },
        )
        _append_analysis_job_event(
            job,
            status=AnalysisJobStatus.QUEUED.value,
            active_node=active_node,
            message=progress_message,
            source="agent_worker_queue",
            metadata={"work_item_id": work_item_id},
        )
        work_item, _work_item_created = AgentWorkItem.objects.update_or_create(
            work_item_id=work_item_id,
            defaults={
                "job": job,
                "ai_session": None,
                "status": AgentWorkItemStatus.QUEUED.value,
                "attempt_no": 0,
                "max_attempts": max(1, _positive_int_or_default(max_attempts, default=2)),
                "locked_at": None,
                "started_at": None,
                "completed_at": None,
                "next_run_at": timezone.now(),
                "payload": {
                    "contract_version": "agent_worker_queue.v1",
                    "persistence_mode": "analysis_job",
                    "request_payload": _json_compatible(payload),
                    "job_payload": _json_compatible(
                        {
                            **job_payload,
                            "status": AnalysisJobStatus.QUEUED.value,
                            "active_node": active_node,
                            "progress_message": progress_message,
                            "node_execution": {},
                        }
                    ),
                    "execution_payload": _json_compatible(
                        {
                            **payload,
                            "job_id": job_id,
                            "session_id": session.session_id,
                            "message_id": message_id,
                            "attachments": job_payload.get("attachments", []),
                        }
                    ),
                    "analysis_plan": _json_compatible(analysis_plan),
                },
                "result": {},
                "error_code": "",
                "metadata": {
                    "source": "canonical_analysis_job_queue",
                    "job_id": job_id,
                    "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
                },
            },
        )

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": AgentWorkItemStatus.QUEUED.value,
        "execution_mode": "async_worker",
        "progress_state": _work_item_progress_state(work_item, job_status=job.status),
        "tables": [AnalysisJob._meta.db_table, AgentWorkItem._meta.db_table],
        "analysis_job_table": AnalysisJob._meta.db_table,
        "agent_work_items_table": AgentWorkItem._meta.db_table,
        "job_id": job.job_id,
        "work_item_id": work_item.work_item_id,
        "work_item_status": work_item.status,
        "progress_cache": progress_cache,
        "session_cache": session_cache,
    }


def process_agent_work_items(*, limit: int = 1, stale_after_seconds: int | None = None) -> dict[str, Any]:
    """Run queued agent work items once, using the DB row as the worker boundary."""

    now = timezone.now()
    normalized_limit = max(1, min(_positive_int_or_default(limit, default=1), 50))
    stale_requeued = _requeue_stale_agent_work_items(
        now=now,
        stale_after_seconds=stale_after_seconds,
    )
    work_items = list(
        AgentWorkItem.objects.select_related("job", "job__session", "ai_session")
        .filter(
            status__in=[
                AgentWorkItemStatus.QUEUED.value,
                AgentWorkItemStatus.RETRYING.value,
            ]
        )
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        .order_by("created_at")[:normalized_limit]
    )

    results = [process_agent_work_item(work_item.work_item_id) for work_item in work_items]
    return {
        "backend": "postgresql",
        "contract_version": "agent_worker_queue.v1",
        "requested_limit": normalized_limit,
        "stale_requeued": len(stale_requeued),
        "processed": len([item for item in results if item.get("status") != "skipped"]),
        "work_items": results,
        "stale_work_items": stale_requeued,
    }


def process_agent_work_item(work_item_id: str) -> dict[str, Any]:
    normalized_work_item_id = _text(work_item_id)
    if not normalized_work_item_id:
        return _agent_work_item_skipped("missing_work_item_id")

    claimed = _claim_agent_work_item(normalized_work_item_id)
    if not claimed["claimed"]:
        return claimed

    try:
        work_item = AgentWorkItem.objects.select_related("job", "job__session").get(
            work_item_id=normalized_work_item_id
        )
        node_execution = _execute_agent_work_item_plan(work_item)
        final_status = _analysis_job_status_from_node_execution(node_execution)
        completed_job_payload = _completed_job_payload_for_work_item(
            work_item,
            node_execution=node_execution,
            final_status=final_status,
        )
        persistence = persist_analysis_job_execution(
            _dict_or_empty(work_item.payload.get("request_payload")),
            completed_job_payload,
        )
        return _complete_agent_work_item(
            normalized_work_item_id,
            final_status=final_status,
            node_execution=node_execution,
            persistence=persistence,
        )
    except Exception as exc:  # pragma: no cover - exercised through retry smoke tests.
        return _fail_agent_work_item(normalized_work_item_id, exc)


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
    report_owner_id = owner_id or (job.owner_id if job else "") or (session.owner_id if session else "")
    source_storage_uri = _text(payload.get("storage_uri")) or f"mock://reports/{report_id}"
    object_storage = build_report_storage_reference(
        report_id=report_id,
        owner_id=report_owner_id,
        session_id=session.session_id if session else "",
        job_id=job.job_id if job else "",
        source_uri=source_storage_uri,
    )
    object_storage_write = write_object(
        object_storage,
        _report_object_body_for_write(payload, report_payload),
        metadata={
            "report_id": report_id,
            "action": _text(payload.get("action")) or "save",
            "session_id": session.session_id if session else "",
            "job_id": job.job_id if job else "",
        },
    )
    object_storage["write_result"] = object_storage_write
    object_storage["status"] = object_storage_write["status"]
    object_storage["writes_binary"] = object_storage_write["writes_binary"]
    object_storage["persistence_state"] = object_storage_write["persistence_state"]

    report, _created = Report.objects.update_or_create(
        report_id=report_id,
        defaults={
            "owner_id": report_owner_id,
            "session": session,
            "job": job,
            "display_result": display_result,
            "report_type": _report_type(payload.get("report_type")),
            "status": _report_status(report_payload.get("status")),
            "title": _report_title(payload, report_payload),
            "storage_uri": object_storage["storage_uri"],
            "content_summary": _report_content_summary(display_result, report_payload),
            "content": {
                "format": _text(payload.get("format")) or "mock_text",
                "action": _text(payload.get("action")) or "save",
                "case_id": report_payload.get("case_id"),
                "download_url": report_payload.get("download_url"),
                "object_storage": object_storage,
            },
            "metadata": {
                "source": "canonical_report_action",
                "action": _text(payload.get("action")) or "save",
                "mock_status": report_payload.get("status"),
                "limitations": report_payload.get("limitations", []),
                "object_storage_status": object_storage["status"],
                "object_storage": object_storage,
                "object_storage_write": object_storage_write,
                "source_storage_uri": source_storage_uri,
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
        "object_storage": object_storage,
    }


def get_report_download_metadata(report_id: str) -> dict[str, Any] | None:
    report = (
        Report.objects.select_related("session", "job", "display_result")
        .filter(report_id=report_id)
        .first()
    )
    if report is None:
        return None

    object_storage = _report_object_storage(report)
    storage_uri = object_storage["storage_uri"]
    storage_backend = object_storage["backend"]
    return {
        "report_id": report.report_id,
        "owner_id": report.owner_id,
        "session_id": report.session.session_id if report.session_id else None,
        "job_id": report.job.job_id if report.job_id else None,
        "filename": object_storage.get("filename") or f"{report.report_id}.txt",
        "content_type": object_storage.get("content_type") or "text/plain; charset=utf-8",
        "storage_uri": storage_uri,
        "storage_backend": storage_backend,
        "object_storage": object_storage,
        "object_key": object_storage.get("key", ""),
        "status": report.status,
        "body": _report_download_body(
            report,
            storage_backend=storage_backend,
            object_storage=object_storage,
        ),
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

    candidate_jobs = list(queryset[: max(limit, 1) * 3])
    jobs = [
        job
        for job in candidate_jobs
        if _conversation_is_saved_for_job(job)
    ][: max(limit, 1)]
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

    report_rows = list(saved_reports.select_related("session"))
    saved_report_count = sum(1 for report in report_rows if _conversation_is_saved_for_report(report))

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
        "progress_cache": progress_cache_policy(),
        "object_storage": object_storage_policy(),
        "active_cases": sum(1 for case in cases if case["case_status"] in active_statuses),
        "due_soon_cases": 0,
        "saved_reports": saved_report_count,
        "recent_analysis_count": len(cases),
        "cases": cases,
        "conversation_save_policy": {
            "policy_version": CONVERSATION_SAVE_POLICY_VERSION,
            "saved_state": "saved",
            "hidden_states": ["pending", "session_only"],
        },
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
    object_storage = _uploaded_file_object_storage(uploaded_file)

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
        "object_storage": object_storage,
        "status": uploaded_file.status,
        "scan_status": uploaded_file.scan_status,
        "privacy_risk": uploaded_file.privacy_risk,
        "scan_result": metadata.get("scan_result"),
        "created_at": uploaded_file.created_at.isoformat(),
        "checks": checks,
        "agent_handoff": uploaded_file.agent_handoff or {},
        "limitations": limitations,
        "persistence": {
            "backend": "postgresql",
            "table": UploadedFile._meta.db_table,
            "status": "metadata_saved",
            "object_storage": object_storage,
        },
    }
    return {key: value for key, value in attachment.items() if value is not None}


def _uploaded_file_object_storage(uploaded_file: UploadedFile) -> dict[str, Any]:
    metadata = uploaded_file.metadata if isinstance(uploaded_file.metadata, dict) else {}
    object_storage = metadata.get("object_storage")
    if isinstance(object_storage, dict) and object_storage.get("storage_uri"):
        return dict(object_storage)
    return storage_reference_from_uri(
        uploaded_file.storage_uri,
        resource_type="uploaded_file",
        resource_id=uploaded_file.attachment_id,
        filename=Path(uploaded_file.original_filename).name,
        content_type=uploaded_file.content_type,
        size_bytes=uploaded_file.size_bytes,
    )


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


def _conversation_save_state_result(status: str, save_state: str, *, reason: str | None = None) -> dict[str, Any]:
    result = {
        "backend": "postgresql",
        "policy_version": CONVERSATION_SAVE_POLICY_VERSION,
        "status": status,
        "conversation_save_state": save_state,
    }
    if reason:
        result["reason"] = reason
    return result


def _metadata_with_conversation_save_state(
    metadata: Any,
    save_state: str,
    *,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    next_metadata["conversation_save_policy"] = CONVERSATION_SAVE_POLICY_VERSION
    next_metadata["conversation_save_state"] = save_state
    if raw_payload:
        auth_context = raw_payload.get("auth_context") if isinstance(raw_payload.get("auth_context"), dict) else {}
        if auth_context:
            existing_auth_context = (
                next_metadata.get("auth_context")
                if isinstance(next_metadata.get("auth_context"), dict)
                else {}
            )
            next_metadata["auth_context"] = {
                **existing_auth_context,
                **{key: value for key, value in auth_context.items() if value is not None},
            }
        next_metadata.setdefault("conversation_save_source", _conversation_save_source(raw_payload))
    return next_metadata


def _conversation_save_source(payload: dict[str, Any]) -> str:
    if payload.get("conversation_save_source"):
        return _text(payload.get("conversation_save_source"))
    if payload.get("provider") == "google":
        return "auth_login"
    if payload.get("save_state") or payload.get("conversation_save_state"):
        return "save_state_endpoint"
    return "chat_message"


def _conversation_is_saved_for_job(job: AnalysisJob) -> bool:
    state = _conversation_metadata_state(job.metadata)
    if state:
        return state == "saved"
    return _conversation_is_saved_metadata(job.session.metadata if job.session_id else {})


def _conversation_is_saved_for_report(report: Report) -> bool:
    state = _conversation_metadata_state(report.metadata)
    if state:
        return state == "saved"
    return _conversation_is_saved_metadata(report.session.metadata if report.session_id else {})


def _conversation_is_saved_metadata(metadata: Any) -> bool:
    state = _conversation_metadata_state(metadata)
    return state not in {"pending", "session_only"}


def _conversation_metadata_state(metadata: Any) -> str:
    return _text(_dict_or_empty(metadata).get("conversation_save_state"))


def _update_session_message_save_state(session: ChatSession, save_state: str) -> int:
    updated = 0
    for message in ChatMessage.objects.filter(session=session):
        message.metadata = _metadata_with_conversation_save_state(message.metadata, save_state)
        message.save(update_fields=["metadata"])
        updated += 1
    return updated


def _update_session_job_save_state(session: ChatSession, save_state: str, *, owner_id: str = "") -> int:
    updated = 0
    for job in AnalysisJob.objects.filter(session=session):
        job.metadata = _metadata_with_conversation_save_state(job.metadata, save_state)
        update_fields = ["metadata", "updated_at"]
        if save_state == "saved" and owner_id and not job.owner_id:
            job.owner_id = owner_id
            update_fields.append("owner_id")
        job.save(update_fields=update_fields)
        updated += 1
    return updated


def _update_session_history_save_state(session_id: str, save_state: str) -> int:
    updated = 0
    for event in HistoryEvent.objects.filter(subject_session_id=session_id):
        event.metadata = _metadata_with_conversation_save_state(event.metadata, save_state)
        event.save(update_fields=["metadata"])
        updated += 1
    return updated


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


def _json_compatible(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return _text(value)


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


def _analysis_plan_first_node(analysis_plan: dict[str, Any]) -> str:
    steps = analysis_plan.get("steps") or []
    for step in steps:
        if not isinstance(step, dict):
            continue
        node_code = _text(step.get("node_code"))
        if node_code:
            return node_code
    return ""


def _node_execution_summary(node_execution: dict[str, Any]) -> dict[str, Any]:
    if not node_execution:
        return {
            "contract_version": "supervisor_execution.v1",
            "orchestration_mode": "not_recorded",
            "node_codes": [],
        }

    executions = [
        execution
        for execution in node_execution.get("executions", [])
        if isinstance(execution, dict)
    ]
    node_codes = []
    for execution in executions:
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        node_code = _text(agent_output.get("node_code") or execution.get("node_code"))
        if node_code and node_code not in node_codes:
            node_codes.append(node_code)

    return {
        "contract_version": "supervisor_execution.v1",
        "orchestration_mode": "background_session",
        "execution_mode": _text(node_execution.get("execution_mode")) or "mock",
        "job_id": _text(node_execution.get("job_id")) or None,
        "plan_id": _text(node_execution.get("plan_id")) or None,
        "session_id": _text(node_execution.get("session_id")) or None,
        "message_id": _text(node_execution.get("message_id")) or None,
        "status_counts": _dict_or_empty(node_execution.get("status_counts")),
        "completed_node_codes": _list_or_empty(node_execution.get("completed_node_codes")),
        "node_codes": node_codes,
        "node_count": len(executions),
    }


def _analysis_job_status_from_node_execution(node_execution: dict[str, Any]) -> str:
    executions = [
        execution
        for execution in node_execution.get("executions", [])
        if isinstance(execution, dict)
    ]
    if not executions:
        return AnalysisJobStatus.FAILED.value

    counts = _dict_or_empty(node_execution.get("status_counts"))
    failed = int(counts.get("failed") or 0)
    partial = int(counts.get("partial") or 0)
    success = int(counts.get("success") or 0)
    if failed and not success and not partial:
        return AnalysisJobStatus.FAILED.value
    if failed or partial:
        return AnalysisJobStatus.PARTIAL.value
    return AnalysisJobStatus.SUCCESS.value


def _final_node_from_execution(node_execution: dict[str, Any]) -> str:
    completed = _list_or_empty(node_execution.get("completed_node_codes"))
    if completed:
        return _text(completed[-1])
    executions = [
        execution
        for execution in node_execution.get("executions", [])
        if isinstance(execution, dict)
    ]
    if not executions:
        return ""
    last_execution = executions[-1]
    agent_output = last_execution.get("agent_output") if isinstance(last_execution.get("agent_output"), dict) else {}
    return _text(agent_output.get("node_code") or last_execution.get("node_code"))


def _worker_completion_message(final_status: str) -> str:
    if final_status == AnalysisJobStatus.SUCCESS.value:
        return "Agent worker item completed."
    if final_status == AnalysisJobStatus.PARTIAL.value:
        return "Agent worker item completed with partial results."
    return "Agent worker item failed."


def _agent_worker_retry_backoff(work_item: AgentWorkItem) -> timedelta:
    base_seconds = _agent_worker_setting("AGENT_WORKER_RETRY_BACKOFF_SECONDS", 60)
    max_seconds = _agent_worker_setting("AGENT_WORKER_RETRY_BACKOFF_MAX_SECONDS", 900)
    multiplier = 2 ** max(0, work_item.attempt_no - 1)
    return timedelta(seconds=min(base_seconds * multiplier, max_seconds))


def _agent_worker_setting(name: str, default: int) -> int:
    return _positive_int_or_default(getattr(settings, name, default), default=default)


def _agent_work_item_skipped(
    reason: str,
    *,
    work_item_id: str = "",
    current_status: str = "",
    next_run_at: Any = None,
) -> dict[str, Any]:
    result = {
        "backend": "postgresql",
        "status": "skipped",
        "claimed": False,
        "reason": reason,
    }
    if work_item_id:
        result["work_item_id"] = work_item_id
    if current_status:
        result["current_status"] = current_status
    if next_run_at:
        result["next_run_at"] = next_run_at
    return result


def _upsert_initial_job_event(
    job: AnalysisJob,
    *,
    progress: dict[str, Any],
    source: str = "canonical_chat_message",
    overwrite_existing: bool = True,
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

    if not overwrite_existing:
        return

    first_event.status = status
    first_event.active_node = active_node
    first_event.message = message
    first_event.metadata = {"source": source}
    first_event.save(update_fields=["status", "active_node", "message", "metadata"])


def _append_analysis_job_event(
    job: AnalysisJob,
    *,
    status: str,
    active_node: str = "",
    message: str = "",
    source: str,
    metadata: dict[str, Any] | None = None,
) -> AnalysisJobEvent:
    event_metadata = dict(metadata or {})
    event_metadata["source"] = source
    return AnalysisJobEvent.objects.create(
        job=job,
        status=_analysis_job_status(status),
        active_node=_text(active_node),
        message=_text(message),
        metadata=event_metadata,
    )


def _requeue_stale_agent_work_items(
    *,
    now,
    stale_after_seconds: int | None = None,
) -> list[dict[str, Any]]:
    stale_after = _positive_int_or_default(
        stale_after_seconds,
        default=_agent_worker_setting("AGENT_WORKER_STALE_AFTER_SECONDS", 900),
    )
    cutoff = now - timedelta(seconds=stale_after)
    requeued: list[dict[str, Any]] = []

    with transaction.atomic():
        stale_items = list(
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .filter(
                status=AgentWorkItemStatus.RUNNING.value,
                locked_at__isnull=False,
                locked_at__lte=cutoff,
            )
            .order_by("locked_at")[:50]
        )
        for work_item in stale_items:
            job = work_item.job
            can_retry = work_item.attempt_no < work_item.max_attempts
            work_item.status = (
                AgentWorkItemStatus.RETRYING.value
                if can_retry
                else AgentWorkItemStatus.FAILED.value
            )
            work_item.locked_at = None
            work_item.completed_at = None if can_retry else now
            work_item.next_run_at = now if can_retry else None
            work_item.error_code = "worker_lock_timeout"
            work_item.result = {
                "error_code": "worker_lock_timeout",
                "message": f"Agent worker lock exceeded {stale_after} seconds.",
                "retryable": can_retry,
                "stale_after_seconds": stale_after,
            }
            work_item.save(
                update_fields=[
                    "status",
                    "locked_at",
                    "completed_at",
                    "next_run_at",
                    "error_code",
                    "result",
                    "updated_at",
                ]
            )
            job_status = AnalysisJobStatus.RUNNING.value if can_retry else AnalysisJobStatus.FAILED.value
            message = (
                "Agent worker lock expired; item was requeued."
                if can_retry
                else "Agent worker lock expired; item failed."
            )
            _update_job_worker_state(
                job,
                status=job_status,
                active_node=job.active_node,
                progress_message=message,
                work_item=work_item,
            )
            _append_analysis_job_event(
                job,
                status=job_status,
                active_node=job.active_node,
                message=message,
                source="agent_worker_queue",
                metadata={
                    "work_item_id": work_item.work_item_id,
                    "attempt_no": work_item.attempt_no,
                    "error_code": "worker_lock_timeout",
                    "retryable": can_retry,
                    "stale_after_seconds": stale_after,
                },
            )
            requeued.append(
                {
                    "work_item_id": work_item.work_item_id,
                    "job_id": job.job_id,
                    "status": work_item.status,
                    "retryable": can_retry,
                    "attempt_no": work_item.attempt_no,
                    "max_attempts": work_item.max_attempts,
                }
            )

    for item in requeued:
        job = AnalysisJob.objects.select_related("session").filter(job_id=item["job_id"]).first()
        if job is not None:
            write_analysis_job_progress(job)
            write_chat_session_state(job.session, latest_job=job)
    return requeued


def _claim_agent_work_item(work_item_id: str) -> dict[str, Any]:
    with transaction.atomic():
        work_item = (
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .filter(work_item_id=work_item_id)
            .first()
        )
        if work_item is None:
            return _agent_work_item_skipped("work_item_not_found", work_item_id=work_item_id)
        if work_item.status not in {
            AgentWorkItemStatus.QUEUED.value,
            AgentWorkItemStatus.RETRYING.value,
        }:
            return _agent_work_item_skipped(
                "work_item_not_queued",
                work_item_id=work_item.work_item_id,
                current_status=work_item.status,
            )

        now = timezone.now()
        if work_item.next_run_at and work_item.next_run_at > now:
            return _agent_work_item_skipped(
                "work_item_not_ready",
                work_item_id=work_item.work_item_id,
                current_status=work_item.status,
                next_run_at=work_item.next_run_at,
            )

        work_item.status = AgentWorkItemStatus.RUNNING.value
        work_item.attempt_no += 1
        work_item.locked_at = now
        work_item.started_at = work_item.started_at or now
        work_item.completed_at = None
        work_item.next_run_at = None
        work_item.error_code = ""
        work_item.save(
            update_fields=[
                "status",
                "attempt_no",
                "locked_at",
                "started_at",
                "completed_at",
                "next_run_at",
                "error_code",
                "updated_at",
            ]
        )

        job = work_item.job
        active_node = _analysis_plan_first_node(_dict_or_empty(work_item.payload.get("analysis_plan")))
        _update_job_worker_state(
            job,
            status=AnalysisJobStatus.RUNNING.value,
            active_node=active_node or job.active_node,
            progress_message="Agent worker item is running.",
            work_item=work_item,
        )
        _append_analysis_job_event(
            job,
            status=AnalysisJobStatus.RUNNING.value,
            active_node=active_node or job.active_node,
            message="Agent worker item is running.",
            source="agent_worker_queue",
            metadata={"work_item_id": work_item.work_item_id, "attempt_no": work_item.attempt_no},
        )

    progress_cache = write_analysis_job_progress(job)
    write_chat_session_state(job.session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": AgentWorkItemStatus.RUNNING.value,
        "claimed": True,
        "work_item_id": work_item.work_item_id,
        "job_id": job.job_id,
        "attempt_no": work_item.attempt_no,
        "progress_state": _work_item_progress_state(work_item, job_status=job.status),
        "progress_cache": progress_cache,
    }


def _execute_agent_work_item_plan(work_item: AgentWorkItem) -> dict[str, Any]:
    from app.services.agent_node_service import execute_mock_plan

    queue_payload = _dict_or_empty(work_item.payload)
    analysis_plan = _dict_or_empty(queue_payload.get("analysis_plan"))
    job_payload = _dict_or_empty(queue_payload.get("job_payload"))
    execution_payload = _dict_or_empty(queue_payload.get("execution_payload"))
    execution_payload.setdefault("job_id", work_item.job.job_id)
    execution_payload.setdefault("session_id", work_item.job.session.session_id)
    execution_payload.setdefault("message_id", _text(job_payload.get("message_id")))
    return execute_mock_plan(analysis_plan, execution_payload)


def _completed_job_payload_for_work_item(
    work_item: AgentWorkItem,
    *,
    node_execution: dict[str, Any],
    final_status: str,
) -> dict[str, Any]:
    queue_payload = _dict_or_empty(work_item.payload)
    job_payload = _dict_or_empty(queue_payload.get("job_payload"))
    analysis_plan = _dict_or_empty(queue_payload.get("analysis_plan") or job_payload.get("analysis_plan"))
    return {
        **job_payload,
        "job_id": work_item.job.job_id,
        "session_id": work_item.job.session.session_id,
        "message_id": _text(job_payload.get("message_id")),
        "status": final_status,
        "active_node": _final_node_from_execution(node_execution),
        "progress_message": _worker_completion_message(final_status),
        "analysis_plan": analysis_plan,
        "analysis_plan_id": _text(job_payload.get("analysis_plan_id") or analysis_plan.get("plan_id")),
        "node_execution": node_execution,
        "status_counts": _dict_or_empty(node_execution.get("status_counts")),
        "work_item_id": work_item.work_item_id,
    }


def _complete_agent_work_item(
    work_item_id: str,
    *,
    final_status: str,
    node_execution: dict[str, Any],
    persistence: dict[str, Any],
) -> dict[str, Any]:
    with transaction.atomic():
        work_item = (
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .get(work_item_id=work_item_id)
        )
        job = work_item.job
        ai_session = AiSession.objects.filter(ai_session_id=persistence.get("ai_session_id")).first()
        work_item.ai_session = ai_session
        work_item.status = (
            AgentWorkItemStatus.FAILED.value
            if final_status == AnalysisJobStatus.FAILED.value
            else AgentWorkItemStatus.SUCCESS.value
        )
        work_item.completed_at = timezone.now()
        work_item.locked_at = None
        work_item.next_run_at = None
        work_item.error_code = ""
        work_item.result = {
            "final_status": final_status,
            "node_execution": _node_execution_summary(node_execution),
            "persistence": {
                "agent_results_saved": persistence.get("agent_results_saved", 0),
                "agent_invocations_saved": persistence.get("agent_invocations_saved", 0),
                "retrieval_events_saved": persistence.get("retrieval_events_saved", 0),
            },
        }
        work_item.save(
            update_fields=[
                "ai_session",
                "status",
                "completed_at",
                "locked_at",
                "next_run_at",
                "error_code",
                "result",
                "updated_at",
            ]
        )
        _update_job_worker_state(
            job,
            status=final_status,
            active_node=_final_node_from_execution(node_execution),
            progress_message=_worker_completion_message(final_status),
            work_item=work_item,
        )
        _append_analysis_job_event(
            job,
            status=final_status,
            active_node=job.active_node,
            message=_worker_completion_message(final_status),
            source="agent_worker_queue",
            metadata={"work_item_id": work_item.work_item_id, "attempt_no": work_item.attempt_no},
        )

    progress_cache = write_analysis_job_progress(job)
    session_cache = write_chat_session_state(job.session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": work_item.status,
        "job_status": final_status,
        "work_item_id": work_item.work_item_id,
        "job_id": job.job_id,
        "attempt_no": work_item.attempt_no,
        "progress_state": _work_item_progress_state(work_item, job_status=final_status),
        "progress_cache": progress_cache,
        "session_cache": session_cache,
        "persistence": persistence,
    }


def _fail_agent_work_item(work_item_id: str, exc: Exception) -> dict[str, Any]:
    error_code = exc.__class__.__name__
    with transaction.atomic():
        work_item = (
            AgentWorkItem.objects.select_for_update()
            .select_related("job", "job__session")
            .filter(work_item_id=work_item_id)
            .first()
        )
        if work_item is None:
            return _agent_work_item_skipped("work_item_not_found", work_item_id=work_item_id)

        job = work_item.job
        can_retry = work_item.attempt_no < work_item.max_attempts
        work_item.status = (
            AgentWorkItemStatus.RETRYING.value
            if can_retry
            else AgentWorkItemStatus.FAILED.value
        )
        work_item.locked_at = None
        work_item.completed_at = None if can_retry else timezone.now()
        retry_after = _agent_worker_retry_backoff(work_item) if can_retry else None
        work_item.next_run_at = timezone.now() + retry_after if retry_after else None
        work_item.error_code = error_code
        work_item.result = {
            "error_code": error_code,
            "message": _text(exc),
            "retryable": can_retry,
            "retry_after_seconds": int(retry_after.total_seconds()) if retry_after else 0,
        }
        work_item.save(
            update_fields=[
                "status",
                "locked_at",
                "completed_at",
                "next_run_at",
                "error_code",
                "result",
                "updated_at",
            ]
        )
        job_status = AnalysisJobStatus.RUNNING.value if can_retry else AnalysisJobStatus.FAILED.value
        _update_job_worker_state(
            job,
            status=job_status,
            active_node=job.active_node,
            progress_message="Agent worker item will retry." if can_retry else "Agent worker item failed.",
            work_item=work_item,
        )
        _append_analysis_job_event(
            job,
            status=job_status,
            active_node=job.active_node,
            message="Agent worker item will retry." if can_retry else "Agent worker item failed.",
            source="agent_worker_queue",
            metadata={
                "work_item_id": work_item.work_item_id,
                "attempt_no": work_item.attempt_no,
                "error_code": error_code,
                "retryable": can_retry,
            },
        )

    progress_cache = write_analysis_job_progress(job)
    write_chat_session_state(job.session, latest_job=job)
    return {
        "backend": "postgresql",
        "status": work_item.status,
        "job_status": job.status,
        "work_item_id": work_item.work_item_id,
        "job_id": job.job_id,
        "attempt_no": work_item.attempt_no,
        "error_code": error_code,
        "retryable": can_retry,
        "progress_state": _work_item_progress_state(work_item, job_status=job.status),
        "progress_cache": progress_cache,
    }


def _update_job_worker_state(
    job: AnalysisJob,
    *,
    status: str,
    active_node: str,
    progress_message: str,
    work_item: AgentWorkItem,
) -> None:
    metadata = _dict_or_empty(job.metadata)
    metadata["work_queue"] = {
        **_dict_or_empty(metadata.get("work_queue")),
        "contract_version": "agent_worker_queue.v1",
        "work_item_id": work_item.work_item_id,
        "status": work_item.status,
        "progress_state": _work_item_progress_state(work_item, job_status=status),
        "attempt_no": work_item.attempt_no,
        "max_attempts": work_item.max_attempts,
        "next_run_at": work_item.next_run_at.isoformat() if work_item.next_run_at else None,
    }
    job.status = _analysis_job_status(status)
    job.active_node = _text(active_node)
    job.progress_message = _text(progress_message)
    job.metadata = metadata
    job.save(update_fields=["status", "active_node", "progress_message", "metadata", "updated_at"])


def _work_item_progress_state(
    work_item: AgentWorkItem,
    *,
    job_status: str,
) -> dict[str, Any]:
    state = AgentWorkItemStatus.RETRYING.value if work_item.status == AgentWorkItemStatus.RETRYING.value else work_item.status
    if state == AgentWorkItemStatus.RETRYING.value:
        state = "retry_waiting"
    retry_after_seconds = 0
    if work_item.next_run_at:
        retry_after_seconds = max(0, int((work_item.next_run_at - timezone.now()).total_seconds()))
    return {
        "contract_version": "agent_worker_progress.v1",
        "state": state,
        "work_item_status": work_item.status,
        "job_status": _analysis_job_status(job_status),
        "attempt_no": work_item.attempt_no,
        "max_attempts": work_item.max_attempts,
        "retryable": work_item.status == AgentWorkItemStatus.RETRYING.value,
        "retry_after_seconds": retry_after_seconds,
        "next_run_at": work_item.next_run_at.isoformat() if work_item.next_run_at else None,
    }


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
        now = timezone.now()

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
                "started_at": now,
                "completed_at": None if status == AgentInvocationStatus.RUNNING.value else now,
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
                    final_status=status,
                ),
            },
        )
        _persist_retrieval_event_for_invocation(
            job=job,
            invocation=invocation,
            execution=execution,
            agent_output=agent_output,
            agent_result=agent_result,
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


def _agent_work_item_id(job_id: str) -> str:
    readable_id = f"awork_{job_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:20]
    return f"awork_{digest}"


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
            "metadata": _history_metadata_snapshot(event_payload.get("metadata")),
            "privacy": _dict_or_empty(event_payload.get("privacy")),
        },
    )
    return event


def _history_metadata_snapshot(metadata: Any) -> dict[str, Any]:
    raw_metadata = _dict_or_empty(metadata)
    sanitized: dict[str, Any] = {}
    dropped_keys = []

    for key, value in raw_metadata.items():
        normalized_key = str(key)
        if (
            normalized_key not in HISTORY_METADATA_ALLOWED_KEYS
            or normalized_key.lower() in SENSITIVE_METADATA_KEYS
        ):
            dropped_keys.append(normalized_key)
            continue
        sanitized[normalized_key] = _strip_sensitive_history_metadata(value)

    if dropped_keys:
        sanitized["metadata_policy"] = {
            "policy_version": HISTORY_POLICY_VERSION,
            "dropped_keys": sorted(dropped_keys),
        }
    return sanitized


def _strip_sensitive_history_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_sensitive_history_metadata(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_strip_sensitive_history_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _history_retention_days(subject_type: str | None) -> int:
    return HISTORY_RETENTION_DAYS.get(_history_subject_type(subject_type), HISTORY_RETENTION_DAYS["anonymous"])


def _history_subject_type(subject_type: str | None) -> str:
    normalized = _text(subject_type)
    if normalized == "authenticated":
        return "user"
    if normalized in HISTORY_RETENTION_DAYS:
        return normalized
    return "anonymous"


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
    final_status: str,
) -> dict[str, Any]:
    plan_step = execution.get("plan_step") if isinstance(execution.get("plan_step"), dict) else {}
    return {
        "source": "canonical_analysis_job",
        "orchestration_policy": "sync_worker_progress.v1",
        "queue_runtime": "inline_sync",
        "execution_id": execution.get("execution_id"),
        "agent_result_id": agent_result.result_id if agent_result else None,
        "plan_step": plan_step,
        "adapter_context": execution.get("adapter_context") or {},
        "execution_status": execution.get("execution_status") or agent_output.get("execution_status"),
        "status_timeline": _agent_invocation_status_timeline(final_status),
        "created_at": agent_output.get("created_at") or execution.get("created_at"),
    }


def _persist_retrieval_event_for_invocation(
    *,
    job: AnalysisJob,
    invocation: AgentInvocation,
    execution: dict[str, Any],
    agent_output: dict[str, Any],
    agent_result: AgentResult | None,
) -> RetrievalEvent | None:
    if invocation.node_code != "law_ground_search":
        return None

    structured_result = _dict_or_empty(agent_output.get("structured_result"))
    retrieval = _dict_or_empty(structured_result.get("retrieval"))
    matched_laws = _list_or_empty(structured_result.get("matched_laws"))
    source_refs = [
        _text(item.get("source_reference"))
        for item in matched_laws
        if isinstance(item, dict) and _text(item.get("source_reference"))
    ]
    if not source_refs:
        source_refs = [
            _text(item.get("source_reference"))
            for item in _list_or_empty(agent_output.get("evidence"))
            if isinstance(item, dict) and _text(item.get("source_reference"))
        ]
    query_text = _text(retrieval.get("query")) or _law_ground_query_from_execution(execution)
    event, _created = RetrievalEvent.objects.update_or_create(
        retrieval_event_id=_retrieval_event_id(job.job_id, invocation.invocation_id),
        defaults={
            "job": job,
            "invocation": invocation,
            "query_text": query_text,
            "query_type": _text(retrieval.get("backend")) or "mock_or_semantic",
            "top_k": _positive_int_or_default(retrieval.get("top_k"), default=len(source_refs)),
            "result_count": _positive_int_or_default(retrieval.get("result_count"), default=len(source_refs)),
            "source_refs": source_refs,
            "filters": {"node_code": invocation.node_code, "source_type": "law"},
            "latency_ms": _positive_int_or_none(retrieval.get("latency_ms")),
            "metadata": {
                "source": "agent_invocation_persistence",
                "retrieval_contract_version": retrieval.get("contract_version"),
                "retrieval_status": retrieval.get("status"),
                "retrieval_backend": retrieval.get("backend"),
                "retrieval_quality": structured_result.get("retrieval_quality"),
                "fallback_from": retrieval.get("fallback_from"),
                "attempted_backends": retrieval.get("attempted_backends") or [],
                "embedding": retrieval.get("embedding") or {},
                "sql_tables": retrieval.get("sql_tables") or [],
                "agent_result_id": agent_result.result_id if agent_result else None,
                "execution_id": execution.get("execution_id"),
            },
        },
    )
    return event


def _agent_invocation_status_timeline(final_status: str) -> list[dict[str, str]]:
    timeline = [
        {"status": AgentInvocationStatus.QUEUED.value, "stage": "scheduled"},
        {"status": AgentInvocationStatus.RUNNING.value, "stage": "worker_started"},
    ]
    if final_status == AgentInvocationStatus.QUEUED.value:
        return timeline[:1]
    if final_status == AgentInvocationStatus.RUNNING.value:
        return timeline
    timeline.append({"status": final_status, "stage": "worker_finished"})
    if final_status == AgentInvocationStatus.FAILED.value:
        timeline.append({"status": AgentInvocationStatus.RETRYING.value, "stage": "retryable_review"})
    return timeline


def _law_ground_query_from_execution(execution: dict[str, Any]) -> str:
    agent_input = _dict_or_empty(execution.get("agent_input"))
    context = _dict_or_empty(agent_input.get("context"))
    supervisor = _dict_or_empty(context.get("supervisor_handoff"))
    for package in _list_or_empty(supervisor.get("agent_input_packages")):
        if not isinstance(package, dict) or package.get("node_code") != "law_ground_search":
            continue
        payload = _dict_or_empty(package.get("payload"))
        query = payload.get("search_query") or payload.get("violation_text")
        if query:
            return _text(query)
    return _text(agent_input.get("user_text"))


def _retrieval_event_id(job_id: str, invocation_id: str) -> str:
    readable_id = f"retr_{job_id}_{invocation_id}"
    if len(readable_id) <= 64:
        return readable_id
    digest = hashlib.sha1(f"{job_id}:{invocation_id}".encode("utf-8")).hexdigest()[:20]
    return f"retr_{digest}"


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


def _report_object_storage(report: Report) -> dict[str, Any]:
    metadata = report.metadata if isinstance(report.metadata, dict) else {}
    object_storage = metadata.get("object_storage")
    if isinstance(object_storage, dict) and object_storage.get("storage_uri"):
        return dict(object_storage)
    return storage_reference_from_uri(
        report.storage_uri or f"mock://reports/{report.report_id}",
        resource_type="report",
        resource_id=report.report_id,
        filename=f"{report.report_id}.txt",
        content_type="text/plain; charset=utf-8",
    )


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


def _report_download_body(
    report: Report,
    *,
    storage_backend: str,
    object_storage: dict[str, Any] | None = None,
) -> str:
    object_storage = object_storage or _report_object_storage(report)
    lines = [
        f"Report metadata download for {report.report_id}",
        f"status: {report.status}",
        f"storage_backend: {storage_backend}",
        f"storage_uri: {object_storage.get('storage_uri') or report.storage_uri}",
        f"object_key: {object_storage.get('key') or ''}",
        f"object_storage_policy: {object_storage.get('policy_version') or ''}",
    ]
    if report.job_id:
        lines.append(f"job_id: {report.job.job_id}")
    if report.display_result_id:
        lines.append(f"display_result_id: {report.display_result.display_result_id}")
    if report.content_summary:
        lines.append("")
        lines.append(report.content_summary)
    return "\n".join(lines) + "\n"


def _report_object_body_for_write(
    payload: dict[str, Any],
    report_payload: dict[str, Any],
) -> str:
    lines = [
        f"Report object for {report_payload.get('report_id')}",
        f"action: {_text(payload.get('action')) or 'save'}",
        f"status: {_text(report_payload.get('status'))}",
        f"title: {_text(payload.get('title'))}",
        f"case_id: {_text(report_payload.get('case_id'))}",
    ]
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
