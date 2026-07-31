"""Emit privacy-safe operational health snapshots for local or CloudWatch logs."""

from __future__ import annotations

from datetime import timezone as datetime_timezone
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from app.services.operational_health_gate import evaluate_operational_health_gate
from chatbot.operational_observability import (
    HEALTH_CONTRACT_VERSION,
    build_operational_health_snapshot,
)


class Command(BaseCommand):
    help = "Emit one or repeated operational_health.v1 JSON snapshots."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--once",
            action="store_true",
            help="Emit one snapshot and exit (default).",
        )
        mode.add_argument(
            "--loop",
            action="store_true",
            help="Emit snapshots until interrupted.",
        )
        parser.add_argument(
            "--gate-mode",
            choices=("transaction", "acceptance"),
            help="Evaluate the snapshot for a release transaction or acceptance window.",
        )
        parser.add_argument(
            "--interval-seconds",
            type=int,
            default=getattr(settings, "OPERATIONAL_HEALTH_INTERVAL_SECONDS", 60),
        )
        parser.add_argument(
            "--window-minutes",
            type=int,
            default=getattr(settings, "OPERATIONAL_HEALTH_WINDOW_MINUTES", 15),
        )
        parser.add_argument(
            "--queue-age-warn-seconds",
            type=int,
            default=getattr(settings, "OPERATIONAL_QUEUE_AGE_WARN_SECONDS", 300),
        )
        parser.add_argument(
            "--lease-stale-seconds",
            type=int,
            default=getattr(settings, "OPERATIONAL_LEASE_STALE_SECONDS", 300),
        )
        parser.add_argument(
            "--legal-max-age-hours",
            type=int,
            default=getattr(settings, "OPERATIONAL_LEGAL_MAX_AGE_HOURS", 168),
        )

    def handle(self, *args, **options):
        del args
        self._validate_options(options)
        while True:
            snapshot = self._snapshot(options)
            gate_mode = options.get("gate_mode")
            if gate_mode:
                snapshot = dict(snapshot)
                snapshot["gate"] = evaluate_operational_health_gate(
                    snapshot,
                    expected_dataset_version=getattr(
                        settings,
                        "LEGAL_DATASET_VERSION",
                        "",
                    ),
                    expected_release_version=getattr(
                        settings,
                        "APP_RELEASE_VERSION",
                        "",
                    ),
                    mode=gate_mode,
                )
            self.stdout.write(
                json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            if snapshot.get("gate", {}).get("decision") == "fail":
                raise CommandError("operational health gate rejected snapshot")
            if not options["loop"]:
                return
            try:
                time.sleep(options["interval_seconds"])
            except KeyboardInterrupt:
                return

    def _snapshot(self, options) -> dict:
        try:
            return build_operational_health_snapshot(
                window_minutes=options["window_minutes"],
                queue_age_warn_seconds=options["queue_age_warn_seconds"],
                lease_stale_seconds=options["lease_stale_seconds"],
                legal_run_summary_path=getattr(
                    settings,
                    "OPERATIONAL_LEGAL_RUN_SUMMARY_PATH",
                    "",
                ),
                legal_max_age_hours=options["legal_max_age_hours"],
                legal_required_sources=list(
                    getattr(
                        settings,
                        "OPERATIONAL_LEGAL_REQUIRED_SOURCES",
                        [],
                    )
                ),
                legal_expected_dataset_version=getattr(
                    settings,
                    "LEGAL_DATASET_VERSION",
                    "",
                ),
                legal_expected_release_version=getattr(
                    settings,
                    "APP_RELEASE_VERSION",
                    "",
                ),
            )
        except Exception:  # The monitor must emit only a stable safe failure.
            return _safe_failure_snapshot()

    def _validate_options(self, options) -> None:
        if options.get("gate_mode") and options["loop"]:
            raise CommandError("--gate-mode cannot be combined with --loop")
        if options["interval_seconds"] < 10:
            raise CommandError("--interval-seconds must be at least 10")
        for name in (
            "window_minutes",
            "queue_age_warn_seconds",
            "lease_stale_seconds",
            "legal_max_age_hours",
        ):
            if options[name] <= 0:
                cli_name = name.replace("_", "-")
                raise CommandError(f"--{cli_name} must be greater than zero")


def _safe_failure_snapshot() -> dict:
    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "event_type": "operational_health",
        "observed_at": timezone.now()
        .astimezone(datetime_timezone.utc)
        .isoformat(),
        "status": "fail",
        "queue": {
            "queued_count": 0,
            "oldest_queued_age_seconds": 0,
            "running_count": 0,
            "stale_running_count": 0,
        },
        "worker": {
            "retrying_count": 0,
            "recent_failure_count": 0,
            "recent_timeout_count": 0,
        },
        "providers": {
            "recent_failure_count": 0,
            "roles": {},
        },
        "legal_data": {
            "status": "invalid",
            "missing_source_count": 0,
            "failed_source_count": 0,
            "stale_source_count": 0,
            "issue_count": 1,
        },
        "alerts": [
            {
                "code": "monitor_configuration_invalid",
                "severity": "critical",
            }
        ],
    }
