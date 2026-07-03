"""Smoke test the optional Supervisor LLM planner boundary."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from app.services.chatbot_mock_service import submit_message
from app.services.supervisor_llm_service import validate_slot_filling_state


class Command(BaseCommand):
    help = "Run a safe Supervisor LLM smoke test without printing secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-text",
            default="어린이보호구역 앞에서 아이가 갑자기 아파 비상 정차했고 과태료 고지서를 받았습니다.",
            help="User text for the smoke conversation.",
        )
        parser.add_argument("--scenario", default="fine_notice", help="Mock scenario to route through Supervisor.")
        parser.add_argument("--session-id", default="ses_supervisor_llm_smoke", help="Smoke session id.")
        parser.add_argument(
            "--require-used",
            action="store_true",
            help="Fail unless both Supervisor conversation and planner report llm status 'used'.",
        )
        parser.add_argument(
            "--require-slot-state",
            action="store_true",
            help="Fail unless slot_filling_state.v1 is present and valid in ready Agent packages.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        response = submit_message(
            {
                "session_id": options["session_id"],
                "user_text": options["user_text"],
                "mock_scenario": options["scenario"],
                "mock_status": "success",
            }
        )
        supervisor_state = response.get("supervisor_state") or {}
        analysis_plan = response.get("analysis_plan") or {}
        supervisor_llm = supervisor_state.get("llm") or {}
        planner_llm = analysis_plan.get("llm_planner") or {}
        slot_validation = validate_slot_filling_state(supervisor_state, analysis_plan)
        result = {
            "contract_version": "supervisor_llm_smoke.v1",
            "status": "pass",
            "supervisor_llm": _safe_llm_metadata(supervisor_llm),
            "planner_llm": _safe_llm_metadata(planner_llm),
            "slot_state": slot_validation,
            "supervisor_stage": supervisor_state.get("stage"),
            "plan_step_count": len(analysis_plan.get("steps") or []),
            "ready_agent_count": len(
                [
                    item
                    for item in supervisor_state.get("agent_input_packages", [])
                    if isinstance(item, dict) and item.get("status") == "ready"
                ]
            ),
        }

        if options["require_used"] and (
            result["supervisor_llm"]["status"] != "used"
            or result["planner_llm"]["status"] != "used"
        ):
            result["status"] = "fail"
        if options["require_slot_state"] and not slot_validation["valid"]:
            result["status"] = "fail"

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] == "fail":
            raise CommandError("Supervisor LLM smoke failed.")


def _safe_llm_metadata(metadata: dict) -> dict:
    return {
        "status": metadata.get("status"),
        "reason": metadata.get("reason"),
        "provider": metadata.get("provider"),
        "model": metadata.get("model"),
    }


def _text_result(result: dict) -> str:
    return "\n".join(
        [
            f"Supervisor LLM smoke: {result['status']}",
            f"- supervisor_llm: {result['supervisor_llm'].get('status')} ({result['supervisor_llm'].get('reason')})",
            f"- planner_llm: {result['planner_llm'].get('status')} ({result['planner_llm'].get('reason')})",
            f"- slot_state: {result['slot_state'].get('valid')} ({result['slot_state'].get('slot_contract_version')})",
            f"- supervisor_stage: {result.get('supervisor_stage')}",
            f"- plan_step_count: {result.get('plan_step_count')}",
            f"- ready_agent_count: {result.get('ready_agent_count')}",
        ]
    )
