from __future__ import annotations

from datetime import datetime, timedelta, timezone as datetime_timezone
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from chatbot.models import (
    AgentInvocation,
    AgentInvocationStatus,
    AgentWorkItem,
    AgentWorkItemStatus,
    AnalysisJob,
    ChatSession,
)
from chatbot.operational_observability import build_operational_health_snapshot


class OperationalObservabilityTests(TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 24, 2, 0, tzinfo=datetime_timezone.utc)
        self.session = ChatSession.objects.create(session_id="sess_ops")
        self.job = AnalysisJob.objects.create(
            job_id="job_ops",
            session=self.session,
        )

    def test_empty_operational_snapshot_is_safe_and_passes(self):
        snapshot = build_operational_health_snapshot(
            observed_at=self.now,
            legal_run_summary_path="",
        )

        self.assertEqual(snapshot["contract_version"], "operational_health.v1")
        self.assertEqual(snapshot["event_type"], "operational_health")
        self.assertEqual(snapshot["status"], "pass")
        self.assertEqual(snapshot["queue"]["queued_count"], 0)
        self.assertEqual(snapshot["alerts"], [])

    def test_queue_running_and_retry_states_create_deterministic_alerts(self):
        oldest = AgentWorkItem.objects.create(
            work_item_id="work_queued_oldest",
            job=self.job,
            status=AgentWorkItemStatus.QUEUED,
        )
        recent = AgentWorkItem.objects.create(
            work_item_id="work_queued_recent",
            job=self.job,
            status=AgentWorkItemStatus.QUEUED,
        )
        AgentWorkItem.objects.filter(pk=oldest.pk).update(
            created_at=self.now - timedelta(seconds=600),
        )
        AgentWorkItem.objects.filter(pk=recent.pk).update(
            created_at=self.now - timedelta(seconds=60),
        )
        AgentWorkItem.objects.create(
            work_item_id="work_running_stale",
            job=self.job,
            status=AgentWorkItemStatus.RUNNING,
            locked_at=self.now - timedelta(seconds=601),
        )
        AgentWorkItem.objects.create(
            work_item_id="work_retrying",
            job=self.job,
            status=AgentWorkItemStatus.RETRYING,
            next_run_at=self.now + timedelta(seconds=60),
        )

        snapshot = build_operational_health_snapshot(
            observed_at=self.now,
            queue_age_warn_seconds=300,
            lease_stale_seconds=300,
        )

        self.assertEqual(snapshot["queue"]["queued_count"], 2)
        self.assertEqual(snapshot["queue"]["oldest_queued_age_seconds"], 600)
        self.assertEqual(snapshot["queue"]["running_count"], 1)
        self.assertEqual(snapshot["queue"]["stale_running_count"], 1)
        self.assertEqual(snapshot["worker"]["retrying_count"], 1)
        self.assertEqual(
            [item["code"] for item in snapshot["alerts"]],
            [
                "queue_backlog",
                "queue_oldest_age_exceeded",
                "worker_lease_stale",
                "worker_retrying",
            ],
        )

    def test_recent_worker_and_provider_failures_are_safely_categorized(self):
        timeout_work = AgentWorkItem.objects.create(
            work_item_id="work_timeout",
            job=self.job,
            status=AgentWorkItemStatus.FAILED,
            completed_at=self.now - timedelta(minutes=2),
            error_code="vision_remote_timeout",
            metadata={
                "user_query": "홍길동의 사고 영상",
                "signed_url": "https://objects.example/private?secret=token",
            },
        )
        failed_work = AgentWorkItem.objects.create(
            work_item_id="work_failed",
            job=self.job,
            status=AgentWorkItemStatus.FAILED,
            completed_at=self.now - timedelta(minutes=3),
            error_code="arbitrary-provider-error-with-secret",
        )
        AgentWorkItem.objects.filter(pk__in=[timeout_work.pk, failed_work.pk]).update(
            updated_at=self.now - timedelta(minutes=1),
        )
        invocation = AgentInvocation.objects.create(
            invocation_id="inv_vision_failed",
            job=self.job,
            node_code="vision_media_analysis",
            status=AgentInvocationStatus.FAILED,
            completed_at=self.now - timedelta(minutes=1),
            error_code="vision_remote_unavailable",
            metadata={
                "api_key": "runpod-secret",
                "provider_response": "private upstream diagnostic",
            },
        )
        AgentInvocation.objects.filter(pk=invocation.pk).update(
            created_at=self.now - timedelta(minutes=1),
        )

        snapshot = build_operational_health_snapshot(
            observed_at=self.now,
            window_minutes=15,
        )

        self.assertEqual(snapshot["worker"]["recent_failure_count"], 2)
        self.assertEqual(snapshot["worker"]["recent_timeout_count"], 1)
        self.assertEqual(snapshot["providers"]["recent_failure_count"], 1)
        self.assertEqual(snapshot["providers"]["roles"], {"vision": 1})
        self.assertEqual(
            [item["code"] for item in snapshot["alerts"]],
            ["worker_failure", "worker_timeout", "provider_failure"],
        )
        rendered = str(snapshot)
        for forbidden in (
            "홍길동",
            "objects.example",
            "secret=token",
            "arbitrary-provider-error",
            "runpod-secret",
            "private upstream diagnostic",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_legal_run_summary_reports_verified_dataset_without_source_details(self):
        with TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "run_summary.json"
            summary_path.write_text(
                json.dumps(
                    self._legal_summary(
                        last_verified_at=self.now - timedelta(hours=1),
                    )
                ),
                encoding="utf-8",
            )

            snapshot = build_operational_health_snapshot(
                observed_at=self.now,
                legal_run_summary_path=str(summary_path),
                legal_max_age_hours=24,
                legal_required_sources=["traffic_act"],
                legal_expected_dataset_version="dataset-v1",
                legal_expected_release_version="release-abc123",
            )

        self.assertEqual(
            snapshot["legal_data"],
            {
                "status": "success",
                "dataset_version": "dataset-v1",
                "release_version": "release-abc123",
                "missing_source_count": 0,
                "failed_source_count": 0,
                "stale_source_count": 0,
                "issue_count": 0,
            },
        )
        self.assertEqual(snapshot["alerts"], [])
        self.assertNotIn("traffic_act", str(snapshot))

    def test_legal_run_summary_missing_stale_and_invalid_are_distinct(self):
        missing = build_operational_health_snapshot(
            observed_at=self.now,
            legal_run_summary_path="Z:/does-not-exist/run_summary.json",
        )
        self.assertEqual(missing["legal_data"]["status"], "missing")
        self.assertEqual(missing["legal_data"]["issue_count"], 1)
        self.assertEqual(
            [item["code"] for item in missing["alerts"]],
            ["legal_data_missing"],
        )

        with TemporaryDirectory() as temp_dir:
            stale_path = Path(temp_dir) / "stale.json"
            stale_path.write_text(
                json.dumps(
                    self._legal_summary(
                        last_verified_at=self.now - timedelta(hours=25),
                    )
                ),
                encoding="utf-8",
            )
            stale = build_operational_health_snapshot(
                observed_at=self.now,
                legal_run_summary_path=str(stale_path),
                legal_max_age_hours=24,
                legal_required_sources=["traffic_act"],
                legal_expected_dataset_version="dataset-v1",
                legal_expected_release_version="release-abc123",
            )
            invalid_path = Path(temp_dir) / "invalid.json"
            invalid_path.write_text("{not-json", encoding="utf-8")
            invalid = build_operational_health_snapshot(
                observed_at=self.now,
                legal_run_summary_path=str(invalid_path),
            )

        self.assertEqual(stale["legal_data"]["stale_source_count"], 1)
        self.assertEqual(stale["legal_data"]["issue_count"], 1)
        self.assertEqual(
            [item["code"] for item in stale["alerts"]],
            ["legal_data_stale"],
        )
        self.assertEqual(invalid["legal_data"]["status"], "invalid")
        self.assertEqual(
            [item["code"] for item in invalid["alerts"]],
            ["monitor_configuration_invalid"],
        )
        self.assertNotIn("not-json", str(invalid))

    def test_legal_run_summary_provenance_mismatch_fails_closed(self):
        with TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "run_summary.json"
            summary_path.write_text(
                json.dumps(
                    self._legal_summary(
                        last_verified_at=self.now - timedelta(hours=1),
                    )
                ),
                encoding="utf-8",
            )

            dataset_mismatch = build_operational_health_snapshot(
                observed_at=self.now,
                legal_run_summary_path=str(summary_path),
                legal_max_age_hours=24,
                legal_required_sources=["traffic_act"],
                legal_expected_dataset_version="dataset-v2",
                legal_expected_release_version="release-abc123",
            )
            release_mismatch = build_operational_health_snapshot(
                observed_at=self.now,
                legal_run_summary_path=str(summary_path),
                legal_max_age_hours=24,
                legal_required_sources=["traffic_act"],
                legal_expected_dataset_version="dataset-v1",
                legal_expected_release_version="release-different",
            )

        for snapshot in (dataset_mismatch, release_mismatch):
            with self.subTest(snapshot=snapshot):
                self.assertEqual(snapshot["status"], "fail")
                self.assertEqual(snapshot["legal_data"]["status"], "failed")
                self.assertEqual(
                    snapshot["legal_data"]["reason_code"],
                    "legal_data_provenance_mismatch",
                )
                self.assertEqual(
                    snapshot["alerts"],
                    [
                        {
                            "code": "legal_data_provenance_mismatch",
                            "severity": "critical",
                        }
                    ],
                )

    def test_configured_legal_monitor_requires_safe_expected_versions(self):
        with TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "run_summary.json"
            summary_path.write_text(
                json.dumps(
                    self._legal_summary(
                        last_verified_at=self.now - timedelta(hours=1),
                    )
                ),
                encoding="utf-8",
            )

            snapshot = build_operational_health_snapshot(
                observed_at=self.now,
                legal_run_summary_path=str(summary_path),
                legal_expected_dataset_version="dataset v1",
                legal_expected_release_version="release-abc123",
            )

        self.assertEqual(snapshot["status"], "fail")
        self.assertEqual(snapshot["legal_data"]["status"], "invalid")
        self.assertEqual(
            snapshot["alerts"],
            [
                {
                    "code": "monitor_configuration_invalid",
                    "severity": "critical",
                }
            ],
        )

    @override_settings(
        OPERATIONAL_LEGAL_RUN_SUMMARY_PATH="C:/evidence/run_summary.json",
        OPERATIONAL_LEGAL_REQUIRED_SOURCES=["traffic_act"],
        LEGAL_DATASET_VERSION="dataset-v1",
        APP_RELEASE_VERSION="release-abc123",
    )
    @mock.patch(
        "chatbot.management.commands.observe_operational_health.build_operational_health_snapshot"
    )
    def test_observe_command_passes_expected_provenance(self, snapshot_builder):
        snapshot_builder.return_value = {
            "contract_version": "operational_health.v1",
            "status": "pass",
        }
        stdout = StringIO()

        call_command("observe_operational_health", "--once", stdout=stdout)

        snapshot_builder.assert_called_once()
        kwargs = snapshot_builder.call_args.kwargs
        self.assertEqual(
            kwargs["legal_expected_dataset_version"],
            "dataset-v1",
        )
        self.assertEqual(
            kwargs["legal_expected_release_version"],
            "release-abc123",
        )

    @override_settings(
        LEGAL_DATASET_VERSION="dataset-v1",
        APP_RELEASE_VERSION="release-abc123",
    )
    @mock.patch(
        "chatbot.management.commands.observe_operational_health.build_operational_health_snapshot"
    )
    def test_transaction_gate_accepts_queue_backlog_only(self, snapshot_builder):
        snapshot_builder.return_value = {
            "contract_version": "operational_health.v1",
            "event_type": "operational_health",
            "status": "warn",
            "legal_data": {
                "status": "success",
                "issue_count": 0,
                "dataset_version": "dataset-v1",
                "release_version": "release-abc123",
            },
            "alerts": [{"code": "queue_backlog", "severity": "warning"}],
        }
        stdout = StringIO()

        call_command(
            "observe_operational_health",
            "--once",
            "--gate-mode",
            "transaction",
            stdout=stdout,
        )

        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["gate"]["decision"], "pass")
        self.assertEqual(rendered["gate"]["reason_codes"], [])

    @override_settings(
        LEGAL_DATASET_VERSION="dataset-v1",
        APP_RELEASE_VERSION="release-abc123",
    )
    @mock.patch(
        "chatbot.management.commands.observe_operational_health.build_operational_health_snapshot"
    )
    def test_acceptance_gate_returns_reset_for_warning(self, snapshot_builder):
        snapshot_builder.return_value = {
            "contract_version": "operational_health.v1",
            "event_type": "operational_health",
            "status": "warn",
            "legal_data": {
                "status": "success",
                "issue_count": 0,
                "dataset_version": "dataset-v1",
                "release_version": "release-abc123",
            },
            "alerts": [{"code": "queue_backlog", "severity": "warning"}],
        }
        stdout = StringIO()

        call_command(
            "observe_operational_health",
            "--once",
            "--gate-mode",
            "acceptance",
            stdout=stdout,
        )

        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["gate"]["decision"], "reset")
        self.assertEqual(
            rendered["gate"]["reason_codes"],
            ["acceptance_window_reset"],
        )

    @override_settings(
        LEGAL_DATASET_VERSION="dataset-v1",
        APP_RELEASE_VERSION="release-abc123",
    )
    @mock.patch(
        "chatbot.management.commands.observe_operational_health.build_operational_health_snapshot"
    )
    def test_acceptance_gate_raises_safe_error_for_critical_snapshot(
        self,
        snapshot_builder,
    ):
        snapshot_builder.return_value = {
            "contract_version": "operational_health.v1",
            "event_type": "operational_health",
            "status": "fail",
            "legal_data": {
                "status": "success",
                "issue_count": 0,
                "dataset_version": "dataset-v1",
                "release_version": "release-abc123",
            },
            "alerts": [
                {
                    "code": "provider_failure",
                    "severity": "critical",
                    "private_detail": "secret-provider-diagnostic",
                }
            ],
        }
        stdout = StringIO()

        with self.assertRaisesMessage(
            CommandError,
            "operational health gate rejected snapshot",
        ) as raised:
            call_command(
                "observe_operational_health",
                "--once",
                "--gate-mode",
                "acceptance",
                stdout=stdout,
            )

        self.assertNotIn("secret-provider-diagnostic", str(raised.exception))
        self.assertEqual(json.loads(stdout.getvalue())["gate"]["decision"], "fail")

    def test_observe_command_rejects_gate_mode_with_loop(self):
        with self.assertRaisesMessage(
            CommandError,
            "--gate-mode cannot be combined with --loop",
        ):
            call_command(
                "observe_operational_health",
                "--loop",
                "--gate-mode",
                "transaction",
            )

    def test_observe_command_prints_one_compact_json_line(self):
        stdout = StringIO()

        call_command("observe_operational_health", "--once", stdout=stdout)

        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            json.loads(lines[0])["contract_version"],
            "operational_health.v1",
        )

    @mock.patch(
        "chatbot.management.commands.observe_operational_health.time.sleep",
        side_effect=KeyboardInterrupt,
    )
    def test_observe_loop_stops_cleanly_after_one_snapshot(self, _sleep):
        stdout = StringIO()

        call_command(
            "observe_operational_health",
            "--loop",
            "--interval-seconds",
            "10",
            stdout=stdout,
        )

        self.assertEqual(len(stdout.getvalue().splitlines()), 1)

    def test_observe_command_rejects_unsafe_numeric_options(self):
        invalid_arguments = (
            ("--interval-seconds", "9"),
            ("--window-minutes", "0"),
            ("--queue-age-warn-seconds", "0"),
            ("--lease-stale-seconds", "0"),
            ("--legal-max-age-hours", "0"),
        )
        for name, value in invalid_arguments:
            with self.subTest(name=name):
                with self.assertRaises(CommandError):
                    call_command(
                        "observe_operational_health",
                        "--once",
                        name,
                        value,
                    )

    @mock.patch(
        "chatbot.management.commands.observe_operational_health.build_operational_health_snapshot",
        side_effect=RuntimeError("secret-provider-diagnostic"),
    )
    def test_observe_command_suppresses_unexpected_exception_text(self, _snapshot):
        stdout = StringIO()

        call_command("observe_operational_health", "--once", stdout=stdout)

        rendered = stdout.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(
            payload["alerts"],
            [
                {
                    "code": "monitor_configuration_invalid",
                    "severity": "critical",
                }
            ],
        )
        self.assertNotIn("secret-provider-diagnostic", rendered)

    def _legal_summary(self, *, last_verified_at: datetime) -> dict:
        return {
            "contract_version": "legal_ingestion_run_summary.v2",
            "run_id": "legal_ingestion:test",
            "dataset_version": "dataset-v1",
            "release_version": "release-abc123",
            "source_summaries": [
                {
                    "source_id": "traffic_act",
                    "status": "success",
                    "last_verified_at": last_verified_at.isoformat(),
                }
            ],
        }
