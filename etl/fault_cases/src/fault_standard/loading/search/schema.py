"""DDL for PostgreSQL search tables built from fault-standard core data."""

from __future__ import annotations

SEARCH_SCHEMA = "search"
EMBEDDING_DIMENSION = 3072


def table_ref(table_name: str) -> str:
    """Return a schema-qualified search table name."""
    return f"{SEARCH_SCHEMA}.{table_name}"


def create_search_schema(conn) -> None:
    """Create search schema, vector extension, document tables, and indexes."""
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SEARCH_SCHEMA};")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("search_loads")} (
                search_load_id BIGSERIAL PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                source_core_load_id BIGINT,
                load_mode TEXT NOT NULL,
                document_strategy TEXT NOT NULL,
                embedding_model TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("rule_search_documents")} (
                document_id TEXT PRIMARY KEY,
                search_load_id BIGINT REFERENCES {table_ref("search_loads")}(search_load_id) ON DELETE SET NULL,
                source_batch_id BIGINT NOT NULL,
                rulebook_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                document_type TEXT NOT NULL,
                document_scope TEXT,
                title TEXT,
                search_text TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                embedding VECTOR({EMBEDDING_DIMENSION}),
                embedding_model TEXT,
                embedding_created_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                search_text_tsv TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('simple', coalesce(search_text, ''))
                ) STORED
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("search_result_logs")} (
                search_log_id BIGSERIAL PRIMARY KEY,
                query_text TEXT NOT NULL,
                document_id TEXT,
                rule_id TEXT,
                similarity_score NUMERIC,
                rank INTEGER,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_search_rule_documents_rule_id
            ON {table_ref("rule_search_documents")} (rule_id);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_search_rule_documents_rulebook_id
            ON {table_ref("rule_search_documents")} (rulebook_id);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_search_rule_documents_source_batch_id
            ON {table_ref("rule_search_documents")} (source_batch_id);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_search_rule_documents_document_type
            ON {table_ref("rule_search_documents")} (document_type);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_search_rule_documents_tsv
            ON {table_ref("rule_search_documents")} USING GIN (search_text_tsv);
            """
        )

    conn.commit()

