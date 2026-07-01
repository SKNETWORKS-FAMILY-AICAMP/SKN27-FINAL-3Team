"""Export ingested JSONL chunks and embeddings to PostgreSQL/pgvector SQL seed file."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def escape_sql_string(val: str | None) -> str:
    if val is None:
        return "NULL"
    # Escape single quotes for SQL insertion
    escaped = val.replace("'", "''")
    return f"'{escaped}'"


def export_to_sql(
    chunks_path: str = "output/law_ingestion/chunks/law_chunks.jsonl",
    embeddings_path: str = "output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl",
    output_sql_path: str = "output/law_ingestion/publish/law_db_seed.sql",
) -> int:
    chunks_file = Path(chunks_path)
    embeddings_file = Path(embeddings_path)
    out_file = Path(output_sql_path)

    if not chunks_file.exists():
        print(f"Chunks file not found: {chunks_file}", file=sys.stderr)
        return 1
    if not embeddings_file.exists():
        print(f"Embeddings file not found: {embeddings_file}", file=sys.stderr)
        return 1

    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Load chunks
    chunks = {}
    for line in chunks_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            chunks[row["chunk_id"]] = row

    vector_dim = infer_vector_dimensions(embeddings_file)

    sql_statements = [
        "-- Auto-generated PostgreSQL/pgvector database seed file",
        "CREATE EXTENSION IF NOT EXISTS vector;",
        "",
        "CREATE TABLE IF NOT EXISTS law_chunks (",
        "    chunk_id VARCHAR(255) PRIMARY KEY,",
        "    source_id VARCHAR(100) NOT NULL,",
        "    source_name VARCHAR(255) NOT NULL,",
        "    source_type VARCHAR(50) NOT NULL,",
        "    chunk_type VARCHAR(50) NOT NULL,",
        "    article_no VARCHAR(50),",
        "    appendix_no VARCHAR(50),",
        "    form_no VARCHAR(50),",
        "    provision_text TEXT NOT NULL,",
        "    normalized_text TEXT NOT NULL,",
        "    source_url TEXT,",
        "    enforce_date DATE,",
        "    expire_date DATE,",
        "    is_searchable BOOLEAN DEFAULT TRUE,",
        "    domain_tags TEXT[] DEFAULT '{}',",
        "    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP",
        ");",
        "",
        "CREATE INDEX IF NOT EXISTS idx_law_chunks_domain_tags ON law_chunks USING GIN (domain_tags);",
        "CREATE INDEX IF NOT EXISTS idx_law_chunks_temporal ON law_chunks (enforce_date, expire_date);",
        "",
        "DROP TABLE IF EXISTS law_embeddings CASCADE;",
        f"CREATE TABLE law_embeddings (",
        "    chunk_id VARCHAR(255) REFERENCES law_chunks(chunk_id) ON DELETE CASCADE,",
        f"    embedding_vector vector({vector_dim}),",
        "    embedding_provider VARCHAR(50) NOT NULL,",
        "    PRIMARY KEY (chunk_id)",
        ");",
        "",
        "CREATE INDEX IF NOT EXISTS law_embeddings_hnsw_idx ON law_embeddings USING hnsw (embedding_vector vector_cosine_ops);",
        "",
        "BEGIN;",
        "TRUNCATE TABLE law_embeddings CASCADE;",
        "TRUNCATE TABLE law_chunks CASCADE;",
        ""
    ]

    # Generate inserts for law_chunks
    for chunk_id, chunk in chunks.items():
        chunk_id_esc = escape_sql_string(chunk_id)
        source_id_esc = escape_sql_string(chunk["source_id"])
        source_name_esc = escape_sql_string(chunk["source_name"])
        source_type_esc = escape_sql_string(chunk["source_type"])
        chunk_type_esc = escape_sql_string(chunk["chunk_type"])
        article_no_esc = escape_sql_string(chunk.get("article_no"))
        appendix_no_esc = escape_sql_string(chunk.get("appendix_no"))
        form_no_esc = escape_sql_string(chunk.get("form_no"))
        provision_text_esc = escape_sql_string(chunk["provision_text"])
        normalized_text_esc = escape_sql_string(chunk["normalized_text"])
        source_url_esc = escape_sql_string(chunk.get("source_url"))
        
        # Enforce and expire date formatting
        enforce_date = chunk.get("enforce_date")
        enforce_date_val = f"'{enforce_date}'" if enforce_date else "NULL"
        expire_date = chunk.get("expire_date")
        expire_date_val = f"'{expire_date}'" if expire_date else "NULL"
        
        # Searchable and domain tags formatting
        is_searchable_val = "TRUE" if chunk.get("is_searchable", True) else "FALSE"
        tags = chunk.get("domain_tags") or []
        tags_val = "ARRAY[" + ",".join(escape_sql_string(t) for t in tags) + "]::TEXT[]" if tags else "ARRAY[]::TEXT[]"

        sql_statements.append(
            f"INSERT INTO law_chunks (chunk_id, source_id, source_name, source_type, chunk_type, article_no, appendix_no, form_no, provision_text, normalized_text, source_url, enforce_date, expire_date, is_searchable, domain_tags) VALUES ({chunk_id_esc}, {source_id_esc}, {source_name_esc}, {source_type_esc}, {chunk_type_esc}, {article_no_esc}, {appendix_no_esc}, {form_no_esc}, {provision_text_esc}, {normalized_text_esc}, {source_url_esc}, {enforce_date_val}, {expire_date_val}, {is_searchable_val}, {tags_val});"
        )

    sql_statements.append("")

    out_file.write_text("\n".join(sql_statements) + "\n", encoding="utf-8")

    embedding_count = 0
    with out_file.open("a", encoding="utf-8", newline="\n") as handle:
        for line in embeddings_file.open("r", encoding="utf-8-sig"):
            if not line.strip():
                continue
            emb = json.loads(line)
            chunk_id = emb["chunk_id"]
            if chunk_id not in chunks:
                continue
            vector = emb["embedding_vector"]
            if not vector:
                continue
            provider = emb.get("embedding_provider") or emb.get("embedding_version") or "sentence-transformers"
            vector_str = f"'[{','.join(map(str, vector))}]'"
            handle.write(
                f"INSERT INTO law_embeddings (chunk_id, embedding_vector, embedding_provider) VALUES ({escape_sql_string(chunk_id)}, {vector_str}, {escape_sql_string(provider)});\n"
            )
            embedding_count += 1
        handle.write("\nCOMMIT;\n")

    print(f"Exported SQL seed file to: {out_file} (Total chunks: {len(chunks)}, Embeddings: {embedding_count}, Dim: {vector_dim})")
    return 0


def infer_vector_dimensions(embeddings_file: Path) -> int:
    with embeddings_file.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            vector = json.loads(line).get("embedding_vector")
            if vector:
                return len(vector)
    raise ValueError(f"No embedding vectors found in {embeddings_file}")


if __name__ == "__main__":
    sys.exit(export_to_sql())
