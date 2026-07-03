"""Check production readiness for the canonical Django runtime."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from chatbot.readiness import FAIL, build_production_readiness_report


class Command(BaseCommand):
    help = "Validate production readiness settings without calling external services."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-database",
            action="store_true",
            help="Skip live database table introspection checks.",
        )
        parser.add_argument(
            "--format",
            choices=["json", "text"],
            default="json",
            help="Output format.",
        )
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Return a non-zero exit code when any check fails.",
        )

    def handle(self, *args, **options):
        report = build_production_readiness_report(
            include_database=not options["skip_database"],
        )
        if options["format"] == "json":
            self.stdout.write(json.dumps(report, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_report(report))

        if options["fail_on_error"] and report["status"] == FAIL:
            raise CommandError("Production readiness checks failed.")


def _text_report(report: dict) -> str:
    lines = [
        f"Production readiness: {report['status']}",
        f"Summary: pass={report['summary']['pass']} warn={report['summary']['warn']} fail={report['summary']['fail']}",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['name']}: {check['status']}")
        for detail in check["details"]:
            lines.append(f"  [{detail['status']}] {detail['message']}")
    return "\n".join(lines)
