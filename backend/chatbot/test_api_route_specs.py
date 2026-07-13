from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import resolve

from app.contracts.api_route_specs import API_ROUTE_SPECS, DEFERRED_ROUTE_SPECS
from chatbot.urls import urlpatterns


# This module belongs to Django's unittest runner, not the offline pytest suite.
__test__ = False


class ApiRouteSpecShadowTests(SimpleTestCase):
    def test_case_specs_resolve_to_the_declared_django_routes_and_views(self) -> None:
        for spec in API_ROUTE_SPECS:
            concrete_path = spec.path.replace("{case_id}", "case_contract_test")
            match = resolve(concrete_path)

            self.assertEqual(match.url_name, spec.route_name)
            self.assertEqual(match.func.__name__, spec.view_name)

    def test_every_api_route_is_modeled_or_explicitly_deferred(self) -> None:
        api_route_names = {
            pattern.name
            for pattern in urlpatterns
            if pattern.name
        }
        modeled_route_names = {spec.route_name for spec in API_ROUTE_SPECS}
        deferred_route_names = {spec.route_name for spec in DEFERRED_ROUTE_SPECS}

        self.assertEqual(
            api_route_names,
            modeled_route_names | deferred_route_names,
        )
        self.assertFalse(modeled_route_names & deferred_route_names)

        for spec in DEFERRED_ROUTE_SPECS:
            concrete_path = spec.path
            for parameter in ("attachment_id", "job_id", "report_id"):
                concrete_path = concrete_path.replace(
                    "{" + parameter + "}",
                    f"{parameter}_contract_test",
                )
            match = resolve(concrete_path)
            self.assertEqual(match.url_name, spec.route_name)
            self.assertEqual(match.func.__name__, spec.view_name)
