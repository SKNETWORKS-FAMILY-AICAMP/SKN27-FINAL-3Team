"""Application queries for the canonical FileRead surface."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from chatbot.repositories import (
    access_subject_from_payload,
    authorize_resource_access,
    get_chat_session_access_metadata,
    get_uploaded_file,
    get_uploaded_file_access_metadata,
    list_uploaded_files,
)


GuestViolationResolver = Callable[[Mapping[str, Any]], dict[str, Any] | None]

PUBLIC_FILE_ATTACHMENT_FIELDS = (
    "attachment_id",
    "case_id",
    "session_id",
    "message_id",
    "purpose",
    "type",
    "original_filename",
    "filename",
    "content_type",
    "size_bytes",
    "status",
    "scan_status",
    "retention_expires_at",
    "privacy_risk",
    "created_at",
    "limitations",
)

@dataclass(frozen=True)
class ListFileAttachmentsQuery:
    identity_payload: Mapping[str, Any]
    session_id: str | None
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class GetFileAttachmentQuery:
    attachment_id: str
    identity_payload: Mapping[str, Any]
    session_id: str | None
    guest_violation_resolver: GuestViolationResolver


@dataclass(frozen=True)
class ListFileAttachmentsResult:
    payload: dict[str, Any]


@dataclass(frozen=True)
class GetFileAttachmentResult:
    payload: dict[str, Any]


class FileReadGuestIdentityInvalid(Exception):
    def __init__(self, violation: Mapping[str, Any]) -> None:
        super().__init__("file read guest identity is invalid")
        self.violation = dict(violation)


class FileReadAccessDenied(Exception):
    def __init__(self, access: Mapping[str, Any]) -> None:
        super().__init__("file read access denied")
        self.access = dict(access)


class FileReadNotFound(Exception):
    """The requested file attachment does not exist."""


def execute_list_file_attachments(
    query: ListFileAttachmentsQuery,
) -> ListFileAttachmentsResult:
    """Authorize and project a public attachment list with a trusted scope."""

    trusted_identity = _trusted_identity(query.identity_payload, query.session_id)
    subject = access_subject_from_payload(trusted_identity)["subject"]
    violation = query.guest_violation_resolver(subject)
    if violation:
        raise FileReadGuestIdentityInvalid(violation)

    subject_type = str(subject.get("subject_type") or "")
    owner_id = str(subject.get("user_id") or "")
    if not query.session_id:
        if subject_type != "user" or not owner_id:
            raise FileReadAccessDenied(_unscoped_list_access_denied())
        attachments = list_uploaded_files(owner_id=owner_id)
    else:
        session_access = get_chat_session_access_metadata(query.session_id)
        if subject_type == "guest" and session_access is None:
            raise FileReadAccessDenied(_unscoped_list_access_denied())
        access = _authorize_session_query(
            query.session_id,
            trusted_identity,
            resource_type="uploaded_file_list",
        )
        if not access["allowed"]:
            raise FileReadAccessDenied(access)
        if subject_type not in {"user", "guest"}:
            raise FileReadAccessDenied(_unscoped_list_access_denied())
        attachments = list_uploaded_files(
            session_id=query.session_id,
            owner_id=owner_id or None,
        )

    return ListFileAttachmentsResult(
        payload={
            "attachments": [
                project_file_attachment_public(attachment) for attachment in attachments
            ]
        }
    )


def execute_get_file_attachment(
    query: GetFileAttachmentQuery,
) -> GetFileAttachmentResult:
    """Authorize and project one attachment with guest and session parity."""

    trusted_identity = _trusted_identity(query.identity_payload, query.session_id)
    subject = access_subject_from_payload(trusted_identity)["subject"]
    violation = query.guest_violation_resolver(subject)
    if violation:
        raise FileReadGuestIdentityInvalid(violation)

    access_metadata = get_uploaded_file_access_metadata(query.attachment_id)
    if access_metadata is not None:
        _authorize_supplied_session_scope(
            query.session_id,
            access_metadata,
            trusted_identity,
        )
        access = authorize_resource_access(access_metadata, trusted_identity)
        if not access["allowed"]:
            raise FileReadAccessDenied(access)

    attachment = get_uploaded_file(query.attachment_id)
    if attachment is None:
        raise FileReadNotFound()
    return GetFileAttachmentResult(
        payload={"attachment": project_file_attachment_public(attachment)}
    )


def _trusted_identity(
    identity_payload: Mapping[str, Any],
    session_id: str | None,
) -> dict[str, Any]:
    auth_context = identity_payload.get("auth_context")
    trusted_identity = (
        {"auth_context": dict(auth_context)}
        if isinstance(auth_context, Mapping)
        else {}
    )
    if session_id:
        trusted_identity["session_id"] = session_id
    return trusted_identity


def _authorize_session_query(
    session_id: str | None,
    identity_payload: dict[str, Any],
    *,
    resource_type: str,
) -> dict[str, Any]:
    if not session_id:
        return authorize_resource_access({"type": resource_type}, identity_payload)
    session_access = get_chat_session_access_metadata(session_id)
    if session_access is None:
        return authorize_resource_access(
            {"type": resource_type, "session_id": session_id},
            identity_payload,
        )
    session_access["type"] = resource_type
    return authorize_resource_access(session_access, identity_payload)


def project_file_attachment_public(attachment: Mapping[str, Any]) -> dict[str, Any]:
    """Return the single allow-listed FileRead representation for public GET routes."""

    record = dict(attachment)
    return {
        field: record[field]
        for field in PUBLIC_FILE_ATTACHMENT_FIELDS
        if field in record
    }


def _authorize_supplied_session_scope(
    session_id: str | None,
    access_metadata: Mapping[str, Any],
    identity_payload: dict[str, Any],
) -> None:
    if not session_id:
        return

    session_access = get_chat_session_access_metadata(session_id)
    if session_access is not None:
        access = authorize_resource_access(session_access, identity_payload)
        if not access["allowed"]:
            raise FileReadAccessDenied(access)

    actual_session_id = str(access_metadata.get("session_id") or "")
    if actual_session_id != session_id:
        raise FileReadAccessDenied(
            {
                "contract_version": "object_access.v1",
                "allowed": False,
                "reason": "session_mismatch",
                "resource": {
                    "type": "uploaded_file",
                    "attachment_id": access_metadata.get("attachment_id"),
                },
            }
        )


def _unscoped_list_access_denied() -> dict[str, Any]:
    return {
        "contract_version": "object_access.v1",
        "allowed": False,
        "reason": "trusted_scope_required",
        "resource": {"type": "uploaded_file_list"},
    }