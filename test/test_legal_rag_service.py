from datetime import date

from app.services import legal_rag_service as service


class FakeIntrospection:
    def __init__(self, table_names):
        self._table_names = table_names

    def table_names(self):
        return self._table_names


class FakeCursor:
    description = [
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
        ("score",),
    ]

    def __init__(self, rows):
        self.rows = rows
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
                0.91,
            )
        ]
    )
    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_DIMENSIONS", "32")
    monkeypatch.setattr(service, "_django_connection", lambda: FakeConnection(cursor))

    result = service.search_legal_rag("school zone emergency stopping", top_k=2)

    assert result["status"] == "ready"
    assert result["backend"] == "postgres_pgvector"
    assert result["embedding"]["provider"] == "hash"
    assert result["embedding"]["dimensions"] == 32
    assert result["sql_tables"] == ["law_chunks", "law_embeddings"]
    assert result["results"][0]["source_reference"] == "law_chunk_001"
    assert result["results"][0]["score"] == 0.91
    assert result["results"][0]["effective_date"] == "2026-01-01"
    assert cursor.params[-1] == 2
    assert "law_embeddings" in cursor.sql


def test_legal_rag_falls_back_when_pgvector_is_unavailable(monkeypatch):
    class MissingTableConnection:
        vendor = "postgresql"
        introspection = FakeIntrospection([])

    monkeypatch.setenv("LEGAL_RAG_VECTOR_ENABLED", "1")
    monkeypatch.setenv("LEGAL_RAG_QUERY_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setattr(service, "_django_connection", lambda: MissingTableConnection())

    def fake_lexical(query, *, top_k, source_type):
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
        "django_rag_tables",
    ]
