from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from app.services import agent_node_service
from app.services.google_auth_service import issue_access_token
from chatbot.models import (
    AgentInvocation,
    AgentResult,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    AnalysisJobStatus,
    AuthSession,
    AuthSessionStatus,
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
        self.assertEqual(work_item.error_code, "RuntimeError")
        self.assertEqual(work_item.result["message"], "Agent worker execution failed.")
