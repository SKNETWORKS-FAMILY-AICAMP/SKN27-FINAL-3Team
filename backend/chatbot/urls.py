"""Mock chatbot API routes for frontend integration."""

from __future__ import annotations

from django.urls import path

from chatbot import views

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path("mock/chat/scenarios/", views.demo_scenarios, name="demo-scenarios"),
    path("mock/attachments/", views.attachments, name="attachments"),
    path("mock/attachments/<str:attachment_id>/", views.attachment_detail, name="attachment-detail"),
    path("mock/analysis/jobs/", views.analysis_jobs, name="analysis-jobs"),
    path("mock/analysis/jobs/<str:job_id>/", views.analysis_job_detail, name="analysis-job-detail"),
    path("mock/agents/nodes/", views.agent_nodes, name="agent-nodes"),
    path("mock/agents/nodes/run/", views.run_agent_node, name="run-agent-node"),
    path("mock/agents/plans/run/", views.run_agent_plan, name="run-agent-plan"),
    path("mock/chat/sessions/", views.create_chat_session, name="create-chat-session"),
    path("mock/chat/messages/", views.submit_chat_message, name="submit-chat-message"),
    path("mock/reports/", views.report_action, name="report-action"),
    path("mock/reports/<str:report_id>/download/", views.download_report, name="download-report"),
]

