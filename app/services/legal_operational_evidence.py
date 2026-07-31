"""Build privacy-safe legal operational evidence from a verified RAG seed."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from app.services.rag_seed_bundle import RagSeedBundle, iter_rag_seed_jsonl
from etl.legal.ingestion.reporter import RUN_SUMMARY_CONTRACT_VERSION


_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class LegalOperationalEvidenceError(ValueError):
    """Raised when release-bound operational evidence cannot be built safely."""


def build_legal_operational_evidence(
    bundle: RagSeedBundle,
    *,
    dataset_version: str,
    release_version: str,
    verified_at: datetime,
) -> dict[str, object]:
    """Derive a deterministic, content-free run summary from verified chunks."""

    normalized_dataset_version = _safe_version(dataset_version)
    normalized_release_version = _safe_version(release_version)
    if normalized_dataset_version is None or normalized_release_version is None:
        raise LegalOperationalEvidenceError(
            "operational evidence provenance is invalid"
        )
    if verified_at.tzinfo is None:
        raise LegalOperationalEvidenceError(
            "verified_at must include timezone information"
        )
    verified_at_text = verified_at.astimezone(timezone.utc).isoformat()

    legal_artifact = bundle.artifacts.get("legal_chunks")
    if legal_artifact is None:
        raise LegalOperationalEvidenceError(
            "verified RAG seed has no legal chunks"
        )

    sources: dict[str, dict[str, Any]] = {}
    seen_chunk_ids: set[str] = set()
    for row in iter_rag_seed_jsonl(legal_artifact):
        source_id = _required_text(row.get("source_id"))
        chunk_id = _required_text(row.get("chunk_id"))
        source_name = _required_text(row.get("source_name"))
        source_type = _required_text(row.get("source_type"))
        enforce_date = _required_text(row.get("enforce_date"))
        expire_date = str(row.get("expire_date") or "").strip() or None
        if None in (source_id, chunk_id, source_name, source_type, enforce_date):
            raise LegalOperationalEvidenceError(
                "verified legal chunk metadata is incomplete"
            )
        if chunk_id in seen_chunk_ids:
            raise LegalOperationalEvidenceError(
                "verified legal chunks contain a duplicate identity"
            )
        seen_chunk_ids.add(chunk_id)

        source = sources.setdefault(
            source_id,
            {
                "source_id": source_id,
                "source_name": source_name,
                "source_type": source_type,
                "versions": set(),
                "chunk_ids": [],
                "effective_dates": set(),
            },
        )
        if (
            source["source_name"] != source_name
            or source["source_type"] != source_type
        ):
            raise LegalOperationalEvidenceError(
                "verified legal chunk source metadata is inconsistent"
            )
        source["versions"].add((enforce_date, expire_date))
        source["chunk_ids"].append(chunk_id)
        source["effective_dates"].add(enforce_date)

    if not sources:
        raise LegalOperationalEvidenceError(
            "verified RAG seed has no legal chunks"
        )

    source_summaries = [
        _source_summary(source, verified_at_text=verified_at_text)
        for source in (sources[source_id] for source_id in sorted(sources))
    ]
    manifest_sha256 = _sha256(bundle.manifest_path.read_bytes())
    run_identity = "\n".join(
        (
            manifest_sha256,
            normalized_dataset_version,
            normalized_release_version,
        )
    ).encode("utf-8")
    return {
        "contract_version": RUN_SUMMARY_CONTRACT_VERSION,
        "run_id": f"production-rag-seed:{_sha256(run_identity)}",
        "mode": "production-rag-seed-derived",
        "status": "success",
        "dataset_version": normalized_dataset_version,
        "release_version": normalized_release_version,
        "source_summaries": source_summaries,
        "total_sources": len(source_summaries),
        "total_versions": sum(
            int(row["version_count"]) for row in source_summaries
        ),
        "total_raw_documents": 0,
        "total_chunks": len(seen_chunk_ids),
        "searchable_chunks": len(seen_chunk_ids),
        "failed_chunks": 0,
        "partial_chunks": 0,
        "relation_count": 0,
        "extra_relation_count": 0,
        "embedding_input_count": 0,
        "started_at": verified_at_text,
        "finished_at": verified_at_text,
        "limitations": ["derived_from_verified_production_rag_seed"],
    }


def _source_summary(
    source: dict[str, Any],
    *,
    verified_at_text: str,
) -> dict[str, object]:
    chunk_ids = sorted(str(value) for value in source["chunk_ids"])
    effective_dates = sorted(str(value) for value in source["effective_dates"])
    return {
        "source_id": source["source_id"],
        "source_name": source["source_name"],
        "source_type": source["source_type"],
        "provider": "production-rag-seed",
        "provider_source_id": source["source_id"],
        "status": "success",
        "version_count": len(source["versions"]),
        "raw_document_count": 0,
        "chunk_count": len(chunk_ids),
        "searchable_chunk_count": len(chunk_ids),
        "first_effective_at": effective_dates[0],
        "last_effective_at": effective_dates[-1],
        "collected_at": None,
        "last_verified_at": verified_at_text,
        "data_version": f"sha256:{_sha256(chr(10).join(chunk_ids).encode('utf-8'))}",
        "errors": [],
    }


def _required_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_version(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if _SAFE_VERSION_PATTERN.fullmatch(text) else None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
