"""Routes that are reachable only through ``config.mock_urls`` in local tests."""

from __future__ import annotations

from django.urls import path

from chatbot import mock_views


app_name = "explicit_mock"

urlpatterns = [
    path("attachments/", mock_views.attachments, name="attachments"),
    path("analysis/jobs/", mock_views.analysis_jobs, name="analysis-jobs"),
    path("history/", mock_views.history, name="history"),
    path("agents/plans/", mock_views.agent_plan, name="agent-plan"),
]
