"""Process pending uploaded file scan records."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from chatbot.file_scan_service import process_uploaded_file_scans


class Command(BaseCommand):
    help = "Run the configured file scan policy over pending uploaded_files rows."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20, help="Maximum rows to process. Use 0 for no limit.")
        parser.add_argument("--format", choices=["text", "json"], default="text")

    def handle(self, *args, **options):
        result = process_uploaded_file_scans(limit=options["limit"])
        if options["format"] == "json":
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
