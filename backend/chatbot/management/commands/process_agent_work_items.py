"""Run queued agent work items once."""

from __future__ import annotations

import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from chatbot.repositories import process_agent_work_items


class Command(BaseCommand):
    help = "Process queued agent work items once."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Maximum number of queued work items to process.",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep polling for queued work items until interrupted.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=int,
            default=getattr(settings, "AGENT_WORKER_LOOP_SLEEP_SECONDS", 5),
            help="Sleep interval between polling loops.",
        )
        parser.add_argument(
            "--max-loops",
            type=int,
            default=0,
            help="Stop after this many polling loops. Zero means no loop limit.",
        )
        parser.add_argument(
            "--stale-after-seconds",
            type=int,
            default=getattr(settings, "AGENT_WORKER_STALE_AFTER_SECONDS", 900),
            help="Requeue RUNNING work items locked longer than this value.",
        )

    def handle(self, *args, **options):
        loop = bool(options["loop"])
        max_loops = max(0, int(options["max_loops"] or 0))
        sleep_seconds = max(1, int(options["sleep_seconds"] or 1))
        iteration = 0

        while True:
            iteration += 1
            result = process_agent_work_items(
                limit=options["limit"],
                stale_after_seconds=options["stale_after_seconds"],
            )
            result["loop_iteration"] = iteration
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))

            if not loop or (max_loops and iteration >= max_loops):
                break
            time.sleep(sleep_seconds)
