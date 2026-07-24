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
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params or []
        self.executions.append((sql, self.params))

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
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_DATASET_VERSION", "sha256:verified-dataset")
    monkeypatch.setenv("LEGAL_DATASET_VERIFIED_AT", "2026-07-23T10:00:00+00:00")
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(cursor))

    result = service.search_legal_rag("school zone emergency stopping", top_k=2)

    assert result["error_code"] == "", result["error_code"]
    assert result["status"] == "ready", result
    assert result["backend"] == "postgres_pgvector"
    assert result["embedding"]["provider"] == "hash"
    assert result["embedding"]["dimensions"] == 1024
    assert result["sql_tables"] == ["law_chunks", "law_embeddings"]
    assert result["results"][0]["source_reference"] == "law_chunk_001"
    assert result["results"][0]["score"] == 0.91
    assert result["results"][0]["effective_date"] == "2026-01-01"
    assert result["effective_at"] == service.current_legal_date().isoformat()
    assert datetime.fromisoformat(result["retrieved_at"]).tzinfo is not None
    assert result["data_provenance"] == {
        "contract_version": "legal_dataset_provenance.v1",
        "dataset_version": "sha256:verified-dataset",
        "verified_at": "2026-07-23T10:00:00+00:00",
        "effective_at": result["effective_at"],
        "retrieved_at": result["retrieved_at"],
    }
    assert cursor.params[-1] == 2
    assert "law_embeddings" in cursor.sql
    assert "btrim(c.source_url) <> ''" in cursor.sql
    assert "btrim(c.provision_text) <> ''" in cursor.sql
    assert "e.embedding_vector IS NOT NULL" in cursor.sql
    assert set(result["latency_breakdown_ms"]) == {
        "preflight_ms",
        "embedding_ms",
        "vector_query_ms",
        "result_mapping_ms",
    }
    assert all(
        isinstance(value, int) and value >= 0
        for value in result["latency_breakdown_ms"].values()
    )


def test_legal_rag_reports_pgvector_unavailable_without_lexical_fallback(monkeypatch):
    class MissingTableConnection:
        vendor = "postgresql"
        introspection = FakeIntrospection([])

    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_MODEL", "hashing-vectorizer")
    monkeypatch.setenv("LEGAL_RAG_SEED_EMBEDDING_DIMENSIONS", "1024")
    monkeypatch.setattr(service, "_django_connection", lambda: MissingTableConnection())

    def unexpected_fallback(*_args, **_kwargs):
        raise AssertionError("legal RAG must not call a lexical or Django fallback")

    monkeypatch.setattr(
        service,
        "_search_law_chunks_lexical",
        unexpected_fallback,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_search_django_rag_tables",
        unexpected_fallback,
        raising=False,
    )

    result = service.search_legal_rag("fallback query", top_k=1)

    assert result["backend"] == "postgres_pgvector"
    assert result["status"] == "unavailable"
    assert result["error_code"] == "missing_tables:law_chunks,law_embeddings"
    assert "fallback_from" not in result
    assert "attempted_backends" not in result


def test_legal_rag_reports_vector_disabled_when_runtime_is_not_enabled(monkeypatch):
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

    result = service.search_legal_rag("신호 지시 준수", top_k=2)

    assert result["status"] == "disabled"
    assert result["backend"] == "postgres_pgvector"
    assert result["error_code"] == "vector_disabled"
    assert result["results"] == []
    assert cursor.sql == ""


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


def test_pgvector_sets_local_hnsw_options_before_vector_select(monkeypatch):
    cursor = FakeCursor([])
    connection = FakeConnection(cursor)
    connection.alias = "legal-rag"
    atomic_calls = []

    class FakeAtomic:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    def fake_atomic(*, using):
        atomic_calls.append(using)
        return FakeAtomic()

    monkeypatch.setattr(service.transaction, "atomic", fake_atomic)

    service._query_pgvector_rows(
        connection,
        query_vector=[1.0] + [0.0] * 1023,
        top_k=5,
        source_type="law",
        allowed_source_types=("law",),
        effective_at=date(2026, 7, 21),
        embedding_space={
            "provider": "hash",
            "model": "hashing-vectorizer",
            "dimensions": 1024,
        },
    )

    sql_statements = [sql for sql, _params in cursor.executions]

    assert sql_statements[:2] == [
        "SET LOCAL hnsw.ef_search = 400",
        "SET LOCAL hnsw.iterative_scan = 'strict_order'",
    ]
    assert "ORDER BY e.embedding_vector <=> %s::vector" in sql_statements[2]
    assert "c.source_type = ANY(%s)" in sql_statements[2]
    assert "c.enforce_date <= %s" in sql_statements[2]
    assert "btrim(c.source_url) <> ''" in sql_statements[2]
    assert atomic_calls == ["legal-rag"]


def test_vector_disabled_does_not_emit_token_coverage_metadata(monkeypatch):
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

    assert result["status"] == "disabled"
    assert result["backend"] == "postgres_pgvector"
    assert result["error_code"] == "vector_disabled"
    assert "score_kind" not in result
    assert result["results"] == []
    assert cursor.sql == ""


def test_review_case_source_type_is_rejected_before_database_access(monkeypatch):
    monkeypatch.setattr(
        service,
        "_django_connection",
        lambda: (_ for _ in ()).throw(AssertionError("unsupported source must not query a database")),
    )

    result = service.search_legal_rag("traffic signal", source_type="review_case")

    assert result["status"] == "invalid_filter"
    assert result["backend"] == "postgres_pgvector"
    assert result["error_code"] == "unsupported_source_type"


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
            "backend": "postgres_pgvector",
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
    assert provisions[0]["match_reason"] == "pgvector_similarity"


def test_vector_confidence_rejects_low_similarity_score():
    from ai.agents.law_ground_search.search import evaluate_confidence

    provision = {
        "score": 0.39,
        "_retrieval": {"backend": "postgres_pgvector"},
    }

    result = evaluate_confidence([provision])

    assert result["is_confident"] is False
    assert result["reason_code"] == "low_vector_score"


def test_vector_confidence_accepts_similarity_above_threshold():
    from ai.agents.law_ground_search.search import evaluate_confidence

    provision = {
        "score": 2 / 3,
        "_retrieval": {"backend": "postgres_pgvector"},
    }

    result = evaluate_confidence([provision])

    assert result["is_confident"] is True
    assert result["reason_code"] == "vector_score_sufficient"


def test_temporal_basis_rejects_compact_iso_date():
    effective_at, error = service._resolve_effective_at(
        {"mode": "as_of", "effective_at": "20260715"}
    )

    assert effective_at is None
    assert error == "invalid_effective_at"


def test_hash_embedding_tokens_do_not_treat_underscore_as_a_token():
    assert service._hash_tokens("__ ___") == []
    assert service._hash_tokens("traffic_signal") == ["traffic", "signal"]


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


def test_openai_embedding_client_is_reused_without_exposing_the_key(monkeypatch):
    created = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            assert kwargs == {
                "model": "text-embedding-3-large",
                "input": "public law query",
                "encoding_format": "float",
                "dimensions": 1024,
            }
            return SimpleNamespace(data=[SimpleNamespace(embedding=[3.0, 4.0])])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.embeddings = FakeEmbeddings()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("LEGAL_RAG_OPENAI_API_KEY", "test-key-not-for-output")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_TIMEOUT_SECONDS", "12")
    service._openai_embedding_client.cache_clear()

    first = service._openai_embedding(
        "public law query",
        model_id="text-embedding-3-large",
        dimensions=1024,
    )
    second = service._openai_embedding(
        "public law query",
        model_id="text-embedding-3-large",
        dimensions=1024,
    )

    assert first == second == [0.6, 0.8]
    assert len(created) == 1
    assert created[0]["base_url"] == "https://api.openai.com/v1"
    assert "test-key-not-for-output" not in repr(first)
    service._openai_embedding_client.cache_clear()


def test_graph_expansion_is_disabled_without_filtered_core_results(monkeypatch):
    from ai.agents.law_ground_search import search as law_search

    monkeypatch.setattr(law_search, "_search_pgvector_legal_rag", lambda **_kwargs: [])

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
        "_search_pgvector_legal_rag",
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
