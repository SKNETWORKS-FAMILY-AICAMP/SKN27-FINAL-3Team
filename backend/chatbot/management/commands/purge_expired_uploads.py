"""Delete expired upload objects and scrub their database records."""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from chatbot.file_retention_service import purge_expired_uploads


class Command(BaseCommand):
    help = "Delete expired clean/quarantine objects and scrub uploaded_files tombstones."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--format", choices=["text", "json"], default="text")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval-seconds", type=int, default=60)
        parser.add_argument("--max-loops", type=int, default=0)
        parser.add_argument("--fail-on-error", action="store_true")

    def handle(self, *args, **options):
        loop = bool(options["loop"])
        max_loops = max(0, int(options["max_loops"] or 0))
        interval_seconds = max(1, int(options["interval_seconds"] or 1))
        iteration = 0

        while True:
            iteration += 1
            result = purge_expired_uploads(
                limit=options["limit"],
                dry_run=bool(options["dry_run"]),
            )
            result["loop_iteration"] = iteration
            self._write_result(result, output_format=options["format"])
            if options["fail_on_error"] and result["retryable"] and not loop:
                raise CommandError("expired upload purge has retryable failures")
            if not loop or (max_loops and iteration >= max_loops):
                break
            time.sleep(interval_seconds)

    def _write_result(self, result, *, output_format):
        if output_format == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return
        self.stdout.write(
            "Expired upload purge: "
            f"{result['status']} selected={result['selected']} "
            f"purged={result['purged']} retryable={result['retryable']} "
            f"skipped={result['skipped']} dry_run={result['dry_run']}"
        )
