"""Explicit local-test URL configuration for the isolated Mock runtime."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import include, path


if not (settings.EXPLICIT_MOCK_RUNTIME_ENABLED and settings.DEBUG):
    raise ImproperlyConfigured(
        "Explicit Mock runtime requires EXPLICIT_MOCK_RUNTIME_ENABLED=True and DEBUG=True."
    )


urlpatterns = [
    path("api/", include("chatbot.urls")),
    path("api/mock/", include("chatbot.mock_urls")),
]
