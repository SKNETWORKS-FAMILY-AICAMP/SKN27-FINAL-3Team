from __future__ import annotations

import importlib


def test_mypage_summary_has_a_compatibility_preserving_shadow_contract() -> None:
    contracts = importlib.import_module("app.contracts.mypage")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    spec = next(
        item
        for item in route_specs.MYPAGE_API_ROUTE_SPECS
        if (item.method, item.path) == ("GET", "/api/mypage/summary/")
    )

    assert spec.route_name == "canonical-mypage-summary"
    assert spec.view_name == "mypage_summary"
    assert spec.request_model is None
    assert spec.response_model is contracts.MyPageSummaryResponse
    assert spec.success_status == 200
    assert spec.auth_required is True
    assert spec.auth_optional is False
    assert spec.contract_status == "shadow"
    assert spec.tags == ("MyPage",)

    parameters = {(item.name, item.location): item for item in spec.request_parameters}
    assert set(parameters) == {
        ("session_id", "query"),
        ("owner_id", "query"),
        ("user_id", "query"),
        ("limit", "query"),
    }
    assert "takes precedence" in parameters[("owner_id", "query")].description
    assert "only when owner_id is absent" in parameters[("user_id", "query")].description
    assert "default of 10" in parameters[("limit", "query")].description
    assert "invalid values fall back" in parameters[("limit", "query")].description

    response_model = contracts.MyPageSummaryResponse
    assert response_model.model_config["extra"] == "allow"
    assert set(response_model.model_fields) >= {
        "active_cases",
        "due_soon_cases",
        "saved_reports",
        "recent_analysis_count",
        "cases",
        "conversation_save_policy",
        "limitations",
    }

    deferred = {(item.method, item.path) for item in route_specs.DEFERRED_ROUTE_SPECS}
    assert ("GET", "/api/mypage/summary/") not in deferred


def test_openapi_documents_mypage_summary_as_an_app_jwt_protected_route() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    operation = generator.build_openapi_document()["paths"]["/api/mypage/summary/"]["get"]

    assert operation["operationId"] == "getMyPageSummary"
    assert operation["security"] == [{"bearerAuth": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MyPageSummaryResponse"
    }
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "session_id",
        "owner_id",
        "user_id",
        "limit",
    ]
    assert generator.build_openapi_document()["components"]["schemas"][
        "MyPageSummaryResponse"
    ]["additionalProperties"] is True
