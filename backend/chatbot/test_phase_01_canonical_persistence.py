from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

from app.services.report_query_service import report_api_surface, report_execution_mode
from chatbot.models import AnalysisJob


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_FILES = (
    "backend/chatbot/views.py",
    "backend/chatbot/repositories.py",
    "backend/chatbot/file_scan_service.py",
    "app/services/agent_node_service.py",
    "app/services/report_query_service.py",
)
PROHIBITED_MARKERS = (
    "mock_scenario",
    "mock_status",
    "canonical_mock",
    "mock://",
    "mock_analysis_jobs",
    "mock_history_events",
)


class CanonicalPersistenceContractTests(SimpleTestCase):
    def test_legacy_physical_column_remains_without_canonical_usage(self) -> None:
        self.assertIsNotNone(AnalysisJob._meta.get_field("mock_scenario"))
        for relative_path in CANONICAL_FILES:
            with self.subTest(relative_path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
                for marker in PROHIBITED_MARKERS:
                    self.assertNotIn(marker, source)

    def test_canonical_report_surface_has_no_mock_public_label(self) -> None:
        self.assertEqual(report_api_surface(canonical=True, source=""), "canonical")
        self.assertEqual(report_api_surface(canonical=True, source="analysis_worker_reporting"), "canonical")
        self.assertEqual(report_execution_mode(source=""), "canonical")
        self.assertEqual(report_execution_mode(source="analysis_worker_reporting"), "async_worker")
