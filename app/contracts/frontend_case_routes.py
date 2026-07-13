"""Deterministic frontend Case route catalog generation."""

from __future__ import annotations

from collections.abc import Iterable
import json

from app.contracts.api_route_specs import CASE_API_ROUTE_SPECS, RouteSpec


def build_frontend_case_route_catalog(
    specs: Iterable[RouteSpec] = CASE_API_ROUTE_SPECS,
) -> dict[str, dict[str, str]]:
    return {
        spec.operation_id: {
            "method": spec.method,
            "path": spec.path.removeprefix("/api/"),
        }
        for spec in specs
    }


def render_frontend_case_routes_json(
    specs: Iterable[RouteSpec] = CASE_API_ROUTE_SPECS,
) -> str:
    return json.dumps(
        build_frontend_case_route_catalog(specs),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
