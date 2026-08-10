"""Smoke test demo persona flows before real Agent adapters are connected."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from app.mock_runtime.chat import submit_message
from app.services.persona_catalog_service import get_demo_persona, list_demo_personas


class Command(BaseCommand):
    help = "Run demo persona mock-contract flows and verify expected nodes."

    def add_arguments(self, parser):
        parser.add_argument("--persona-id", default="", help="Run one persona id instead of the full catalog.")
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        persona_id = options["persona_id"].strip()
        personas = [_summary_from_config(get_demo_persona(persona_id))] if persona_id else list_demo_personas()
        personas = [persona for persona in personas if persona]
        if persona_id and not personas:
            raise CommandError(f"Unknown persona id: {persona_id}")

        runs = [_run_persona(persona) for persona in personas]
        result = {
            "contract_version": "persona_catalog_smoke.v1",
            "status": "pass" if all(run["status"] == "pass" for run in runs) else "fail",
            "persona_count": len(runs),
            "runs": runs,
        }

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] == "fail":
            raise CommandError("Persona catalog smoke failed.")


def _summary_from_config(config: dict | None) -> dict:
    if not config:
        return {}
    return {
        "persona_id": config["persona"]["persona_id"],
        "name": config["persona"]["name"],
        "role": config["persona"]["role"],
        "case_type": config["persona"]["case_type"],
        "scenario": config["scenario"],
        "routing_intent": config["routing_intent"],
        "stage": config["stage"],
        "sample_user_text": config["sample_user_text"],
        "expected_nodes": list(config["expected_nodes"]),
        "report_action_ready": bool(config.get("report_action_ready")),
    }


def _run_persona(persona: dict) -> dict:
    response = submit_message(
        {
            "session_id": f"ses_smoke_{persona['persona_id']}",
            "user_text": persona["sample_user_text"],
            "persona_id": persona["persona_id"],
        }
    )
    expected_nodes = set(persona["expected_nodes"])
    plan_nodes = {step.get("node_code") for step in response.get("analysis_plan", {}).get("steps", [])}
    missing_nodes = sorted(expected_nodes - plan_nodes)
    report_ready = bool(response.get("report_links"))
    status = "pass"
    failures = []
    if response.get("status") != "success":
        failures.append("response_not_success")
    if response.get("mock_scenario") != persona["scenario"]:
        failures.append("scenario_mismatch")
    if response.get("routing_intent") != persona["routing_intent"]:
        failures.append("routing_intent_mismatch")
    if missing_nodes:
        failures.append("missing_expected_nodes")
    if report_ready != persona["report_action_ready"]:
        failures.append("report_action_boundary_mismatch")
    if failures:
        status = "fail"

    return {
        "persona_id": persona["persona_id"],
        "scenario": response.get("mock_scenario"),
        "routing_intent": response.get("routing_intent"),
        "stage": response.get("persona_run", {}).get("stage"),
        "status": status,
        "failures": failures,
        "missing_nodes": missing_nodes,
        "plan_node_count": len(plan_nodes),
        "report_action_ready": report_ready,
    }


def _text_result(result: dict) -> str:
    lines = [
        f"Persona catalog smoke: {result['status']}",
        f"- persona_count: {result['persona_count']}",
    ]
    for run in result["runs"]:
        lines.append(
            f"- {run['persona_id']}: {run['status']} "
            f"scenario={run['scenario']} stage={run['stage']} nodes={run['plan_node_count']}"
        )
        if run["failures"]:
            lines.append(f"  failures={','.join(run['failures'])}")
        if run["missing_nodes"]:
            lines.append(f"  missing_nodes={','.join(run['missing_nodes'])}")
    return "\n".join(lines)
