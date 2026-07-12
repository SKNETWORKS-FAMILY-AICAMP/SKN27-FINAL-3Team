"""Repository-wide pytest markers and deterministic live-test opt-in."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests that call real external services or credentials",
    )


def pytest_configure(config: pytest.Config) -> None:
    for marker, description in {
        "unit": "isolated unit test",
        "integration": "local integration test",
        "live": "real external service test; requires --run-live",
        "aws": "AWS-backed test; normally combined with live",
    }.items():
        config.addinivalue_line("markers", f"{marker}: {description}")


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live test requires explicit --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)

