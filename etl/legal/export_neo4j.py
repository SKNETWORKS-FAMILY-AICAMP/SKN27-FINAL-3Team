"""Load legal RAG artifacts and query-understanding hints into Neo4j."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from etl.common.utils import load_env_file, read_jsonl_iter as read_jsonl
import yaml

from neo4j import GraphDatabase


DEFAULT_OUTPUT_DIR = Path("output/law_ingestion")
DEFAULT_HINT_TERMS = Path("storage/rag/law_query_terms.yaml")
DEFAULT_BATCH_SIZE = 500
LAW_GRAPH_RELATION_TYPES = ("HAS_PENALTY", "HAS_APPENDIX", "HAS_EXCEPTION", "RELATED_TO")

SOURCE_FIELDS = [
    "source_id",
    "source_name",
    "source_type",
    "provider",
    "provider_source_id",
    "enabled",
    "priority",
]

VERSION_FIELDS = [
    "source_version_id",
    "source_id",
    "mst",
    "enforce_date",
    "expire_date",
    "promulgation_date",
    "promulgation_no",
    "law_serial_no",
    "raw_document_id",
    "version_status",
]

CHUNK_FIELDS = [
    "chunk_id",
    "source_ref",
    "source_id",
    "source_name",
    "source_type",
    "source_version_id",
    "mst",
    "chunk_type",
    "article_no",
    "article_title",
    "paragraph_no",
    "item_no",
    "appendix_no",
    "form_no",
    "structure_id",
    "segment_no",
    "provision_text",
    "normalized_text",
    "source_url",
    "enforce_date",
    "expire_date",
    "content_hash",
    "parse_status",
    "validation_status",
    "is_searchable",
    "domain_tags",
]

HINT_TARGET_LABELS = {
    "vehicle_type": "VehicleType",
    "violation_type": "ViolationType",
    "penalty_type": "PenaltyType",
}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_file(Path(args.env_file))

    uri = args.neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = args.neo4j_user or os.getenv("NEO4J_USER", "neo4j")
    password = args.neo4j_password or os.getenv("NEO4J_PASSWORD", "change-me")
    database = args.neo4j_database or os.getenv("NEO4J_DATABASE", "neo4j")

    output_dir = Path(args.output_dir)
    hint_terms_path = Path(args.hint_terms)

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            create_constraints(session)

            totals = {}
            if not args.skip_legal:
                totals.update(
                    import_legal_artifacts(
                        session,
                        output_dir,
                        args.batch_size,
                        import_similarity=args.import_similarity,
                    )
                )
            if not args.skip_hints:
                totals.update(import_hint_terms(session, hint_terms_path))

    print("Neo4j export completed:")
    for key, value in totals.items():
        print(f"- {key}: {value}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--hint-terms", default=str(DEFAULT_HINT_TERMS))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--neo4j-uri")
    parser.add_argument("--neo4j-user")
    parser.add_argument("--neo4j-password")
    parser.add_argument("--neo4j-database")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--skip-legal", action="store_true")
    parser.add_argument("--skip-hints", action="store_true")
    parser.add_argument(
        "--import-similarity",
        action="store_true",
        help="Compute LawChunk SIMILAR_TO relations from embeddings. Disabled by default for the 99,590-row baseline.",
    )
    return parser.parse_args(argv)





def create_constraints(session) -> None:
    constraints = [
        "CREATE CONSTRAINT legal_source_id IF NOT EXISTS FOR (n:LegalSource) REQUIRE n.source_id IS UNIQUE",
        "CREATE CONSTRAINT law_version_id IF NOT EXISTS FOR (n:LawVersion) REQUIRE n.source_version_id IS UNIQUE",
        "CREATE CONSTRAINT law_chunk_id IF NOT EXISTS FOR (n:LawChunk) REQUIRE n.chunk_id IS UNIQUE",
        "CREATE CONSTRAINT user_term_text IF NOT EXISTS FOR (n:UserTerm) REQUIRE n.text IS UNIQUE",
        "CREATE CONSTRAINT legal_term_text IF NOT EXISTS FOR (n:LegalTerm) REQUIRE n.text IS UNIQUE",
        "CREATE CONSTRAINT law_search_term_text IF NOT EXISTS FOR (n:LawSearchTerm) REQUIRE n.text IS UNIQUE",
        "CREATE CONSTRAINT vehicle_type_code IF NOT EXISTS FOR (n:VehicleType) REQUIRE n.code IS UNIQUE",
        "CREATE CONSTRAINT violation_type_code IF NOT EXISTS FOR (n:ViolationType) REQUIRE n.code IS UNIQUE",
        "CREATE CONSTRAINT penalty_type_code IF NOT EXISTS FOR (n:PenaltyType) REQUIRE n.code IS UNIQUE",
    ]
    for query in constraints:
        session.run(query).consume()


def import_legal_artifacts(session, output_dir: Path, batch_size: int, import_similarity: bool = False) -> dict[str, int]:
    sources_path = output_dir / "normalized" / "legal_sources.jsonl"
    versions_path = output_dir / "normalized" / "legal_source_versions.jsonl"
    chunks_path = output_dir / "chunks" / "law_chunks.jsonl"
    relations_path = output_dir / "relations" / "law_relations.jsonl"
    extra_relations_path = output_dir / "relations" / "law_extra_relations.jsonl"

    require_files([sources_path, versions_path, chunks_path, relations_path])

    sources = [to_props(row, SOURCE_FIELDS) for row in read_jsonl(sources_path)]
    versions = [to_props(row, VERSION_FIELDS) for row in read_jsonl(versions_path)]
    chunks = [to_props(row, CHUNK_FIELDS) for row in read_jsonl(chunks_path)]
    base_relations = list(read_jsonl(relations_path))
    extra_relations = list(read_jsonl(extra_relations_path)) if extra_relations_path.exists() else []
    relations = dedupe_relations([*base_relations, *extra_relations])

    run_batches(
        session,
        """
        UNWIND $rows AS row
        MERGE (source:LegalSource {source_id: row.source_id})
        SET source += row
        """,
        sources,
        batch_size,
    )

    run_batches(
        session,
        """
        UNWIND $rows AS row
        MATCH (source:LegalSource {source_id: row.source_id})
        MERGE (version:LawVersion {source_version_id: row.source_version_id})
        SET version += row
        MERGE (source)-[:HAS_VERSION]->(version)
        """,
        versions,
        batch_size,
    )

    run_batches(
        session,
        """
        UNWIND $rows AS row
        MATCH (version:LawVersion {source_version_id: row.source_version_id})
        MERGE (chunk:LawChunk {chunk_id: row.chunk_id})
        SET chunk += row
        MERGE (version)-[:HAS_CHUNK]->(chunk)
        """,
        chunks,
        batch_size,
    )

    relation_count = import_relations(session, relations, batch_size)
    similarity_count = 0
    if import_similarity:
        similarity_count = import_similarity_relations(session, output_dir, batch_size)

    return {
        "legal_sources": len(sources),
        "law_versions": len(versions),
        "law_chunks": len(chunks),
        "law_relations": relation_count,
        "law_extra_relations": len(extra_relations),
        "similarity_relations": similarity_count,
    }



def import_relations(session, relations: list[dict], batch_size: int) -> int:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for relation in relations:
        rel_type = safe_relation_type(relation.get("relation_type") or "RELATED_TO")
        grouped[rel_type].append(
            {
                "relation_id": relation.get("relation_id"),
                "from_id": relation.get("from_chunk_id"),
                "to_id": relation.get("to_chunk_id"),
                "confidence": relation.get("confidence"),
                "evidence_text": relation.get("evidence_text"),
                "created_at": relation.get("created_at"),
            }
        )

    total = 0
    for rel_type, rows in grouped.items():
        query = f"""
        UNWIND $rows AS row
        OPTIONAL MATCH (fromVersion:LawVersion {{source_version_id: row.from_id}})
        OPTIONAL MATCH (fromChunk:LawChunk {{chunk_id: row.from_id}})
        WITH row, coalesce(fromVersion, fromChunk) AS fromNode
        MATCH (toNode:LawChunk {{chunk_id: row.to_id}})
        WHERE fromNode IS NOT NULL
        MERGE (fromNode)-[rel:{rel_type}]->(toNode)
        SET rel.relation_id = row.relation_id,
            rel.confidence = row.confidence,
            rel.evidence_text = row.evidence_text,
            rel.created_at = row.created_at
        """
        run_batches(session, query, rows, batch_size)
        total += len(rows)
    return total


def dedupe_relations(relations: list[dict]) -> list[dict]:
    deduped: dict[tuple[str, str, str], dict] = {}
    for relation in relations:
        rel_type = safe_relation_type(relation.get("relation_type") or "RELATED_TO")
        from_id = relation.get("from_chunk_id")
        to_id = relation.get("to_chunk_id")
        if not from_id or not to_id:
            continue
        deduped[(rel_type, str(from_id), str(to_id))] = relation
    return list(deduped.values())


def import_hint_terms(session, hint_terms_path: Path) -> dict[str, int]:
    if not hint_terms_path.exists():
        raise FileNotFoundError(f"Hint terms file not found: {hint_terms_path}")

    data = yaml.safe_load(hint_terms_path.read_text(encoding="utf-8-sig")) or {}
    terms = data.get("terms") or []

    for term in terms:
        term_type = str(term.get("type") or "").strip()
        label = HINT_TARGET_LABELS.get(term_type)
        if not label:
            raise ValueError(f"Unsupported hint term type: {term_type}")

        params = {
            "code": str(term["code"]),
            "term_type": term_type,
            "canonical": str(term["canonical"]),
            "user_terms": [str(value) for value in term.get("user_terms", [])],
            "search_terms": [str(value) for value in term.get("search_terms", [])],
        }
        query = f"""
        MERGE (legal:LegalTerm {{text: $canonical}})
        SET legal.code = $code,
            legal.term_type = $term_type
        WITH legal
        MERGE (target:{label} {{code: $code}})
        SET target.name = $canonical,
            target.term_type = $term_type
        MERGE (legal)-[:INDICATES]->(target)
        WITH legal, target
        UNWIND $user_terms AS userTerm
        MERGE (user:UserTerm {{text: userTerm}})
        MERGE (user)-[:NORMALIZES_TO]->(legal)
        WITH legal, target
        UNWIND $search_terms AS searchTerm
        MERGE (search:LawSearchTerm {{text: searchTerm}})
        MERGE (legal)-[:SEARCHES_WITH]->(search)
        MERGE (target)-[:SEARCHES_WITH]->(search)
        """
        session.run(query, **params).consume()

    return {"hint_terms": len(terms)}





def import_similarity_relations(session, output_dir: Path, batch_size: int) -> int:
    embeddings_path = output_dir / "embeddings" / "law_embeddings_e5_large.jsonl"
    if not embeddings_path.exists():
        print(f"Embeddings file not found: {embeddings_path}. Skipping SIMILAR_TO relations.")
        return 0

    print("Computing embedding cosine similarities for LawChunk nodes...")
    embeddings = []
    chunk_ids = []
    
    for line in read_jsonl(embeddings_path):
        vec = line.get("embedding_vector")
        chunk_id = line.get("chunk_id")
        if vec and chunk_id:
            embeddings.append(vec)
            chunk_ids.append(chunk_id)

    if not embeddings:
        return 0

    import numpy as np
    
    vec_arr = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(vec_arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vec_arr = vec_arr / norms

    # ponytail: O(N^2) pairwise similarity scan has a memory ceiling of O(N^2) space.
    # We resolve this by processing in blocks of 2000 vectors to limit memory to ~1GB.
    # For scaling beyond 100k rows, use pgvector/FAISS/Qdrant vector search to fetch Top-K similar chunks instead of CPU-side O(N^2) scan.
    print(f"Computing pairwise similarities for {vec_arr.shape[0]} vectors in blocks to prevent OOM...")
    similarity_relations = []
    num_vectors = vec_arr.shape[0]
    block_size = 2000
    
    for i in range(0, num_vectors, block_size):
        end_i = min(i + block_size, num_vectors)
        block = vec_arr[i:end_i]
        
        # Compute block similarities with all vectors: Shape (block_size x num_vectors)
        sim_block = np.dot(block, vec_arr.T)
        
        # Filter elements >= 0.85 where column index (c) > row index (r)
        for local_r in range(sim_block.shape[0]):
            r = i + local_r
            # Find column indices where similarity >= 0.85
            c_indices = np.where(sim_block[local_r] >= 0.85)[0]
            for c in c_indices:
                if c > r:
                    similarity_relations.append({
                        "from_id": chunk_ids[r],
                        "to_id": chunk_ids[c],
                        "score": float(sim_block[local_r, c])
                    })
        
        if (i // block_size) % 5 == 0 or end_i == num_vectors:
            print(f"  Processed similarity calculations: {end_i}/{num_vectors}")

    print(f"Found {len(similarity_relations)} pairs with similarity >= 0.85")

    query = """
    UNWIND $rows AS row
    MATCH (c1:LawChunk {chunk_id: row.from_id})
    MATCH (c2:LawChunk {chunk_id: row.to_id})
    MERGE (c1)-[r:SIMILAR_TO]->(c2)
    SET r.score = row.score
    """
    run_batches(session, query, similarity_relations, batch_size)
    return len(similarity_relations)


def require_files(paths: list[Path]) -> None:
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Required Neo4j export inputs are missing: " + ", ".join(missing))


def to_props(row: dict, fields: list[str]) -> dict:
    return {field: row.get(field) for field in fields if field in row}


def run_batches(session, query: str, rows: list[dict], batch_size: int) -> None:
    for index in range(0, len(rows), batch_size):
        session.run(query, rows=rows[index : index + batch_size]).consume()


def safe_relation_type(value: str) -> str:
    relation_type = re.sub(r"[^0-9A-Za-z_]", "_", value.strip().upper())
    if not relation_type or not re.match(r"^[A-Z_][0-9A-Z_]*$", relation_type):
        raise ValueError(f"Invalid relation type: {value}")
    return relation_type


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Neo4j export failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
