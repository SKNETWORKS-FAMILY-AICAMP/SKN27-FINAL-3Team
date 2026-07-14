"""Load a verified production RAG seed into pgvector and Elasticsearch."""

from __future__ import annotations

import json
import os
from io import StringIO
from typing import Any, Callable, Iterable

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from app.services.rag_seed_bundle import (
    RagSeedArtifact,
    RagSeedBundle,
    RagSeedValidationError,
    iter_rag_seed_jsonl,
    load_and_validate_rag_seed_manifest,
    validate_elasticsearch_index_targets,
)


REVIEW_CASE_INDEX = os.getenv("REVIEW_CASE_ES_BM25_INDEX", "review_case_chunks_bm25_nori_v1")
FAULT_RATIO_INDEX = os.getenv(
    "FAULT_RATIO_PRECEDENT_ES_BM25_INDEX",
    "precedent_fault_ratio_chunks_bm25_nori_v1",
)


class SeedLoadError(RuntimeError):
    """Safe operator-facing error that never includes source documents or credentials."""


class Command(BaseCommand):
    help = "Verify and load a production RAG seed manifest into pgvector and two BM25/Nori indexes."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, help="Path to production_rag_seed_manifest.v1 JSON.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate all artifacts and print the plan without connecting to PostgreSQL or Elasticsearch.",
        )
        parser.add_argument(
            "--replace-legal",
            action="store_true",
            help="Truncate legal pgvector tables before loading. Omit for an idempotent upsert.",
        )
        parser.add_argument(
            "--recreate-es",
            action="store_true",
            help="Delete and recreate both Elasticsearch indexes before loading.",
        )
        parser.add_argument("--batch-size", type=int, default=500, help="Database and ES bulk batch size.")
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options):
        try:
            bundle = load_and_validate_rag_seed_manifest(options["manifest"])
            result = execute_rag_seed_load(
                bundle,
                dry_run=bool(options["dry_run"]),
                replace_legal=bool(options["replace_legal"]),
                recreate_es=bool(options["recreate_es"]),
                batch_size=max(1, int(options["batch_size"] or 500)),
            )
        except (RagSeedValidationError, SeedLoadError) as exc:
            raise CommandError(str(exc)) from None

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(_text_result(result))


def execute_rag_seed_load(
    bundle: RagSeedBundle,
    *,
    dry_run: bool,
    replace_legal: bool,
    recreate_es: bool,
    batch_size: int,
) -> dict[str, Any]:
    """Execute a verified, idempotent three-target load or return its dry-run plan."""

    try:
        review_case_index, fault_ratio_index = validate_elasticsearch_index_targets(
            REVIEW_CASE_INDEX,
            FAULT_RATIO_INDEX,
        )
    except RagSeedValidationError as exc:
        raise SeedLoadError(str(exc)) from None

    if not dry_run:
        # Re-verify immediately before external writes. This narrows the window in
        # which a mutable bundle could diverge from the manifest that was approved.
        approved_identity = _bundle_identity(bundle)
        verified_bundle = load_and_validate_rag_seed_manifest(bundle.manifest_path)
        if _bundle_identity(verified_bundle) != approved_identity:
            raise SeedLoadError("RAG seed bundle changed after approval")
        bundle = verified_bundle

    result: dict[str, Any] = {
        "contract_version": "production_rag_seed_load.v1",
        "status": "validated" if dry_run else "loaded",
        "external_writes": not dry_run,
        "manifest": str(bundle.manifest_path),
        "embedding_space": dict(bundle.embedding_space),
        "artifacts": {role: artifact.row_count for role, artifact in bundle.artifacts.items()},
        "targets": {
            "legal": "postgresql_pgvector",
            "review_case": review_case_index,
            "precedent_fault_ratio": fault_ratio_index,
        },
        "options": {
            "replace_legal": replace_legal,
            "recreate_es": recreate_es,
            "batch_size": batch_size,
        },
    }
    if dry_run:
        return result

    loads = {
        "legal": _load_legal_pgvector(bundle, replace=replace_legal, batch_size=batch_size),
        "review_case": _load_review_case_elasticsearch(
            bundle,
            recreate=recreate_es,
            batch_size=batch_size,
        ),
        "precedent_fault_ratio": _load_fault_ratio_elasticsearch(
            bundle,
            recreate=recreate_es,
            batch_size=batch_size,
        ),
    }
    result["loads"] = loads
    return result


def _load_legal_pgvector(bundle: RagSeedBundle, *, replace: bool, batch_size: int) -> dict[str, Any]:
    output = StringIO()
    try:
        call_command(
            "load_legal_rag_pgvector",
            chunks=str(bundle.artifacts["legal_chunks"].path),
            embeddings=str(bundle.artifacts["legal_embeddings"].path),
            replace=replace,
            batch_size=batch_size,
            format="json",
            stdout=output,
        )
        payload = json.loads(output.getvalue())
    except Exception:
        raise SeedLoadError("PostgreSQL legal RAG load failed") from None
    loaded = payload.get("loaded") or {}
    counts = payload.get("counts") or {}
    loaded_chunks = int(loaded.get("chunks") or 0)
    loaded_embeddings = int(loaded.get("embeddings") or 0)
    if (
        loaded_chunks != bundle.artifacts["legal_chunks"].row_count
        or loaded_embeddings != bundle.artifacts["legal_embeddings"].row_count
    ):
        raise SeedLoadError(
            "PostgreSQL legal RAG load count did not match the verified artifact"
        )
    return {
        "target": "postgresql_pgvector",
        "loaded_chunks": loaded_chunks,
        "loaded_embeddings": loaded_embeddings,
        "law_chunks_after": int(counts.get("law_chunks") or 0),
        "law_embeddings_after": int(counts.get("law_embeddings") or 0),
    }


def _load_review_case_elasticsearch(
    bundle: RagSeedBundle,
    *,
    recreate: bool,
    batch_size: int,
) -> dict[str, Any]:
    try:
        from elasticsearch import helpers

        from etl.fault_cases.src.review_case.search.elasticsearch import bm25_indexer

        settings = bm25_indexer.ELASTICSEARCH_SETTINGS
        client = bm25_indexer.get_elasticsearch_client(settings)
        return _bulk_index_artifact(
            artifact=bundle.artifacts["review_case_chunks"],
            client=client,
            ensure_index=bm25_indexer.ensure_index,
            action_builder=lambda row: bm25_indexer.build_action(
                index_name=REVIEW_CASE_INDEX,
                index_version=settings.bm25_index_version,
                row=row,
            ),
            index_name=REVIEW_CASE_INDEX,
            recreate=recreate,
            batch_size=batch_size,
            request_timeout=settings.request_timeout,
            bulk_fn=helpers.bulk,
        )
    except SeedLoadError:
        raise
    except Exception:
        raise SeedLoadError("Elasticsearch review-case load failed") from None


def _load_fault_ratio_elasticsearch(
    bundle: RagSeedBundle,
    *,
    recreate: bool,
    batch_size: int,
) -> dict[str, Any]:
    try:
        from elasticsearch import helpers

        from etl.fault_cases.src.traffic_precedents.precedent_search.elasticsearch import bm25_indexer

        settings = bm25_indexer.ELASTICSEARCH_SETTINGS
        client = bm25_indexer.get_elasticsearch_client(settings)
        return _bulk_index_artifact(
            artifact=bundle.artifacts["precedent_fault_ratio_chunks"],
            client=client,
            ensure_index=bm25_indexer.ensure_index,
            action_builder=lambda row: bm25_indexer.build_action(
                dataset="fault_ratio",
                index_name=FAULT_RATIO_INDEX,
                index_version=settings.bm25_index_version,
                row=row,
            ),
            index_name=FAULT_RATIO_INDEX,
            recreate=recreate,
            batch_size=batch_size,
            request_timeout=settings.request_timeout,
            bulk_fn=helpers.bulk,
        )
    except SeedLoadError:
        raise
    except Exception:
        raise SeedLoadError("Elasticsearch fault-ratio precedent load failed") from None


def _bulk_index_artifact(
    *,
    artifact: RagSeedArtifact,
    client: Any,
    ensure_index: Callable[..., dict[str, Any]],
    action_builder: Callable[[dict[str, Any]], dict[str, Any]],
    index_name: str,
    recreate: bool,
    batch_size: int,
    request_timeout: int,
    bulk_fn: Callable[..., tuple[int, Any]],
) -> dict[str, Any]:
    """Stream one verified artifact through an existing ES mapping/action builder."""

    index_status = ensure_index(client=client, index_name=index_name, recreate=recreate)
    actions: Iterable[dict[str, Any]] = (
        action_builder(row) for row in iter_rag_seed_jsonl(artifact)
    )
    success_count, errors = bulk_fn(
        client.options(request_timeout=request_timeout),
        actions,
        chunk_size=max(1, batch_size),
        raise_on_error=False,
        raise_on_exception=False,
        stats_only=True,
    )
    error_count = len(errors) if isinstance(errors, list) else int(errors or 0)
    if error_count:
        raise SeedLoadError(f"Elasticsearch bulk load failed for {error_count} document(s)")
    if int(success_count) != artifact.row_count:
        raise SeedLoadError("Elasticsearch bulk load count did not match the verified artifact")
    client.indices.refresh(index=index_name)
    return {
        "index": index_name,
        "selected": artifact.row_count,
        "indexed": int(success_count),
        "created": bool(index_status.get("created")),
        "recreated": bool(index_status.get("recreated")),
    }


def _text_result(result: dict[str, Any]) -> str:
    lines = [
        f"Production RAG seed: {result['status']}",
        f"- external_writes: {str(result['external_writes']).lower()}",
    ]
    embedding_space = result["embedding_space"]
    lines.append(
        "- embedding_space: "
        f"{embedding_space['provider']}/{embedding_space['model']}/"
        f"{embedding_space['dimensions']}"
    )
    for role, count in result["artifacts"].items():
        lines.append(f"- {role}: {count}")
    for target, name in result["targets"].items():
        lines.append(f"- target_{target}: {name}")
    return "\n".join(lines)


def _bundle_identity(bundle: RagSeedBundle) -> tuple[Any, ...]:
    artifact_identity = tuple(
        (
            role,
            artifact.relative_path,
            str(artifact.path),
            artifact.sha256,
            artifact.byte_count,
            artifact.row_count,
        )
        for role, artifact in sorted(bundle.artifacts.items())
    )
    embedding_space = tuple(sorted(bundle.embedding_space.items()))
    return bundle.contract_version, embedding_space, artifact_identity
