"""Process pending uploaded file scan records."""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand

from chatbot.file_scan_service import process_uploaded_file_scans


class Command(BaseCommand):
    help = "Run the configured file scan policy over pending uploaded_files rows."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20, help="Maximum rows to process. Use 0 for no limit.")
        parser.add_argument("--format", choices=["text", "json"], default="text")
        parser.add_argument("--loop", action="store_true", help="Keep polling until interrupted.")
        parser.add_argument("--sleep-seconds", type=int, default=5, help="Polling delay when --loop is set.")
        parser.add_argument("--max-loops", type=int, default=0, help="Stop after N loops; zero has no limit.")

    def handle(self, *args, **options):
        loop = bool(options["loop"])
        max_loops = max(0, int(options["max_loops"] or 0))
        sleep_seconds = max(1, int(options["sleep_seconds"] or 1))
        iteration = 0

        while True:
            iteration += 1
            result = process_uploaded_file_scans(limit=options["limit"])
            result["loop_iteration"] = iteration
            self._write_result(result, output_format=options["format"])

            if not loop or (max_loops and iteration >= max_loops):
                break
            time.sleep(sleep_seconds)

    def _write_result(self, result, *, output_format):
        if output_format == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return

        self.stdout.write(
            "File scan batch: "
            f"{result['status']} processed={result['processed']} "
            f"clean={result['clean']} rejected={result['rejected']}"
        )
        for item in result["results"]:
            self.stdout.write(
                f"- {item['attachment_id']}: {item['status']} "
                f"findings={len(item['findings'])}"
            )
