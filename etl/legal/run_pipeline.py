"""Unified runner for end-to-end legal data ingestion, embedding, and database seed generation."""

from __future__ import annotations

import sys
from etl.legal.ingestion.run import main as ingestion_main
from etl.legal.embedding.run import main as embedding_main
from etl.legal.export_sql import export_to_sql


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="etl/legal/manifests/traffic_law_manifest.yaml")
    parser.add_argument("--output-dir", default="output/law_ingestion")
    parser.add_argument("--client", default="auto", choices=["auto", "offline", "law_go_kr"])
    parser.add_argument("--provider", default="sentence-transformers", choices=["auto", "sentence-transformers", "openai"])
    parser.add_argument("--embedding-output", default="law_embeddings_e5_large.jsonl")
    parser.add_argument("--embedding-report", default="embedding_report_e5_large.json")
    parser.add_argument("--db-load", action="store_true", help="Directly load data into local PostgreSQL and Neo4j databases")
    args = parser.parse_args(argv)

    print(">>> Stage 1: Ingesting laws and annexes...")
    ing_args = [
        "--manifest", args.manifest,
        "--output-dir", args.output_dir,
        "--mode", "artifact",
        "--client", args.client,
    ]
    ing_code = ingestion_main(ing_args)
    if ing_code != 0:
        print("Ingestion failed.", file=sys.stderr)
        return ing_code

    print("\n>>> Stage 2: Generating embeddings...")
    emb_args = [
        "--input", f"{args.output_dir}/embeddings/embedding_inputs.jsonl",
        "--output", f"{args.output_dir}/embeddings/{args.embedding_output}",
        "--report", f"{args.output_dir}/reports/{args.embedding_report}",
        "--provider", args.provider,
    ]
    emb_code = embedding_main(emb_args)
    if emb_code != 0:
        print("Embedding generation failed.", file=sys.stderr)
        return emb_code

    print("\n>>> Stage 3: Exporting SQL seed for PostgreSQL/pgvector...")
    sql_code = export_to_sql(
        chunks_path=f"{args.output_dir}/chunks/law_chunks.jsonl",
        embeddings_path=f"{args.output_dir}/embeddings/{args.embedding_output}",
        output_sql_path=f"{args.output_dir}/publish/law_db_seed.sql",
    )
    if sql_code != 0:
        print("SQL seed export failed.", file=sys.stderr)
        return sql_code

    if args.db_load:
        print("\n>>> Stage 4: Loading data directly to PostgreSQL...")
        from etl.legal.load_sql import load_to_postgres
        pg_code = load_to_postgres(
            chunks_path=f"{args.output_dir}/chunks/law_chunks.jsonl",
            embeddings_path=f"{args.output_dir}/embeddings/{args.embedding_output}",
        )
        if pg_code != 0:
            print("PostgreSQL load failed.", file=sys.stderr)
            return pg_code

        print("\n>>> Stage 5: Loading data directly to Neo4j...")
        from etl.legal.export_neo4j import main as neo4j_main
        neo_args = [
            "--output-dir", args.output_dir,
            "--hint-terms", "storage/rag/law_query_terms.yaml",
        ]
        try:
            neo_code = neo4j_main(neo_args)
            if neo_code != 0:
                print("Neo4j load failed.", file=sys.stderr)
                return neo_code
        except Exception as exc:
            print(f"Neo4j load failed with exception: {exc}", file=sys.stderr)
            return 1

    print("\n>>> Legal data pipeline executed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
