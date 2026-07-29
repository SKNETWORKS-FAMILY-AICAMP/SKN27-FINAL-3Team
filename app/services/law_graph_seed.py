"""Derive a deterministic legal Neo4j seed from a verified RAG seed bundle.

The production RAG bundle stays on its immutable v1 contract.  This module
only reads its validated ``legal_chunks`` artifact and derives graph rows for
Neo4j; it never copies embeddings or alters the source bundle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.services.rag_seed_bundle import RagSeedBundle, iter_rag_seed_jsonl
from etl.legal.extract_extra_relations import build_extra_relations


LEGAL_GRAPH_SEED_CONTRACT_VERSION = "legal_graph_seed.v1"
_DETERMINISTIC_RELATION_TIMESTAMP = "1970-01-01T00:00:00+00:00"


@dataclass(frozen=True)
class LawGraphSeed:
    """Neo4j rows and provenance derived from one validated legal seed."""

    dataset_version: str
    manifest_sha256: str
    canonical_chunk_sha256: str
    sources: tuple[Mapping[str, Any], ...]
    versions: tuple[Mapping[str, Any], ...]
    chunks: tuple[Mapping[str, Any], ...]
    relations: tuple[Mapping[str, Any], ...]


def build_law_graph_seed(
    bundle: RagSeedBundle,
    *,
    dataset_version: str,
) -> LawGraphSeed:
    """Build stable source/version/chunk graph rows from verified legal chunks.

    ``bundle`` must already come from ``load_and_validate_rag_seed_manifest``.
    Sorting by stable identifiers makes graph rows independent of JSONL order.
    """

    normalized_dataset_version = _required_text(dataset_version, "dataset_version")
    legal_artifact = bundle.artifacts.get("legal_chunks")
    if legal_artifact is None:
        raise ValueError("verified RAG seed bundle has no legal_chunks artifact")

    source_rows: dict[str, dict[str, Any]] = {}
    version_rows: dict[str, dict[str, Any]] = {}
    chunk_rows: list[dict[str, Any]] = []
    for row in iter_rag_seed_jsonl(legal_artifact):
        source_id = str(row["source_id"])
        source = _source_props(row)
        current_source = source_rows.setdefault(source_id, source)
        if current_source != source:
            raise ValueError(f"legal_chunks source_id {source_id!r} has inconsistent source metadata")

        source_version_id = _source_version_id(row)
        version = _version_props(row, source_version_id)
        current_version = version_rows.setdefault(source_version_id, version)
        if current_version != version:
            raise ValueError(
                f"legal_chunks source version {source_version_id!r} has inconsistent metadata"
            )
        chunk_rows.append(_chunk_props(row, source_version_id))

    chunks = tuple(sorted(chunk_rows, key=lambda item: str(item["chunk_id"])))
    relations = tuple(
        build_extra_relations(
            chunks,
            created_at=_DETERMINISTIC_RELATION_TIMESTAMP,
        )
    )
    return LawGraphSeed(
        dataset_version=normalized_dataset_version,
        manifest_sha256=_sha256(bundle.manifest_path),
        canonical_chunk_sha256=_canonical_sha256(chunks),
        sources=tuple(source_rows[key] for key in sorted(source_rows)),
        versions=tuple(version_rows[key] for key in sorted(version_rows)),
        chunks=chunks,
        relations=relations,
    )


def _source_props(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": str(row["source_id"]),
        "source_name": str(row["source_name"]),
        "source_type": str(row["source_type"]),
        "provider": "production-rag-seed",
        "provider_source_id": str(row["source_id"]),
        "enabled": True,
        "priority": 100,
    }


def _source_version_id(row: Mapping[str, Any]) -> str:
    source_id = _required_text(row.get("source_id"), "source_id")
    enforce_date = _required_text(row.get("enforce_date"), "enforce_date")
    expire_date = str(row.get("expire_date") or "").strip() or "active"
    return f"{source_id}:{enforce_date}:{expire_date}"


def _version_props(row: Mapping[str, Any], source_version_id: str) -> dict[str, Any]:
    return {
        "source_version_id": source_version_id,
        "source_id": str(row["source_id"]),
        "mst": str(row["enforce_date"]),
        "enforce_date": str(row["enforce_date"]),
        "expire_date": _optional_text(row.get("expire_date")),
        "promulgation_date": _optional_text(row.get("promulgation_date")),
        "promulgation_no": _optional_text(row.get("promulgation_no")),
        "law_serial_no": _optional_text(row.get("law_serial_no")),
        "raw_document_id": str(row["source_id"]),
        "version_status": "active" if not _optional_text(row.get("expire_date")) else "historical",
    }


def _chunk_props(row: Mapping[str, Any], source_version_id: str) -> dict[str, Any]:
    provision_text = str(row["provision_text"])
    normalized_text = str(row["normalized_text"])
    return {
        "chunk_id": str(row["chunk_id"]),
        "source_ref": str(row["source_id"]),
        "source_id": str(row["source_id"]),
        "source_name": str(row["source_name"]),
        "source_type": str(row["source_type"]),
        "source_version_id": source_version_id,
        "mst": str(row["enforce_date"]),
        "chunk_type": str(row["chunk_type"]),
        "article_no": _optional_text(row.get("article_no")),
        "article_title": _optional_text(row.get("article_title")),
        "paragraph_no": _optional_text(row.get("paragraph_no")),
        "item_no": _optional_text(row.get("item_no")),
        "appendix_no": _optional_text(row.get("appendix_no")),
        "form_no": _optional_text(row.get("form_no")),
        "structure_id": _optional_text(row.get("structure_id")),
        "segment_no": _optional_text(row.get("segment_no")),
        "provision_text": provision_text,
        "normalized_text": normalized_text,
        "source_url": str(row["source_url"]),
        "enforce_date": str(row["enforce_date"]),
        "expire_date": _optional_text(row.get("expire_date")),
        "content_hash": _text_sha256(provision_text, normalized_text),
        "parse_status": "verified-rag-seed",
        "validation_status": "verified",
        "is_searchable": True,
        "domain_tags": sorted(str(tag) for tag in row.get("domain_tags", [])),
    }


def _canonical_sha256(rows: tuple[Mapping[str, Any], ...]) -> str:
    encoded = "".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_sha256(*values: str) -> str:
    return hashlib.sha256("\u001f".join(values).encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field} must be a non-empty string")
    return text
