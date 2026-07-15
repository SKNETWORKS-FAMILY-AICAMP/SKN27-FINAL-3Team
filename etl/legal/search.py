"""Semantic similarity search query interface for legal RAG agents."""

from __future__ import annotations

import os
import re
from pathlib import Path
from etl.common.utils import load_env_file, normalize_l2, read_jsonl_iter

_ARTICLE_NO_PATTERN = re.compile(r"제(\d+)조(?:의(\d+))?")
_DEFAULT_SENTENCE_TRANSFORMER_MODEL = "intfloat/multilingual-e5-large"
_DEFAULT_OPENAI_MODEL = "text-embedding-3-large"


def parse_law_code(law_code: str) -> tuple[str, str] | None:
    """"도로교통법 제148조의2 제1항" 같은 law_code에서 (source_name, article_no)를 추출한다.

    law_code는 표준 인용 순서("제148조의2" — 조가 먼저)를 쓰지만, law_chunks.article_no는
    ingestion 단계(ingestion/parser.py `_article_no`)가 만드는 내부 저장 순서
    ("제148의2조" — 의가 먼저)를 쓴다. 조회 전에 순서를 저장 포맷에 맞춰 변환한다 —
    그렇지 않으면 가지번호(의N)가 있는 조문에서 엉뚱한 본조를 조회하게 된다.
    """
    match = _ARTICLE_NO_PATTERN.search(law_code)
    if not match:
        return None
    source_name = law_code[:match.start()].strip()
    if not source_name:
        return None
    number, branch = match.group(1), match.group(2)
    article_no = f"제{number}의{branch}조" if branch else f"제{number}조"
    return source_name, article_no


def _connect_law_db():
    import psycopg2

    try:
        connect_timeout = max(1, int(os.environ.get("LEGAL_DB_CONNECT_TIMEOUT_SECONDS", "3")))
    except ValueError:
        connect_timeout = 3

    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "change-me"),
        dbname=os.environ.get("POSTGRES_DB", "law_db"),
        connect_timeout=connect_timeout,
        application_name="skn27-legal-search",
    )


def law_code_exists(law_code: str) -> bool:
    """law_chunks에 law_code에 해당하는 조문이 존재하는지 단일 조회한다 (LDB_CHECK, DATA-003 §7).

    재시도 없음. law_code 파싱 실패·DB 연결 오류 등 어떤 이유로든 확인이 안 되면 False를
    반환한다 — 호출 측(law_code_check_node)은 이 값으로 판정을 막지 않고 disclaimer 문구만
    조건부로 바꾼다.
    """
    parsed = parse_law_code(law_code)
    if not parsed:
        return False
    source_name, article_no = parsed

    conn = None
    try:
        conn = _connect_law_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM law_chunks WHERE source_name = %s AND article_no = %s LIMIT 1;",
                (source_name, article_no),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        print(f"[Error] law_code_exists lookup failed: {exc}")
        return False
    finally:
        if conn is not None:
            conn.close()


def get_provision_text(source_name: str, article_no: str) -> str | None:
    """law_chunks에서 (source_name, article_no)에 해당하는 조문 원문을 조회한다.

    같은 조문이라도 개정 이력별로 여러 버전이 저장돼 있을 수 있어(enforce_date가 다른
    행), 가장 최근에 시행된 버전을 반환한다. 재시도 없음 — 조회 실패·미존재는 모두 None.
    호출 측(law_refs.py)은 None일 때 하드코딩된 폴백 원문으로 대체한다.
    """
    conn = None
    try:
        conn = _connect_law_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT provision_text FROM law_chunks
                WHERE source_name = %s AND article_no = %s
                ORDER BY enforce_date DESC NULLS LAST
                LIMIT 1;
                """,
                (source_name, article_no),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as exc:
        print(f"[Error] get_provision_text lookup failed: {exc}")
        return None
    finally:
        if conn is not None:
            conn.close()


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

    # PostgreSQL production schema enforces one explicit 1024-dimensional space.
    resolved_model_id = model_id or (
        _DEFAULT_OPENAI_MODEL if provider == "openai" else _DEFAULT_SENTENCE_TRANSFORMER_MODEL
    )
    embedding_metadata = {
        "embedding_provider": provider,
        "embedding_model": resolved_model_id,
        "embedding_dimensions": 1024,
    }

    # Generate query vector
    if provider == "sentence-transformers":
        query_vector = embed_query_with_sentence_transformers(
            query,
            model_id=resolved_model_id,
            device=device,
        )
    elif provider == "openai":
        query_vector = embed_query_with_openai(
            query,
            model_id=resolved_model_id,
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
              AND e.embedding_model = %s
              AND e.embedding_dimensions = %s
        """
        vector_str = "[" + ",".join(map(str, query_vector)) + "]"
        params = [
            vector_str,
            provider,
            resolved_model_id,
            infer_embedding_dimensions(embedding_metadata),
        ]
        
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
