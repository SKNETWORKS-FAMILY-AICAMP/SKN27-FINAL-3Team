"""Load the legal pgvector seed and preserve source-specific corpus preparation."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from app.services.rag_seed_bundle import (
    RagSeedBundle,
    RagSeedValidationError,
    load_and_validate_rag_seed_manifest,
)


class SeedLoadError(RuntimeError):
    """Safe operator-facing error that never includes source documents or credentials."""


class Command(BaseCommand):
    help = "Verify a production RAG manifest and load its legal pgvector seed."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, help="Path to production_rag_seed_manifest.v1 JSON.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate all artifacts and print the plan without connecting to PostgreSQL.",
        )
        parser.add_argument(
            "--replace-legal",
            action="store_true",
            help="Truncate legal pgvector tables before loading. Omit for an idempotent upsert.",
        )
        parser.add_argument("--batch-size", type=int, default=500, help="PostgreSQL legal-load batch size.")
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options):
        try:
            bundle = load_and_validate_rag_seed_manifest(options["manifest"])
            result = execute_rag_seed_load(
                bundle,
                dry_run=bool(options["dry_run"]),
                replace_legal=bool(options["replace_legal"]),
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
    batch_size: int,
) -> dict[str, Any]:
    """Load only legal data; other corpus loaders require full source artifacts."""

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
            "review_case": "source_specific_pgvector_loader_required",
            "precedent_fault_ratio": "source_specific_pgvector_loader_required",
        },
        "options": {
            "replace_legal": replace_legal,
            "batch_size": batch_size,
        },
        "preconditions": [
            "Run review_case source DB load, embedding, and HNSW creation before cutover.",
            "Run fault_ratio source DB load, embedding, and HNSW creation before cutover.",
            "Run verify_pgvector_rag_readiness after the legal load.",
        ],
    }
    if dry_run:
        return result

    loads = {
        "legal": _load_legal_pgvector(
            bundle,
            replace=replace_legal,
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
            artifact.sha256,
            artifact.byte_count,
            artifact.row_count,
        )
        for role, artifact in sorted(bundle.artifacts.items())
    )
    embedding_space = tuple(sorted(bundle.embedding_space.items()))
    return bundle.contract_version, embedding_space, artifact_identity
