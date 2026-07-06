from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import (
    ELASTICSEARCH_HOST,
    ELASTICSEARCH_PASSWORD,
    ELASTICSEARCH_REQUEST_TIMEOUT,
    ELASTICSEARCH_USER,
)


@dataclass(frozen=True)
class AgentElasticsearchSettings:
    host: str = ELASTICSEARCH_HOST
    username: str = ELASTICSEARCH_USER
    password: str = ELASTICSEARCH_PASSWORD
    request_timeout: int = ELASTICSEARCH_REQUEST_TIMEOUT


def build_elasticsearch_client_kwargs(
    settings: AgentElasticsearchSettings = AgentElasticsearchSettings(),
) -> dict[str, Any]:
    """Build kwargs for the official Elasticsearch Python client."""

    kwargs: dict[str, Any] = {
        "hosts": [settings.host],
        "request_timeout": settings.request_timeout,
    }

    if settings.username:
        if not settings.password:
            raise ValueError(
                "Elasticsearch password is required when username is set. "
                "Set TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD or ELASTIC_PASSWORD in .env."
            )
        kwargs["basic_auth"] = (settings.username, settings.password)

    return kwargs


def get_elasticsearch_client(
    settings: AgentElasticsearchSettings = AgentElasticsearchSettings(),
) -> Any:
    """Create an Elasticsearch client for Agent runtime use.

    Import is intentionally inside the function so unit tests and skeleton runs
    do not require the package until a real client is requested.
    """

    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:
        raise RuntimeError(
            "elasticsearch package is required to create the Agent Elasticsearch client. "
            "Install requirements.txt first."
        ) from exc

    return Elasticsearch(**build_elasticsearch_client_kwargs(settings))


def ping_elasticsearch(client: Any) -> bool:
    """Return whether the provided client can reach Elasticsearch."""

    return bool(client.ping())
