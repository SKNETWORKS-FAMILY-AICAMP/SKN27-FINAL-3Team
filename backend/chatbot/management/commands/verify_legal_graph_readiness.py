"""Verify private Neo4j legal graph provenance without exposing credentials."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from neo4j import GraphDatabase


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Command(BaseCommand):
    help = "Verify the active Neo4j legal graph matches the approved RAG seed."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options) -> None:
        result = verify_legal_graph_readiness()
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(f"Legal graph readiness: {result['status']}")
        if result["status"] != "ready":
            raise CommandError("legal graph readiness verification failed")


def verify_legal_graph_readiness() -> dict[str, Any]:
    """Check connectivity, metadata, graph cardinality, and a safe expansion query."""

    config = _runtime_config()
    if config is None:
        return _failure("graph_runtime_config_missing")
    uri, user, password, database, dataset_version, manifest_sha256, canonical_sha256 = config
    try:
        with GraphDatabase.driver(uri, auth=(user, password)) as driver:
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                metadata = session.run(
                    """
                    MATCH (dataset:LegalGraphDataset {dataset_version: $dataset_version})
                    WHERE dataset.status = 'active'
                    RETURN dataset.dataset_version AS dataset_version,
                           dataset.manifest_sha256 AS manifest_sha256,
                           dataset.canonical_chunk_sha256 AS canonical_chunk_sha256,
                           dataset.legal_chunk_count AS legal_chunk_count
                    LIMIT 1
                    """,
                    dataset_version=dataset_version,
                ).single()
                if metadata is None:
                    return _failure("graph_metadata_missing")
                if metadata.get("manifest_sha256") != manifest_sha256:
                    return _failure("manifest_sha256_mismatch")
                if canonical_sha256 and metadata.get("canonical_chunk_sha256") != canonical_sha256:
                    return _failure("canonical_chunk_sha256_mismatch")
                graph_count_record = session.run(
                    "MATCH (chunk:LawChunk) RETURN count(chunk) AS chunk_count"
                ).single()
                graph_count = int((graph_count_record or {}).get("chunk_count") or 0)
                expected_count = int(metadata.get("legal_chunk_count") or 0)
                if graph_count != expected_count or expected_count <= 0:
                    return _failure("legal_chunk_count_mismatch")
                version_temporal = session.run(
                    """
                    MATCH (version:LawVersion)
                    RETURN count(version) AS version_count,
                           count(version.enforce_date) AS enforce_date_count,
                           count(
                               CASE
                                   WHEN version.version_status = 'historical'
                                        AND version.expire_date IS NULL
                                   THEN 1
                               END
                           ) AS historical_missing_expire_count
                    """
                ).single()
                version_count = int(
                    (version_temporal or {}).get("version_count") or 0
                )
                version_enforce_count = int(
                    (version_temporal or {}).get("enforce_date_count") or 0
                )
                version_missing_expire = int(
                    (version_temporal or {}).get(
                        "historical_missing_expire_count"
                    )
                    or 0
                )
                if (
                    version_count <= 0
                    or version_enforce_count != version_count
                    or version_missing_expire != 0
                ):
                    return _failure(
                        "law_version_temporal_metadata_invalid"
                    )
                chunk_temporal = session.run(
                    """
                    MATCH (chunk:LawChunk)
                    OPTIONAL MATCH
                        (version:LawVersion)-[:HAS_CHUNK]->(chunk)
                    WITH chunk, collect(version)[0] AS version
                    RETURN count(chunk) AS chunk_count,
                           count(chunk.enforce_date) AS enforce_date_count,
                           count(
                               CASE
                                   WHEN version.version_status = 'historical'
                                        AND chunk.expire_date IS NULL
                                   THEN 1
                               END
                           ) AS historical_missing_expire_count
                    """
                ).single()
                temporal_chunk_count = int(
                    (chunk_temporal or {}).get("chunk_count") or 0
                )
                chunk_enforce_count = int(
                    (chunk_temporal or {}).get("enforce_date_count") or 0
                )
                chunk_missing_expire = int(
                    (chunk_temporal or {}).get(
                        "historical_missing_expire_count"
                    )
                    or 0
                )
                if (
                    temporal_chunk_count != graph_count
                    or chunk_enforce_count != graph_count
                    or chunk_missing_expire != 0
                ):
                    return _failure(
                        "law_chunk_temporal_metadata_invalid"
                    )
                session.run(
                    """
                    MATCH (c1:LawChunk)-[r]-(c2:LawChunk)
                    WHERE type(r) IN $relation_types
                    RETURN count(c2) AS expanded
                    LIMIT 1
                    """,
                    relation_types=["HAS_PENALTY", "HAS_APPENDIX", "HAS_EXCEPTION", "RELATED_TO"],
                ).consume()
    except Exception:
        return _failure("neo4j_unavailable")
    return {
        "contract_version": "legal_graph_readiness.v1",
        "status": "ready",
        "error_code": "",
        "dataset_version": dataset_version,
        "legal_chunk_count": graph_count,
    }


def _runtime_config() -> tuple[str, str, str, str, str, str, str] | None:
    values = {
        name: str(os.getenv(name, "") or "").strip()
        for name in (
            "NEO4J_URI",
            "NEO4J_USER",
            "NEO4J_PASSWORD",
            "NEO4J_DATABASE",
            "LEGAL_DATASET_VERSION",
            "LEGAL_RAG_SEED_MANIFEST_SHA256",
            "LEGAL_GRAPH_CANONICAL_CHUNK_SHA256",
        )
    }
    required = (
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "LEGAL_DATASET_VERSION",
        "LEGAL_RAG_SEED_MANIFEST_SHA256",
    )
    if any(not values[name] for name in required):
        return None
    if not _SHA256.fullmatch(values["LEGAL_RAG_SEED_MANIFEST_SHA256"]):
        return None
    canonical = values["LEGAL_GRAPH_CANONICAL_CHUNK_SHA256"]
    if canonical and not _SHA256.fullmatch(canonical):
        return None
    return (
        values["NEO4J_URI"],
        values["NEO4J_USER"],
        values["NEO4J_PASSWORD"],
        values["NEO4J_DATABASE"],
        values["LEGAL_DATASET_VERSION"],
        values["LEGAL_RAG_SEED_MANIFEST_SHA256"],
        canonical,
    )


def _failure(error_code: str) -> dict[str, Any]:
    return {
        "contract_version": "legal_graph_readiness.v1",
        "status": "fail",
        "error_code": error_code,
    }
