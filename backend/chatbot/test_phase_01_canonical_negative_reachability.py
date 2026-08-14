from __future__ import annotations

from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from app.services.agent_node_service import execute_agent_plan
from chatbot.views import _history_source


class CanonicalNegativeReachabilityTests(SimpleTestCase):
    def test_canonical_agent_plan_never_calls_explicit_mock_dispatch(self) -> None:
        with patch("app.mock_runtime.agent_execution.execute_mock_plan") as explicit_mock_plan:
            result = execute_agent_plan({"plan_id": "plan_phase_01", "steps": []}, {})

        explicit_mock_plan.assert_not_called()
        self.assertEqual(result["plan_id"], "plan_phase_01")
        self.assertEqual(result["executions"], [])

    def test_canonical_history_source_never_labels_the_request_as_mock(self) -> None:
        source = _history_source(RequestFactory().get("/api/history/"))

        self.assertEqual(source["execution_mode"], "canonical")
        self.assertNotIn("mock", str(source).lower())
