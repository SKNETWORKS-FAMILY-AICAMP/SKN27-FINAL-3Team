"""Load and embed a manifest-bound review-case pgvector seed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from app.services.rag_seed_bundle import (
    RagSeedValidationError,
    load_and_validate_rag_seed_manifest,
)
from app.services.review_case_seed_service import (
    ReviewCaseSeedError,
    read_review_case_seed_rows,
    replace_and_upsert_review_case_rows,
)
from etl.fault_cases.src.review_case.db_loading.db_config import (
    EMBEDDING_SETTINGS,
    PGVECTOR_INDEX_SETTINGS,
)
from etl.fault_cases.src.review_case.embedding.run_embedding import (
    create_embeddings,
)
from etl.fault_cases.src.review_case.search.pgvector.create_index import (
    count_embedding_rows,
    index_exists,
)


class ReviewCasePgvectorSeedError(RuntimeError):
    """Credential-safe operator error for an incomplete seed promotion."""


class Command(BaseCommand):
    help = (
        "Validate, load, and embed the review-case artifact from a production "
        "RAG seed manifest."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            required=True,
            help="Path to production_rag_seed_manifest.v1 JSON.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace existing review-case source rows before loading.",
        )
        parser.add_argument(
            "--allow-paid-provider-call",
            action="store_true",
            help="Explicitly authorize paid OpenAI embedding calls.",
        )
        parser.add_argument(
            "--format",
            choices=["json", "text"],
            default="json",
        )

    def handle(self, *args, **options):
        try:
            bundle = load_and_validate_rag_seed_manifest(
                Path(str(options["manifest"]))
            )
            if not bool(options["allow_paid_provider_call"]):
                raise ReviewCasePgvectorSeedError(
                    "explicit paid provider approval is required; rerun with "
                    "--allow-paid-provider-call"
                )
            result = execute_review_case_pgvector_seed(
                bundle,
                replace=bool(options["replace"]),
            )
        except (
            RagSeedValidationError,
            ReviewCaseSeedError,
            ReviewCasePgvectorSeedError,
        ) as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError(
                "review-case pgvector seed load failed; inspect private "
                "runtime logs"
            ) from None

        if options["format"] == "json":
            self.stdout.write(
                json.dumps(result, ensure_ascii=False, sort_keys=True)
            )
        else:
            self.stdout.write(_text_result(result))


def execute_review_case_pgvector_seed(
    bundle,
    *,
    replace: bool,
) -> dict[str, Any]:
    expected_space = {
        "provider": EMBEDDING_SETTINGS.provider,
        "model": EMBEDDING_SETTINGS.model,
        "dimensions": EMBEDDING_SETTINGS.dim,
    }
    if dict(bundle.embedding_space) != expected_space:
        raise ReviewCasePgvectorSeedError(
            "manifest embedding space does not match the canonical "
            "review-case embedding space"
        )

    artifact = bundle.artifacts["review_case_chunks"]
    rows = read_review_case_seed_rows(artifact.path)
    expected_count = int(artifact.row_count)
    if len(rows) != expected_count:
        raise ReviewCasePgvectorSeedError(
            "review-case source row count did not match the verified manifest"
        )

    source_counts = replace_and_upsert_review_case_rows(
        rows,
        replace=replace,
    )
    if int(source_counts.get("review_case_chunks") or 0) != expected_count:
        raise ReviewCasePgvectorSeedError(
            "review-case loaded row count did not match the verified manifest"
        )

    embedding_report = create_embeddings(limit=None, dry_run=False)
    embedding_count = count_embedding_rows()
    if embedding_count != expected_count:
        raise ReviewCasePgvectorSeedError(
            "review-case embedding row count did not match the verified "
            "manifest"
        )

    index_name = PGVECTOR_INDEX_SETTINGS.index_name
    if not index_exists(index_name):
        raise ReviewCasePgvectorSeedError(
            "canonical review-case HNSW index was not found"
        )

    return {
        "contract_version": "review_case_pgvector_seed_load.v1",
        "status": "loaded",
        "source": {
            "review_case_documents": int(
                source_counts.get("review_case_documents") or 0
            ),
            "review_case_chunks": int(
                source_counts.get("review_case_chunks") or 0
            ),
        },
        "embedding": {
            "provider": EMBEDDING_SETTINGS.provider,
            "model": EMBEDDING_SETTINGS.model,
            "version": EMBEDDING_SETTINGS.version,
            "dimensions": EMBEDDING_SETTINGS.dim,
            "pending_selected": int(
                embedding_report.get("pending_chunk_count_selected") or 0
            ),
            "inserted_or_updated": int(
                embedding_report.get("inserted_or_updated_embeddings") or 0
            ),
            "count_after": embedding_count,
        },
        "index": {
            "name": index_name,
            "exists": True,
        },
    }


def _text_result(result: dict[str, Any]) -> str:
    source = result["source"]
    embedding = result["embedding"]
    index = result["index"]
    return "\n".join(
        [
            f"Review-case pgvector seed: {result['status']}",
            f"- documents: {source['review_case_documents']}",
            f"- chunks: {source['review_case_chunks']}",
            f"- embeddings: {embedding['count_after']}",
            (
                "- embedding_space: "
                f"{embedding['provider']}/{embedding['model']}/"
                f"{embedding['dimensions']}"
            ),
            f"- hnsw_index: {index['name']} ({index['exists']})",
        ]
    )
