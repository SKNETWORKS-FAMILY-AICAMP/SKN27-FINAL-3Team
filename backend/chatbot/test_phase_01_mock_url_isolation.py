from __future__ import annotations

import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve


ROOT = Path(__file__).resolve().parents[2]


class ExplicitMockUrlIsolationTests(SimpleTestCase):
    def _resolve_mock_url(self):
        sys.modules.pop("config.mock_urls", None)
        clear_url_caches()
        try:
            return resolve("/api/mock/attachments/", urlconf="config.mock_urls")
        except ModuleNotFoundError as exc:
            self.fail(f"Explicit Mock URLConf is missing: {exc}")

    def tearDown(self) -> None:
        sys.modules.pop("config.mock_urls", None)
        clear_url_caches()
        super().tearDown()

    def test_default_urlconf_keeps_explicit_mock_routes_unresolvable(self) -> None:
        canonical_match = resolve("/api/health/", urlconf="config.urls")

        self.assertEqual(canonical_match.url_name, "health-check")
        with self.assertRaises(Resolver404):
            resolve("/api/mock/attachments/", urlconf="config.urls")

    @override_settings(EXPLICIT_MOCK_RUNTIME_ENABLED=True, DEBUG=True)
    def test_explicit_mock_urlconf_resolves_only_when_both_local_conditions_are_true(self) -> None:
        match = self._resolve_mock_url()

        self.assertEqual(match.namespace, "explicit_mock")
        self.assertEqual(match.url_name, "attachments")

    @override_settings(EXPLICIT_MOCK_RUNTIME_ENABLED=False, DEBUG=True)
    def test_explicit_mock_urlconf_fails_closed_when_flag_is_disabled(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            self._resolve_mock_url()

    @override_settings(EXPLICIT_MOCK_RUNTIME_ENABLED=True, DEBUG=False)
    def test_explicit_mock_urlconf_fails_closed_when_debug_is_disabled(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            self._resolve_mock_url()

    def test_canonical_url_modules_do_not_import_mock_url_or_view_modules(self) -> None:
        for relative_path in ("backend/config/urls.py", "backend/chatbot/urls.py"):
            with self.subTest(relative_path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertNotIn("mock_urls", source)
                self.assertNotIn("mock_views", source)
