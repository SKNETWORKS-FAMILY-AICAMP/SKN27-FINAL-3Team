"""Read-only exact verification for a precedent NEW++ seed."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.seed_integrity import (
    SeedIntegrityError,
    verify_seed,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.db import (
    connect_database,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.errors import (
    SearchStageError,
)


class Command(BaseCommand):
    help = "Verify one precedent NEW++ seed without changing database state."

    def add_arguments(self, parser):
        parser.add_argument("--expected-seed-version", required=True)
        parser.add_argument("--format", choices=["json"], default="json")

    def handle(self, *args, **options):
        try:
            result = verify_seed(
                expected_seed_version=str(
                    options["expected_seed_version"] or ""
                ).strip(),
                connection_factory=connect_database,
            )
        except (SeedIntegrityError, SearchStageError) as exc:
            raise CommandError(f"precedent seed verification failed ({exc.code})") from None
        except Exception:
            raise CommandError(
                "precedent seed verification failed; inspect private runtime logs"
            ) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
