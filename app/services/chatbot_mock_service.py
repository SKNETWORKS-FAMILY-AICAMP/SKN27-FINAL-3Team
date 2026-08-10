"""Legacy compatibility shim for Explicit Mock chat fixtures."""

from app.mock_runtime.chat import (
    build_analysis_plan,
    create_session,
    list_demo_personas,
    list_demo_scenarios,
    perform_report_action,
    submit_message,
)

__all__ = [
    "build_analysis_plan",
    "create_session",
    "list_demo_personas",
    "list_demo_scenarios",
    "perform_report_action",
    "submit_message",
]
