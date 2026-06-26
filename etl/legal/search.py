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
) -> list[dict]:
    if top_k <= 0:
        return []

    # 1. Load chunks
    chunks = {row["chunk_id"]: row for row in read_jsonl(chunks_path)}

    # 2. Read embedding metadata without materializing all vectors.
    embedding_metadata = read_first_embedding_metadata(Path(embeddings_path))

    # 3. Generate query vector
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

    # 4. Compute cosine similarity and keep only top_k results in memory.
    top_results = []
    sequence = 0
    for emb in read_jsonl_iter(embeddings_path):
        chunk_id = emb["chunk_id"]
        chunk = chunks.get(chunk_id)
        if not chunk:
            continue
        vector = emb["embedding_vector"]
        if not vector or len(vector) != len(query_vector):
            continue
        # Dot product
        score = sum(q * v for q, v in zip(query_vector, vector))
        result = {**chunk, "score": round(score, 6)}
        heap_item = (score, sequence, result)
        sequence += 1
        if len(top_results) < top_k:
            heappush(top_results, heap_item)
        elif score > top_results[0][0]:
            heappop(top_results)
            heappush(top_results, heap_item)

    # 5. Sort and return top_k
    return [item[2] for item in sorted(top_results, key=lambda row: row[0], reverse=True)]


def read_first_embedding_metadata(embeddings_path: Path) -> dict:
    for row in read_jsonl_iter(embeddings_path):
        return row
    raise ValueError(f"No embeddings found in {embeddings_path}")


def infer_embedding_model(embedding_metadata: dict) -> str:
    model = embedding_metadata.get("embedding_model")
    if model:
        return model
    raise ValueError("model_id is required when embeddings do not include embedding_model")


def infer_embedding_dimensions(embedding_metadata: dict) -> int:
    dimensions = embedding_metadata.get("embedding_dimensions")
    if dimensions:
        return int(dimensions)
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
