"""Static shadow-contract regressions for ``GET /api/history/``."""

from __future__ import annotations

import importlib


def test_history_route_spec_declares_public_dto_filters_and_auth_boundary() -> None:
    contracts = importlib.import_module("app.contracts.history")
    route_specs = importlib.import_module("app.contracts.api_route_specs")

    spec = next(
        item
        for item in route_specs.HISTORY_API_ROUTE_SPECS
        if (item.method, item.path) == ("GET", "/api/history/")
    )

    assert spec.response_model is contracts.HistoryListResponse
    assert spec.auth_required is False
    assert spec.auth_optional is False
    assert spec.security_requirements == (
        {"bearerAuth": ()},
        {"guestCredentialAuth": ()},
    )
    assert [(parameter.name, parameter.location) for parameter in spec.request_parameters] == [
        ("X-Guest-Credential", "header"),
        ("X-Guest-Id", "header"),
        ("session_id", "query"),
        ("user_id", "query"),
        ("guest_id", "query"),
        ("job_id", "query"),
        ("event_type", "query"),
        ("limit", "query"),
    ]
    assert spec.request_parameters[-1].description.endswith("default is 100.")
    assert not {
        (item.method, item.path) for item in route_specs.DEFERRED_ROUTE_SPECS
    }.intersection({("GET", "/api/history/")})


def test_history_openapi_contract_keeps_guest_credential_distinct_from_guest_id() -> None:
    generator = importlib.import_module("app.contracts.openapi_v1")
    document = generator.build_openapi_document()
    operation = document["paths"]["/api/history/"]["get"]

    assert operation["security"] == [
        {"bearerAuth": []},
        {"guestCredentialAuth": []},
    ]
    assert document["components"]["securitySchemes"]["guestCredentialAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-Guest-Credential",
        "description": "Server-verified guest credential for protected guest routes.",
    }
    assert operation["parameters"][:2] == [
        {
            "name": "X-Guest-Credential",
            "in": "header",
            "required": False,
            "description": "Signed guest credential required to prove a supplied guest identity.",
            "schema": {"type": "string"},
        },
        {
            "name": "X-Guest-Id",
            "in": "header",
            "required": False,
            "description": "Optional guest identifier. It is not valid identity proof without X-Guest-Credential.",
            "schema": {"type": "string"},
        },
    ]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HistoryListResponse"
    }
