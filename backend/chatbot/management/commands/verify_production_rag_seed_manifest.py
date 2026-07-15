"""Verify a production RAG seed manifest without connecting to external services."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from app.services.rag_seed_bundle import RagSeedValidationError, load_and_validate_rag_seed_manifest


class Command(BaseCommand):
    help = "Verify paths, hashes, sizes, row counts, schemas, and legal embedding dimensions."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True, help="Path to production_rag_seed_manifest.v1 JSON.")
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options):
        try:
            bundle = load_and_validate_rag_seed_manifest(options["manifest"])
        except RagSeedValidationError as exc:
            raise CommandError(str(exc)) from None

        result = {
            "contract_version": bundle.contract_version,
            "status": "verified",
            "manifest": str(bundle.manifest_path),
            "embedding_space": dict(bundle.embedding_space),
            "artifacts": {role: artifact.row_count for role, artifact in bundle.artifacts.items()},
        }
        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            self.stdout.write(_text_result(result))


def _text_result(result: dict) -> str:
    lines = [f"Production RAG seed manifest: {result['status']}", f"- manifest: {result['manifest']}"]
    embedding_space = result["embedding_space"]
    lines.append(
        "- embedding_space: "
        f"{embedding_space['provider']}/{embedding_space['model']}/"
        f"{embedding_space['dimensions']}"
    )
    lines.extend(f"- {role}: {count}" for role, count in result["artifacts"].items())
    return "\n".join(lines)
