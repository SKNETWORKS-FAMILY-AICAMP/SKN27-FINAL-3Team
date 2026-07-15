import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import legal_rag_service as service


class FakeIntrospection:
    def __init__(self, table_names):
        self._table_names = table_names

    def table_names(self):
        return self._table_names


VECTOR_DESCRIPTION = [
        ("chunk_id",),
        ("source_id",),
        ("source_name",),
        ("source_type",),
        ("chunk_type",),
        ("article_no",),
        ("appendix_no",),
        ("form_no",),
        ("provision_text",),
        ("normalized_text",),
        ("source_url",),
        ("enforce_date",),
        ("expire_date",),
        ("domain_tags",),
        ("embedding_provider",),
        ("embedding_model",),
        ("embedding_dimensions",),
        ("score",),
]


class FakeCursor:

    def __init__(self, rows, description=None):
        self.rows = rows
        self.description = description or VECTOR_DESCRIPTION
        self.sql = ""
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (1,)


class FakeConnection:
    vendor = "postgresql"

    def __init__(self, cursor):
        self.introspection = FakeIntrospection(["law_chunks", "law_embeddings"])
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_legal_rag_uses_pgvector_when_enabled(monkeypatch):
    cursor = FakeCursor(
        [
            (
                "law_chunk_001",
                "road_traffic_act",
                "Road Traffic Act",
                "law",
                "article",
                "Article 32",
                None,
                None,
                "Emergency stopping in a school zone can require factual evidence.",
                "school zone emergency stopping evidence",
                "https://example.test/law",
                date(2026, 1, 1),
                None,
                ["school_zone", "fine_notice"],
                "hash",
                "hashing-vectorizer",
                1024,
                0.91,
            )
        ]
    )
    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(cursor))

    result = service.search_legal_rag("school zone emergency stopping", top_k=2)

    assert result["status"] == "ready"
    assert result["backend"] == "postgres_pgvector"
    assert result["embedding"]["provider"] == "hash"
    assert result["embedding"]["dimensions"] == 1024
    assert result["sql_tables"] == ["law_chunks", "law_embeddings"]
    assert result["results"][0]["source_reference"] == "law_chunk_001"
    assert result["results"][0]["score"] == 0.91
    assert result["results"][0]["effective_date"] == "2026-01-01"
    assert cursor.params[-1] == 2
    assert "law_embeddings" in cursor.sql
    assert "btrim(c.source_url) <> ''" in cursor.sql
    assert "btrim(c.provision_text) <> ''" in cursor.sql
    assert "e.embedding_vector IS NOT NULL" in cursor.sql


def test_legal_rag_falls_back_when_pgvector_is_unavailable(monkeypatch):
    class MissingTableConnection:
        vendor = "postgresql"
        introspection = FakeIntrospection([])

    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setattr(service, "_django_connection", lambda: MissingTableConnection())

    def fake_lexical(query, *, top_k, source_type, **_filters):
        return {
            "contract_version": "legal_rag_search.v1",
            "status": "ready",
            "backend": "django_rag_tables",
            "query": query,
            "top_k": top_k,
            "result_count": 1,
            "latency_ms": 0,
            "results": [{"source_reference": "rag_fallback"}],
            "error_code": "",
        }

    monkeypatch.setattr(service, "_search_django_rag_tables", fake_lexical)

    result = service.search_legal_rag("fallback query", top_k=1)

    assert result["backend"] == "django_rag_tables"
    assert result["fallback_from"]["backend"] == "postgres_pgvector"
    assert result["fallback_from"]["status"] == "unavailable"
    assert [item["backend"] for item in result["attempted_backends"]] == [
        "postgres_pgvector",
        "postgres_lexical",
        "django_rag_tables",
    ]


def test_legal_rag_uses_seeded_law_chunks_lexical_when_vector_is_disabled(monkeypatch):
    lexical_description = [
        item
        for item in VECTOR_DESCRIPTION
        if item
        not in {
            ("embedding_provider",),
            ("embedding_model",),
            ("embedding_dimensions",),
            ("score",),
        }
    ] + [("matched_token_count",), ("query_token_count",), ("score",)]
    cursor = FakeCursor(
        [
            (
                "law_chunk_lexical_001",
                "road_traffic_act",
                "도로교통법",
                "law",
                "article",
                "제5조",
                None,
                None,
                "모든 차마의 운전자는 신호 또는 지시를 따라야 한다.",
                "신호 지시 준수",
                "https://example.test/law/5",
                date(2026, 1, 1),
                None,
                ["traffic_signal"],
                3,
                3,
                1.0,
            )
        ],
        description=lexical_description,
    )
    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "0")
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(cursor))
    monkeypatch.setattr(
        service,
        "_search_django_rag_tables",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("seeded law_chunks lexical results must win before legacy Django RAG")
        ),
    )

    result = service.search_legal_rag("신호 지시 준수", top_k=2)

    assert result["status"] == "ready"
    assert result["backend"] == "postgres_lexical"
    assert result["sql_tables"] == ["law_chunks"]
    assert result["results"][0]["source_reference"] == "law_chunk_lexical_001"
    assert result["results"][0]["article"] == "제5조"
    assert "law_chunks" in cursor.sql
    assert "c.source_type = ANY(%s)" in cursor.sql
    assert "btrim(c.source_url) <> ''" in cursor.sql
    assert "btrim(c.provision_text) <> ''" in cursor.sql
    assert cursor.params[-1] == 2


def test_pgvector_applies_legal_family_scope_and_effective_date(monkeypatch):
    cursor = FakeCursor([])
    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(cursor))

    result = service.search_legal_rag(
        "signal compliance",
        top_k=2,
        source_type="law",
        temporal_basis={"mode": "as_of", "effective_at": "2026-02-01"},
        scope={"jurisdiction": "KR", "allowed_source_types": ["law", "enforcement_decree"]},
    )

    assert result["status"] in {"empty", "unavailable"}
    assert "c.source_type = ANY(%s)" in cursor.sql
    assert "c.enforce_date IS NOT NULL" in cursor.sql
    assert "c.enforce_date <= %s" in cursor.sql
    assert "c.expire_date IS NULL OR c.expire_date >= %s" in cursor.sql
    assert ["law", "enforcement_decree"] in cursor.params
    assert cursor.params.count(date(2026, 2, 1)) == 2


def test_lexical_score_is_normalized_token_coverage_with_match_metadata(monkeypatch):
    lexical_description = [
        item
        for item in VECTOR_DESCRIPTION
        if item
        not in {
            ("embedding_provider",),
            ("embedding_model",),
            ("embedding_dimensions",),
            ("score",),
        }
    ] + [("matched_token_count",), ("query_token_count",), ("score",)]
    cursor = FakeCursor(
        [
            (
                "law-chunk-coverage",
                "road-traffic-act",
                "Road Traffic Act",
                "law",
                "article",
                "Article 5",
                None,
                None,
                "Drivers must obey traffic signals.",
                "traffic signal compliance",
                "https://example.test/law/5",
                date(2025, 1, 1),
                None,
                ["signal"],
                2,
                3,
                2 / 3,
            )
        ],
        description=lexical_description,
    )
    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "0")
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(cursor))

    result = service.search_legal_rag(
        "traffic signal evidence",
        top_k=1,
        temporal_basis={"mode": "as_of", "effective_at": "2026-02-01"},
        scope={"allowed_source_types": ["law"]},
    )

    assert result["status"] == "ready"
    assert result["score_kind"] == "token_coverage"
    assert result["query_token_count"] == 3
    assert result["results"][0]["matched_token_count"] == 2
    assert result["results"][0]["query_token_count"] == 3
    assert result["results"][0]["score"] == round(2 / 3, 6)
    assert "/ 3.0" in cursor.sql
    assert ["law"] in cursor.params
    assert cursor.params.count(date(2026, 2, 1)) == 2


def test_django_legal_fallback_filters_family_and_effective_date(monkeypatch):
    filter_calls = []

    class RecordingQuerySet:
        def filter(self, *args, **kwargs):
            filter_calls.append((args, kwargs))
            return self

        def select_related(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def __getitem__(self, _key):
            return self

        def __iter__(self):
            return iter(())

    queryset = RecordingQuerySet()

    class RecordingManager:
        def filter(self, *args, **kwargs):
            filter_calls.append((args, kwargs))
            return queryset

    fake_rag_chunk = SimpleNamespace(
        _meta=SimpleNamespace(db_table="rag_chunks"),
        objects=RecordingManager(),
    )
    monkeypatch.setitem(sys.modules, "chatbot.models", SimpleNamespace(RagChunk=fake_rag_chunk))
    monkeypatch.setattr(
        service,
        "_django_connection",
        lambda: SimpleNamespace(introspection=FakeIntrospection(["rag_chunks"])),
    )

    result = service._search_django_rag_tables(
        "traffic signal",
        top_k=2,
        source_type="law",
        allowed_source_types=("law", "enforcement_rule"),
        effective_at=date(2026, 2, 1),
    )

    assert result["status"] == "empty"
    combined_kwargs = {key: value for _args, kwargs in filter_calls for key, value in kwargs.items()}
    assert combined_kwargs["source_type__in"] == ("law", "enforcement_rule")
    assert combined_kwargs["source_document__isnull"] is False
    assert combined_kwargs["source_document__source_type__in"] == ("law", "enforcement_rule")
    assert combined_kwargs["source_document__jurisdiction"] == "KR"
    assert combined_kwargs["source_document__effective_date__isnull"] is False
    assert combined_kwargs["source_document__effective_date__lte"] == date(2026, 2, 1)
    assert combined_kwargs["content__regex"] == r"\S"
    assert combined_kwargs["source_document__source_url__regex"] == r"\S"
    assert any("expire_date__isnull" in str(args) and "expire_date__gte" in str(args) for args, _ in filter_calls)


def test_invalid_legal_scope_fails_before_database_access(monkeypatch):
    monkeypatch.setattr(
        service,
        "_django_connection",
        lambda: (_ for _ in ()).throw(AssertionError("invalid scope must not access a database")),
    )

    result = service.search_legal_rag(
        "traffic signal",
        source_type="law",
        temporal_basis={"mode": "as_of", "effective_at": "not-a-date"},
        scope={"jurisdiction": "US", "allowed_source_types": ["statute"]},
    )

    assert result["status"] == "invalid_filter"
    assert result["results"] == []
    assert result["error_code"]


def test_law_agent_forwards_filters_and_uses_full_provision_text(monkeypatch):
    from ai.agents.law_ground_search import search as law_search

    calls = []
    full_text = "Full legal provision text " * 30

    def fake_search(query, **kwargs):
        calls.append((query, kwargs))
        return {
            "status": "ready",
            "backend": "postgres_lexical",
            "score_kind": "token_coverage",
            "query_token_count": 3,
            "results": [
                {
                    "source_reference": "law-1",
                    "source_type": "law",
                    "source_name": "Road Traffic Act",
                    "article": "Article 5",
                    "summary": full_text[:240],
                    "provision_text": full_text,
                    "source_url": "https://example.test/law/5",
                    "matched_token_count": 3,
                    "query_token_count": 3,
                    "score": 1.0,
                }
            ],
        }

    monkeypatch.setattr("app.services.legal_rag_service.search_legal_rag", fake_search)
    temporal_basis = {"mode": "as_of", "effective_at": "2026-02-01"}
    scope = {"jurisdiction": "KR", "allowed_source_types": ["law"]}

    provisions = law_search.search_law_provisions(
        query_text="traffic signal evidence",
        article_refs=[],
        temporal_basis=temporal_basis,
        scope=scope,
    )

    assert calls == [
        (
            "traffic signal evidence",
            {
                "top_k": 5,
                "source_type": "law",
                "temporal_basis": temporal_basis,
                "scope": scope,
            },
        )
    ]
    assert provisions[0]["provision_text"] == full_text
    assert provisions[0]["summary"] == full_text[:240]


def test_lexical_confidence_requires_more_than_one_matched_token():
    from ai.agents.law_ground_search.search import evaluate_confidence

    provision = {
        "score": 1.0,
        "matched_token_count": 1,
        "query_token_count": 1,
        "_retrieval": {"backend": "postgres_lexical", "score_kind": "token_coverage"},
    }

    result = evaluate_confidence([provision])

    assert result["is_confident"] is False
    assert result["reason_code"] == "insufficient_lexical_term_support"


def test_lexical_confidence_accepts_multi_token_coverage():
    from ai.agents.law_ground_search.search import evaluate_confidence

    provision = {
        "score": 2 / 3,
        "matched_token_count": 2,
        "query_token_count": 3,
        "_retrieval": {"backend": "postgres_lexical", "score_kind": "token_coverage"},
    }

    result = evaluate_confidence([provision])

    assert result["is_confident"] is True
    assert result["reason_code"] == "lexical_token_coverage_sufficient"


def test_temporal_basis_rejects_compact_iso_date():
    effective_at, error = service._resolve_effective_at(
        {"mode": "as_of", "effective_at": "20260715"}
    )

    assert effective_at is None
    assert error == "invalid_effective_at"


def test_lexical_tokens_do_not_treat_underscore_as_search_wildcard():
    assert service._tokens("__ ___") == []
    assert service._tokens("traffic_signal") == ["traffic", "signal"]


def test_vector_query_embedding_space_must_match_configured_seed(monkeypatch):
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "sentence-transformers")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")

    with pytest.raises(RuntimeError, match="embedding_space_mismatch"):
        service._validate_query_embedding_space(
            {"provider": "openai", "model": "text-embedding-3-large", "dimensions": 1024}
        )


def test_embedding_space_mismatch_stops_before_query_embedding_call(monkeypatch):
    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "sentence-transformers")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "query-model")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "sentence-transformers")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "seed-model")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setattr(
        service,
        "_build_query_embedding",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("embedding call must not run before configuration preflight")
        ),
    )
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(FakeCursor([])))

    response = service._search_pgvector(
        "traffic signal",
        top_k=1,
        source_type="law",
        allowed_source_types=("law",),
        effective_at=date(2026, 1, 1),
    )

    assert response["status"] == "unavailable"
    assert response["error_code"] == "embedding_space_mismatch"


def test_empty_seed_space_stops_before_query_embedding_call(monkeypatch):
    class EmptySeedCursor(FakeCursor):
        def fetchone(self):
            return None

    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "sentence-transformers")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "sentence-transformers")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setattr(
        service,
        "_build_query_embedding",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("embedding call must not run for an empty seed space")
        ),
    )
    empty_seed_cursor = EmptySeedCursor([])
    monkeypatch.setattr(
        service,
        "_django_connection",
        lambda: FakeConnection(empty_seed_cursor),
    )

    response = service._search_pgvector(
        "traffic signal",
        top_k=1,
        source_type="law",
        allowed_source_types=("law",),
        effective_at=date(2026, 1, 1),
    )

    assert response["status"] == "unavailable"
    assert response["error_code"] == "no_eligible_seed_embeddings"
    assert "btrim(c.source_url) <> ''" in empty_seed_cursor.sql
    assert "btrim(c.provision_text) <> ''" in empty_seed_cursor.sql
    assert "e.embedding_vector IS NOT NULL" in empty_seed_cursor.sql


def test_current_legal_date_uses_asia_seoul_boundary():
    utc_instant = datetime(2026, 1, 1, 15, 30, tzinfo=timezone.utc)

    assert service.current_legal_date(utc_instant) == date(2026, 1, 2)


def test_sentence_transformer_model_is_cached_per_process(monkeypatch):
    created = []

    class FakeVector:
        def tolist(self):
            return [1.0, 0.0]

    class FakeModel:
        def __init__(self, model_id, device):
            created.append((model_id, device))

        def encode(self, *_args, **_kwargs):
            return [FakeVector()]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeModel),
    )
    service._sentence_transformer_model.cache_clear()

    service._sentence_transformer_embedding("first", model_id="model-a")
    service._sentence_transformer_embedding("second", model_id="model-a")

    assert created == [("model-a", "cpu")]
    service._sentence_transformer_model.cache_clear()


def test_graph_expansion_is_disabled_without_filtered_core_results(monkeypatch):
    from ai.agents.law_ground_search import search as law_search

    monkeypatch.setattr(law_search, "_search_fallback_legal_rag", lambda **_kwargs: [])

    class UnexpectedSession:
        def run(self, *_args, **_kwargs):
            raise AssertionError("article references must not create evidence without a filtered core result")

    result = law_search.search_law_provisions(
        query_text="Article 5",
        article_refs=["Article 5"],
        temporal_basis={"mode": "as_of", "effective_at": "2020-01-01"},
        scope={"allowed_source_types": ["law"]},
        neo4j_session=UnexpectedSession(),
    )

    assert result == []


def test_graph_expansion_rechecks_source_family_and_effective_window(monkeypatch):
    from ai.agents.law_ground_search import search as law_search

    core = {
        "chunk_id": "core-law-1",
        "source_id": "road-traffic-act",
        "source_type": "law",
        "provision_text": "Core provision",
        "source_url": "https://example.test/core",
        "score": 0.8,
    }
    monkeypatch.setattr(
        law_search,
        "_search_fallback_legal_rag",
        lambda **_kwargs: [dict(core)],
    )
    future_node = {
        "chunk_id": "future-decree-5",
        "source_id": "other-decree",
        "source_ref": "future-decree-5",
        "source_name": "Future decree",
        "source_type": "enforcement_decree",
        "is_searchable": True,
        "article_no": "Article 5",
        "provision_text": "Future provision",
        "source_url": "https://example.test/future",
        "enforce_date": "2030-01-01",
        "expire_date": None,
    }

    class RecordingSession:
        def __init__(self):
            self.calls = []

        def run(self, query, **params):
            self.calls.append((query, params))
            if "MATCH (c1:LawChunk" in query:
                return [{"cid": "core-law-1", "relation_type": "RELATED_TO", "c2": future_node}]
            return [{"c": future_node}]

    session = RecordingSession()
    result = law_search.search_law_provisions(
        query_text="Article 5",
        article_refs=["Article 5"],
        temporal_basis={"mode": "as_of", "effective_at": "2020-01-01"},
        scope={"allowed_source_types": ["law"]},
        neo4j_session=session,
    )

    assert result == [core]
    assert len(session.calls) == 2
    assert all("is_searchable = true" in call[0] for call in session.calls)
    assert all(call[1]["allowed_source_types"] == ["law"] for call in session.calls)
    assert all(call[1]["effective_at"] == date(2020, 1, 1) for call in session.calls)
    assert session.calls[1][1]["core_source_ids"] == ["road-traffic-act"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_searchable": False},
        {"expire_date": "not-a-date"},
        {"chunk_id": ""},
        {"source_id": ""},
        {"provision_text": ""},
        {"source_url": ""},
    ],
)
def test_graph_expansion_rejects_unsearchable_or_malformed_expiry(overrides):
    from ai.agents.law_ground_search import search as law_search

    node = {
        "chunk_id": "law-1",
        "source_id": "road-traffic-act",
        "provision_text": "Drivers must obey traffic signals.",
        "source_url": "https://example.test/law/1",
        "source_type": "law",
        "is_searchable": True,
        "enforce_date": "2020-01-01",
        "expire_date": None,
        **overrides,
    }

    assert not law_search._graph_node_is_allowed(
        node,
        allowed_source_types=("law",),
        effective_at=date(2026, 1, 1),
    )
