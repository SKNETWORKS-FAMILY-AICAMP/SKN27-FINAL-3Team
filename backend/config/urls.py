"""URL configuration for the demo backend workspace."""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("api/", include("chatbot.urls")),
]

