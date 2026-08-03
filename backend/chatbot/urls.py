"""Mock chatbot API routes for frontend integration."""

from __future__ import annotations

from django.urls import path

from chatbot import views

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path("health/live/", views.health_live, name="health-live"),
    path("health/ready/", views.health_ready, name="health-ready"),
    path("capabilities/", views.capabilities, name="capabilities"),
    path("auth/guest-session/", views.guest_session, name="auth-guest-session"),
    path("auth/google/code/", views.auth_google_code, name="auth-google-code"),
    path("auth/refresh/", views.auth_refresh, name="auth-refresh"),
    path("auth/logout/", views.auth_logout, name="auth-logout"),
    path("auth/me/", views.auth_me, name="auth-me"),
    path("auth/resume/", views.auth_resume, name="auth-resume"),
    path("mypage/summary/", views.mypage_summary, name="canonical-mypage-summary"),
    path("history/", views.history_events, name="canonical-history-events"),
    path("chat/sessions/", views.create_chat_session, name="canonical-create-chat-session"),
    path("chat/messages/", views.submit_chat_message, name="canonical-submit-chat-message"),
    path("chat/save-state/", views.update_chat_save_state, name="canonical-chat-save-state"),
    path("cases/", views.consultation_cases, name="canonical-consultation-cases"),
    path(
        "cases/<str:case_id>/workspace/",
        views.consultation_case_workspace,
        name="canonical-consultation-case-workspace",
    ),
    path(
        "cases/<str:case_id>/facts/confirm/",
        views.consultation_case_fact_confirmation,
        name="canonical-consultation-case-fact-confirmation",
    ),
    path(
        "cases/<str:case_id>/analysis/jobs/",
        views.consultation_case_analysis_jobs,
        name="canonical-consultation-case-analysis-jobs",
    ),
    path("files/", views.attachments, name="canonical-files"),
    path("files/<str:attachment_id>/", views.attachment_detail, name="canonical-file-detail"),
    path("analysis/jobs/", views.analysis_jobs, name="canonical-analysis-jobs"),
    path("analysis/jobs/<str:job_id>/", views.analysis_job_detail, name="canonical-analysis-job-detail"),
    path("analysis/results/<str:job_id>/", views.analysis_result, name="canonical-analysis-result"),
    path("agents/nodes/", views.agent_nodes, name="canonical-agent-nodes"),
    path("reports/", views.report_action, name="canonical-report-action"),
    path("reports/<str:report_id>/", views.report_detail, name="canonical-report-detail"),
    path(
        "reports/<str:report_id>/document-confirmation/",
        views.report_document_confirmation,
        name="canonical-report-document-confirmation",
    ),
    path("reports/<str:report_id>/download/", views.download_report, name="canonical-download-report"),
]

