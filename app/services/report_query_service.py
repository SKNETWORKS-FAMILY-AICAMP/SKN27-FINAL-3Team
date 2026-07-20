"""Public projections for persisted report query records."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.report import (
    ReportApiError,
    ReportApiErrorResponse,
    ReportContent,
    ReportDetail,
    ReportDetailResponse,
    ReportListResponse,
    ReportMetadata,
    ReportQuality,
    ReportReportingPayload,
    ReportSection,
    ReportSummary,
)


WORKER_REPORT_SOURCE = "analysis_worker_reporting"
PUBLIC_REPORTING_PAYLOAD_KEYS = (
    "report_type",
    "screen_id",
    "stage",
    "title",
    "summary",
    "document_variant",
    "document_readiness",
    "report_actions",
    "appeal_gate",
    "sections",
)
PUBLIC_REPORT_QUALITY_KEYS = (
    "contract_version",
    "partial_report",
    "review_required",
    "limitation_count",
    "limitations",
    "confidence_label",
)
PUBLIC_REPORT_ERROR_KEYS = (
    "contract_version",
    "type",
    "code",
    "status",
    "message",
    "missing_fields",
    "retryable",
    "required_action",
    "action",
    "reason",
    "policy_version",
    "report_id",
    "guest_id",
    "guest_status",
)


def compose_report_list_response(
    records: Sequence[Mapping[str, Any]],
    *,
    api_surface: str,
) -> dict[str, Any]:
    """Project stored report summaries into the explicit public list DTO."""

    response = ReportListResponse(
        api_surface=api_surface,
        reports=[_report_summary(record) for record in records],
    )
    return response.model_dump(mode="json")


def compose_report_detail_response(
    record: Mapping[str, Any],
    *,
    api_surface: str,
    execution_mode: str,
) -> dict[str, Any]:
    """Project one stored report without leaking persistence-only metadata."""

    content = _mapping(record.get("content"))
    metadata = _mapping(record.get("metadata"))
    report = ReportDetail(
        **_report_summary(record).model_dump(mode="python"),
        content=ReportContent(
            contract_version=_optional_text(content.get("contract_version")),
            format=_optional_text(content.get("format")),
            action=_optional_text(content.get("action")),
            reporting_payload=ReportReportingPayload(
                **_public_reporting_payload(content.get("reporting_payload"))
            ),
        ),
        metadata=ReportMetadata(
            report_quality=ReportQuality(
                **_public_report_quality(metadata.get("report_quality"))
            ),
            limitations=_text_list(metadata.get("limitations")),
        ),
    )
    response = ReportDetailResponse(
        api_surface=api_surface,
        execution_mode=execution_mode,
        report=report,
    )
    return response.model_dump(mode="json")


def compose_report_error_response(error: Mapping[str, Any]) -> dict[str, Any]:
    """Return a narrow report error envelope without access or storage internals."""

    public = {
        key: deepcopy(error[key])
        for key in PUBLIC_REPORT_ERROR_KEYS
        if key in error
    }
    public["missing_fields"] = _text_list(public.get("missing_fields"))
    auth = _mapping(error.get("auth"))
    if auth:
        public["auth"] = _public_error_auth(auth)
    subject = _mapping(error.get("subject"))
    if subject:
        public["subject"] = _public_error_subject(subject)
    access = _mapping(error.get("access"))
    if access:
        public["access"] = _public_error_access(access)
    response = ReportApiErrorResponse(error=ReportApiError(**public))
    return response.model_dump(mode="json")


def report_api_surface(*, canonical: bool, source: object) -> str:
    """Keep the existing public API-surface labels in one place."""

    if not canonical:
        return "mock"
    if _optional_text(source) == WORKER_REPORT_SOURCE:
        return "canonical"
    return "canonical_mock"


def report_execution_mode(*, source: object) -> str:
    """Return the public execution-mode label for a stored report source."""

    if _optional_text(source) == WORKER_REPORT_SOURCE:
        return "async_worker"
    return "mock"


def _report_summary(record: Mapping[str, Any]) -> ReportSummary:
    return ReportSummary(
        report_id=record.get("report_id"),
        report_type=record.get("report_type"),
        screen_id=_text(record.get("screen_id")),
        title=_text(record.get("title")),
        status=record.get("status"),
        session_id=_optional_text(record.get("session_id")),
        job_id=_optional_text(record.get("job_id")),
        summary=_text(record.get("summary")),
        download_url=_optional_text(record.get("download_url")),
        partial_report=bool(record.get("partial_report")),
        created_at=record.get("created_at"),
        updated_at=record.get("updated_at"),
    )


def _public_reporting_payload(value: object) -> dict[str, Any]:
    payload = _mapping(value)
    public: dict[str, Any] = {}
    for key in PUBLIC_REPORTING_PAYLOAD_KEYS:
        if key == "sections":
            public[key] = _public_sections(payload.get(key))
        elif key == "document_readiness":
            readiness = _mapping(payload.get(key))
            if readiness:
                public[key] = {
                    "ready_for_docx": bool(readiness.get("ready_for_docx")),
                    "missing_field_details": _public_document_fields(
                        readiness.get("missing_field_details")
                    ),
                    "next_questions": _public_document_fields(readiness.get("next_questions")),
                }
        elif key == "report_actions":
            public[key] = _public_report_actions(payload.get(key))
        elif key == "appeal_gate":
            appeal_gate = _mapping(payload.get(key))
            if appeal_gate:
                public[key] = {
                    "blocked": bool(appeal_gate.get("blocked")),
                    "reason": _optional_text(appeal_gate.get("reason")),
                }
        elif key in payload:
            public[key] = deepcopy(payload[key])
    return public


def _public_document_fields(value: object) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for item in _sequence(value):
        source = _mapping(item)
        field = _optional_text(source.get("field"))
        label = _optional_text(source.get("label"))
        question = _optional_text(source.get("question"))
        if not any((field, label, question)):
            continue
        fields.append(
            {
                key: item_value
                for key, item_value in (
                    ("field", field),
                    ("label", label),
                    ("question", question),
                )
                if item_value is not None
            }
        )
    return fields


def _public_report_actions(value: object) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for item in _sequence(value):
        source = _mapping(item)
        action_type = _optional_text(source.get("type"))
        label = _optional_text(source.get("label"))
        document_type = _optional_text(source.get("document_type"))
        document_format = _optional_text(source.get("document_format"))
        if not all((action_type, label, document_type)):
            continue
        action = {
            "type": action_type,
            "label": label,
            "document_type": document_type,
        }
        if document_format == "docx":
            action["document_format"] = document_format
        actions.append(action)
    return actions


def _public_report_quality(value: object) -> dict[str, Any]:
    quality = _mapping(value)
    public: dict[str, Any] = {}
    for key in PUBLIC_REPORT_QUALITY_KEYS:
        if key == "limitations":
            public[key] = _text_list(quality.get(key))
        elif key in quality:
            public[key] = deepcopy(quality[key])
    return public


def _public_error_auth(auth: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _optional_text(auth.get(key))
        for key in ("scheme", "reason")
        if _optional_text(auth.get(key)) is not None
    }


def _public_error_subject(subject: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _optional_text(subject.get(key))
        for key in (
            "subject_id",
            "subject_type",
            "user_id",
            "guest_id",
            "auth_session_id",
        )
        if _optional_text(subject.get(key)) is not None
    }


def _public_error_access(access: Mapping[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {
        "allowed": bool(access.get("allowed")),
    }
    for key in ("contract_version", "reason"):
        value = _optional_text(access.get(key))
        if value is not None:
            public[key] = value
    resource = _mapping(access.get("resource"))
    if resource:
        public["resource"] = {
            key: _optional_text(resource.get(key))
            for key in ("type", "report_id", "session_id")
            if _optional_text(resource.get(key)) is not None
        }
    return public


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _public_sections(value: object) -> list[ReportSection]:
    if not isinstance(value, list):
        return []
    return [
        ReportSection(
            title=_optional_text(item.get("title")),
            body=_optional_text(item.get("body")),
            items=_text_list(item.get("items")),
        )
        for item in value
        if isinstance(item, Mapping)
    ]


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None
