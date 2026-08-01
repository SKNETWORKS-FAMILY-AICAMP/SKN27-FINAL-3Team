"""Stage the tracked provider-free precedent NEW++ bootstrap."""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.seed_integrity import (
    SeedIntegrityError,
    stage_seed,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.db import (
    connect_database,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.errors import (
    SearchStageError,
)


DEFAULT_EMBEDDINGS = Path(
    "etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/"
    "01_document_embeddings_qwen3_4b.npy"
)
DEFAULT_METADATA = Path(
    "etl/fault_cases/bootstrap/precedent/qwen3_4b_bge_v1/"
    "02_document_embedding_metadata.jsonl"
)


class Command(BaseCommand):
    help = "Validate and stage the immutable precedent NEW++ bootstrap."

    def add_arguments(self, parser):
        parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
        parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
        parser.add_argument("--format", choices=["json"], default="json")

    def handle(self, *args, **options):
        try:
            result = stage_seed(
                embeddings_path=options["embeddings"],
                metadata_path=options["metadata"],
                connection_factory=connect_database,
            )
        except (SeedIntegrityError, SearchStageError) as exc:
            raise CommandError(f"precedent seed staging failed ({exc.code})") from None
        except (OSError, ValueError):
            raise CommandError("precedent seed staging input verification failed") from None
        except Exception:
            raise CommandError(
                "precedent seed staging failed; inspect private runtime logs"
            ) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
