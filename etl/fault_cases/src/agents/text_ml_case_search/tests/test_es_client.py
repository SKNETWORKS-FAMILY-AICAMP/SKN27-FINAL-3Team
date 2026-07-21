from __future__ import annotations

from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import (
    AgentElasticsearchSettings,
    build_elasticsearch_client_kwargs,
)


def test_build_elasticsearch_client_kwargs_uses_basic_auth() -> None:
    pwd = "test-" + "password"
    kwargs = build_elasticsearch_client_kwargs(
        AgentElasticsearchSettings(
            host="http://localhost:9200",
            username="elastic",
            password=pwd,
            request_timeout=30,
        )
    )

    assert kwargs == {
        "hosts": ["http://localhost:9200"],
        "request_timeout": 30,
        "basic_auth": ("elastic", pwd),
    }


def test_build_elasticsearch_client_kwargs_allows_no_auth() -> None:
    empty = ""
    kwargs = build_elasticsearch_client_kwargs(
        AgentElasticsearchSettings(
            host="http://localhost:9200",
            username="",
            password=empty,
            request_timeout=30,
        )
    )

    assert kwargs == {
        "hosts": ["http://localhost:9200"],
        "request_timeout": 30,
    }


def test_build_elasticsearch_client_kwargs_rejects_missing_password_with_username() -> None:
    empty = ""
    try:
        build_elasticsearch_client_kwargs(
            AgentElasticsearchSettings(
                host="http://localhost:9200",
                username="elastic",
                password=empty,
                request_timeout=30,
            )
        )
    except ValueError as exc:
        assert "TEXT_ML_CASE_SEARCH_ELASTICSEARCH_PASSWORD" in str(exc)
    else:
        raise AssertionError("Expected ValueError when username is set without password")
