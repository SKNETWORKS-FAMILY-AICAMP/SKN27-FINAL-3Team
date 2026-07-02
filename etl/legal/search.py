"""Semantic similarity search query interface for legal RAG agents."""

from __future__ import annotations

import os
from heapq import heappop, heappush
from pathlib import Path
from etl.common.utils import load_env_file, normalize_l2, read_jsonl, read_jsonl_iter




def search_laws(
    query: str,
    *,
    chunks_path: str = "output/law_ingestion/chunks/law_chunks.jsonl",
    embeddings_path: str = "output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl",
    provider: str = "sentence-transformers",
    model_id: str | None = None,
    device: str = "cpu",
    top_k: int = 5,
    temporal_basis: dict = None,
    scope: dict = None,
) -> list[dict]:
    if top_k <= 0:
        return []

    # PostgreSQL schema enforces vector(1024)
    embedding_metadata = {"embedding_provider": provider, "embedding_dimensions": 1024}

    # Generate query vector
    if provider == "sentence-transformers":
        query_vector = embed_query_with_sentence_transformers(
            query,
            model_id=model_id or infer_embedding_model(embedding_metadata),
            device=device,
        )
    elif provider == "openai":
        query_vector = embed_query_with_openai(
            query,
            model_id=model_id or infer_embedding_model(embedding_metadata),
            dimensions=infer_embedding_dimensions(embedding_metadata),
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    # Query PostgreSQL with pgvector
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import os

    db_host = os.environ.get("POSTGRES_HOST", "localhost")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_user = os.environ.get("POSTGRES_USER", "postgres")
    db_password = os.environ.get("POSTGRES_PASSWORD", "change-me")
    db_name = os.environ.get("POSTGRES_DB", "law_db")

    top_results = []
    conn = None
    cur = None
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_password,
            dbname=db_name
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        
        # Temporal basis handling
        temporal_basis = temporal_basis or {}
        mode = temporal_basis.get("mode", "latest")
        effective_at = temporal_basis.get("effective_at")
        
        if mode == "latest" and not effective_at:
            from datetime import date
            effective_at = date.today().isoformat()
        
        # pgvector uses <=> for cosine distance. Similarity = 1 - distance
        query_sql = """
            SELECT 
                c.chunk_id, c.source_name, c.source_type, c.article_no, c.appendix_no, 
                c.provision_text, c.source_url,
                1 - (e.embedding_vector <=> %s::vector) AS score
            FROM law_embeddings e
            JOIN law_chunks c ON e.chunk_id = c.chunk_id
            WHERE e.embedding_provider = %s
        """
        vector_str = "[" + ",".join(map(str, query_vector)) + "]"
        params = [vector_str, provider]
        
        if effective_at:
            query_sql += " AND (c.enforce_date <= %s OR c.enforce_date IS NULL)"
            query_sql += " AND (c.expire_date >= %s OR c.expire_date IS NULL)"
            params.extend([effective_at, effective_at])
            
        scope = scope or {}
        allowed_sources = scope.get("allowed_source_types")
        if allowed_sources:
            query_sql += " AND c.source_type = ANY(%s)"
            params.append(allowed_sources)
            
        query_sql += " ORDER BY e.embedding_vector <=> %s::vector LIMIT %s;"
        params.extend([vector_str, top_k])
        
        cur.execute(query_sql, params)
        
        rows = cur.fetchall()
        for row in rows:
            res = dict(row)
            res["score"] = round(res["score"], 6)
            top_results.append(res)
            
    except Exception as e:
        print(f"[Error] PostgreSQL vector search failed: {e}")
        return []
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()

    return top_results


def read_first_embedding_metadata(embeddings_path: Path) -> dict:
    for row in read_jsonl_iter(embeddings_path):
        return row
    raise ValueError(f"No embeddings found in {embeddings_path}")


def infer_embedding_model(embedding_metadata: dict) -> str:
    model = embedding_metadata.get("embedding_model")
    if model:
        return model
    
    # Fallback if model is not in metadata
    provider = embedding_metadata.get("embedding_provider")
    if provider == "openai":
        return "text-embedding-3-large"  # or small, but we will pass dimensions anyway
        
    raise ValueError("model_id is required when embeddings do not include embedding_model")


def infer_embedding_dimensions(embedding_metadata: dict) -> int:
    dimensions = embedding_metadata.get("embedding_dimensions")
    if dimensions:
        return int(dimensions)
    
    # Fallback to checking the length of the actual vector
    vector = embedding_metadata.get("embedding_vector")
    if vector and isinstance(vector, list):
        return len(vector)
        
    raise ValueError("embedding_dimensions is required for OpenAI query embedding")


def embed_query_with_sentence_transformers(
    query: str,
    *,
    model_id: str,
    device: str = "cpu",
) -> list[float]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for this search provider."
        ) from exc

    prefix = "query: " if "e5" in model_id.lower() else ""
    model = SentenceTransformer(model_id, device=device)
    vector = model.encode(
        [prefix + query],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    return vector.astype(float).tolist()


def embed_query_with_openai(
    query: str,
    *,
    model_id: str,
    dimensions: int,
) -> list[float]:
    load_env_file(Path(".env"))
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required. Put it in .env or the environment.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the openai package from requirements.txt.") from exc

    response = OpenAI().embeddings.create(
        model=model_id,
        input=query,
        dimensions=dimensions,
        encoding_format="float",
    )
    return normalize_l2(response.data[0].embedding)





if __name__ == "__main__":
    # Quick self-test CLI
    import sys
    search_query = "신호위반 범칙금" if len(sys.argv) < 2 else sys.argv[1]
    print(f"Searching for: '{search_query}'...")
    try:
        results = search_laws(search_query, top_k=3)
        for index, item in enumerate(results, 1):
            ref = item.get("article_no") or item.get("appendix_no") or "본문"
            print(f"\n[{index}] {item['source_name']} {ref} (Score: {item['score']})")
            print(item["provision_text"][:200] + "...")
    except Exception as exc:
        print("Search failed:", exc)
