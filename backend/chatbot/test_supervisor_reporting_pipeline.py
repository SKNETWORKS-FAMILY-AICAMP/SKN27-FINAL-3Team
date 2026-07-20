from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from chatbot import repositories as repository_module
from django.db import connection
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone

from chatbot.case_repository import confirm_case_facts, start_case_analysis
from chatbot.models import (
    AgentInvocation,
    AgentResult,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisDisplayResult,
    AnalysisJob,
    AnalysisJobStatus,
    Case,
    CaseStatus,
    ChatSession,
    ChatSessionStatus,
    ConfirmedFactVersion,
    Report,
    ReportStatus,
    ReportType,
    RetrievalEvent,
    UploadedFile,
    UploadedFileStatus,
)
from chatbot.repositories import (
    authorize_report_download_metadata,
    enqueue_analysis_job_work,
    get_analysis_job_record,
    get_report_access_metadata,
    get_report_download_metadata,
    get_report_record_detail,
    list_report_records,
    mark_conversation_save_state,
    persist_analysis_reporting_bundle,
    process_agent_work_item,
    ReportReferenceError,
)


ANALYSIS_NODES = (
    "fine_notice_analysis",
    "law_ground_search",
    "appeal_decision_flow",
)
REPORTING_NODE = "objection_report_generation"


def _queued_work(*, suffix: str) -> tuple[dict, dict]:
    owner_id = f"usr_reporting_{suffix}"
    session_id = f"ses_reporting_{suffix}"
    job_id = f"job_reporting_{suffix}"
    plan_id = f"plan_reporting_{suffix}"
    ChatSession.objects.create(
        session_id=session_id,
        owner_id=owner_id,
        status=ChatSessionStatus.ACTIVE,
    )
    steps = []
    previous = None
    for order, node_code in enumerate((*ANALYSIS_NODES, REPORTING_NODE), start=1):
        steps.append(
            {
                "order": order,
                "node_code": node_code,
                "status": "ready",
                "execution_mode": "sync",
                "depends_on": [previous] if previous else [],
            }
        )
        previous = node_code
    payload = {
        "owner_id": owner_id,
        "user_id": owner_id,
        "session_id": session_id,
        "user_text": "confirmed facts for a fine notice objection",
        "context": {"user_facts": "confirmed persisted facts"},
    }
    job_payload = {
        "job_id": job_id,
        "session_id": session_id,
        "message_id": f"msg_reporting_{suffix}",
        "routing_intent": "fine_notice_objection",
        "status": "queued",
        "active_node": ANALYSIS_NODES[0],
        "progress_message": "Analysis queued.",
        "analysis_plan_id": plan_id,
        "analysis_plan": {
            "contract_version": "analysis_plan.v2",
            "plan_id": plan_id,
            "session_id": session_id,
            "message_id": f"msg_reporting_{suffix}",
            "routing_intent": "fine_notice_objection",
            "steps": steps,
        },
        "chat_response": {},
        "node_execution": {},
    }
    return enqueue_analysis_job_work(payload, job_payload), payload


def _agent_output(node_code: str, *, status: str = "success") -> dict:
    structured_by_node = {
        "fine_notice_analysis": {
            "notice_fields": {
                "agency": "Persisted Traffic Agency",
                "violation_text": "persisted violation",
            }
        },
        "law_ground_search": {
            "matched_laws": [
                {
                    "law_name": "Road Traffic Act",
                    "article": "Article 1",
                    "summary": "persisted legal ground",
                    "source_reference": "law:1",
                }
            ],
            "retrieval": {
                "contract_version": "law_retrieval.v1",
                "status": "ready",
                "backend": "django_rag_tables",
                "attempted_backends": ["postgres_lexical", "django_rag_tables"],
            },
            "retrieval_quality": "django_rag_tables",
        },
        "text_ml_case_search": {
            "query_text": "confirmed intersection collision facts",
            "normalized_description": "ego straight, other vehicle left turn",
            "similar_cases": [
                {
                    "title": "Intersection left-turn collision",
                    "summary": "A comparable reviewed case candidate.",
                }
            ],
            "issue_tags": ["signal priority", "left turn"],
            "recommended_evidence": ["blackbox video"],
        },
        "appeal_decision_flow": {
            "judgment_status": "success",
            "overall_possibility": "medium",
            "guide": {"summary": "persisted guide"},
        },
        "vision_media_analysis": {
            "analysis_status": "unavailable",
        },
        "objection_report_generation": {
            "document_type": "objection_form",
            "document_variant": "fine_notice",
            "document_title": "Objection draft",
            "recipient_agency": "Persisted Traffic Agency",
            "case_summary": "Canonical persisted report summary",
            "requested_action": "Review the disposition",
            "objection_reasons": ["Persisted reason"],
            "legal_grounds": [{"source_reference": "law:1"}],
            "required_attachments": ["notice"],
            "form_sections": [{"title": "Facts", "body": "Persisted facts"}],
            "form_data": {"recipient": "Persisted Traffic Agency"},
            "document_readiness": {"ready_for_docx": True, "missing_field_details": []},
            "report_actions": [
                {
                    "type": "download_objection",
                    "label": "Objection DOCX download",
                    "document_type": "objection_form",
                    "document_format": "docx",
                }
            ],
            "appeal_decision": {"judgment_status": "success"},
            "appeal_gate": {"blocked": False, "reason": ""},
            "petition_purpose": "Review the disposition",
            "petition_reason": "Persisted reason",
            "drafting_source": "rule_based_fallback",
            "missing_fields": [],
            "readiness": {"ready_for_download": status == "success"},
            "oauth": {"access_token": "report-token-must-not-persist"},
            "debug_credentials": {
                "session_cookie": "report-cookie-must-not-persist",
                "storage_uri": "s3://private-report-bucket/private",
            },
        },
    }
    return {
        "job_id": None,
        "node_code": node_code,
        "node_name": node_code,
        "node_type": "agent",
        "owner": "test",
        "status": status,
        "execution_status": status,
        "summary": f"{node_code} {status}",
        "structured_result": structured_by_node[node_code],
        "evidence": [{"source_type": "test", "source_reference": node_code}],
        "next_actions": [],
        "limitations": [f"{node_code} limitation"] if status == "partial" else [],
        "created_at": "2026-07-14T00:00:00+00:00",
    }


def _node_execution(
    node_codes: tuple[str, ...],
    *,
    job_id: str,
    plan_id: str,
    statuses: dict[str, str] | None = None,
    reporting_handoff: dict | None = None,
) -> dict:
    statuses = statuses or {}
    executions = []
    counts: dict[str, int] = {}
    completed = []
    for order, node_code in enumerate(node_codes, start=1):
        status = statuses.get(node_code, "success")
        output = _agent_output(node_code, status=status)
        output["job_id"] = job_id
        if node_code == REPORTING_NODE and reporting_handoff:
            source = reporting_handoff["source"]
            output["structured_result"]["supervisor_handoff"] = {
                "contract_version": reporting_handoff["contract_version"],
                "handoff_id": reporting_handoff["handoff_id"],
                "gate_status": reporting_handoff["gate"]["status"],
                "source_fingerprint": source["fingerprint"],
                "source_result_ids": source["result_ids"],
            }
        executions.append(
            {
                "execution_id": f"exec_{job_id}_{node_code}",
                "execution_mode": "sync",
                "job_id": job_id,
                "node_code": node_code,
                "node": {
                    "node_code": node_code,
                    "node_name": node_code,
                    "node_type": "agent",
                    "owner": "test",
                    "status": "sync_adapter_ready",
                },
                "adapter_context": {"execution_mode": "sync"},
                "plan_step": {"order": order, "node_code": node_code},
                "agent_output": output,
            }
        )
        counts[status] = counts.get(status, 0) + 1
        if status == "success":
            completed.append(node_code)
    return {
        "execution_mode": "sync",
        "job_id": job_id,
        "plan_id": plan_id,
        "executions": executions,
        "status_counts": counts,
        "completed_node_codes": completed,
        "limitations": [],
    }


def _reporting_handoff_from_payload(payload: dict) -> dict | None:
    context = payload.get("context") if isinstance(payload, dict) else None
    handoff = context.get("supervisor_reporting_handoff") if isinstance(context, dict) else None
    return handoff if isinstance(handoff, dict) else None


def _ready_case_evidence_source(
    *,
    case: Case,
    owner_id: str,
    session: ChatSession,
    suffix: str,
) -> list[dict[str, str]]:
    attachment_id = f"att_reporting_evidence_{suffix}"
    UploadedFile.objects.create(
        attachment_id=attachment_id,
        owner_id=owner_id,
        session=session,
        case=case,
        purpose="supporting_evidence",
        file_type="pdf",
        original_filename=f"{attachment_id}.pdf",
        content_type="application/pdf",
        storage_uri=f"mock://reporting-evidence/{attachment_id}",
        status=UploadedFileStatus.READY.value,
        scan_status="passed",
    )
    return [{"source_type": "official_document", "source_ref": attachment_id}]


class SupervisorReportingPipelineTests(TestCase):
    def test_confirmed_case_worker_uses_real_reporting_adapter_and_creates_report(self) -> None:
        from app.services.agent_node_service import execute_agent_plan as real_execute_plan

        owner_id = "usr_reporting_confirmed_case"
        case = Case.objects.create(
            case_id="case_reporting_confirmed_case",
            owner_id=owner_id,
            title="Confirmed case Reporting",
            current_fact_version=1,
        )
        session = ChatSession.objects.create(
            session_id="ses_reporting_confirmed_case",
            owner_id=owner_id,
            case=case,
            status=ChatSessionStatus.ACTIVE,
        )
        fact_version = ConfirmedFactVersion.objects.create(
            fact_version_id="fact_reporting_confirmed_case",
            case=case,
            version_no=1,
            status="confirmed",
            facts={
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_left_turn",
                "signal_priority": "ego_green",
                "collision_location": "front_left",
            },
            sources=_ready_case_evidence_source(
                case=case,
                owner_id=owner_id,
                session=session,
                suffix="confirmed_case",
            ),
            conflicts=[],
            confirmed_by=owner_id,
            confirmed_at=timezone.now(),
        )
        queued = start_case_analysis(
            case.case_id,
            owner_id=owner_id,
            payload={"fact_version_id": fact_version.fact_version_id},
        )
        job_id = queued["job"]["job_id"]

        def execute_plan(plan, payload):
            case.refresh_from_db()
            self.assertEqual(case.status, CaseStatus.ANALYZING)
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            if node_codes == (REPORTING_NODE,):
                return real_execute_plan(plan, payload)
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id=queued["analysis_plan"]["plan_id"],
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item"]["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        report = Report.objects.get(job=job)
        case.refresh_from_db()
        self.assertEqual(result["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(report.report_type, "fault_ratio_analysis")
        self.assertEqual(report.status, ReportStatus.READY)
        self.assertEqual(report.source_fact_version, fact_version)
        self.assertEqual(case.status, CaseStatus.READY)
        self.assertEqual(case.current_report_version, 1)
        self.assertEqual(
            job.metadata["supervisor_reporting_handoff"]["target"]["report_type"],
            "fault_ratio_analysis",
        )
        self.assertIn(
            '"road_layout":"four_way_intersection"',
            job.metadata["supervisor_reporting_handoff"]["case_context"]["user_facts"],
        )
        self.assertEqual(job.metadata["report_links"][0]["report_id"], report.report_id)

    def test_new_confirmed_facts_cancel_a_queued_older_case_analysis(self) -> None:
        owner_id = "usr_reporting_superseded_case"
        case = Case.objects.create(
            case_id="case_reporting_superseded_case",
            owner_id=owner_id,
            title="Superseded case analysis",
        )
        session = ChatSession.objects.create(
            session_id="ses_reporting_superseded_case",
            owner_id=owner_id,
            case=case,
            status=ChatSessionStatus.ACTIVE,
        )
        fact_payload = {
            "facts": {
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_left_turn",
                "signal_priority": "ego_green",
                "collision_location": "front_left",
            },
            "sources": _ready_case_evidence_source(
                case=case,
                owner_id=owner_id,
                session=session,
                suffix="queued_superseded",
            ),
            "conflicts": [],
        }
        first_fact = confirm_case_facts(
            case.case_id,
            owner_id=owner_id,
            payload=fact_payload,
        )
        queued = start_case_analysis(
            case.case_id,
            owner_id=owner_id,
            payload={"fact_version_id": first_fact["fact_version_id"]},
        )
        second_fact = confirm_case_facts(
            case.case_id,
            owner_id=owner_id,
            payload={
                **fact_payload,
                "facts": {
                    **fact_payload["facts"],
                    "collision_location": "rear_left",
                },
            },
        )

        with patch("app.services.agent_node_service.execute_agent_plan") as execute_plan:
            result = process_agent_work_item(queued["work_item"]["work_item_id"])

        execute_plan.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "superseded_case_analysis")
        work_item = AgentWorkItem.objects.get(
            work_item_id=queued["work_item"]["work_item_id"]
        )
        job = AnalysisJob.objects.get(job_id=queued["job"]["job_id"])
        case.refresh_from_db()
        self.assertEqual(work_item.status, AgentWorkItemStatus.CANCELED)
        self.assertEqual(work_item.error_code, "superseded_case_analysis")
        self.assertEqual(job.status, AnalysisJobStatus.FAILED)
        self.assertEqual(case.status, CaseStatus.INTAKE)
        self.assertEqual(
            case.metadata["active_fact_version_id"],
            second_fact["fact_version_id"],
        )
        self.assertFalse(Report.objects.filter(job=job).exists())
        self.assertFalse(AnalysisDisplayResult.objects.filter(job=job).exists())

    def test_new_facts_before_paid_dispatch_cancel_without_agent_call(self) -> None:
        owner_id = "usr_reporting_predispatch_superseded"
        case = Case.objects.create(
            case_id="case_reporting_predispatch_superseded",
            owner_id=owner_id,
            title="Predispatch superseded case analysis",
        )
        session = ChatSession.objects.create(
            session_id="ses_reporting_predispatch_superseded",
            owner_id=owner_id,
            case=case,
            status=ChatSessionStatus.ACTIVE,
        )
        first_payload = {
            "facts": {
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_left_turn",
                "signal_priority": "ego_green",
                "collision_location": "front_left",
            },
            "sources": _ready_case_evidence_source(
                case=case,
                owner_id=owner_id,
                session=session,
                suffix="predispatch_superseded",
            ),
            "conflicts": [],
        }
        first_fact = confirm_case_facts(
            case.case_id,
            owner_id=owner_id,
            payload=first_payload,
        )
        queued = start_case_analysis(
            case.case_id,
            owner_id=owner_id,
            payload={"fact_version_id": first_fact["fact_version_id"]},
        )
        original_reserve = repository_module._reserve_paid_agent_phase_call

        def supersede_before_reserve(*args, **kwargs):
            confirm_case_facts(
                case.case_id,
                owner_id=owner_id,
                payload={
                    **first_payload,
                    "facts": {
                        **first_payload["facts"],
                        "collision_location": "rear_left",
                    },
                },
            )
            return original_reserve(*args, **kwargs)

        with (
            patch(
                "chatbot.repositories._reserve_paid_agent_phase_call",
                side_effect=supersede_before_reserve,
            ),
            patch("app.services.agent_node_service.execute_agent_plan") as execute_plan,
        ):
            result = process_agent_work_item(queued["work_item"]["work_item_id"])

        execute_plan.assert_not_called()
        work_item = AgentWorkItem.objects.get(
            work_item_id=queued["work_item"]["work_item_id"]
        )
        self.assertEqual(result["status"], AgentWorkItemStatus.CANCELED)
        self.assertEqual(work_item.status, AgentWorkItemStatus.CANCELED)
        self.assertEqual(work_item.error_code, "superseded_case_analysis")
        self.assertFalse(
            AgentInvocation.objects.filter(
                job__job_id=queued["job"]["job_id"],
                node_code="__paid_analysis_phase__",
            ).exists()
        )

    def test_new_facts_during_analysis_skip_reporting_and_final_case_write(self) -> None:
        owner_id = "usr_reporting_midrun_superseded"
        case = Case.objects.create(
            case_id="case_reporting_midrun_superseded",
            owner_id=owner_id,
            title="Mid-run superseded case analysis",
        )
        session = ChatSession.objects.create(
            session_id="ses_reporting_midrun_superseded",
            owner_id=owner_id,
            case=case,
            status=ChatSessionStatus.ACTIVE,
        )
        fact_payload = {
            "facts": {
                "road_layout": "four_way_intersection",
                "vehicle_actions": "ego_straight_other_left_turn",
                "signal_priority": "ego_green",
                "collision_location": "front_left",
            },
            "sources": _ready_case_evidence_source(
                case=case,
                owner_id=owner_id,
                session=session,
                suffix="midrun_superseded",
            ),
            "conflicts": [],
        }
        first_fact = confirm_case_facts(
            case.case_id,
            owner_id=owner_id,
            payload=fact_payload,
        )
        queued = start_case_analysis(
            case.case_id,
            owner_id=owner_id,
            payload={"fact_version_id": first_fact["fact_version_id"]},
        )
        analysis_calls: list[tuple[str, ...]] = []

        def execute_plan(plan, _payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            analysis_calls.append(node_codes)
            if node_codes == (REPORTING_NODE,):
                self.fail("superseded facts must stop before Reporting Agent execution")
            confirm_case_facts(
                case.case_id,
                owner_id=owner_id,
                payload={
                    **fact_payload,
                    "facts": {
                        **fact_payload["facts"],
                        "collision_location": "rear_left",
                    },
                },
            )
            return _node_execution(
                node_codes,
                job_id=queued["job"]["job_id"],
                plan_id=queued["analysis_plan"]["plan_id"],
            )

        with patch(
            "app.services.agent_node_service.execute_agent_plan",
            side_effect=execute_plan,
        ):
            result = process_agent_work_item(queued["work_item"]["work_item_id"])

        work_item = AgentWorkItem.objects.get(
            work_item_id=queued["work_item"]["work_item_id"]
        )
        job = AnalysisJob.objects.get(job_id=queued["job"]["job_id"])
        case.refresh_from_db()
        self.assertEqual(len(analysis_calls), 1)
        self.assertNotIn((REPORTING_NODE,), analysis_calls)
        self.assertEqual(result["status"], AgentWorkItemStatus.CANCELED)
        self.assertEqual(work_item.status, AgentWorkItemStatus.CANCELED)
        self.assertEqual(work_item.error_code, "superseded_case_analysis")
        self.assertEqual(job.status, AnalysisJobStatus.FAILED)
        self.assertEqual(case.status, CaseStatus.INTAKE)
        self.assertFalse(AgentResult.objects.filter(job=job, node_code=REPORTING_NODE).exists())
        self.assertFalse(Report.objects.filter(job=job).exists())
        self.assertFalse(AnalysisDisplayResult.objects.filter(job=job).exists())

    def test_canonical_reporting_plan_is_always_queued_for_persisted_handoff(self) -> None:
        steps = []
        previous = None
        for order, node_code in enumerate((*ANALYSIS_NODES, REPORTING_NODE), start=1):
            steps.append(
                {
                    "order": order,
                    "node_code": node_code,
                    "status": "ready",
                    "execution_mode": "sync",
                    "depends_on": [previous] if previous else [],
                }
            )
            previous = node_code

        from chatbot.views import run_agent_plan

        request = RequestFactory().post(
                "/api/agents/plans/run/",
                data={
                    "session_id": "ses_reporting_force_worker",
                    "user_text": "force Reporting through the persistence boundary",
                    "analysis_plan": {
                        "contract_version": "analysis_plan.v2",
                        "plan_id": "plan_reporting_force_worker",
                        "session_id": "ses_reporting_force_worker",
                        "steps": steps,
                    },
                },
                content_type="application/json",
            )
        with patch("chatbot.views.execute_agent_plan") as execute_plan:
            response = run_agent_plan(request)

        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["node_execution"]["status"], "queued")
        self.assertEqual(body["persistence"]["status"], AgentWorkItemStatus.QUEUED)
        execute_plan.assert_not_called()

    def test_worker_real_reporting_adapter_consumes_persisted_handoff(self) -> None:
        from app.services.agent_node_service import execute_agent_plan as real_execute_plan

        queued, _payload = _queued_work(suffix="real_reporting")
        job_id = queued["job_id"]

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            if node_codes == (REPORTING_NODE,):
                return real_execute_plan(plan, payload)
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_real_reporting",
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        reporting_result = AgentResult.objects.get(
            job__job_id=job_id,
            node_code=REPORTING_NODE,
        )
        handoff = AnalysisJob.objects.get(job_id=job_id).metadata[
            "supervisor_reporting_handoff"
        ]
        self.assertEqual(result["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(
            reporting_result.structured_result["supervisor_handoff"]["source_fingerprint"],
            handoff["source"]["fingerprint"],
        )
        self.assertEqual(
            reporting_result.structured_result["appeal_decision"]["overall_possibility"],
            "medium",
        )
        self.assertEqual(
            reporting_result.structured_result["adapter_trace"]["input_source"],
            "agent_input.context.supervisor_reporting_handoff",
        )
        download = get_report_download_metadata(
            f"rep_{job_id}",
            document_type="objection_form",
        )
        self.assertIn("Persisted Traffic Agency", download["text_body"])
        self.assertIn("confirmed persisted facts", download["text_body"])
        objection = get_report_download_metadata(
            f"rep_{job_id}",
            document_type="objection_form",
        )
        self.assertIn("Persisted Traffic Agency", objection["text_body"])
        self.assertIn("confirmed persisted facts", objection["text_body"])
        self.assertIn("Road Traffic Act", objection["text_body"])

    def test_worker_persists_analysis_before_reporting_and_finishes_bundle_first(self) -> None:
        queued, _payload = _queued_work(suffix="success")
        job_id = queued["job_id"]
        plan_id = "plan_reporting_success"
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            if node_codes == (REPORTING_NODE,):
                persisted = list(
                    AgentResult.objects.filter(job__job_id=job_id)
                    .order_by("raw_output__plan_step__order")
                    .values_list("node_code", flat=True)
                )
                self.assertEqual(persisted, list(ANALYSIS_NODES))
                handoff = payload["context"]["supervisor_reporting_handoff"]
                self.assertEqual(handoff["gate"]["status"], "ready")
                self.assertTrue(handoff["source"]["persisted"])
                self.assertEqual(
                    handoff["source"]["result_ids"],
                    list(
                        AgentResult.objects.filter(job__job_id=job_id)
                        .order_by("raw_output__plan_step__order")
                        .values_list("result_id", flat=True)
                    ),
                )
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id=plan_id,
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        from chatbot import repositories

        original_complete = repositories._complete_agent_work_item

        def complete_after_bundle(*args, **kwargs):
            self.assertTrue(AnalysisDisplayResult.objects.filter(job__job_id=job_id).exists())
            self.assertTrue(Report.objects.filter(job__job_id=job_id).exists())
            return original_complete(*args, **kwargs)

        with (
            patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan),
            patch("chatbot.repositories._complete_agent_work_item", side_effect=complete_after_bundle),
        ):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        report = Report.objects.get(job=job)
        display = AnalysisDisplayResult.objects.get(job=job)
        reporting_result = AgentResult.objects.get(job=job, node_code=REPORTING_NODE)
        self.assertEqual(calls, [ANALYSIS_NODES, (REPORTING_NODE,)])
        self.assertEqual(result["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(report.report_id, f"rep_{job_id}")
        self.assertEqual(report.status, ReportStatus.READY)
        self.assertEqual(report.storage_uri, "")
        self.assertEqual(report.content["contract_version"], "analysis_report.v1")
        self.assertEqual(
            report.content["reporting_payload"]["stage"],
            "agent_execution_ready",
        )
        self.assertEqual(
            report.content["reporting_payload"]["sections"][0]["items"],
            ["Persisted facts"],
        )
        self.assertEqual(
            [card["type"] for card in report.content["reporting_payload"]["document_cards"]],
            ["objection_draft", "fact_summary", "insurance_submission"],
        )
        self.assertNotIn(
            "download_report",
            [action["type"] for action in report.content["reporting_payload"]["report_actions"]],
        )
        self.assertEqual(
            report.content["reporting_payload"]["source"],
            "supervisor_agent_result_aggregation",
        )
        self.assertEqual(
            report.content["reporting_payload"]["provenance"]["handoff_id"],
            job.metadata["supervisor_reporting_handoff"]["handoff_id"],
        )
        self.assertEqual(report.content["source"]["reporting_result_id"], reporting_result.result_id)
        self.assertEqual(report.display_result, display)
        self.assertEqual(display.report_links[0]["report_id"], report.report_id)
        self.assertEqual(
            job.metadata["supervisor_reporting_handoff"]["source"]["fingerprint"],
            report.content["source"]["handoff_fingerprint"],
        )
        job_detail = get_analysis_job_record(job_id)
        self.assertEqual(
            job_detail["supervisor_reporting_handoff"]["handoff_id"],
            job.metadata["supervisor_reporting_handoff"]["handoff_id"],
        )
        self.assertEqual(job_detail["latest_report_id"], report.report_id)
        law_result = AgentResult.objects.get(job=job, node_code="law_ground_search")
        self.assertEqual(
            law_result.structured_result["retrieval"]["attempted_backends"],
            ["postgres_lexical", "django_rag_tables"],
        )
        law_api_result = next(
            item
            for item in job_detail["agent_results"]
            if item["node_code"] == "law_ground_search"
        )
        self.assertEqual(
            law_api_result["structured_result"]["retrieval"],
            law_result.structured_result["retrieval"],
        )
        law_supervisor_result = next(
            item
            for item in job_detail["supervisor_execution"]["node_results"]
            if item["node_code"] == "law_ground_search"
        )
        self.assertEqual(
            law_supervisor_result["structured_result"]["matched_laws"][0][
                "source_reference"
            ],
            "law:1",
        )
        retrieval_event = RetrievalEvent.objects.get(
            invocation__job=job,
            invocation__node_code="law_ground_search",
        )
        self.assertEqual(retrieval_event.source_refs, ["law:1"])
        self.assertEqual(retrieval_event.metadata["retrieval_status"], "ready")
        self.assertEqual(retrieval_event.metadata["retrieval_backend"], "django_rag_tables")
        self.assertEqual(
            retrieval_event.metadata["attempted_backends"],
            ["postgres_lexical", "django_rag_tables"],
        )
        self.assertEqual(job_detail["report_links"][0]["report_id"], report.report_id)
        report_detail = get_report_record_detail(report.report_id)
        self.assertEqual(report_detail["content"]["contract_version"], "analysis_report.v1")
        self.assertEqual(
            report_detail["content"]["source"]["reporting_result_id"],
            reporting_result.result_id,
        )
        self.assertEqual(
            report_detail["content"]["reporting_payload"].get("document_variant"),
            "fine_notice",
        )
        self.assertEqual(
            report_detail["content"]["reporting_payload"]["appeal_gate"],
            {"blocked": False, "reason": ""},
        )
        self.assertEqual(
            report_detail["content"]["reporting_payload"]["report_actions"][0]["document_format"],
            "docx",
        )
        download = get_report_download_metadata(
            report.report_id,
            document_type="objection_form",
        )
        self.assertEqual(download["storage_backend"], "database")
        self.assertEqual(download["object_storage"]["status"], "generated_on_demand")
        self.assertEqual(
            download["object_storage"]["filename"],
            f"{report.report_id}.docx",
        )
        self.assertEqual(
            download["object_storage"]["content_type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(download["storage_uri"], "")
        self.assertEqual(
            download["content_type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(download["filename"].endswith(".docx"))
        self.assertTrue(download["body"].startswith(b"PK"))
        self.assertNotIn("mock://", repr(download))
        from chatbot.views import download_report, report_detail

        identity = {
            "auth_context": {
                "user_id": "usr_reporting_success",
                "subject_type": "user",
            }
        }
        repository_module.confirm_report_document(
            report.report_id,
            owner_id="usr_reporting_success",
        )
        with patch("chatbot.views._request_access_payload", return_value=identity):
            detail_response = report_detail(
                RequestFactory().get(f"/api/reports/{report.report_id}/"),
                report.report_id,
            )
            download_response = download_report(
                RequestFactory().get(
                    f"/api/reports/{report.report_id}/download/?document_type=objection_form"
                ),
                report.report_id,
            )
        detail_body = json.loads(detail_response.content)
        self.assertEqual(detail_body["api_surface"], "canonical")
        self.assertEqual(detail_body["execution_mode"], "async_worker")
        self.assertEqual(download_response["X-API-Surface"], "canonical")
        self.assertEqual(download_response["X-Execution-Mode"], "async_worker")
        self.assertTrue(
            download_response["Content-Type"].startswith(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
        )

    def test_download_metadata_renders_official_docx_and_rejects_general_variant(self) -> None:
        variants = (
            (
                "rep_docx_fine",
                "fine_notice_objection",
                "objection_form",
                {
                    "document_variant": "fine_notice",
                    "form_data": {"recipient": "강남구청", "applicant_name": "홍길동"},
                    "petition_purpose": "처분의 재검토를 요청합니다.",
                    "petition_reason": "사실관계 확인이 필요합니다.",
                },
                "과태료 처분에 대한 이의신청서",
            ),
            (
                "rep_docx_traffic",
                "fault_ratio_analysis",
                "objection_form",
                {
                    "document_variant": "traffic_accident",
                    "form_data": {
                        "applicant_name": "김운전자",
                        "recipient": "서초경찰서",
                        "objection_points": "블랙박스 영상 재검토",
                    },
                },
                "블랙박스 영상 재검토",
            ),
            (
                "rep_docx_general",
                "fine_notice_objection",
                "report",
                {
                    "sections": [{"title": "핵심 분석", "items": ["분석 리포트 본문"]}],
                },
                "분석 리포트 본문",
            ),
        )

        for report_id, report_type, document_type, reporting_payload, expected_text in variants:
            report = Report.objects.create(
                report_id=report_id,
                owner_id="usr_docx_variants",
                report_type=report_type,
                status=ReportStatus.READY,
                title="DOCX variant report",
                content={"reporting_payload": reporting_payload},
            )

            download = get_report_download_metadata(report.report_id, document_type=document_type)

            if document_type == "report":
                self.assertIsNone(download)
                continue

            self.assertIsNotNone(download)
            self.assertEqual(
                download["content_type"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            self.assertTrue(download["filename"].endswith(".docx"))
            self.assertTrue(download["body"].startswith(b"PK"))
            with ZipFile(BytesIO(download["body"])) as docx_archive:
                document_xml = docx_archive.read("word/document.xml").decode("utf-8")
            self.assertIn(expected_text, document_xml)

    def test_partial_required_analysis_does_not_dispatch_reporting(self) -> None:
        queued, _payload = _queued_work(suffix="partial")
        job_id = queued["job_id"]
        plan_id = "plan_reporting_partial"
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            statuses = {"law_ground_search": "partial"} if node_codes == ANALYSIS_NODES else {}
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id=plan_id,
                statuses=statuses,
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        display = AnalysisDisplayResult.objects.get(job=job)
        self.assertEqual(calls, [ANALYSIS_NODES])
        self.assertEqual(result["job_status"], AnalysisJobStatus.PARTIAL)
        self.assertEqual(job.status, AnalysisJobStatus.PARTIAL)
        self.assertFalse(Report.objects.filter(job=job).exists())
        self.assertEqual(display.report_links, [])
        self.assertFalse(
            AgentInvocation.objects.filter(
                job=job,
                node_code="__paid_reporting_phase__",
            ).exists()
        )
        self.assertEqual(job.metadata["supervisor_reporting_handoff"]["gate"]["status"], "draft")
        self.assertFalse(job.metadata["supervisor_reporting_handoff"]["ready_for_reporting"])

    def test_failed_required_analysis_blocks_reporting_and_report_creation(self) -> None:
        queued, _payload = _queued_work(suffix="blocked")
        job_id = queued["job_id"]
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_blocked",
                statuses={"law_ground_search": "failed"},
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        display = AnalysisDisplayResult.objects.get(job=job)
        self.assertEqual(calls, [ANALYSIS_NODES])
        self.assertEqual(result["job_status"], AnalysisJobStatus.FAILED)
        self.assertEqual(job.status, AnalysisJobStatus.FAILED)
        self.assertFalse(Report.objects.filter(job=job).exists())
        self.assertEqual(display.report_links, [])
        self.assertEqual(job.metadata["supervisor_reporting_handoff"]["gate"]["status"], "blocked")

    def test_failed_optional_dl_result_does_not_downgrade_ready_report(self) -> None:
        queued, _payload = _queued_work(suffix="optional_dl")
        job_id = queued["job_id"]
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        payload = dict(work_item.payload)
        analysis_plan = dict(payload["analysis_plan"])
        original_steps = [dict(step) for step in analysis_plan["steps"]]
        reporting_step = original_steps.pop()
        original_steps.append(
            {
                "order": 4,
                "node_code": "vision_media_analysis",
                "status": "ready",
                "execution_mode": "sync",
                "depends_on": [ANALYSIS_NODES[-1]],
            }
        )
        reporting_step.update(
            {
                "order": 5,
                "depends_on": ["vision_media_analysis"],
            }
        )
        analysis_plan["steps"] = [*original_steps, reporting_step]
        payload["analysis_plan"] = analysis_plan
        payload["job_payload"] = {
            **payload["job_payload"],
            "analysis_plan": analysis_plan,
        }
        work_item.payload = payload
        work_item.save(update_fields=["payload", "updated_at"])

        def execute_plan(plan, execution_payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            statuses = {"vision_media_analysis": "failed"}
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_optional_dl",
                statuses=statuses,
                reporting_handoff=_reporting_handoff_from_payload(execution_payload),
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        report = Report.objects.get(job=job)
        handoff = job.metadata["supervisor_reporting_handoff"]
        self.assertEqual(handoff["gate"]["status"], "ready")
        self.assertEqual(
            handoff["gate"]["unavailable_optional_node_codes"],
            ["vision_media_analysis"],
        )
        self.assertEqual(result["job_status"], AnalysisJobStatus.SUCCESS)
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(report.status, ReportStatus.READY)

    def test_bundle_failure_retries_without_rerunning_analysis(self) -> None:
        queued, _payload = _queued_work(suffix="resume")
        job_id = queued["job_id"]
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_resume",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        with (
            patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan),
            patch(
                "chatbot.repositories.persist_analysis_reporting_bundle",
                side_effect=RuntimeError("bundle unavailable"),
            ),
        ):
            first = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        job = AnalysisJob.objects.get(job_id=job_id)
        self.assertEqual(first["status"], AgentWorkItemStatus.RETRYING)
        self.assertEqual(job.status, AnalysisJobStatus.RUNNING)
        self.assertEqual(calls, [ANALYSIS_NODES, (REPORTING_NODE,)])
        self.assertEqual(AgentResult.objects.filter(job=job).count(), len(ANALYSIS_NODES) + 1)
        work_item.next_run_at = timezone.now()
        work_item.save(update_fields=["next_run_at", "updated_at"])

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            second = process_agent_work_item(queued["work_item_id"])

        job.refresh_from_db()
        self.assertEqual(second["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(calls, [ANALYSIS_NODES, (REPORTING_NODE,)])
        self.assertEqual(Report.objects.filter(job=job).count(), 1)
        self.assertEqual(AnalysisDisplayResult.objects.filter(job=job).count(), 1)

    def test_handoff_persistence_failure_retries_without_rerunning_analysis(self) -> None:
        queued, _payload = _queued_work(suffix="handoff_resume")
        job_id = queued["job_id"]
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_handoff_resume",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        with (
            patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan),
            patch(
                "chatbot.repositories._build_and_persist_reporting_handoff",
                side_effect=RuntimeError("handoff store unavailable"),
            ),
        ):
            first = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        job = AnalysisJob.objects.get(job_id=job_id)
        self.assertEqual(first["status"], AgentWorkItemStatus.RETRYING)
        self.assertEqual(calls, [ANALYSIS_NODES])
        self.assertEqual(AgentResult.objects.filter(job=job).count(), len(ANALYSIS_NODES))
        self.assertFalse(job.metadata.get("supervisor_reporting_handoff"))
        work_item.next_run_at = timezone.now()
        work_item.save(update_fields=["next_run_at", "updated_at"])

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            second = process_agent_work_item(queued["work_item_id"])

        job.refresh_from_db()
        self.assertEqual(second["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(calls, [ANALYSIS_NODES, (REPORTING_NODE,)])
        self.assertEqual(AgentResult.objects.filter(job=job).count(), len(ANALYSIS_NODES) + 1)
        self.assertEqual(Report.objects.filter(job=job).count(), 1)

    def test_analysis_checkpoint_failure_never_repeats_the_paid_call(self) -> None:
        queued, _payload = _queued_work(suffix="analysis_checkpoint_cost_guard")
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            return _node_execution(
                node_codes,
                job_id=queued["job_id"],
                plan_id="plan_reporting_analysis_checkpoint_cost_guard",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        with (
            patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan),
            patch(
                "chatbot.repositories._persist_worker_execution_checkpoint",
                side_effect=RuntimeError("checkpoint unavailable"),
            ),
        ):
            first = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        guard = AgentInvocation.objects.get(
            job__job_id=queued["job_id"],
            node_code="__paid_analysis_phase__",
        )
        self.assertEqual(first["status"], AgentWorkItemStatus.FAILED)
        self.assertEqual(work_item.error_code, "PaidAgentCallRetryBlockedError")
        self.assertEqual(guard.metadata["state"], "provider_response_received")
        self.assertFalse(guard.metadata["automatic_retry_allowed"])
        self.assertEqual(calls, [ANALYSIS_NODES])

        second = process_agent_work_item(queued["work_item_id"])
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["reason"], "work_item_not_queued")
        self.assertEqual(calls, [ANALYSIS_NODES])
        self.assertFalse(AgentResult.objects.filter(job__job_id=queued["job_id"]).exists())
        self.assertFalse(Report.objects.filter(job__job_id=queued["job_id"]).exists())

    def test_reporting_output_without_handoff_provenance_is_not_persisted(self) -> None:
        queued, _payload = _queued_work(suffix="missing_provenance")
        job_id = queued["job_id"]

        def execute_plan(plan, _payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_missing_provenance",
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        self.assertEqual(result["status"], AgentWorkItemStatus.RETRYING)
        self.assertFalse(AgentResult.objects.filter(job=job, node_code=REPORTING_NODE).exists())
        self.assertFalse(Report.objects.filter(job=job).exists())

    def test_reporting_output_with_forged_handoff_provenance_is_not_persisted(self) -> None:
        queued, _payload = _queued_work(suffix="forged_provenance")
        job_id = queued["job_id"]

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            execution = _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_forged_provenance",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )
            if node_codes == (REPORTING_NODE,):
                trace = execution["executions"][0]["agent_output"]["structured_result"][
                    "supervisor_handoff"
                ]
                trace["contract_version"] = "forged.v1"
                trace["gate_status"] = "forged"
                trace["source_result_ids"] = ["res_forged"]
            return execution

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=job_id)
        self.assertEqual(result["status"], AgentWorkItemStatus.RETRYING)
        self.assertFalse(AgentResult.objects.filter(job=job, node_code=REPORTING_NODE).exists())
        self.assertFalse(Report.objects.filter(job=job).exists())

    def test_duplicate_reporting_steps_fail_closed_before_agent_execution(self) -> None:
        queued, _payload = _queued_work(suffix="duplicate_reporting")
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        payload = dict(work_item.payload)
        analysis_plan = dict(payload["analysis_plan"])
        analysis_plan["steps"] = [
            *analysis_plan["steps"],
            {
                "order": 5,
                "node_code": REPORTING_NODE,
                "status": "ready",
                "execution_mode": "sync",
                "depends_on": [REPORTING_NODE],
            },
        ]
        payload["analysis_plan"] = analysis_plan
        work_item.payload = payload
        work_item.save(update_fields=["payload", "updated_at"])

        with patch("app.services.agent_node_service.execute_agent_plan") as execute_plan:
            result = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(result["status"], AgentWorkItemStatus.RETRYING)
        execute_plan.assert_not_called()
        self.assertFalse(AgentResult.objects.filter(job__job_id=queued["job_id"]).exists())
        self.assertFalse(Report.objects.filter(job__job_id=queued["job_id"]).exists())

    def test_blocked_reporting_step_never_reserves_or_dispatches_a_paid_call(self) -> None:
        queued, _payload = _queued_work(suffix="blocked_reporting_step")
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        payload = dict(work_item.payload)
        analysis_plan = dict(payload["analysis_plan"])
        analysis_plan["steps"] = [
            *analysis_plan["steps"][:-1],
            {
                **analysis_plan["steps"][-1],
                "status": "blocked",
            },
        ]
        payload["analysis_plan"] = analysis_plan
        work_item.payload = payload
        work_item.save(update_fields=["payload", "updated_at"])
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, execution_payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            return _node_execution(
                node_codes,
                job_id=queued["job_id"],
                plan_id="plan_reporting_blocked_reporting_step",
                reporting_handoff=_reporting_handoff_from_payload(execution_payload),
            )

        with patch(
            "app.services.agent_node_service.execute_agent_plan",
            side_effect=execute_plan,
        ):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=queued["job_id"])
        self.assertEqual(result["status"], AgentWorkItemStatus.FAILED)
        self.assertEqual(calls, [ANALYSIS_NODES])
        self.assertEqual(
            job.metadata["supervisor_reporting_handoff"]["gate"]["reason_codes"],
            ["reporting_step_not_executable"],
        )
        self.assertFalse(
            AgentInvocation.objects.filter(
                job=job,
                node_code="__paid_reporting_phase__",
            ).exists()
        )
        self.assertFalse(Report.objects.filter(job=job).exists())

    def test_unknown_analysis_status_is_persisted_as_failed_and_blocks_reporting(self) -> None:
        queued, _payload = _queued_work(suffix="invalid_status")
        job_id = queued["job_id"]
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, _payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            execution = _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_invalid_status",
            )
            if node_codes == ANALYSIS_NODES:
                execution["executions"][1]["agent_output"]["status"] = "unexpected"
            return execution

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        invalid = AgentResult.objects.get(job__job_id=job_id, node_code="law_ground_search")
        self.assertEqual(result["job_status"], AnalysisJobStatus.FAILED)
        self.assertEqual(invalid.status, "failed")
        self.assertEqual(calls, [ANALYSIS_NODES])
        self.assertFalse(Report.objects.filter(job__job_id=job_id).exists())

    def test_raw_user_text_is_not_used_as_reporting_case_facts(self) -> None:
        queued, _payload = _queued_work(suffix="raw_text_boundary")
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        payload = dict(work_item.payload)
        execution_payload = dict(payload["execution_payload"])
        execution_payload["context"] = {}
        execution_payload["user_text"] = "RAW-USER-SECRET-193"
        payload["execution_payload"] = execution_payload
        work_item.payload = payload
        work_item.save(update_fields=["payload", "updated_at"])

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            return _node_execution(
                node_codes,
                job_id=queued["job_id"],
                plan_id="plan_reporting_raw_text_boundary",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            result = process_agent_work_item(queued["work_item_id"])

        job = AnalysisJob.objects.get(job_id=queued["job_id"])
        reporting_result = AgentResult.objects.get(job=job, node_code=REPORTING_NODE)
        report = Report.objects.get(job=job)
        self.assertEqual(result["status"], AgentWorkItemStatus.SUCCESS)
        self.assertNotIn("RAW-USER-SECRET-193", repr(job.metadata["supervisor_reporting_handoff"]))
        self.assertNotIn("RAW-USER-SECRET-193", repr(reporting_result.structured_result))
        self.assertNotIn("RAW-USER-SECRET-193", repr(reporting_result.evidence))
        self.assertNotIn("RAW-USER-SECRET-193", repr(report.content))

    def test_reporting_failure_does_not_repeat_a_paid_agent_call(self) -> None:
        queued, _payload = _queued_work(suffix="reporting_failure")
        job_id = queued["job_id"]
        case = Case.objects.create(
            case_id="case_reporting_failure",
            owner_id="usr_reporting_reporting_failure",
            title="Terminal Reporting failure",
            status=CaseStatus.QUEUED,
            current_fact_version=1,
        )
        linked_job = AnalysisJob.objects.get(job_id=job_id)
        fact_version = ConfirmedFactVersion.objects.create(
            fact_version_id="fact_reporting_failure",
            case=case,
            version_no=1,
            status="confirmed",
            facts={"case": "terminal reporting failure"},
            confirmed_by=linked_job.owner_id,
            confirmed_at=timezone.now(),
        )
        linked_job.case = case
        linked_job.metadata = {
            **linked_job.metadata,
            "fact_version_id": fact_version.fact_version_id,
        }
        linked_job.save(update_fields=["case", "metadata", "updated_at"])
        case.metadata = {
            **case.metadata,
            "active_analysis_job_id": linked_job.job_id,
            "active_fact_version_id": fact_version.fact_version_id,
        }
        case.save(update_fields=["metadata", "updated_at"])
        linked_job.session.case = case
        linked_job.session.save(update_fields=["case", "updated_at"])
        calls: list[tuple[str, ...]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            calls.append(node_codes)
            statuses = {REPORTING_NODE: "failed"} if node_codes == (REPORTING_NODE,) else {}
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_failure",
                statuses=statuses,
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            first = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        job = AnalysisJob.objects.get(job_id=job_id)
        case.refresh_from_db()
        self.assertEqual(first["status"], AgentWorkItemStatus.FAILED)
        self.assertEqual(work_item.status, AgentWorkItemStatus.FAILED)
        self.assertEqual(work_item.error_code, "PaidAgentCallRetryBlockedError")
        self.assertEqual(job.status, AnalysisJobStatus.FAILED)
        case.refresh_from_db()
        self.assertEqual(case.status, CaseStatus.NEEDS_INPUT)
        self.assertEqual(calls, [ANALYSIS_NODES, (REPORTING_NODE,)])
        retry = process_agent_work_item(queued["work_item_id"])
        self.assertEqual(retry["status"], "skipped")
        self.assertEqual(retry["reason"], "work_item_not_queued")
        self.assertFalse(Report.objects.filter(job=job).exists())
        self.assertFalse(AgentResult.objects.filter(job=job, node_code=REPORTING_NODE).exists())

    def test_reporting_bundle_retry_is_idempotent_and_fingerprint_mismatch_fails_closed(
        self,
    ) -> None:
        queued, _payload = _queued_work(suffix="idempotent_bundle")
        job = AnalysisJob.objects.select_related("session").get(job_id=queued["job_id"])
        case = Case.objects.create(
            case_id="case_reporting_idempotent_bundle",
            owner_id=job.owner_id,
            title="Reporting idempotency",
            current_fact_version=1,
        )
        fact_version = ConfirmedFactVersion.objects.create(
            fact_version_id="fact_reporting_idempotent_bundle",
            case=case,
            version_no=1,
            status="confirmed",
            facts={"case": "reporting idempotency"},
            confirmed_by=job.owner_id,
            confirmed_at=timezone.now(),
        )
        job.case = case
        job.metadata = {
            **job.metadata,
            "fact_version_id": fact_version.fact_version_id,
        }
        job.save(update_fields=["case", "metadata", "updated_at"])
        case.metadata = {
            **case.metadata,
            "active_analysis_job_id": job.job_id,
            "active_fact_version_id": fact_version.fact_version_id,
        }
        case.save(update_fields=["metadata", "updated_at"])
        job.session.case = case
        job.session.save(update_fields=["case", "updated_at"])

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            return _node_execution(
                node_codes,
                job_id=job.job_id,
                plan_id="plan_reporting_idempotent_bundle",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            process_agent_work_item(queued["work_item_id"])

        job.refresh_from_db()
        case.refresh_from_db()
        handoff = job.metadata["supervisor_reporting_handoff"]
        reused = persist_analysis_reporting_bundle(
            job_id=job.job_id,
            final_status=job.status,
            handoff=handoff,
        )
        case.refresh_from_db()
        self.assertEqual(reused["status"], "reused")
        self.assertEqual(case.status, CaseStatus.READY)
        self.assertEqual(case.current_report_version, 1)
        self.assertEqual(Report.objects.filter(job=job).count(), 1)
        report = Report.objects.get(job=job)
        self.assertEqual(report.source_fact_version, fact_version)
        self.assertNotIn("raw_output", repr(report.content))
        self.assertNotIn("confirmed facts for a fine notice objection", repr(report.content))
        self.assertNotIn("report-token-must-not-persist", repr(report.content))
        self.assertNotIn("access_token", repr(report.content))
        self.assertNotIn("report-cookie-must-not-persist", repr(report.content))
        self.assertNotIn("private-report-bucket", repr(report.content))

        changed_handoff = {
            **handoff,
            "source": {**handoff["source"], "fingerprint": "sha256:" + ("0" * 64)},
        }
        with self.assertRaises(ReportReferenceError):
            persist_analysis_reporting_bundle(
                job_id=job.job_id,
                final_status=job.status,
                handoff=changed_handoff,
            )

    def test_case_bound_worker_report_requires_a_confirmed_fact_version(self) -> None:
        queued, _payload = _queued_work(suffix="missing_case_fact_version")
        job = AnalysisJob.objects.select_related("session").get(job_id=queued["job_id"])
        case = Case.objects.create(
            case_id="case_reporting_missing_fact_version",
            owner_id=job.owner_id,
            title="Missing report fact provenance",
        )
        job.case = case
        job.save(update_fields=["case", "updated_at"])
        job.session.case = case
        job.session.save(update_fields=["case", "updated_at"])

        with patch("app.services.agent_node_service.execute_agent_plan") as execute_plan:
            result = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        execute_plan.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "case_fact_provenance_required")
        self.assertEqual(work_item.status, AgentWorkItemStatus.FAILED)
        self.assertEqual(work_item.error_code, "case_fact_provenance_required")
        self.assertFalse(
            AgentInvocation.objects.filter(
                job=job,
                node_code="__paid_analysis_phase__",
            ).exists()
        )
        self.assertFalse(Report.objects.filter(job=job).exists())
        self.assertFalse(AnalysisDisplayResult.objects.filter(job=job).exists())

    def test_worker_public_payloads_strip_signed_urls_and_sensitive_limitations(self) -> None:
        queued, _payload = _queued_work(suffix="sanitized_public_payloads")
        job_id = queued["job_id"]
        job = AnalysisJob.objects.get(job_id=job_id)
        job.metadata = {
            **job.metadata,
            "attachments": [
                {
                    "attachment_id": "att_safe",
                    "filename": "notice Authorization: Bearer sk-file-secret",
                    "purpose": "fine_notice password=attachment-purpose-secret",
                    "storage_uri": "s3://private-display-attachment",
                }
            ],
        }
        job.save(update_fields=["metadata", "updated_at"])

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            execution = _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_sanitized_public_payloads",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )
            if node_codes == ANALYSIS_NODES:
                first = execution["executions"][0]["agent_output"]
                first["summary"] = (
                    "https://storage.googleapis.com/private?"
                    "X-Goog-Credential=summary-user&X-Goog-Signature=summary-secret"
                )
                first["limitations"] = [
                    "safe limitation",
                    "https://storage.example/private?X-Amz-Signature=quality-secret",
                    (
                        "https://storage.googleapis.com/private?"
                        "X-Goog-Credential=quality-user&X-Goog-Signature=gcs-quality-secret"
                    ),
                    "https://url-user:url-password@example.com/private",
                ]
            if node_codes == (REPORTING_NODE,):
                reporting = execution["executions"][0]["agent_output"]
                reporting["structured_result"]["document_title"] = (
                    "Report Authorization: Bearer sk-title-secret"
                )
            return execution

        with patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan):
            process_agent_work_item(queued["work_item_id"])

        report = Report.objects.get(job__job_id=job_id)
        display = AnalysisDisplayResult.objects.get(job__job_id=job_id)
        job_detail = get_analysis_job_record(job_id)
        public_payload = repr(
            {
                "report": report.content,
                "report_metadata": report.metadata,
                "display_progress": display.progress,
                "display_limitations": display.limitations,
                "display_cards": display.cards,
                "display_attachments": display.attachments,
                "job_detail": job_detail,
            }
        )
        self.assertIn("safe limitation", public_payload)
        for secret in (
            "summary-user",
            "summary-secret",
            "quality-secret",
            "quality-user",
            "gcs-quality-secret",
            "url-user",
            "url-password",
            "report-token-must-not-persist",
            "report-cookie-must-not-persist",
            "private-report-bucket",
            "file-secret",
            "attachment-purpose-secret",
            "private-display-attachment",
            "title-secret",
        ):
            self.assertNotIn(secret, public_payload)

    def test_reporting_job_rejects_legacy_mock_report_action(self) -> None:
        from chatbot.views import report_action

        queued, _payload = _queued_work(suffix="worker_only_action")
        request = RequestFactory().post(
            "/api/reports/",
            data={
                "action": "save",
                "session_id": "ses_reporting_worker_only_action",
                "report_id": f"rep_{queued['job_id']}",
            },
            content_type="application/json",
        )
        identity_body = {
            "action": "save",
            "session_id": "ses_reporting_worker_only_action",
            "report_id": f"rep_{queued['job_id']}",
            "auth_context": {
                "user_id": "usr_reporting_worker_only_action",
                "subject_type": "user",
            },
        }
        with (
            patch("chatbot.views._is_canonical_mock_request", return_value=True),
            patch("chatbot.views._payload_with_request_identity", return_value=identity_body),
            patch("chatbot.views.record_usage_event") as usage,
        ):
            response = report_action(request)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.content)["error"]["code"],
            "worker_report_action_required",
        )
        usage.assert_not_called()

    def test_guest_report_download_requires_guest_binding_not_only_session_id(self) -> None:
        guest_id = "a" * 32
        session = ChatSession.objects.create(
            session_id="ses_guest_reporting_download",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={"auth_context": {"guest_id": guest_id, "subject_type": "guest"}},
        )
        job = AnalysisJob.objects.create(
            job_id="job_guest_reporting_download",
            session=session,
            owner_id="",
            status=AnalysisJobStatus.SUCCESS,
        )
        report = Report.objects.create(
            report_id="rep_guest_reporting_download",
            owner_id="",
            session=session,
            job=job,
            status=ReportStatus.READY,
            title="Guest report",
            content={
                "contract_version": "analysis_report.v1",
                "reporting_payload": {"document_variant": "fine_notice"},
            },
        )

        download = get_report_download_metadata(
            report.report_id,
            document_type="objection_form",
        )
        self.assertEqual(download["guest_id"], f"gst_{guest_id}")
        attacker = authorize_report_download_metadata(
            download,
            {
                "session_id": session.session_id,
                "auth_context": {
                    "user_id": "usr_attacker",
                    "subject_type": "user",
                },
            },
        )
        owner = authorize_report_download_metadata(
            download,
            {
                "auth_context": {
                    "guest_id": guest_id,
                    "subject_type": "guest",
                }
            },
        )
        self.assertFalse(attacker["allowed"])
        self.assertEqual(attacker["reason"], "guest_mismatch")
        self.assertTrue(owner["allowed"])
        self.assertEqual(owner["reason"], "guest_match")

    def test_unbound_report_cannot_be_authorized_by_session_id_alone(self) -> None:
        decision = authorize_report_download_metadata(
            {
                "report_id": "rep_unbound",
                "owner_id": "",
                "guest_id": "",
                "session_id": "ses_unbound",
                "storage_backend": "database",
            },
            {"session_id": "ses_unbound"},
        )

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "unbound_resource")

    def test_saving_guest_session_promotes_worker_report_to_authenticated_owner(self) -> None:
        guest_id = "gst_guest_report_promotion"
        session = ChatSession.objects.create(
            session_id="ses_guest_report_promotion",
            owner_id="",
            status=ChatSessionStatus.ACTIVE,
            metadata={
                "conversation_save_state": "pending",
                "auth_context": {"guest_id": guest_id, "subject_type": "guest"},
            },
        )
        job = AnalysisJob.objects.create(
            job_id="job_guest_report_promotion",
            session=session,
            owner_id="",
            status=AnalysisJobStatus.SUCCESS,
            metadata={"conversation_save_state": "pending"},
        )
        report = Report.objects.create(
            report_id="rep_guest_report_promotion",
            owner_id="",
            session=session,
            job=job,
            status=ReportStatus.READY,
            title="Guest worker report",
            metadata={
                "source": "analysis_worker_reporting",
                "guest_id": guest_id,
                "conversation_save_state": "pending",
            },
        )

        result = mark_conversation_save_state(
            session_id=session.session_id,
            save_state="saved",
            owner_id="usr_promoted_report_owner",
            guest_id=guest_id,
        )

        report.refresh_from_db()
        self.assertEqual(result["reports_updated"], 1)
        self.assertEqual(report.owner_id, "usr_promoted_report_owner")
        self.assertEqual(report.metadata["conversation_save_state"], "saved")
        self.assertEqual(
            [item["report_id"] for item in list_report_records(owner_id="usr_promoted_report_owner")],
            [report.report_id],
        )
        access_metadata = get_report_access_metadata(report.report_id)
        access = authorize_report_download_metadata(
            access_metadata,
            {
                "auth_context": {
                    "user_id": "usr_promoted_report_owner",
                    "subject_type": "user",
                }
            },
        )
        self.assertTrue(access["allowed"])
        self.assertEqual(access["reason"], "owner_match")

    def test_legacy_worker_draft_report_has_no_direct_download(self) -> None:
        session = ChatSession.objects.create(
            session_id="ses_reporting_draft_download",
            owner_id="usr_reporting_draft_download",
            status=ChatSessionStatus.ACTIVE,
        )
        report = Report.objects.create(
            report_id="rep_reporting_draft_download",
            owner_id="usr_reporting_draft_download",
            session=session,
            status=ReportStatus.DRAFT,
            title="Legacy draft report",
            metadata={"source": "analysis_worker_reporting"},
        )

        from chatbot.views import download_report

        request = RequestFactory().get(
            f"/api/reports/{report.report_id}/download/?document_type=objection_form"
        )
        with patch(
            "chatbot.views._request_access_payload",
            return_value={
                "auth_context": {
                    "user_id": "usr_reporting_draft_download",
                    "subject_type": "user",
                }
            },
        ):
            response = download_report(request, report.report_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b'"code": "report_not_ready"', response.content)

    def test_download_blocks_denied_not_applicable_and_deadline_passed_appeals(self) -> None:
        from chatbot.views import download_report

        decisions = (
            {"judgment_status": "denied"},
            {"judgment_status": "not_applicable"},
            {"judgment_status": "success", "deadline_passed": True},
        )
        identity = {"auth_context": {"user_id": "usr_appeal_gate", "subject_type": "user"}}

        for index, appeal_decision in enumerate(decisions, start=1):
            report = Report.objects.create(
                report_id=f"rep_appeal_gate_{index}",
                owner_id="usr_appeal_gate",
                status=ReportStatus.READY,
                title="Appeal gate report",
                content={"reporting_payload": {"appeal_decision": appeal_decision}},
                metadata={"source": "analysis_worker_reporting"},
            )
            request = RequestFactory().get(
                f"/api/reports/{report.report_id}/download/?document_type=objection_form"
            )
            with patch("chatbot.views._request_access_payload", return_value=identity):
                response = download_report(request, report.report_id)

            self.assertEqual(response.status_code, 409)
            self.assertIn(b'"code": "appeal_gate_blocked"', response.content)
            self.assertIn(b'"reason": "appeal_gate_blocked"', response.content)

    def test_unauthorized_report_request_is_rejected_before_pdf_rendering(self) -> None:
        session = ChatSession.objects.create(
            session_id="ses_render_after_auth",
            owner_id="usr_render_owner",
            status=ChatSessionStatus.ACTIVE,
        )
        Report.objects.create(
            report_id="rep_render_after_auth",
            owner_id="usr_render_owner",
            session=session,
            status=ReportStatus.READY,
            title="Private report",
        )
        from chatbot.views import download_report

        request = RequestFactory().get("/api/reports/rep_render_after_auth/download/")

        with (
            patch(
                "chatbot.views._request_access_payload",
                return_value={
                    "auth_context": {
                        "user_id": "usr_render_attacker",
                        "subject_type": "user",
                    }
                },
            ),
            patch("chatbot.views.get_report_download_metadata") as render_download,
        ):
            response = download_report(request, "rep_render_after_auth")

        self.assertEqual(response.status_code, 403)
        render_download.assert_not_called()


class SupervisorReportingCommitOrderingTests(TransactionTestCase):
    reset_sequences = True

    def test_terminal_cache_is_published_only_after_report_transaction_commits(self) -> None:
        queued, _payload = _queued_work(suffix="cache_commit")
        job_id = queued["job_id"]
        terminal_observations: list[tuple[bool, bool]] = []

        def execute_plan(plan, payload):
            node_codes = tuple(step["node_code"] for step in plan["steps"])
            return _node_execution(
                node_codes,
                job_id=job_id,
                plan_id="plan_reporting_cache_commit",
                reporting_handoff=_reporting_handoff_from_payload(payload),
            )

        def write_progress(job):
            if job.status in {
                AnalysisJobStatus.SUCCESS,
                AnalysisJobStatus.PARTIAL,
                AnalysisJobStatus.FAILED,
            }:
                terminal_observations.append(
                    (
                        connection.in_atomic_block,
                        Report.objects.filter(job=job).exists(),
                    )
                )
            return {"status": "cached", "job_id": job.job_id}

        with (
            patch("app.services.agent_node_service.execute_agent_plan", side_effect=execute_plan),
            patch("chatbot.repositories.write_analysis_job_progress", side_effect=write_progress),
            patch(
                "chatbot.repositories.write_chat_session_state",
                return_value={"status": "cached"},
            ),
        ):
            result = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(result["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(result["persistence"]["progress_cache"]["status"], "cached")
        self.assertEqual(result["persistence"]["session_cache"]["status"], "cached")
        self.assertTrue(terminal_observations)
        self.assertTrue(all(not in_atomic for in_atomic, _has_report in terminal_observations))
        self.assertTrue(all(has_report for _in_atomic, has_report in terminal_observations))


class DocumentConfirmationRepositoryTests(TestCase):
    def setUp(self) -> None:
        self.report = Report.objects.create(
            report_id="rep_document_confirmation",
            owner_id="usr_document_confirmation",
            status=ReportStatus.READY,
            title="Official objection form",
            content={
                "reporting_payload": {
                    "document_variant": "fine_notice",
                    "form_data": {"recipient": "Traffic agency", "applicant_name": "Applicant"},
                    "sections": [{"title": "Facts", "body": "Confirmed facts"}],
                    "petition_purpose": "Review the disposition",
                    "petition_reason": "The facts require review.",
                    "appeal_gate": {"blocked": False, "reason": ""},
                }
            },
            metadata={"source": "analysis_worker_reporting"},
        )

    def test_confirmation_projects_safe_current_and_stale_states(self) -> None:
        confirmed = repository_module.confirm_report_document(
            self.report.report_id,
            owner_id=self.report.owner_id,
        )

        self.assertEqual(
            {key: confirmed[key] for key in ("required", "confirmed", "stale")},
            {"required": True, "confirmed": True, "stale": False},
        )
        self.assertIsNotNone(confirmed["confirmed_at"])
        self.report.refresh_from_db()
        self.assertIn("input_fingerprint", self.report.metadata["document_confirmation"])

        current_detail = get_report_record_detail(self.report.report_id)
        current_state = current_detail["content"]["reporting_payload"][
            "document_confirmation"
        ]
        self.assertEqual(
            {key: current_state[key] for key in ("required", "confirmed", "stale")},
            {"required": True, "confirmed": True, "stale": False},
        )
        self.assertNotIn("input_fingerprint", json.dumps(current_detail, sort_keys=True))

        payload = dict(self.report.content["reporting_payload"])
        payload["petition_reason"] = "The reason changed after final confirmation."
        self.report.content = {"reporting_payload": payload}
        self.report.save(update_fields=["content", "updated_at"])

        stale_detail = get_report_record_detail(self.report.report_id)
        self.assertEqual(
            stale_detail["content"]["reporting_payload"]["document_confirmation"],
            {"required": True, "confirmed": False, "stale": True, "confirmed_at": None},
        )

    def test_download_only_allows_current_confirmed_official_document(self) -> None:
        from chatbot.views import download_report

        identity = {
            "auth_context": {
                "user_id": self.report.owner_id,
                "subject_type": "user",
            }
        }

        with patch("chatbot.views._request_access_payload", return_value=identity):
            general_response = download_report(
                RequestFactory().get(
                    f"/api/reports/{self.report.report_id}/download/?document_type=report"
                ),
                self.report.report_id,
            )
            unconfirmed_response = download_report(
                RequestFactory().get(
                    f"/api/reports/{self.report.report_id}/download/?document_type=objection_form"
                ),
                self.report.report_id,
            )

        self.assertEqual(general_response.status_code, 409)
        self.assertIn(b'"code": "document_download_not_available"', general_response.content)
        self.assertEqual(unconfirmed_response.status_code, 409)
        self.assertIn(b'"code": "document_confirmation_required"', unconfirmed_response.content)

        repository_module.confirm_report_document(
            self.report.report_id,
            owner_id=self.report.owner_id,
        )
        with patch("chatbot.views._request_access_payload", return_value=identity):
            confirmed_response = download_report(
                RequestFactory().get(
                    f"/api/reports/{self.report.report_id}/download/?document_type=objection_form"
                ),
                self.report.report_id,
            )

        self.assertEqual(confirmed_response.status_code, 200)
        self.assertTrue(confirmed_response.content.startswith(b"PK"))

    def test_download_metadata_rejects_general_report_even_as_objection_form(self) -> None:
        general_report = Report.objects.create(
            report_id="rep_general_document_download",
            owner_id=self.report.owner_id,
            report_type=ReportType.GENERAL,
            status=ReportStatus.READY,
            title="General analysis report",
            content={
                "reporting_payload": {
                    "document_variant": "general",
                    "sections": [{"title": "Analysis", "body": "View-only analysis."}],
                }
            },
            metadata={"source": "analysis_worker_reporting"},
        )

        download = get_report_download_metadata(
            general_report.report_id,
            document_type="objection_form",
        )

        self.assertIsNone(download)

    def test_download_rechecks_confirmation_after_document_input_changes(self) -> None:
        from chatbot.views import download_report

        repository_module.confirm_report_document(
            self.report.report_id,
            owner_id=self.report.owner_id,
        )
        identity = {
            "auth_context": {
                "user_id": self.report.owner_id,
                "subject_type": "user",
            }
        }
        original_download_metadata = repository_module.get_report_download_metadata

        def change_document_then_render(*args, **kwargs):
            current = Report.objects.get(report_id=self.report.report_id)
            payload = dict(current.content["reporting_payload"])
            payload["petition_reason"] = "Changed after final confirmation."
            current.content = {"reporting_payload": payload}
            current.save(update_fields=["content", "updated_at"])
            return original_download_metadata(*args, **kwargs)

        with (
            patch("chatbot.views._request_access_payload", return_value=identity),
            patch(
                "chatbot.views.get_report_download_metadata",
                side_effect=change_document_then_render,
            ),
        ):
            response = download_report(
                RequestFactory().get(
                    f"/api/reports/{self.report.report_id}/download/?document_type=objection_form"
                ),
                self.report.report_id,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(b'"code": "document_confirmation_required"', response.content)
        self.assertIn(b'"reason": "document_confirmation_stale"', response.content)

    def test_download_rechecks_appeal_gate_after_eligibility_changes(self) -> None:
        from chatbot.views import download_report

        repository_module.confirm_report_document(
            self.report.report_id,
            owner_id=self.report.owner_id,
        )
        identity = {
            "auth_context": {
                "user_id": self.report.owner_id,
                "subject_type": "user",
            }
        }
        original_download_metadata = repository_module.get_report_download_metadata

        def block_appeal_then_render(*args, **kwargs):
            current = Report.objects.get(report_id=self.report.report_id)
            payload = dict(current.content["reporting_payload"])
            payload["appeal_gate"] = {
                "blocked": True,
                "reason": "Appeal deadline passed.",
            }
            current.content = {"reporting_payload": payload}
            current.save(update_fields=["content", "updated_at"])
            return original_download_metadata(*args, **kwargs)

        with (
            patch("chatbot.views._request_access_payload", return_value=identity),
            patch(
                "chatbot.views.get_report_download_metadata",
                side_effect=block_appeal_then_render,
            ),
        ):
            response = download_report(
                RequestFactory().get(
                    f"/api/reports/{self.report.report_id}/download/?document_type=objection_form"
                ),
                self.report.report_id,
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn(b'"code": "appeal_gate_blocked"', response.content)

    def test_confirmation_api_rejects_blocked_appeal_before_writing(self) -> None:
        from chatbot.views import report_document_confirmation

        payload = dict(self.report.content["reporting_payload"])
        payload["appeal_gate"] = {"blocked": True, "reason": "Appeal deadline passed."}
        self.report.content = {"reporting_payload": payload}
        self.report.save(update_fields=["content", "updated_at"])
        request = RequestFactory().post(
            f"/api/reports/{self.report.report_id}/document-confirmation/",
            data=json.dumps(
                {
                    "facts_confirmed": True,
                    "agency_confirmed": True,
                    "deadline_confirmed": True,
                    "attachments_confirmed": True,
                }
            ),
            content_type="application/json",
        )
        identity = {
            "auth_context": {
                "user_id": self.report.owner_id,
                "subject_type": "user",
            }
        }

        with patch("chatbot.views._request_access_payload", return_value=identity):
            response = report_document_confirmation(request, self.report.report_id)

        self.assertEqual(response.status_code, 409)
        self.assertIn(b'"code": "appeal_gate_blocked"', response.content)
        self.report.refresh_from_db()
        self.assertNotIn("document_confirmation", self.report.metadata)
