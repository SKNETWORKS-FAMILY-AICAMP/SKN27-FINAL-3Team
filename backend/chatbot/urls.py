"""Mock chatbot API routes for frontend integration."""

from __future__ import annotations

from django.urls import path

from chatbot import views

urlpatterns = [
    path("health/", views.health_check, name="health-check"),
    path("mock/chat/scenarios/", views.demo_scenarios, name="demo-scenarios"),
    path("mock/chat/sessions/", views.create_chat_session, name="create-chat-session"),
    path("mock/chat/messages/", views.submit_chat_message, name="submit-chat-message"),
    path("mock/reports/", views.report_action, name="report-action"),
    path("mock/reports/<str:report_id>/download/", views.download_report, name="download-report"),
]

