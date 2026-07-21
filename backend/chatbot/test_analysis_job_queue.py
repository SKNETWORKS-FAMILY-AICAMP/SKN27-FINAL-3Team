from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services import agent_node_service
from app.services.google_auth_service import issue_access_token
from chatbot import repositories as repository_module
from chatbot.models import (
    AgentInvocation,
    AgentResult,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    AnalysisJobStatus,
    AuthSession,
    AuthSessionStatus,
    Case,
    ChatSession,
    ChatSessionStatus,
    UsageEvent,
    UsageQuota,
    UserAccount,
)
from chatbot.repositories import (
    _refresh_agent_work_item_lease,
    enqueue_analysis_job_work,
    process_agent_work_item,
    record_usage_event,
    refund_usage_event,
    release_analysis_job_reservation,
    renew_analysis_job_reservation,
    reserve_analysis_job_request,
)
from chatbot.views import _analysis_job_request_fingerprint


TEST_JWT_SIGNING_KEY = "analysis-job-queue-test-signing-key-is-long-enough"


def _authenticated_client(user_id: str) -> Client:
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(hours=1)
    auth_session_id = f"auth_{user_id}"
    token, _claims = issue_access_token(
        user_id=user_id,
        auth_session_id=auth_session_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    user = UserAccount.objects.create(user_id=user_id)
    AuthSession.objects.create(
        auth_session_id=auth_session_id,
        user=user,
        subject_type="user",
        subject_id=f"user:{user_id}",
        status=AuthSessionStatus.ACTIVE,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return Client(HTTP_AUTHORIZATION=f"Bearer {token}")


def _chat_response(*, session_id: str, message_id: str, plan_id: str) -> dict:
    return {
        "contract_version": "chat_message_accepted.v2",
        "session_id": session_id,
        "message_id": message_id,
        "routing_intent": "traffic_law_search",
        "status": "queued",
        "progress": {
            "status": "queued",
            "active_node": "law_ground_search",
            "message": "Analysis queued.",
        },
        "analysis_plan": {
            "plan_id": plan_id,
            "routing_intent": "traffic_law_search",
            "steps": [
                {
                    "order": 1,
                    "node_code": "law_ground_search",
                    "status": "queued",
                }
            ],
        },
        "attachments": [],
        "blocked_attachments": [],
        "limitations": [],
    }


def _server_authoritative_chat_response(*, session_id: str, message_id: str, plan_id: str) -> dict:
    slot_state = {
        "contract_version": "slot_filling_state.v1",
        "slots": {
            "query": {
                "value": "server approved query",
                "source": {"type": "supervisor", "reference": message_id},
                "confidence": 1.0,
                "editable": False,
            }
        },
    }
    response = _chat_response(session_id=session_id, message_id=message_id, plan_id=plan_id)
    response["analysis_plan"]["steps"][0].update(
        {"status": "ready", "depends_on": [], "required_inputs": ["user_text"]}
    )
    response["supervisor_state"] = {
        "contract_version": "supervisor_conversation_state.v2",
        "stage": "agent_execution_ready",
        "slot_state": slot_state,
        "agent_input_packages": [
            {
                "schema_version": "agent_input_schema.v1",
                "node_code": "law_ground_search",
                "status": "ready",
                "required_inputs": ["user_text"],
                "payload": {
                    "user_text": "server approved question",
                    "attachments": [],
                    "slot_state": slot_state,
                },
            }
        ],
    }
    return response


def _queue_payload(*, owner_id: str, session_id: str, job_id: str) -> tuple[dict, dict]:
    plan_id = f"plan_{job_id}"
    request_payload = {
        "owner_id": owner_id,
        "user_id": owner_id,
        "session_id": session_id,
        "user_text": "safe queue request",
    }
    job_payload = {
        "job_id": job_id,
        "session_id": session_id,
        "message_id": f"msg_{job_id}",
        "routing_intent": "traffic_law_search",
        "status": "queued",
        "active_node": "law_ground_search",
        "progress_message": "Analysis queued.",
        "analysis_plan_id": plan_id,
        "analysis_plan": _chat_response(
            session_id=session_id,
            message_id=f"msg_{job_id}",
            plan_id=plan_id,
        )["analysis_plan"],
        "chat_response": {},
        "node_execution": {},
    }
    return request_payload, job_payload


@override_settings(APP_JWT_SECRET=TEST_JWT_SIGNING_KEY)
class AnalysisJobQueueTests(TestCase):
    def test_client_job_id_requires_session_before_reservation(self) -> None:
        client = _authenticated_client("usr_job_without_session")

        response = client.post(
            "/api/analysis/jobs/",
            data={"job_id": "job_without_session", "user_text": "safe request"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"]["code"],
            "analysis_job_session_required",
        )
        self.assertFalse(AnalysisJob.objects.filter(job_id="job_without_session").exists())

    def test_quota_denial_happens_before_planner_execution(self) -> None:
        owner_id = "usr_analysis_quota_blocked"
        session_id = "ses_analysis_quota_blocked"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        UsageQuota.objects.create(
            quota_id="quota_user_usr_analysis_quota_blocked_agent_run",
            subject_id=f"user:{owner_id}",
            scope="agent_run",
            limit_count=1,
            used_count=1,
            reset_at=timezone.now() + timedelta(hours=1),
        )

        with patch("chatbot.views.submit_message") as submit_message:
            response = client.post(
                "/api/analysis/jobs/",
                data={
                    "session_id": session_id,
                    "user_text": "quota should reject before planning",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"]["code"], "rate_limit_exceeded")
        submit_message.assert_not_called()
        usage_event = UsageEvent.objects.get(
            subject_id=f"user:{owner_id}",
            scope="agent_run",
        )
        self.assertEqual(usage_event.amount, 0)
        self.assertEqual(usage_event.metadata["status"], "blocked")

    def test_inflight_reservation_is_not_reported_as_an_accepted_queue_item(self) -> None:
        owner_id = "usr_inflight_reservation"
        session_id = "ses_inflight_reservation"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        request_payload = {
            "job_id": "job_inflight_reservation",
            "session_id": session_id,
            "user_text": "same inflight request",
        }
        repository_payload = {
            **request_payload,
            "owner_id": owner_id,
            "user_id": owner_id,
        }
        reserve_analysis_job_request(
            repository_payload,
            job_id=request_payload["job_id"],
            request_fingerprint=_analysis_job_request_fingerprint(repository_payload),
        )

        with patch("chatbot.views.submit_message") as submit_message:
            response = client.post(
                "/api/analysis/jobs/",
                data=request_payload,
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "analysis_job_reservation_pending")
        self.assertEqual(response.headers["Retry-After"], "1")
        submit_message.assert_not_called()
        self.assertFalse(
            AgentWorkItem.objects.filter(job__job_id=request_payload["job_id"]).exists()
        )

    def test_reservation_is_promoted_to_a_complete_queued_job(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_reservation_promotion",
            session_id="ses_reservation_promotion",
            job_id="job_reservation_promotion",
        )
        fingerprint = "a" * 64
        reservation = reserve_analysis_job_request(
            payload,
            job_id=job_payload["job_id"],
            request_fingerprint=fingerprint,
        )
        job_payload["idempotency"] = {
            "contract_version": "analysis_job_idempotency.v1",
            "request_fingerprint": fingerprint,
            "reservation_token": reservation["reservation_token"],
            "reservation_generation": reservation["reservation_generation"],
            "state": "queued",
        }

        queued = enqueue_analysis_job_work(payload, job_payload)

        job = AnalysisJob.objects.get(job_id=job_payload["job_id"])
        self.assertTrue(reservation["acquired"])
        self.assertEqual(queued["work_item_status"], AgentWorkItemStatus.QUEUED)
        self.assertEqual(job.analysis_plan_id, job_payload["analysis_plan_id"])
        self.assertEqual(job.active_node, "law_ground_search")
        self.assertEqual(job.status_counts, {"queued": 1})
        self.assertEqual(job.metadata["source"], "canonical_analysis_job_queue")
        self.assertEqual(job.metadata["idempotency"]["state"], "queued")
        self.assertEqual(
            job.metadata["idempotency"]["request_fingerprint"],
            fingerprint,
        )

    @override_settings(ANALYSIS_JOB_RESERVATION_STALE_AFTER_SECONDS=1)
    def test_stale_reservation_without_work_item_can_be_recovered(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_stale_reservation",
            session_id="ses_stale_reservation",
            job_id="job_stale_reservation",
        )
        fingerprint = "b" * 64
        original = reserve_analysis_job_request(
            payload,
            job_id=job_payload["job_id"],
            request_fingerprint=fingerprint,
        )
        AnalysisJob.objects.filter(job_id=job_payload["job_id"]).update(
            updated_at=timezone.now() - timedelta(seconds=2)
        )

        recovered = reserve_analysis_job_request(
            payload,
            job_id=job_payload["job_id"],
            request_fingerprint=fingerprint,
        )

        self.assertTrue(recovered["acquired"])
        self.assertTrue(recovered["recovered"])
        self.assertNotEqual(
            recovered["reservation_token"],
            original["reservation_token"],
        )
        self.assertFalse(
            release_analysis_job_reservation(
                job_id=job_payload["job_id"],
                request_fingerprint=fingerprint,
                reservation_token=original["reservation_token"],
            )
        )
        self.assertFalse(
            renew_analysis_job_reservation(
                job_id=job_payload["job_id"],
                request_fingerprint=fingerprint,
                reservation_token=original["reservation_token"],
            )
        )
        self.assertTrue(
            renew_analysis_job_reservation(
                job_id=job_payload["job_id"],
                request_fingerprint=fingerprint,
                reservation_token=recovered["reservation_token"],
            )
        )
        stale_job_payload = {
            **job_payload,
            "idempotency": {
                "contract_version": "analysis_job_idempotency.v1",
                "request_fingerprint": fingerprint,
                "reservation_token": original["reservation_token"],
                "reservation_generation": original["reservation_generation"],
            },
        }
        with self.assertRaises(ValueError):
            enqueue_analysis_job_work(payload, stale_job_payload)
        job_payload["idempotency"] = {
            "contract_version": "analysis_job_idempotency.v1",
            "request_fingerprint": fingerprint,
            "reservation_token": recovered["reservation_token"],
            "reservation_generation": recovered["reservation_generation"],
        }
        enqueue_analysis_job_work(payload, job_payload)
        self.assertEqual(
            AnalysisJob.objects.get(job_id=job_payload["job_id"]).metadata["idempotency"][
                "reservation_token"
            ],
            recovered["reservation_token"],
        )

    def test_heartbeat_refreshes_only_the_current_worker_attempt(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_worker_heartbeat",
            session_id="ses_worker_heartbeat",
            job_id="job_worker_heartbeat",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        stale_locked_at = timezone.now() - timedelta(hours=1)
        AgentWorkItem.objects.filter(work_item_id=queued["work_item_id"]).update(
            status=AgentWorkItemStatus.RUNNING,
            attempt_no=3,
            locked_at=stale_locked_at,
        )

        refreshed = _refresh_agent_work_item_lease(
            queued["work_item_id"],
            expected_attempt_no=3,
        )
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        refreshed_at = work_item.locked_at
        stale_attempt = _refresh_agent_work_item_lease(
            queued["work_item_id"],
            expected_attempt_no=2,
        )
        work_item.refresh_from_db()

        self.assertTrue(refreshed)
        self.assertGreater(refreshed_at, stale_locked_at)
        self.assertFalse(stale_attempt)
        self.assertEqual(work_item.locked_at, refreshed_at)

    def test_post_persists_only_queued_rows_before_worker_execution(self) -> None:
        owner_id = "usr_analysis_queue"
        session_id = "ses_analysis_queue"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        chat_response = _chat_response(
            session_id=session_id,
            message_id="msg_analysis_queue",
            plan_id="plan_analysis_queue",
        )

        with patch("chatbot.views.submit_message", return_value=chat_response):
            response = client.post(
                "/api/analysis/jobs/",
                data={"session_id": session_id, "user_text": "도로교통법 근거를 찾아줘"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 202)
        job_id = response.json()["job"]["job_id"]
        job = AnalysisJob.objects.get(job_id=job_id)
        work_item = AgentWorkItem.objects.get(job=job)
        self.assertEqual(job.owner_id, owner_id)
        self.assertEqual(job.status, AnalysisJobStatus.QUEUED)
        self.assertEqual(work_item.status, AgentWorkItemStatus.QUEUED)
        self.assertEqual(list(job.events.values_list("status", flat=True)), [AnalysisJobStatus.QUEUED])
        self.assertFalse(AgentResult.objects.filter(job=job).exists())
        self.assertFalse(AgentInvocation.objects.filter(job=job).exists())

    def test_public_chat_queue_worker_result_uses_server_supervisor_handoff(self) -> None:
        owner_id = "usr_public_server_handoff"
        session_id = "ses_public_server_handoff"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        chat_response = _server_authoritative_chat_response(
            session_id=session_id,
            message_id="msg_public_server_handoff",
            plan_id="plan_public_server_handoff",
        )

        with patch("chatbot.views.submit_message", return_value=chat_response):
            accepted = client.post(
                "/api/chat/messages/",
                data={
                    "session_id": session_id,
                    "user_text": "client supplied question",
                    "agent_input": {"node_code": "objection_report_generation"},
                    "node_code": "objection_report_generation",
                    "slot_state": {"client": True},
                    "upstream_results": {"law_ground_search": {"status": "success"}},
                    "search_query": "client search override",
                    "context": {
                        "query": {"search_query": "client context query"},
                        "supervisor_handoff": {"client": True},
                    },
                },
                content_type="application/json",
            )

        self.assertEqual(accepted.status_code, 202)
        job_id = accepted.json()["work_item"]["job_id"]
        work_item = AgentWorkItem.objects.get(job__job_id=job_id)
        persisted_payload = work_item.payload["execution_payload"]
        self.assertEqual(persisted_payload["upstream_results"], {})
        self.assertEqual(
            persisted_payload["context"]["supervisor_handoff"],
            chat_response["supervisor_state"],
        )
        for field in ("agent_input", "node_code", "slot_state"):
            self.assertNotIn(field, persisted_payload)

        adapter_output = {
            "status": "success",
            "summary": "server plan completed",
            "structured_result": {"matched_laws": ["law:server"]},
            "evidence": [],
            "next_actions": [],
            "limitations": [],
        }
        with patch(
            "app.services.agent_node_service._run_sync_adapter",
            return_value=adapter_output,
        ) as run_adapter:
            processed = process_agent_work_item(work_item.work_item_id)

        self.assertEqual(processed["status"], AgentWorkItemStatus.SUCCESS)
        adapter_input = run_adapter.call_args.args[0]
        self.assertEqual(adapter_input["node_code"], "law_ground_search")
        self.assertEqual(adapter_input["user_text"], "server approved question")
        self.assertEqual(
            adapter_input["slot_state"],
            chat_response["supervisor_state"]["slot_state"],
        )
        self.assertEqual(adapter_input["upstream_results"], {})
        self.assertEqual(
            adapter_input["context"]["query"]["search_query"],
            "server approved question",
        )

        result_response = client.get(f"/api/analysis/results/{job_id}/")

        self.assertEqual(result_response.status_code, 200)
        result = result_response.json()["result"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            result["supervisor_state"]["agent_input_packages"],
            [{"node_code": "law_ground_search"}],
        )
        self.assertNotIn("slot_state", result["supervisor_state"])
        execution = result["supervisor_execution"]
        self.assertEqual(execution["job_id"], job_id)
        self.assertNotIn("plan_id", execution)
        self.assertTrue(execution["node_results"])
        self.assertEqual(execution["node_results"][0]["node_code"], "law_ground_search")
        self.assertEqual(execution["node_results"][0]["status"], "success")
        self.assertEqual(
            execution["node_results"][0]["structured_result"],
            {"matched_laws": ["law:server"]},
        )
        for field in (
            "analysis_plan",
            "node_execution",
            "chat_response",
            "agent_results",
            "structured_results",
            "supervisor_reporting_handoff",
            "reporting_pipeline",
        ):
            self.assertNotIn(field, result)

    def test_public_analysis_queue_worker_result_uses_server_supervisor_handoff(self) -> None:
        owner_id = "usr_public_analysis_server_handoff"
        session_id = "ses_public_analysis_server_handoff"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        chat_response = _server_authoritative_chat_response(
            session_id=session_id,
            message_id="msg_public_analysis_server_handoff",
            plan_id="plan_public_analysis_server_handoff",
        )

        with patch("chatbot.views.submit_message", return_value=chat_response):
            accepted = client.post(
                "/api/analysis/jobs/",
                data={
                    "session_id": session_id,
                    "user_text": "client supplied question",
                    "agent_input": {"node_code": "objection_report_generation"},
                    "node_code": "objection_report_generation",
                    "slot_state": {"client": True},
                    "upstream_results": {"law_ground_search": {"status": "success"}},
                    "search_query": "client search override",
                    "context": {
                        "query": {"search_query": "client context query"},
                        "law_graph": {"enabled": True},
                        "supervisor_handoff": {"client": True},
                    },
                },
                content_type="application/json",
            )

        self.assertEqual(accepted.status_code, 202)
        job_id = accepted.json()["job"]["job_id"]
        work_item = AgentWorkItem.objects.get(job__job_id=job_id)
        persisted_payload = work_item.payload["execution_payload"]
        self.assertEqual(persisted_payload["upstream_results"], {})
        self.assertEqual(
            persisted_payload["context"]["supervisor_handoff"],
            chat_response["supervisor_state"],
        )
        self.assertNotIn("search_query", persisted_payload)
        self.assertNotIn("query", persisted_payload["context"])
        self.assertNotIn("law_graph", persisted_payload["context"])

        adapter_output = {
            "status": "success",
            "summary": "server plan completed",
            "structured_result": {"matched_laws": ["law:server"]},
            "evidence": [],
            "next_actions": [],
            "limitations": [],
        }
        with patch(
            "app.services.agent_node_service._run_sync_adapter",
            return_value=adapter_output,
        ) as run_adapter:
            processed = process_agent_work_item(work_item.work_item_id)

        self.assertEqual(processed["status"], AgentWorkItemStatus.SUCCESS)
        adapter_input = run_adapter.call_args.args[0]
        self.assertEqual(adapter_input["node_code"], "law_ground_search")
        self.assertEqual(adapter_input["user_text"], "server approved question")
        self.assertEqual(
            adapter_input["slot_state"],
            chat_response["supervisor_state"]["slot_state"],
        )
        self.assertEqual(
            adapter_input["context"]["query"]["search_query"],
            "server approved question",
        )

        result_response = client.get(f"/api/analysis/results/{job_id}/")

        self.assertEqual(result_response.status_code, 200)
        self.assertEqual(result_response.json()["result"]["status"], "success")

    def test_reenqueue_preserves_terminal_job_and_work_item(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_queue_idempotent",
            session_id="ses_queue_idempotent",
            job_id="job_queue_idempotent",
        )
        first = enqueue_analysis_job_work(payload, job_payload)
        job = AnalysisJob.objects.get(job_id=first["job_id"])
        work_item = AgentWorkItem.objects.get(work_item_id=first["work_item_id"])
        job.status = AnalysisJobStatus.SUCCESS
        job.save(update_fields=["status", "updated_at"])
        work_item.status = AgentWorkItemStatus.SUCCESS
        work_item.attempt_no = 1
        work_item.completed_at = timezone.now()
        work_item.result = {"status": "success"}
        work_item.save(
            update_fields=["status", "attempt_no", "completed_at", "result", "updated_at"]
        )
        event_count = job.events.count()

        second = enqueue_analysis_job_work(payload, job_payload)

        job.refresh_from_db()
        work_item.refresh_from_db()
        self.assertEqual(second["work_item_status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(job.status, AnalysisJobStatus.SUCCESS)
        self.assertEqual(work_item.status, AgentWorkItemStatus.SUCCESS)
        self.assertEqual(work_item.attempt_no, 1)
        self.assertEqual(work_item.result, {"status": "success"})
        self.assertEqual(job.events.count(), event_count)

    def test_reenqueue_rejects_cross_owner_job_collision(self) -> None:
        owner_payload, job_payload = _queue_payload(
            owner_id="usr_queue_owner",
            session_id="ses_queue_owner",
            job_id="job_queue_collision",
        )
        enqueue_analysis_job_work(owner_payload, job_payload)
        other_payload = {**owner_payload, "owner_id": "usr_queue_other", "user_id": "usr_queue_other"}

        with self.assertRaises(PermissionError):
            enqueue_analysis_job_work(other_payload, job_payload)

        job = AnalysisJob.objects.get(job_id="job_queue_collision")
        self.assertEqual(job.owner_id, "usr_queue_owner")

    def test_reenqueue_rejects_legacy_blank_owner_from_another_principal(self) -> None:
        session = ChatSession.objects.create(
            session_id="ses_legacy_owner",
            owner_id="usr_legacy_owner",
            status=ChatSessionStatus.ACTIVE,
        )
        AnalysisJob.objects.create(
            job_id="job_legacy_blank_owner",
            session=session,
            owner_id="",
            status=AnalysisJobStatus.QUEUED,
        )
        other_payload, job_payload = _queue_payload(
            owner_id="usr_legacy_attacker",
            session_id=session.session_id,
            job_id="job_legacy_blank_owner",
        )

        with self.assertRaises(PermissionError):
            enqueue_analysis_job_work(other_payload, job_payload)

        self.assertFalse(AgentWorkItem.objects.filter(job__job_id="job_legacy_blank_owner").exists())

    def test_reenqueue_rejects_same_owner_job_bound_to_another_session(self) -> None:
        owner_id = "usr_session_binding"
        first_payload, first_job_payload = _queue_payload(
            owner_id=owner_id,
            session_id="ses_binding_first",
            job_id="job_session_binding",
        )
        enqueue_analysis_job_work(first_payload, first_job_payload)
        second_payload, second_job_payload = _queue_payload(
            owner_id=owner_id,
            session_id="ses_binding_second",
            job_id="job_session_binding",
        )

        with self.assertRaises(ValueError):
            enqueue_analysis_job_work(second_payload, second_job_payload)

        job = AnalysisJob.objects.get(job_id="job_session_binding")
        self.assertEqual(job.session.session_id, "ses_binding_first")

    def test_terminal_job_without_work_item_cannot_be_requeued(self) -> None:
        owner_id = "usr_terminal_without_work"
        session = ChatSession.objects.create(
            session_id="ses_terminal_without_work",
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        AnalysisJob.objects.create(
            job_id="job_terminal_without_work",
            session=session,
            owner_id=owner_id,
            status=AnalysisJobStatus.SUCCESS,
            analysis_plan_id="plan_job_terminal_without_work",
        )
        payload, job_payload = _queue_payload(
            owner_id=owner_id,
            session_id=session.session_id,
            job_id="job_terminal_without_work",
        )

        with self.assertRaises(ValueError):
            enqueue_analysis_job_work(payload, job_payload)

        self.assertFalse(AgentWorkItem.objects.filter(job__job_id="job_terminal_without_work").exists())

    def test_worker_executes_work_item_once_and_skips_terminal_reclaim(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_worker_once",
            session_id="ses_worker_once",
            job_id="job_worker_once",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)

        with patch(
            "app.services.agent_node_service.execute_agent_plan",
            wraps=agent_node_service.execute_agent_plan,
        ) as execute_plan:
            first = process_agent_work_item(queued["work_item_id"])
            result_count = AgentResult.objects.filter(job__job_id=queued["job_id"]).count()
            invocation_count = AgentInvocation.objects.filter(job__job_id=queued["job_id"]).count()
            second = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(first["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["reason"], "work_item_not_queued")
        self.assertEqual(execute_plan.call_count, 1)
        self.assertGreater(result_count, 0)
        self.assertGreater(invocation_count, 0)
        self.assertEqual(
            AgentResult.objects.filter(job__job_id=queued["job_id"]).count(),
            result_count,
        )
        self.assertEqual(
            AgentInvocation.objects.filter(job__job_id=queued["job_id"]).count(),
            invocation_count,
        )

    def test_worker_restoration_discards_legacy_public_execution_controls(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_restored_public_input",
            session_id="ses_restored_public_input",
            job_id="job_restored_public_input",
        )
        payload.update(
            {
                "agent_input": {"node_code": "objection_report_generation"},
                "node_code": "objection_report_generation",
                "slot_state": {"client": True},
                "upstream_results": {"law_ground_search": {"status": "success"}},
                "context": {"supervisor_handoff": {"client": True}},
            }
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])

        restored = repository_module._resolved_agent_work_item_execution_payload(work_item)

        self.assertEqual(restored["upstream_results"], {})
        self.assertNotIn("supervisor_handoff", restored["context"])
        for field in ("agent_input", "node_code", "slot_state"):
            self.assertNotIn(field, restored)

    def test_worker_restoration_uses_enqueued_server_execution_context_not_payload_field(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_server_execution_context",
            session_id="ses_server_execution_context",
            job_id="job_server_execution_context",
        )
        payload["context"] = {
            "user_facts": "payload-controlled facts",
            "case_evidence": {"source": "payload"},
        }
        payload["server_execution_context"] = {
            "contract_version": "server_execution_context.v1",
            "context": {"user_facts": "forged payload facts"},
        }
        trusted_context = {
            "user_facts": "server-confirmed facts",
            "case_evidence": {"source": "server"},
        }
        queued = enqueue_analysis_job_work(
            payload,
            job_payload,
            server_execution_context=trusted_context,
        )
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])

        self.assertEqual(
            work_item.payload["server_execution_context"],
            {
                "contract_version": "server_execution_context.v1",
                "context": trusted_context,
            },
        )
        self.assertNotIn(
            "server_execution_context",
            work_item.payload["execution_payload"],
        )
        self.assertNotIn(
            "server_execution_context",
            work_item.payload["request_payload"],
        )

        restored = repository_module._resolved_agent_work_item_execution_payload(work_item)

        self.assertEqual(restored["context"]["user_facts"], "server-confirmed facts")
        self.assertEqual(restored["context"]["case_evidence"], {"source": "server"})

    def test_worker_restoration_rebuilds_non_supervisor_checkpoint_from_persisted_results(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_restored_server_checkpoint",
            session_id="ses_restored_server_checkpoint",
            job_id="job_restored_server_checkpoint",
        )
        payload["upstream_results"] = {"law_ground_search": {"status": "client"}}
        queued = enqueue_analysis_job_work(payload, job_payload)
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        AgentResult.objects.create(
            result_id="res_restored_server_checkpoint",
            job=work_item.job,
            node_code="law_ground_search",
            status="success",
            summary="persisted server checkpoint",
            structured_result={"matched_laws": ["law:server"]},
        )

        restored = repository_module._resolved_agent_work_item_execution_payload(work_item)

        self.assertEqual(
            restored["upstream_results"],
            {
                "law_ground_search": {
                    "result_id": "res_restored_server_checkpoint",
                    "node_code": "law_ground_search",
                    "status": "success",
                    "summary": "persisted server checkpoint",
                    "structured_result": {"matched_laws": ["law:server"]},
                    "evidence": [],
                    "next_actions": [],
                    "limitations": [],
                }
            },
        )

    def test_non_supervisor_worker_resumes_from_persisted_results_only(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_worker_server_checkpoint",
            session_id="ses_worker_server_checkpoint",
            job_id="job_worker_server_checkpoint",
        )
        payload["upstream_results"] = {"law_ground_search": {"status": "client"}}
        job_payload["analysis_plan"]["steps"].append(
            {
                "order": 2,
                "node_code": "appeal_decision_flow",
                "status": "ready",
                "depends_on": ["law_ground_search"],
                "required_inputs": [],
            }
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        AgentResult.objects.create(
            result_id="res_worker_server_checkpoint",
            job=work_item.job,
            node_code="law_ground_search",
            status="success",
            summary="persisted server checkpoint",
        )

        with patch(
            "app.services.agent_node_service._run_sync_adapter",
            return_value={
                "status": "success",
                "summary": "resumed server step",
                "structured_result": {},
                "evidence": [],
                "next_actions": [],
                "limitations": [],
            },
        ) as run_adapter:
            processed = process_agent_work_item(work_item.work_item_id)

        self.assertEqual(processed["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(run_adapter.call_count, 1)
        resumed_input = run_adapter.call_args.args[0]
        self.assertEqual(resumed_input["node_code"], "appeal_decision_flow")
        self.assertEqual(
            resumed_input["upstream_results"]["law_ground_search"]["status"],
            "success",
        )

    def test_worker_blocks_public_plan_without_supervisor_handoff_before_adapter_call(self) -> None:
        owner_id = "usr_missing_supervisor_handoff"
        session_id = "ses_missing_supervisor_handoff"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        chat_response = _chat_response(
            session_id=session_id,
            message_id="msg_missing_supervisor_handoff",
            plan_id="plan_missing_supervisor_handoff",
        )
        chat_response["analysis_plan"]["steps"][0].update(
            {"status": "ready", "depends_on": [], "required_inputs": ["user_text"]}
        )

        with patch("chatbot.views.submit_message", return_value=chat_response):
            accepted = client.post(
                "/api/chat/messages/",
                data={"session_id": session_id, "user_text": "client text"},
                content_type="application/json",
            )

        self.assertEqual(accepted.status_code, 202)
        work_item = AgentWorkItem.objects.get(
            job__job_id=accepted.json()["work_item"]["job_id"]
        )
        self.assertTrue(
            work_item.payload["execution_payload"]["requires_supervisor_handoff"]
        )
        with patch("app.services.agent_node_service._run_sync_adapter") as run_adapter:
            processed = process_agent_work_item(work_item.work_item_id)

        run_adapter.assert_not_called()
        self.assertEqual(processed["error_code"], "supervisor_handoff_invalid")
        self.assertFalse(
            AgentInvocation.objects.filter(
                job=work_item.job,
                node_code="__paid_analysis_phase__",
            ).exists()
        )

    def test_worker_blocks_malformed_supervisor_package_before_adapter_call(self) -> None:
        owner_id = "usr_malformed_supervisor_package"
        session_id = "ses_malformed_supervisor_package"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        chat_response = _server_authoritative_chat_response(
            session_id=session_id,
            message_id="msg_malformed_supervisor_package",
            plan_id="plan_malformed_supervisor_package",
        )
        chat_response["supervisor_state"]["agent_input_packages"][0]["payload"] = {}

        with patch("chatbot.views.submit_message", return_value=chat_response):
            accepted = client.post(
                "/api/chat/messages/",
                data={"session_id": session_id, "user_text": "client text"},
                content_type="application/json",
            )

        self.assertEqual(accepted.status_code, 202)
        work_item = AgentWorkItem.objects.get(
            job__job_id=accepted.json()["work_item"]["job_id"]
        )
        with patch("app.services.agent_node_service._run_sync_adapter") as run_adapter:
            processed = process_agent_work_item(work_item.work_item_id)

        run_adapter.assert_not_called()
        self.assertEqual(processed["error_code"], "supervisor_handoff_invalid")
        self.assertFalse(
            AgentInvocation.objects.filter(
                job=work_item.job,
                node_code="__paid_analysis_phase__",
            ).exists()
        )

    def test_enqueue_uses_the_sessions_authoritative_case_binding(self) -> None:
        owner_id = "usr_enqueue_existing_case"
        case = Case.objects.create(
            case_id="case_enqueue_existing_case",
            owner_id=owner_id,
            title="Authoritative enqueue case",
        )
        ChatSession.objects.create(
            session_id="ses_enqueue_existing_case",
            owner_id=owner_id,
            case=case,
            status=ChatSessionStatus.ACTIVE,
        )
        payload, job_payload = _queue_payload(
            owner_id=owner_id,
            session_id="ses_enqueue_existing_case",
            job_id="job_enqueue_existing_case",
        )

        queued = enqueue_analysis_job_work(payload, job_payload)

        job = AnalysisJob.objects.get(job_id=queued["job_id"])
        self.assertEqual(job.case, case)

    def test_non_reporting_plan_never_repeats_paid_call_after_final_store_failure(
        self,
    ) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_no_report_cost_guard",
            session_id="ses_no_report_cost_guard",
            job_id="job_no_report_cost_guard",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        node_execution = {
            "execution_mode": "sync",
            "job_id": queued["job_id"],
            "plan_id": job_payload["analysis_plan_id"],
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "node_code": "law_ground_search",
                        "status": "success",
                    },
                }
            ],
            "status_counts": {"success": 1},
            "completed_node_codes": ["law_ground_search"],
            "limitations": [],
        }

        with (
            patch(
                "app.services.agent_node_service.execute_agent_plan",
                return_value=node_execution,
            ) as execute_plan,
            patch(
                "chatbot.repositories.persist_analysis_job_execution",
                side_effect=RuntimeError("final store unavailable"),
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
        self.assertEqual(execute_plan.call_count, 1)

        second = process_agent_work_item(queued["work_item_id"])
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["reason"], "work_item_not_queued")
        self.assertEqual(execute_plan.call_count, 1)

    def test_non_reporting_checkpoint_allows_store_retry_without_paid_recall(
        self,
    ) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_no_report_checkpoint_resume",
            session_id="ses_no_report_checkpoint_resume",
            job_id="job_no_report_checkpoint_resume",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        node_execution = {
            "execution_mode": "sync",
            "job_id": queued["job_id"],
            "plan_id": job_payload["analysis_plan_id"],
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "node_code": "law_ground_search",
                        "status": "success",
                    },
                }
            ],
            "status_counts": {"success": 1},
            "completed_node_codes": ["law_ground_search"],
            "limitations": [],
        }
        original_persist = repository_module.persist_analysis_job_execution
        persist_calls = 0

        def fail_final_store_once(*args, **kwargs):
            nonlocal persist_calls
            persist_calls += 1
            if persist_calls == 2:
                raise RuntimeError("final store unavailable")
            return original_persist(*args, **kwargs)

        with (
            patch(
                "app.services.agent_node_service.execute_agent_plan",
                return_value=node_execution,
            ) as execute_plan,
            patch(
                "chatbot.repositories.persist_analysis_job_execution",
                side_effect=fail_final_store_once,
            ),
        ):
            first = process_agent_work_item(queued["work_item_id"])
            work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
            work_item.next_run_at = timezone.now()
            work_item.save(update_fields=["next_run_at", "updated_at"])
            second = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(first["status"], AgentWorkItemStatus.RETRYING)
        self.assertEqual(second["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(execute_plan.call_count, 1)
        self.assertEqual(
            AgentResult.objects.filter(job__job_id=queued["job_id"]).count(),
            1,
        )

    def test_mixed_plan_reuses_only_the_dispatched_node_checkpoint(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_mixed_checkpoint_resume",
            session_id="ses_mixed_checkpoint_resume",
            job_id="job_mixed_checkpoint_resume",
        )
        job_payload["analysis_plan"]["steps"].append(
            {
                "order": 2,
                "node_code": "appeal_decision_flow",
                "status": "blocked",
                "depends_on": ["law_ground_search"],
            }
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        node_execution = {
            "execution_mode": "sync",
            "job_id": queued["job_id"],
            "plan_id": job_payload["analysis_plan_id"],
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {
                        "node_code": "law_ground_search",
                        "status": "success",
                    },
                }
            ],
            "status_counts": {"success": 1},
            "completed_node_codes": ["law_ground_search"],
            "limitations": [],
        }
        original_persist = repository_module.persist_analysis_job_execution
        persist_calls = 0

        def fail_final_store_once(*args, **kwargs):
            nonlocal persist_calls
            persist_calls += 1
            if persist_calls == 2:
                raise RuntimeError("final store unavailable")
            return original_persist(*args, **kwargs)

        with (
            patch(
                "app.services.agent_node_service.execute_agent_plan",
                return_value=node_execution,
            ) as execute_plan,
            patch(
                "chatbot.repositories.persist_analysis_job_execution",
                side_effect=fail_final_store_once,
            ),
        ):
            first = process_agent_work_item(queued["work_item_id"])
            work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
            work_item.next_run_at = timezone.now()
            work_item.save(update_fields=["next_run_at", "updated_at"])
            second = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(first["status"], AgentWorkItemStatus.RETRYING)
        self.assertEqual(second["status"], AgentWorkItemStatus.SUCCESS)
        self.assertEqual(execute_plan.call_count, 1)
        guard = AgentInvocation.objects.get(
            job__job_id=queued["job_id"],
            node_code="__paid_analysis_phase__",
        )
        self.assertEqual(guard.metadata["expected_node_codes"], ["law_ground_search"])

    def test_stale_lease_cannot_reserve_or_dispatch_a_paid_call(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_stale_paid_dispatch",
            session_id="ses_stale_paid_dispatch",
            job_id="job_stale_paid_dispatch",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        original_reserve = repository_module._reserve_paid_agent_phase_call

        def steal_lease_before_reserve(*args, **kwargs):
            AgentWorkItem.objects.filter(
                work_item_id=queued["work_item_id"]
            ).update(attempt_no=99)
            return original_reserve(*args, **kwargs)

        with (
            patch(
                "chatbot.repositories._reserve_paid_agent_phase_call",
                side_effect=steal_lease_before_reserve,
            ),
            patch("app.services.agent_node_service.execute_agent_plan") as execute_plan,
        ):
            result = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "stale_worker_lease")
        execute_plan.assert_not_called()
        self.assertFalse(
            AgentInvocation.objects.filter(
                job__job_id=queued["job_id"],
                node_code="__paid_analysis_phase__",
            ).exists()
        )

    def test_stale_dispatch_guard_without_checkpoint_requires_manual_recovery(
        self,
    ) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_stale_guard_recovery",
            session_id="ses_stale_guard_recovery",
            job_id="job_stale_guard_recovery",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        job = AnalysisJob.objects.get(job_id=queued["job_id"])
        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        job.status = AnalysisJobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        work_item.status = AgentWorkItemStatus.RUNNING
        work_item.attempt_no = 1
        work_item.locked_at = timezone.now() - timedelta(hours=1)
        work_item.save(
            update_fields=["status", "attempt_no", "locked_at", "updated_at"]
        )
        AgentInvocation.objects.create(
            invocation_id="ainv_job_stale_guard_recovery_paid_analysis",
            job=job,
            node_code="__paid_analysis_phase__",
            status="running",
            attempt_no=1,
            execution_mode="async_worker",
            started_at=timezone.now() - timedelta(hours=1),
            retryable=False,
            metadata={
                "contract_version": "paid_agent_call_guard.v1",
                "phase": "analysis",
                "state": "dispatch_reserved",
                "automatic_retry_allowed": False,
            },
        )

        with patch("app.services.agent_node_service.execute_agent_plan") as execute_plan:
            result = repository_module.process_agent_work_items(
                limit=1,
                stale_after_seconds=1,
            )

        work_item.refresh_from_db()
        self.assertEqual(result["stale_requeued"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(work_item.status, AgentWorkItemStatus.FAILED)
        self.assertEqual(work_item.error_code, "paid_agent_call_retry_blocked")
        execute_plan.assert_not_called()

    def test_http_retry_with_same_job_id_replays_without_new_usage_or_work(self) -> None:
        owner_id = "usr_http_retry"
        session_id = "ses_http_retry"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        chat_response = _chat_response(
            session_id=session_id,
            message_id="msg_http_retry",
            plan_id="plan_http_retry",
        )
        request_payload = {
            "job_id": "job_http_retry",
            "session_id": session_id,
            "user_text": "retry-safe legal analysis",
        }

        with patch("chatbot.views.submit_message", return_value=chat_response) as submit_message:
            first = client.post(
                "/api/analysis/jobs/",
                data=request_payload,
                content_type="application/json",
            )
            second = client.post(
                "/api/analysis/jobs/",
                data=request_payload,
                content_type="application/json",
            )
            conflicting = client.post(
                "/api/analysis/jobs/",
                data={**request_payload, "user_text": "different analysis request"},
                content_type="application/json",
            )
            fact_conflicting = client.post(
                "/api/analysis/jobs/",
                data={
                    **request_payload,
                    "facts": {"accident_location": "different location"},
                    "conversation_history": [{"role": "user", "content": "different facts"}],
                },
                content_type="application/json",
            )
            work_item_id = AgentWorkItem.objects.get(job__job_id="job_http_retry").work_item_id
            process_agent_work_item(work_item_id)
            completed_retry = client.post(
                "/api/analysis/jobs/",
                data=request_payload,
                content_type="application/json",
            )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["job"]["job_id"], "job_http_retry")
        self.assertTrue(second.json()["job"]["idempotent_replay"])
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.json()["error"]["code"], "analysis_job_id_conflict")
        self.assertEqual(fact_conflicting.status_code, 409)
        self.assertEqual(fact_conflicting.json()["error"]["code"], "analysis_job_id_conflict")
        self.assertEqual(completed_retry.status_code, 200)
        self.assertTrue(completed_retry.json()["job"]["idempotent_replay"])
        self.assertEqual(submit_message.call_count, 1)
        self.assertEqual(AnalysisJob.objects.filter(job_id="job_http_retry").count(), 1)
        self.assertEqual(AgentWorkItem.objects.filter(job__job_id="job_http_retry").count(), 1)
        self.assertEqual(UsageEvent.objects.filter(subject_id=f"user:{owner_id}").count(), 1)

    def test_planner_failure_releases_reservation_without_exposing_error(self) -> None:
        owner_id = "usr_planner_failure"
        session_id = "ses_planner_failure"
        client = _authenticated_client(owner_id)
        ChatSession.objects.create(
            session_id=session_id,
            owner_id=owner_id,
            status=ChatSessionStatus.ACTIVE,
        )
        private_error = "Bearer private-token 010-1234-5678"

        with patch(
            "chatbot.views.submit_message",
            side_effect=RuntimeError(private_error),
        ):
            response = client.post(
                "/api/analysis/jobs/",
                data={
                    "job_id": "job_planner_failure",
                    "session_id": session_id,
                    "user_text": "safe request",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(private_error, response.content.decode("utf-8"))
        self.assertFalse(AnalysisJob.objects.filter(job_id="job_planner_failure").exists())
        usage_event = UsageEvent.objects.get(
            subject_id=f"user:{owner_id}",
            scope="agent_run",
        )
        self.assertEqual(usage_event.amount, 0)
        self.assertEqual(usage_event.metadata["status"], "refunded")
        self.assertEqual(usage_event.metadata["refund_reason"], "analysis_planning_failed")
        quota = UsageQuota.objects.get(subject_id=f"user:{owner_id}", scope="agent_run")
        self.assertEqual(quota.used_count, 0)

    def test_usage_refund_is_idempotent(self) -> None:
        owner_id = "usr_usage_refund"
        UserAccount.objects.create(user_id=owner_id)
        usage = record_usage_event(
            {"owner_id": owner_id, "user_id": owner_id},
            scope="agent_run",
        )

        first = refund_usage_event(usage, reason="request_rejected")
        second = refund_usage_event(usage, reason="request_rejected_again")

        self.assertEqual(first["status"], "refunded")
        self.assertEqual(second["status"], "skipped")
        usage_event = UsageEvent.objects.get(usage_event_id=usage["usage_event_id"])
        quota = UsageQuota.objects.get(quota_id=usage["quota_id"])
        self.assertEqual(usage_event.amount, 0)
        self.assertEqual(usage_event.metadata["refund_reason"], "request_rejected")
        self.assertEqual(quota.used_count, 0)

    def test_stale_worker_attempt_cannot_persist_or_complete_after_reclaim(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_worker_lease",
            session_id="ses_worker_lease",
            job_id="job_worker_lease",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        node_execution = {
            "job_id": queued["job_id"],
            "executions": [
                {
                    "node_code": "law_ground_search",
                    "agent_output": {"status": "success"},
                }
            ],
            "status_counts": {"success": 1},
            "completed_node_codes": ["law_ground_search"],
        }

        def supersede_claim(work_item):
            AgentWorkItem.objects.filter(pk=work_item.pk).update(
                status=AgentWorkItemStatus.RUNNING,
                attempt_no=work_item.attempt_no + 1,
            )
            return node_execution

        with (
            patch(
                "chatbot.repositories._execute_agent_work_item_plan",
                side_effect=supersede_claim,
            ),
            patch("chatbot.repositories.persist_analysis_job_execution") as persist,
        ):
            result = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "stale_worker_lease")
        self.assertEqual(work_item.status, AgentWorkItemStatus.RUNNING)
        self.assertEqual(work_item.attempt_no, 2)
        persist.assert_not_called()

    def test_completed_job_surfaces_pending_questions_from_input_required_agent_output(self) -> None:
        """A node that finishes with status=input_required (e.g. appeal_decision_flow
        asking for the missing user_appeal_reason) must reach the user as a pending
        question on the completed job. Today nothing recomputes pending_questions from
        the finished node_execution -- _completed_job_payload_for_work_item only carries
        forward the pre-execution chat_response, which is always empty at queue time.
        """
        payload, job_payload = _queue_payload(
            owner_id="usr_worker_input_required",
            session_id="ses_worker_input_required",
            job_id="job_worker_input_required",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        node_execution = {
            "job_id": queued["job_id"],
            "executions": [
                {
                    "node_code": "appeal_decision_flow",
                    "agent_output": {
                        "node_code": "appeal_decision_flow",
                        "status": "partial",
                        "execution_status": "input_required",
                        "summary": "이의신청 사유 정보 필요",
                        "structured_result": {
                            "judgment_status": "input_required",
                            "missing_fields": ["user_appeal_reason"],
                        },
                        "evidence": [],
                        "next_actions": [
                            "Supervisor가 사용자에게 이의신청 사유 질문 후 재호출"
                        ],
                        "limitations": [],
                    },
                }
            ],
            "status_counts": {"partial": 1},
            "completed_node_codes": ["appeal_decision_flow"],
        }

        with patch(
            "chatbot.repositories._execute_agent_work_item_plan",
            return_value=node_execution,
        ):
            result = process_agent_work_item(queued["work_item_id"])

        self.assertEqual(result["status"], AgentWorkItemStatus.SUCCESS)
        job = AnalysisJob.objects.get(job_id=queued["job_id"])
        pending_questions = job.metadata.get("pending_questions") or []
        self.assertTrue(
            any(q.get("field") == "user_appeal_reason" for q in pending_questions),
            f"expected a pending question for user_appeal_reason, got {pending_questions!r}",
        )

    def test_worker_failure_persists_only_stable_error_metadata(self) -> None:
        payload, job_payload = _queue_payload(
            owner_id="usr_worker_private_error",
            session_id="ses_worker_private_error",
            job_id="job_worker_private_error",
        )
        queued = enqueue_analysis_job_work(payload, job_payload)
        private_error = (
            "홍길동 010-1234-5678 Bearer "
            "eyJhbGciOiJIUzI1NiJ9.payload.signature provider secret"
        )

        with patch(
            "chatbot.repositories._execute_agent_work_item_plan",
            side_effect=RuntimeError(private_error),
        ):
            result = process_agent_work_item(queued["work_item_id"])

        work_item = AgentWorkItem.objects.get(work_item_id=queued["work_item_id"])
        self.assertNotIn(private_error, repr({"result": result, "work_item": work_item.result}))
        self.assertEqual(work_item.error_code, "PaidAgentCallRetryBlockedError")
        self.assertEqual(work_item.result["message"], "Agent worker execution failed.")
