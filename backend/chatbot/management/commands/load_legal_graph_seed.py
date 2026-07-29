"""Load a verified legal RAG bundle into the private Neo4j law graph."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from django.core.management.base import BaseCommand, CommandError

from app.services.law_graph_seed import LawGraphSeed, build_law_graph_seed
from app.services.rag_seed_bundle import RagSeedValidationError, load_and_validate_rag_seed_manifest
from etl.legal.export_neo4j import (
    create_constraints,
    import_hint_terms,
    import_law_graph_seed,
)
from neo4j import GraphDatabase


class LegalGraphSeedLoadError(RuntimeError):
    """Credential-safe operator error for legal graph loading."""


class Command(BaseCommand):
    help = "Validate a production RAG seed and load its legal graph into Neo4j."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--dataset-version", required=True)
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Clear only the private legal graph before loading this approved dataset.",
        )
        parser.add_argument(
            "--hint-terms",
            default="storage/rag/law_query_terms.yaml",
            help="Validated law query term YAML packaged with the release.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options) -> None:
        try:
            bundle = load_and_validate_rag_seed_manifest(Path(options["manifest"]))
            # Validate immediately before graph writes as the mounted seed directory
            # is mutable until the maintenance job has completed.
            bundle = load_and_validate_rag_seed_manifest(bundle.manifest_path)
            seed = build_law_graph_seed(
                bundle,
                dataset_version=str(options["dataset_version"]),
            )
            result = execute_legal_graph_seed_load(
                seed,
                batch_size=max(1, int(options["batch_size"] or 500)),
                replace=bool(options["replace"]),
                hint_terms_path=Path(options["hint_terms"]),
            )
        except (RagSeedValidationError, LegalGraphSeedLoadError, ValueError) as exc:
            raise CommandError(str(exc)) from None
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(
                "Legal graph seed: loaded "
                f"(chunks={result['graph']['law_chunks']}, dataset={result['metadata']['dataset_version']})"
            )


def execute_legal_graph_seed_load(
    seed: LawGraphSeed,
    *,
    batch_size: int,
    hint_terms_path: Path,
    replace: bool = False,
    driver_factory: Callable[..., Any] = GraphDatabase.driver,
) -> dict[str, Any]:
    """Import graph rows, then atomically publish the dataset metadata node."""

    if batch_size < 1:
        raise LegalGraphSeedLoadError("batch_size must be at least 1")
    uri, user, password, database = _neo4j_runtime_config()
    try:
        with driver_factory(uri, auth=(user, password)) as driver:
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                create_constraints(session)
                if replace:
                    _clear_legal_graph(session)
                graph = import_law_graph_seed(session, seed, batch_size=batch_size)
                hints = import_hint_terms(session, hint_terms_path)
                metadata = _write_dataset_metadata(session, seed, legal_chunk_count=graph["law_chunks"])
    except LegalGraphSeedLoadError:
        raise
    except Exception:
        raise LegalGraphSeedLoadError("Neo4j legal graph load failed") from None
    return {
        "contract_version": "legal_graph_seed_load.v1",
        "status": "loaded",
        "replaced": replace,
        "graph": graph,
        "hints": hints,
        "metadata": metadata,
    }


def _write_dataset_metadata(
    session,
    seed: LawGraphSeed,
    *,
    legal_chunk_count: int,
) -> dict[str, Any]:
    metadata = {
        "dataset_version": seed.dataset_version,
        "manifest_sha256": seed.manifest_sha256,
        "canonical_chunk_sha256": seed.canonical_chunk_sha256,
        "legal_chunk_count": int(legal_chunk_count),
    }
    session.run(
        """
        MERGE (dataset:LegalGraphDataset {dataset_version: $dataset_version})
        SET dataset.manifest_sha256 = $manifest_sha256,
            dataset.canonical_chunk_sha256 = $canonical_chunk_sha256,
            dataset.legal_chunk_count = $legal_chunk_count,
            dataset.status = 'active'
        """,
        **metadata,
    ).consume()
    return metadata


def _clear_legal_graph(session) -> None:
    """Remove only labels owned by the legal graph before an approved replacement."""

    session.run(
        """
        MATCH (node)
        WHERE node:LegalGraphDataset
           OR node:LegalSource
           OR node:LawVersion
           OR node:LawChunk
           OR node:UserTerm
           OR node:LegalTerm
           OR node:LawSearchTerm
           OR node:VehicleType
           OR node:ViolationType
           OR node:PenaltyType
        DETACH DELETE node
        """
    ).consume()


def _neo4j_runtime_config() -> tuple[str, str, str, str]:
    values = {
        name: str(os.getenv(name, "") or "").strip()
        for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise LegalGraphSeedLoadError("Neo4j runtime configuration is incomplete")
    return (
        values["NEO4J_URI"],
        values["NEO4J_USER"],
        values["NEO4J_PASSWORD"],
        values["NEO4J_DATABASE"],
    )
