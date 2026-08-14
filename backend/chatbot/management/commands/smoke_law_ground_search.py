"""Smoke test the law_ground_search sync adapter and optional legal RAG path."""

from __future__ import annotations

import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from app.services.agent_node_service import execute_agent_node


class Command(BaseCommand):
    help = "Run a safe law_ground_search sync smoke test without printing secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-text",
            default="Find the legal ground for a road traffic signal violation.",
            help="User-visible text associated with the legal ground query.",
        )
        parser.add_argument(
            "--search-query",
            default="road traffic signal violation article 5",
            help="Search query passed to the law_ground_search adapter context.",
        )
        parser.add_argument("--effective-at", default=date.today().isoformat(), help="YYYY-MM-DD legal basis date.")
        parser.add_argument("--session-id", default="ses_law_ground_search_smoke", help="Smoke session id.")
        parser.add_argument("--message-id", default="msg_law_ground_search_smoke", help="Smoke message id.")
        parser.add_argument("--job-id", default="job_law_ground_search_smoke", help="Smoke job id.")
        parser.add_argument(
            "--require-results",
            action="store_true",
            help="Fail unless at least one legal provision is returned.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        execution = execute_agent_node(
            {
                "node_code": "law_ground_search",
                "execution_mode": "sync",
                "session_id": options["session_id"],
                "message_id": options["message_id"],
                "job_id": options["job_id"],
                "user_text": options["user_text"],
                "context": {
                    "query": {
                        "raw_text": options["search_query"],
                        "search_query": options["search_query"],
                    },
                    "temporal_basis": {
                        "mode": "as_of",
                        "effective_at": options["effective_at"],
                    },
                    "scope": {"jurisdiction": "KR"},
                },
            }
        )
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        structured_result = (
            agent_output.get("structured_result")
            if isinstance(agent_output.get("structured_result"), dict)
            else {}
        )
        law_provisions = structured_result.get("law_provisions")
        evidence = agent_output.get("evidence")
        limitations = [str(item) for item in agent_output.get("limitations") or [] if str(item)]
        law_provision_count = len(law_provisions) if isinstance(law_provisions, list) else 0
        evidence_count = len(evidence) if isinstance(evidence, list) else 0
        result = {
            "contract_version": "law_ground_search_smoke.v1",
            "status": "pass",
            "execution_mode": execution.get("execution_mode"),
            "adapter_execution_mode": (execution.get("adapter_context") or {}).get("execution_mode"),
            "agent_status": agent_output.get("status"),
            "execution_status": agent_output.get("execution_status"),
            "law_provision_count": law_provision_count,
            "evidence_count": evidence_count,
            "limitations": limitations[:5],
        }

        if execution.get("execution_mode") != "sync":
            result["status"] = "fail"
        if agent_output.get("status") == "failed":
            result["status"] = "fail"
        if options["require_results"] and law_provision_count < 1:
            result["status"] = "fail"

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] == "fail":
            raise CommandError("law_ground_search smoke failed.")


def _text_result(result: dict) -> str:
    return "\n".join(
        [
            f"law_ground_search smoke: {result['status']}",
            f"- execution_mode: {result.get('execution_mode')}",
            f"- adapter_execution_mode: {result.get('adapter_execution_mode')}",
            f"- agent_status: {result.get('agent_status')}",
            f"- execution_status: {result.get('execution_status')}",
            f"- law_provision_count: {result.get('law_provision_count')}",
            f"- evidence_count: {result.get('evidence_count')}",
        ]
    )
