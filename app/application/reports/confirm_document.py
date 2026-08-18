"""Application orchestration for confirming a Report document."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.contracts.report import ConfirmReportDocumentRequest
from chatbot.repositories import (
    access_subject_from_payload,
    authorize_report_download_metadata,
    confirm_report_document,
    get_report_access_metadata,
)


@dataclass(frozen=True)
class ConfirmReportDocumentCommand:
    report_id: str
    identity_payload: Mapping[str, Any]
    raw_payload: Mapping[str, Any]


ConfirmReportDocumentCommand.dataclass_fields = ConfirmReportDocumentCommand.__dataclass_fields__


@dataclass(frozen=True)
class ConfirmReportDocumentResult:
    confirmation: dict[str, Any]


class ReportDocumentConfirmationAccessDenied(Exception):
    def __init__(self, access: dict[str, Any]) -> None:
        super().__init__("report document confirmation access denied")
        self.access = access


class ReportDocumentConfirmationLoginRequired(Exception):
    def __init__(self, subject: Mapping[str, Any]) -> None:
        super().__init__("report document confirmation requires an authenticated user")
        self.subject = dict(subject)


class ReportDocumentConfirmationNotFound(Exception):
    """The requested Report has no access metadata."""


def execute_confirm_report_document(
    command: ConfirmReportDocumentCommand,
) -> ConfirmReportDocumentResult:
    """Authorize, validate, then delegate the existing confirmation transaction."""

    auth_context = command.identity_payload.get("auth_context")
    trusted_identity = (
        {"auth_context": dict(auth_context)}
        if isinstance(auth_context, Mapping)
        else {}
    )
    subject = access_subject_from_payload(trusted_identity)["subject"]
    if subject.get("subject_type") != "user":
        raise ReportDocumentConfirmationLoginRequired(subject)

    access_metadata = get_report_access_metadata(command.report_id)
    if access_metadata is None:
        raise ReportDocumentConfirmationNotFound()
    access = authorize_report_download_metadata(access_metadata, trusted_identity)
    if not access["allowed"]:
        raise ReportDocumentConfirmationAccessDenied(access)

    ConfirmReportDocumentRequest.model_validate(dict(command.raw_payload))
    confirmation = confirm_report_document(
        command.report_id,
        owner_id=str(subject.get("user_id") or ""),
    )
    return ConfirmReportDocumentResult(confirmation=confirmation)