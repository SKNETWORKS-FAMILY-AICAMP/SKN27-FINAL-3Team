from __future__ import annotations

from django.test import SimpleTestCase
from django.urls import resolve

from app.contracts.api_route_specs import API_ROUTE_SPECS


# This module belongs to Django's unittest runner, not the offline pytest suite.
__test__ = False


class ApiRouteSpecShadowTests(SimpleTestCase):
    def test_case_specs_resolve_to_the_declared_django_routes_and_views(self) -> None:
        for spec in API_ROUTE_SPECS:
            concrete_path = spec.path.replace("{case_id}", "case_contract_test")
            match = resolve(concrete_path)

            self.assertEqual(match.url_name, spec.route_name)
            self.assertEqual(match.func.__name__, spec.view_name)
