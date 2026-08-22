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
    """Authorize and list attachments using the current repository contract."""

    trusted_identity = _trusted_identity(query.identity_payload, query.session_id)
    subject = access_subject_from_payload(trusted_identity)["subject"]
    violation = query.guest_violation_resolver(subject)
    if violation:
        raise FileReadGuestIdentityInvalid(violation)

    access = _authorize_session_query(
        query.session_id,
        trusted_identity,
        resource_type="uploaded_file_list",
    )
    if not access["allowed"]:
        raise FileReadAccessDenied(access)

    owner_id = str(subject.get("user_id") or "")
    attachments = list_uploaded_files(
        session_id=query.session_id,
        owner_id=owner_id or None,
    )
    return ListFileAttachmentsResult(payload={"attachments": attachments})


def execute_get_file_attachment(
    query: GetFileAttachmentQuery,
) -> GetFileAttachmentResult:
    """Authorize and return one attachment using the current repository contract."""

    trusted_identity = _trusted_identity(query.identity_payload, query.session_id)
    access_metadata = get_uploaded_file_access_metadata(query.attachment_id)
    if access_metadata is not None:
        access = authorize_resource_access(access_metadata, trusted_identity)
        if not access["allowed"]:
            raise FileReadAccessDenied(access)

    attachment = get_uploaded_file(query.attachment_id)
    if attachment is None:
        raise FileReadNotFound()
    return GetFileAttachmentResult(payload={"attachment": attachment})


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
