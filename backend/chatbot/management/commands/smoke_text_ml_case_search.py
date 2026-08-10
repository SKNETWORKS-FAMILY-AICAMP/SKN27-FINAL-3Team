"""Smoke test the text_ml_case_search sync adapter and pgvector retrieval path."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from app.services.agent_node_service import execute_agent_node


class Command(BaseCommand):
    help = "Run a safe text_ml_case_search sync smoke test without printing secrets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-text",
            default=(
                "A car going straight was hit by another car entering from the right side "
                "at an uncontrolled intersection."
            ),
            help="Accident description used as the text ML case-search query.",
        )
        parser.add_argument("--session-id", default="ses_text_ml_case_search_smoke", help="Smoke session id.")
        parser.add_argument("--message-id", default="msg_text_ml_case_search_smoke", help="Smoke message id.")
        parser.add_argument("--job-id", default="job_text_ml_case_search_smoke", help="Smoke job id.")
        parser.add_argument(
            "--require-pgvector",
            action="store_true",
            help="Fail unless the adapter reports unified pgvector retrieval.",
        )
        parser.add_argument(
            "--require-results",
            action="store_true",
            help="Fail unless pgvector-backed similar cases and recommended evidence are returned.",
        )
        parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format.")

    def handle(self, *args, **options):
        execution = execute_agent_node(
            {
                "node_code": "text_ml_case_search",
                "execution_mode": "sync",
                "session_id": options["session_id"],
                "message_id": options["message_id"],
                "job_id": options["job_id"],
                "user_text": options["user_text"],
            }
        )
        agent_output = execution.get("agent_output") if isinstance(execution.get("agent_output"), dict) else {}
        structured_result = (
            agent_output.get("structured_result")
            if isinstance(agent_output.get("structured_result"), dict)
            else {}
        )
        retrieval = structured_result.get("retrieval") if isinstance(structured_result.get("retrieval"), dict) else {}
        limitations = [str(item) for item in agent_output.get("limitations") or [] if str(item)]
        pgvector_rag_enabled = retrieval.get("backend") == "unified_pgvector"
        pgvector_rag_unavailable = any(
            "pgvector" in item.lower() and "unavailable" in item.lower()
            for item in limitations
        )
        similar_cases = structured_result.get("similar_cases")
        recommended_evidence = structured_result.get("recommended_evidence")
        result = {
            "contract_version": "text_ml_case_search_smoke.v1",
            "status": "pass",
            "execution_mode": execution.get("execution_mode"),
            "adapter_execution_mode": (execution.get("adapter_context") or {}).get("execution_mode"),
            "agent_status": agent_output.get("status"),
            "adapter_source": retrieval.get("adapter_source"),
            "retrieval_backend": retrieval.get("backend"),
            "ratio_range_label": structured_result.get("ratio_range_label"),
            "similar_case_count": len(similar_cases) if isinstance(similar_cases, list) else 0,
            "recommended_evidence_count": len(recommended_evidence) if isinstance(recommended_evidence, list) else 0,
            "pgvector_rag_enabled": pgvector_rag_enabled,
            "pgvector_rag_unavailable": pgvector_rag_unavailable,
            "limitations": limitations[:5],
        }

        if execution.get("execution_mode") != "sync":
            result["status"] = "fail"
        if agent_output.get("status") not in {"success", "partial"}:
            result["status"] = "fail"
        if retrieval.get("adapter_source") != "fault_ratio_knowledge_agent":
            result["status"] = "fail"
        if options.get("require_pgvector", False) and not pgvector_rag_enabled:
            result["status"] = "fail"
        if options.get("require_results") and (
            result["similar_case_count"] < 1 or result["recommended_evidence_count"] < 1
        ):
            result["status"] = "fail"

        if options["format"] == "json":
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
        else:
            self.stdout.write(_text_result(result))

        if result["status"] == "fail":
            raise CommandError("text_ml_case_search smoke failed.")


def _text_result(result: dict) -> str:
    return "\n".join(
        [
            f"text_ml_case_search smoke: {result['status']}",
            f"- execution_mode: {result.get('execution_mode')}",
            f"- adapter_execution_mode: {result.get('adapter_execution_mode')}",
            f"- agent_status: {result.get('agent_status')}",
            f"- adapter_source: {result.get('adapter_source')}",
            f"- retrieval_backend: {result.get('retrieval_backend')}",
            f"- ratio_range_label: {result.get('ratio_range_label')}",
            f"- similar_case_count: {result.get('similar_case_count')}",
            f"- recommended_evidence_count: {result.get('recommended_evidence_count')}",
            f"- pgvector_rag_enabled: {result.get('pgvector_rag_enabled')}",
            f"- pgvector_rag_unavailable: {result.get('pgvector_rag_unavailable')}",
        ]
    )
