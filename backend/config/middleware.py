"""Small development CORS middleware for the demo API workspace."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse


class DemoCorsMiddleware:
    """Allow local frontend apps to call the mock API during the mid-demo build."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

