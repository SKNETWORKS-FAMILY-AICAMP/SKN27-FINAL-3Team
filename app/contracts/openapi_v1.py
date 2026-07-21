"""Deterministic OpenAPI v1 generation from the shadow route registry."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import yaml
from pydantic import BaseModel

from app.contracts.api_route_specs import (
    API_ROUTE_SPECS,
    RequestParameterSpec,
    RouteSpec,
)


def _schema_ref(model: type[BaseModel]) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{model.__name__}"}


def _component_schemas(specs: Iterable[RouteSpec]) -> dict[str, dict[str, Any]]:
    models: dict[str, type[BaseModel]] = {}
    for spec in specs:
        if spec.request_model is not None:
            models[spec.request_model.__name__] = spec.request_model
        if spec.response_model is not None:
            models[spec.response_model.__name__] = spec.response_model
        for content in spec.success_content:
            if content.response_model is not None:
                models[content.response_model.__name__] = content.response_model
        for error in spec.errors:
            models[error.response_model.__name__] = error.response_model

    schemas: dict[str, dict[str, Any]] = {}
    for name in sorted(models):
        schema = models[name].model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
        definitions = schema.pop("$defs", {})
        for definition_name in sorted(definitions):
            schemas[definition_name] = definitions[definition_name]
        schemas[name] = schema
    return schemas


def _operation(spec: RouteSpec) -> dict[str, Any]:
    operation: dict[str, Any] = {
        "tags": list(spec.tags),
        "summary": spec.summary,
        "operationId": spec.operation_id,
        "security": _security_requirements(spec),
        "x-contract-status": spec.contract_status,
        "x-django-route-name": spec.route_name,
        "x-django-view": spec.view_name,
        "responses": {
            str(status): _success_response(spec)
            for status in (spec.success_statuses or (spec.success_status,))
        }
        | {
            **{
                str(error.status): {
                    "description": "Typed API error response",
                    "content": {
                        "application/json": {
                            "schema": _schema_ref(error.response_model),
                        }
                    },
                    "x-error-codes": list(error.codes),
                }
                for error in spec.errors
            },
        },
    }
    parameters = [
        {
            "name": parameter.name,
            "in": "path",
            "required": True,
            "description": parameter.description,
            "schema": {
                "type": "string",
                "minLength": parameter.min_length,
                "maxLength": parameter.max_length,
            },
        }
        for parameter in spec.path_parameters
    ]
    parameters.extend(
        _request_parameter(parameter) for parameter in spec.request_parameters
    )
    if parameters:
        operation["parameters"] = [
            *parameters
        ]
    if spec.request_model is not None:
        operation["requestBody"] = {
            "required": spec.request_body_required,
            "content": {
                media_type: {"schema": _schema_ref(spec.request_model)}
                for media_type in spec.request_media_types
            },
        }
    return operation


def _success_response(spec: RouteSpec) -> dict[str, Any]:
    response: dict[str, Any] = {
        "description": "Successful response",
        "content": _success_response_content(spec),
    }
    if spec.success_headers:
        response["headers"] = {
            header.name: {
                "description": header.description,
                "required": header.required,
                "schema": dict(header.schema),
            }
            for header in spec.success_headers
        }
    return response


def _success_response_content(spec: RouteSpec) -> dict[str, dict[str, Any]]:
    if not spec.success_content:
        assert spec.response_model is not None
        return {"application/json": {"schema": _schema_ref(spec.response_model)}}
    return {
        content.media_type: {"schema": _content_schema(content)}
        for content in spec.success_content
    }


def _content_schema(content: Any) -> dict[str, Any]:
    if content.response_model is not None:
        return _schema_ref(content.response_model)
    assert content.schema is not None
    return dict(content.schema)


def _security_requirements(spec: RouteSpec) -> list[dict[str, list[str]]]:
    if spec.security_requirements:
        return [
            {scheme: list(scopes) for scheme, scopes in requirement.items()}
            for requirement in spec.security_requirements
        ]
    if spec.auth_required:
        return [{"bearerAuth": []}]
    if spec.auth_optional:
        return [{}, {"bearerAuth": []}]
    return []


def _request_parameter(parameter: RequestParameterSpec) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if parameter.format:
        schema["format"] = parameter.format
    if parameter.allowed_values:
        schema["enum"] = list(parameter.allowed_values)
    return {
        "name": parameter.name,
        "in": parameter.location,
        "required": parameter.required,
        "description": parameter.description,
        "schema": schema,
    }


def build_openapi_document(
    specs: Iterable[RouteSpec] = API_ROUTE_SPECS,
) -> dict[str, Any]:
    route_specs = tuple(specs)
    paths: dict[str, dict[str, Any]] = {}
    for spec in route_specs:
        paths.setdefault(spec.path, {})[spec.method.lower()] = _operation(spec)

    return {
        "openapi": "3.2.0",
        "info": {
            "title": "SKN27 Traffic Dispute AI API",
            "version": "1.0.0",
            "description": (
                "Generated shadow contract for executable Django API behavior. "
                "It does not replace urlpatterns while route specs remain shadow-only."
            ),
        },
        "jsonSchemaDialect": "https://json-schema.org/draft/2020-12/schema",
        "x-contract-mode": "shadow",
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                },
                "guestCredentialAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Guest-Credential",
                    "description": "Server-verified guest credential for protected guest routes.",
                },
            },
            "schemas": _component_schemas(route_specs),
        },
    }


def render_openapi_yaml(specs: Iterable[RouteSpec] = API_ROUTE_SPECS) -> str:
    return yaml.safe_dump(
        build_openapi_document(specs),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
