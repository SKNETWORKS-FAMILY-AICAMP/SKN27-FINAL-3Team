import pytest

from app.services.openapi_persona_schema_service import (
    build_persona_contract_pack,
    list_personas,
)


def test_list_personas_includes_pm_agent_and_supervisor_roles():
    assert {"hi20260204-maker", "agent", "supervisor", "django_backend"} <= set(
        list_personas()
    )


def test_hi20260204_pack_exposes_openapi_contract_and_review_boundaries():
    pack = build_persona_contract_pack("hi20260204-maker")

    assert pack["openapi"] == "3.2.0"
    assert pack["contract_version"] == "pm-api-json-schema.v0"
    assert pack["endpoint_count"] >= 20
    assert {
        "AnalysisPlan",
        "AgentAdapterOutput",
        "AgentResultValidationResult",
        "ObjectionReportGenerationResult",
        "HistoryEvent",
    } <= set(pack["schemas"])
    assert any(
        item["path"] == "/api/reports/objection-draft/"
        for item in pack["review_required"]["endpoints"]
    )
    assert any("review_required endpoint" in item for item in pack["next_actions"])


def test_agent_pack_contains_adapter_contract_and_node_structured_results():
    pack = build_persona_contract_pack("agent", include_review_required=True)

    assert {
        "AgentAdapterInput",
        "AgentAdapterContext",
        "AgentAdapterOutput",
        "FineNoticeAnalysisResult",
        "LawGroundSearchResult",
        "TextMlCaseSearchResult",
        "VisionMediaAnalysisResult",
        "TrafficAccidentConfirmationOcrResult",
        "ObjectionReportGenerationResult",
    } <= set(pack["schemas"])
    assert {endpoint["path"] for endpoint in pack["endpoints"]} >= {
        "/api/agents/nodes/",
        "/api/agents/nodes/run/",
        "/api/agents/plans/run/",
    }
    assert all(
        endpoint["contract_status"] == "confirmed" for endpoint in pack["endpoints"]
    )


def test_supervisor_pack_can_exclude_review_required_endpoints():
    pack = build_persona_contract_pack("supervisor", include_review_required=False)

    assert "AnalysisPlan" in pack["schemas"]
    assert "AgentPlanExecution" in pack["schemas"]
    assert all(
        endpoint["contract_status"] != "review_required"
        for endpoint in pack["endpoints"]
    )
    assert "/api/reports/objection-draft/" not in {
        endpoint["path"] for endpoint in pack["endpoints"]
    }


def test_unknown_persona_reports_supported_values():
    with pytest.raises(ValueError) as exc_info:
        build_persona_contract_pack("unknown")

    assert "Unsupported persona" in str(exc_info.value)
    assert "hi20260204-maker" in str(exc_info.value)
