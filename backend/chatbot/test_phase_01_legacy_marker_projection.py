from __future__ import annotations

from django.test import Client, TestCase
from django.utils import timezone

from app.services.guest_credential_service import issue_guest_credential
from chatbot.models import HistoryEvent
from chatbot.repositories import record_history_event_record


MARKERS = ("mock_scenario", "mock_status", "canonical_mock", "mock://")


class LegacyHistoryMarkerProjectionTests(TestCase):
    session_id = "ses_phase_01_legacy_history"
    guest_id = "gst_phase_01_legacy_history"

    def setUp(self) -> None:
        self.client = Client(
            HTTP_X_GUEST_ID=self.guest_id,
            HTTP_X_GUEST_CREDENTIAL=issue_guest_credential(self.guest_id)[0],
        )

    def test_new_canonical_history_write_never_persists_mock_markers(self) -> None:
        event = record_history_event_record(
            event_type="chat_message_created",
            status="success",
            summary="canonical event",
            actor={"guest_id": self.guest_id, "auth_state": "guest"},
            subject={"session_id": self.session_id},
            source={"execution_mode": "canonical"},
            metadata={
                "mock_scenario": "fixture",
                "nested": {"mock_status": "success"},
                "source_uri": "mock://uploads/legacy.txt",
            },
        )

        stored = HistoryEvent.objects.get(event_id=event["event_id"])
        serialized = repr(stored.metadata)
        for marker in MARKERS:
            self.assertNotIn(marker, serialized)

    def test_legacy_history_row_keeps_db_bytes_but_never_projects_mock_markers(self) -> None:
        legacy_metadata = {
            "mock_scenario": "fixture",
            "mock_status": "success",
            "canonical_mock": True,
            "nested": {"source_uri": "mock://uploads/legacy.txt"},
            "safe": "retained",
        }
        HistoryEvent.objects.create(
            event_id="evt_phase_01_legacy_marker",
            event_type="chat_message_created",
            event_version="history_event.v1",
            occurred_at=timezone.now(),
            actor_guest_id=self.guest_id,
            actor_auth_state="guest",
            subject_session_id=self.session_id,
            source_execution_mode="canonical",
            status="success",
            summary="legacy event",
            actor={"guest_id": self.guest_id, "auth_state": "guest"},
            subject={"session_id": self.session_id},
            source={"execution_mode": "canonical"},
            metadata=legacy_metadata,
            privacy={"risk_level": "low"},
        )

        response = self.client.get(f"/api/history/?session_id={self.session_id}")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            HistoryEvent.objects.get(event_id="evt_phase_01_legacy_marker").metadata,
            legacy_metadata,
        )
        public_event = next(
            event
            for event in response.json()["events"]
            if event["event_id"] == "evt_phase_01_legacy_marker"
        )
        serialized = repr(public_event["metadata"])
        for marker in MARKERS:
            self.assertNotIn(marker, serialized)
        self.assertEqual(public_event["metadata"]["safe"], "retained")

    def test_legacy_source_marker_is_normalized_in_the_public_dto_only(self) -> None:
        legacy_source = {
            "surface": "mock",
            "api_path": "mock://history/legacy-event",
            "execution_mode": "canonical_mock",
        }
        HistoryEvent.objects.create(
            event_id="evt_phase_01_legacy_source_marker",
            event_type="chat_message_created",
            event_version="history_event.v1",
            occurred_at=timezone.now(),
            actor_guest_id=self.guest_id,
            actor_auth_state="guest",
            subject_session_id=self.session_id,
            source_execution_mode="canonical_mock",
            status="success",
            summary="legacy source event",
            actor={"guest_id": self.guest_id, "auth_state": "guest"},
            subject={"session_id": self.session_id},
            source=legacy_source,
            metadata={},
            privacy={"risk_level": "low"},
        )

        response = self.client.get(f"/api/history/?session_id={self.session_id}")

        self.assertEqual(response.status_code, 200, response.content)
        stored = HistoryEvent.objects.get(event_id="evt_phase_01_legacy_source_marker")
        self.assertEqual(stored.source, legacy_source)
        public_event = next(
            event
            for event in response.json()["events"]
            if event["event_id"] == "evt_phase_01_legacy_source_marker"
        )
        self.assertEqual(public_event["source"]["execution_mode"], "canonical")
        self.assertEqual(public_event["source"]["surface"], "api")
        self.assertIsNone(public_event["source"]["api_path"])
        self.assertNotIn("canonical_mock", repr(public_event))
        self.assertNotIn("mock://", repr(public_event))
