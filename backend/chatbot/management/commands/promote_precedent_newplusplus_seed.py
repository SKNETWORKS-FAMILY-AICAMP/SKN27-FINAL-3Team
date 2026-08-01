"""Promote a verified precedent NEW++ seed using compare-and-swap."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.seed_integrity import (
    SeedIntegrityError,
    promote_seed,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.db import (
    connect_database,
)
from etl.fault_cases.src.traffic_precedents.precedent_search.newplusplus.errors import (
    SearchStageError,
)


class Command(BaseCommand):
    help = "Atomically promote a staged precedent NEW++ seed."

    def add_arguments(self, parser):
        parser.add_argument("--seed-version", required=True)
        parser.add_argument("--expected-active-seed-version", required=True)
        parser.add_argument("--format", choices=["json"], default="json")

    def handle(self, *args, **options):
        expected = str(options["expected_active_seed_version"] or "").strip()
        expected_active = None if expected.lower() == "none" else expected
        try:
            result = promote_seed(
                seed_version=str(options["seed_version"] or "").strip(),
                expected_active_seed_version=expected_active,
                connection_factory=connect_database,
            )
        except (SeedIntegrityError, SearchStageError) as exc:
            raise CommandError(f"precedent seed promotion failed ({exc.code})") from None
        except Exception:
            raise CommandError(
                "precedent seed promotion failed; inspect private runtime logs"
            ) from None
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
