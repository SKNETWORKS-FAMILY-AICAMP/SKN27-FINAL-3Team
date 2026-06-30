"""OpenAPI v0 contract slicing helpers for role/persona handoff."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_OPENAPI_PATH = Path("docs/api/openapi-v0.yaml")

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

PERSONA_CONFIGS: dict[str, dict[str, Any]] = {
    "frontend": {
        "description": "Frontend screen/API consumer contract pack.",
        "tags": ["Auth", "Chat", "Files", "Analysis Results", "Reports", "MyPage", "History"],
        "schemas": [
            "AuthContext",
            "ChatMessageRequest",
            "ChatMessageResponse",
            "AnalysisResult",
            "ReportActionRequest",
            "ReportActionResponse",
            "HistoryEvent",
        ],
    },
    "django_backend": {
        "description": "Django backend route, storage, and mock boundary contract pack.",
        "tags": ["Auth", "Chat", "Files", "Analysis Jobs", "Analysis Results", "Agents", "Reports", "History"],
        "schemas": [
            "AuthErrorEnvelope",
            "CanonicalMockMeta",
            "Attachment",
            "AnalysisJob",
            "AgentAdapterInput",
            "AgentAdapterOutput",
            "HistoryEvent",
        ],
    },
    "supervisor": {
        "description": "Supervisor routing, analysis plan, and display merge contract pack.",
        "tags": ["Chat", "Analysis Jobs", "Analysis Results", "Agents", "Reports", "History"],
        "schemas": [
            "AnalysisPlan",
            "AnalysisPlanStep",
            "AgentPlanExecution",
            "AnalysisResult",
            "AgentResultSummary",
            "ObjectionReportGenerationResult",
            "AgentResultValidationResult",
            "HistoryEvent",
        ],
    },
    "agent": {
        "description": "Agent adapter input/output and node structured_result contract pack.",
        "tags": ["Agents"],
        "schemas": [
            "AgentAdapterInput",
            "AgentAdapterContext",
            "AgentAdapterOutput",
            "FineNoticeAnalysisResult",
            "LawGroundSearchResult",
            "TextMlCaseSearchResult",
            "VisionMediaAnalysisResult",
            "TrafficAccidentConfirmationOcrResult",
            "ObjectionReportGenerationResult",
            "AgentResultValidationResult",
            "Evidence",
        ],
    },
    "hi20260204-maker": {
        "description": "PM/Django/Supervisor/QA scope owned by hi20260204-maker.",
        "tags": [
            "Auth",
            "Chat",
            "Files",
            "Analysis Jobs",
            "Analysis Results",
            "Agents",
            "Reports",
            "MyPage",
            "History",
        ],
        "schemas": [
            "AuthContext",
            "AuthErrorEnvelope",
            "AnalysisPlan",
            "AnalysisJob",
            "AnalysisResult",
            "AgentAdapterInput",
            "AgentAdapterOutput",
            "AgentResultValidationResult",
            "ObjectionReportGenerationResult",
            "ReportActionRequest",
            "ReportActionResponse",
            "ObjectionDraftRequest",
            "ObjectionDraftResponse",
            "HistoryEvent",
            "MyPageSummary",
        ],
    },
}


def list_personas() -> list[str]:
    """Return supported OpenAPI contract slicing personas."""

    return sorted(PERSONA_CONFIGS)


def build_persona_contract_pack(
    persona: str,
    *,
    openapi_path: Path | str = DEFAULT_OPENAPI_PATH,
    include_review_required: bool = True,
) -> dict[str, Any]:
    """Build a role-specific pack of endpoint summaries and referenced schemas."""

    normalized_persona = _normalize_persona(persona)
    config = PERSONA_CONFIGS[normalized_persona]
    document = _load_openapi(Path(openapi_path))
    operations = _select_operations(
        document,
        tags=set(config["tags"]),
        include_review_required=include_review_required,
    )
    schema_names = _collect_schema_names(document, operations, config["schemas"])
    schemas = {
        name: deepcopy(document["components"]["schemas"][name])
        for name in sorted(schema_names)
        if name in document["components"]["schemas"]
    }

    return {
        "persona": normalized_persona,
        "description": config["description"],
        "source": str(openapi_path),
        "openapi": document.get("openapi"),
        "contract_version": document.get("info", {}).get("x-contract-version"),
        "distribution_date": document.get("info", {}).get("x-distribution-date"),
        "include_review_required": include_review_required,
        "endpoint_count": len(operations),
        "schema_count": len(schemas),
        "endpoints": operations,
        "schemas": schemas,
        "review_required": _review_required_items(operations, schemas),
        "next_actions": _next_actions_for(normalized_persona, operations, schemas),
    }


def _normalize_persona(persona: str) -> str:
    normalized = str(persona or "").strip().replace("_", "-")
    aliases = {
        "backend": "django_backend",
        "django": "django_backend",
        "hi20260204": "hi20260204-maker",
        "pm": "hi20260204-maker",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in PERSONA_CONFIGS:
        raise ValueError(f"Unsupported persona: {persona!r}. Use one of {list_personas()}.")
    return normalized


def _load_openapi(openapi_path: Path) -> dict[str, Any]:
    return yaml.safe_load(openapi_path.read_text(encoding="utf-8"))


def _select_operations(
    document: dict[str, Any],
    *,
    tags: set[str],
    include_review_required: bool,
) -> list[dict[str, Any]]:
    selected = []
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_tags = set(operation.get("tags", []))
            if not operation_tags & tags:
                continue
            status = operation.get("x-contract-status", "unspecified")
            if status == "review_required" and not include_review_required:
                continue
            selected.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId"),
                    "summary": operation.get("summary"),
                    "tags": list(operation.get("tags", [])),
                    "contract_status": status,
                    "review_note": operation.get("x-review-note"),
                    "schema_refs": sorted(_ref_names(operation)),
                }
            )
    selected.sort(key=lambda item: (item["path"], item["method"]))
    return selected


def _collect_schema_names(
    document: dict[str, Any],
    operations: list[dict[str, Any]],
    seed_schema_names: list[str],
) -> set[str]:
    available_schemas = document.get("components", {}).get("schemas", {})
    pending = set(seed_schema_names)
    for operation in operations:
        pending.update(operation["schema_refs"])

    collected: set[str] = set()
    while pending:
        schema_name = pending.pop()
        if schema_name in collected or schema_name not in available_schemas:
            continue
        collected.add(schema_name)
        pending.update(_ref_names(available_schemas[schema_name]))
    return collected


def _review_required_items(
    operations: list[dict[str, Any]],
    schemas: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "endpoints": [
            {
                "method": operation["method"],
                "path": operation["path"],
                "summary": operation["summary"],
                "review_note": operation["review_note"],
            }
            for operation in operations
            if operation["contract_status"] == "review_required"
        ],
        "schemas": [
            {
                "name": name,
                "review_note": schema.get("x-review-note"),
                "review_required_values": schema.get("x-review-required-values", []),
            }
            for name, schema in sorted(schemas.items())
            if schema.get("x-contract-status") == "review_required"
            or schema.get("x-review-note")
            or schema.get("x-review-required-values")
        ],
    }


def _next_actions_for(
    persona: str,
    operations: list[dict[str, Any]],
    schemas: dict[str, Any],
) -> list[str]:
    review_required = _review_required_items(operations, schemas)
    actions = []
    if review_required["endpoints"]:
        actions.append("review_required endpoint는 구현하지 말고 정책/저장 범위를 먼저 확정한다.")
    if review_required["schemas"]:
        actions.append("review_required schema는 담당자 sample output과 충돌 여부를 먼저 확인한다.")
    if persona in {"agent", "supervisor", "hi20260204-maker"}:
        actions.append("Agent output은 status, summary, structured_result, evidence, next_actions, limitations를 포함한다.")
    if persona in {"django_backend", "hi20260204-maker"}:
        actions.append("confirmed canonical /api 경로와 mock alias의 응답 차이를 회귀 테스트로 고정한다.")
    return actions


def _ref_names(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            schema_name = _schema_name_from_ref(ref)
            if schema_name:
                refs.add(schema_name)
        for item in value.values():
            refs.update(_ref_names(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_ref_names(item))
    return refs


def _schema_name_from_ref(ref: str) -> str | None:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return None
    return ref[len(prefix) :]
