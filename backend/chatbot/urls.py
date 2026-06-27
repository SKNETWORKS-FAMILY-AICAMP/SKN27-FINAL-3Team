"""Mock chatbot API routes for frontend integration."""

from __future__ import annotations

from django.urls import path

from chatbot import views

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path("chat/sessions/", views.create_chat_session, name="canonical-create-chat-session"),
    path("chat/messages/", views.submit_chat_message, name="canonical-submit-chat-message"),
    path("files/", views.attachments, name="canonical-files"),
    path("files/<str:attachment_id>/", views.attachment_detail, name="canonical-file-detail"),
    path("analysis/jobs/", views.analysis_jobs, name="canonical-analysis-jobs"),
    path("analysis/jobs/<str:job_id>/", views.analysis_job_detail, name="canonical-analysis-job-detail"),
    path("analysis/results/<str:job_id>/", views.analysis_result, name="canonical-analysis-result"),
    path("agents/nodes/", views.agent_nodes, name="canonical-agent-nodes"),
    path("agents/nodes/run/", views.run_agent_node, name="canonical-run-agent-node"),
    path("agents/plans/run/", views.run_agent_plan, name="canonical-run-agent-plan"),
    path("reports/", views.report_action, name="canonical-report-action"),
    path("reports/<str:report_id>/download/", views.download_report, name="canonical-download-report"),
    path("mock/chat/scenarios/", views.demo_scenarios, name="demo-scenarios"),
    path("mock/attachments/", views.attachments, name="attachments"),
    path("mock/attachments/<str:attachment_id>/", views.attachment_detail, name="attachment-detail"),
    path("mock/analysis/jobs/", views.analysis_jobs, name="analysis-jobs"),
    path("mock/analysis/jobs/<str:job_id>/", views.analysis_job_detail, name="analysis-job-detail"),
    path("mock/analysis/results/<str:job_id>/", views.analysis_result, name="analysis-result"),
    path("mock/agents/nodes/", views.agent_nodes, name="agent-nodes"),
    path("mock/agents/nodes/run/", views.run_agent_node, name="run-agent-node"),
    path("mock/agents/plans/run/", views.run_agent_plan, name="run-agent-plan"),
    path("mock/chat/sessions/", views.create_chat_session, name="create-chat-session"),
    path("mock/chat/messages/", views.submit_chat_message, name="submit-chat-message"),
    path("mock/reports/", views.report_action, name="report-action"),
    path("mock/reports/<str:report_id>/download/", views.download_report, name="download-report"),
]

