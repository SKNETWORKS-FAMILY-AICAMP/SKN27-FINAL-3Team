"""Load legal RAG chunks and embeddings directly into PostgreSQL/pgvector database."""

from __future__ import annotations

import json
import os
import sys
import argparse
from pathlib import Path
from etl.common.utils import load_env_file, read_jsonl_iter as read_jsonl

DEFAULT_CHUNKS_PATH = Path("output/law_ingestion/chunks/law_chunks.jsonl")
DEFAULT_EMBEDDINGS_PATH = Path("output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl")
DEFAULT_BATCH_SIZE = 500


def load_to_postgres(
    chunks_path: str | Path = DEFAULT_CHUNKS_PATH,
    embeddings_path: str | Path = DEFAULT_EMBEDDINGS_PATH,
    env_file: str = ".env",
    batch_size: int = DEFAULT_BATCH_SIZE,
    replace: bool = True,
) -> int:
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError as exc:
        print("psycopg2-binary is required. Install dependencies from requirements.txt.", file=sys.stderr)
        return 1

    load_env_file(Path(env_file))

    # Connection params
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "change-me")
    db_name = os.getenv("POSTGRES_DB", "law_db")

    chunks_file = Path(chunks_path)
    embeddings_file = Path(embeddings_path)

    if not chunks_file.exists():
        print(f"Chunks file not found: {chunks_file}", file=sys.stderr)
        return 1
    if not embeddings_file.exists():
        print(f"Embeddings file not found: {embeddings_file}", file=sys.stderr)
        return 1

    # Load chunks
    chunks_list = []
    chunk_ids = set()
    for row in read_jsonl(chunks_file):
        chunk_id = row["chunk_id"]
        chunk_ids.add(chunk_id)
        chunks_list.append((
            chunk_id,
            row["source_id"],
            row["source_name"],
            row["source_type"],
            row["chunk_type"],
            row.get("article_no"),
            row.get("appendix_no"),
            row.get("form_no"),
            row["provision_text"],
            row["normalized_text"],
            row.get("source_url"),
            row.get("enforce_date") or None,
            row.get("expire_date") or None,
            row.get("is_searchable", True),
            row.get("domain_tags") or []
        ))

    vector_dim = infer_vector_dimensions(embeddings_file)

    print(f"Connecting to PostgreSQL ({host}:{port}/{db_name})...")
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=db_name
        )
        conn.autocommit = False
    except Exception as exc:
        print(f"Database connection failed: {exc}", file=sys.stderr)
        return 1

    embedding_count = 0
    try:
        with conn.cursor() as cur:
            # 1. Enable pgvector and create schema
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS law_chunks (
                    chunk_id VARCHAR(255) PRIMARY KEY,
                    source_id VARCHAR(100) NOT NULL,
                    source_name VARCHAR(255) NOT NULL,
                    source_type VARCHAR(50) NOT NULL,
                    chunk_type VARCHAR(50) NOT NULL,
                    article_no VARCHAR(50),
                    appendix_no VARCHAR(50),
                    form_no VARCHAR(50),
                    provision_text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    source_url TEXT,
                    enforce_date DATE,
                    expire_date DATE,
                    is_searchable BOOLEAN DEFAULT TRUE,
                    domain_tags TEXT[] DEFAULT '{}',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cur.execute("DROP TABLE IF EXISTS law_embeddings CASCADE;")
            cur.execute(f"""
                CREATE TABLE law_embeddings (
                    chunk_id VARCHAR(255) REFERENCES law_chunks(chunk_id) ON DELETE CASCADE,
                    embedding_vector vector({vector_dim}),
                    embedding_provider VARCHAR(50) NOT NULL,
                    PRIMARY KEY (chunk_id)
                );
            """)

            # 2. Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_law_chunks_domain_tags ON law_chunks USING GIN (domain_tags);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_law_chunks_temporal ON law_chunks (enforce_date, expire_date);")
            cur.execute("CREATE INDEX IF NOT EXISTS law_embeddings_hnsw_idx ON law_embeddings USING hnsw (embedding_vector vector_cosine_ops);")

            if replace:
                print("Clearing existing law_chunks/law_embeddings before baseline load...")
                cur.execute("TRUNCATE TABLE law_chunks CASCADE;")

            print(f"Upserting {len(chunks_list)} chunks to law_chunks...")
            chunk_upsert_query = """
                INSERT INTO law_chunks (
                    chunk_id, source_id, source_name, source_type, chunk_type,
                    article_no, appendix_no, form_no, provision_text, normalized_text,
                    source_url, enforce_date, expire_date, is_searchable, domain_tags
                ) VALUES %s
                ON CONFLICT (chunk_id) DO UPDATE SET
                    source_id = EXCLUDED.source_id,
                    source_name = EXCLUDED.source_name,
                    source_type = EXCLUDED.source_type,
                    chunk_type = EXCLUDED.chunk_type,
                    article_no = EXCLUDED.article_no,
                    appendix_no = EXCLUDED.appendix_no,
                    form_no = EXCLUDED.form_no,
                    provision_text = EXCLUDED.provision_text,
                    normalized_text = EXCLUDED.normalized_text,
                    source_url = EXCLUDED.source_url,
                    enforce_date = EXCLUDED.enforce_date,
                    expire_date = EXCLUDED.expire_date,
                    is_searchable = EXCLUDED.is_searchable,
                    domain_tags = EXCLUDED.domain_tags
            """
            execute_values(cur, chunk_upsert_query, chunks_list, page_size=batch_size)

            print("Upserting embeddings to law_embeddings...")
            emb_upsert_query = """
                INSERT INTO law_embeddings (
                    chunk_id, embedding_vector, embedding_provider
                ) VALUES %s
                ON CONFLICT (chunk_id) DO UPDATE SET
                    embedding_vector = EXCLUDED.embedding_vector,
                    embedding_provider = EXCLUDED.embedding_provider
            """
            batch = []
            for row in read_jsonl(embeddings_file):
                chunk_id = row["chunk_id"]
                if chunk_id not in chunk_ids:
                    continue
                vector = row["embedding_vector"]
                if not vector:
                    continue
                provider = row.get("embedding_provider") or row.get("embedding_version") or "sentence-transformers"
                vector_str = f"[{','.join(map(str, vector))}]"
                batch.append((chunk_id, vector_str, provider))
                if len(batch) >= batch_size:
                    execute_values(cur, emb_upsert_query, batch, page_size=batch_size)
                    embedding_count += len(batch)
                    print(f"  embedded rows loaded: {embedding_count}", flush=True)
                    batch = []
            if batch:
                execute_values(cur, emb_upsert_query, batch, page_size=batch_size)
                embedding_count += len(batch)

        conn.commit()
        print(f"PostgreSQL/pgvector upload completed successfully! Embeddings: {embedding_count}")
        return 0

    except Exception as exc:
        conn.rollback()
        print(f"Failed to load data to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def infer_vector_dimensions(embeddings_file: Path) -> int:
    for row in read_jsonl(embeddings_file):
        vector = row["embedding_vector"]
        if not vector:
            continue
        return len(vector)
    raise ValueError(f"No embedding vectors found in {embeddings_file}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-path", default=str(DEFAULT_CHUNKS_PATH))
    parser.add_argument("--embeddings-path", default=str(DEFAULT_EMBEDDINGS_PATH))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--no-replace", action="store_true", help="Upsert without clearing existing law_chunks first.")
    args = parser.parse_args(argv)
    return load_to_postgres(
        chunks_path=args.chunks_path,
        embeddings_path=args.embeddings_path,
        env_file=args.env_file,
        batch_size=args.batch_size,
        replace=not args.no_replace,
    )


if __name__ == "__main__":
    sys.exit(main())
