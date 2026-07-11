from __future__ import annotations

from pathlib import Path

import pytest


collect_ignore = ["backend/chatbot/test_production_hardening.py"]


LIVE_TEST_FILES = {
    "test_appeal_decision_flow_real_llm.py",
    "test_appeal_decision_flow_paraphrase_robustness.py",
    "test_fine_notice_ocr.py",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests that call external APIs",
    )
    parser.addoption(
        "--run-aws",
        action="store_true",
        default=False,
        help="run tests against provisioned AWS resources",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_live = bool(config.getoption("--run-live"))
    run_aws = bool(config.getoption("--run-aws"))
    live_skip = pytest.mark.skip(reason="external API test requires --run-live")
    aws_skip = pytest.mark.skip(reason="AWS test requires --run-aws")

    for item in items:
        if Path(str(item.path)).name in LIVE_TEST_FILES:
            item.add_marker(pytest.mark.live)
        if item.get_closest_marker("live") and not run_live:
            item.add_marker(live_skip)
        if item.get_closest_marker("aws") and not run_aws:
            item.add_marker(aws_skip)
