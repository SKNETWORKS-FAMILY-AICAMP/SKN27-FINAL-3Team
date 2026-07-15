"""Build an integrity manifest for the four production RAG seed artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from app.services.rag_seed_bundle import RagSeedValidationError, build_rag_seed_manifest


class Command(BaseCommand):
    help = "Validate four JSONL artifacts and build production_rag_seed_manifest.v1."

    def add_arguments(self, parser):
        parser.add_argument("--bundle-root", required=True, help="Directory containing the seed artifacts.")
        parser.add_argument(
            "--manifest",
            default="rag-seed-manifest.json",
            help="Manifest filename written directly under bundle-root.",
        )
        parser.add_argument("--legal-chunks", required=True, help="Relative legal chunks JSONL path.")
        parser.add_argument("--legal-embeddings", required=True, help="Relative legal embeddings JSONL path.")
        parser.add_argument("--review-case-chunks", required=True, help="Relative review-case JSONL path.")
        parser.add_argument(
            "--precedent-fault-ratio-chunks",
            required=True,
            help="Relative fault-ratio precedent JSONL path.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json")

    def handle(self, *args, **options):
        root = Path(options["bundle_root"]).resolve()
        manifest_option = Path(options["manifest"])
        manifest_path = manifest_option if manifest_option.is_absolute() else root / manifest_option
        artifact_paths = {
            "legal_chunks": options["legal_chunks"],
            "legal_embeddings": options["legal_embeddings"],
            "review_case_chunks": options["review_case_chunks"],
            "precedent_fault_ratio_chunks": options["precedent_fault_ratio_chunks"],
        }
        try:
            manifest = build_rag_seed_manifest(
                bundle_root=root,
                artifact_paths=artifact_paths,
                manifest_path=manifest_option,
            )
        except RagSeedValidationError as exc:
            raise CommandError(str(exc)) from None

        result = {
            "contract_version": manifest["contract_version"],
            "status": "built",
            "manifest": str(manifest_path.resolve()),
            "embedding_space": manifest["embedding_space"],
            "artifacts": {item["role"]: item["row_count"] for item in manifest["artifacts"]},
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
