"""Build release-bound legal operational evidence from a verified RAG seed."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from django.core.management.base import BaseCommand, CommandError

from app.services.legal_operational_evidence import (
    LegalOperationalEvidenceError,
    build_legal_operational_evidence,
)
from app.services.rag_seed_bundle import (
    RagSeedValidationError,
    load_and_validate_rag_seed_manifest,
)


class Command(BaseCommand):
    help = "Emit one privacy-safe legal run summary JSON document."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--dataset-version", required=True)
        parser.add_argument("--release-version", required=True)
        parser.add_argument("--verified-at", required=True)

    def handle(self, *args, **options):
        verified_at = _parse_timestamp(options["verified_at"])
        if verified_at is None:
            raise CommandError("operational evidence timestamp is invalid")
        try:
            bundle = load_and_validate_rag_seed_manifest(options["manifest"])
            summary = build_legal_operational_evidence(
                bundle,
                dataset_version=options["dataset_version"],
                release_version=options["release_version"],
                verified_at=verified_at,
            )
        except RagSeedValidationError:
            raise CommandError("production RAG seed validation failed") from None
        except LegalOperationalEvidenceError as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(
            json.dumps(
                summary,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
