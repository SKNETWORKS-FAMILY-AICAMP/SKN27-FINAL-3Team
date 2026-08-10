"""Read-only count audit for Phase 1 legacy mock persistence markers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
MARKERS = ("mock_scenario", "mock_status", "canonical_mock", "mock://", "mock_analysis_jobs", "mock_history_events")


def _configure_django() -> None:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def _marker_counts(rows: list[Any]) -> dict[str, int]:
    counts = {marker: 0 for marker in MARKERS}
    for row in rows:
        text = json.dumps(row or {}, ensure_ascii=False, default=str)
        for marker in MARKERS:
            if marker in text:
                counts[marker] += 1
    return counts


def audit() -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": "phase_01_mock_persistence_audit.v1",
        "mode": "read_only_count_only",
        "local_test_audit": {"status": "NOT_EXECUTED", "reason": "database_unavailable"},
        "production_database_audit": "NOT_EXECUTED",
        "physical_column_removal": "DEFERRED",
        "marker_counts": {marker: 0 for marker in MARKERS},
    }
    try:
        _configure_django()
        from chatbot.models import AgentWorkItem, AnalysisJob, ChatMessage, HistoryEvent, Report, UploadedFile

        model_rows = {
            "analysis_jobs": list(AnalysisJob.objects.values_list("mock_scenario", "metadata")),
            "chat_messages": list(ChatMessage.objects.values_list("metadata", flat=True)),
            "uploaded_files": list(UploadedFile.objects.values_list("metadata", flat=True)),
            "reports": list(Report.objects.values_list("metadata", flat=True)),
            "agent_work_items": list(AgentWorkItem.objects.values_list("payload", flat=True)),
            "history_events": list(HistoryEvent.objects.values_list("metadata", flat=True)),
        }
    except Exception as exc:
        result["local_test_audit"] = {"status": "NOT_EXECUTED", "reason": exc.__class__.__name__}
        return result

    counts = {marker: 0 for marker in MARKERS}
    row_counts: dict[str, int] = {}
    for name, rows in model_rows.items():
        row_counts[name] = len(rows)
        for marker, count in _marker_counts(rows).items():
            counts[marker] += count
    result["local_test_audit"] = {"status": "COMPLETED", "row_counts": row_counts}
    result["marker_counts"] = counts
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("json",), default="json")
    parser.parse_args()
    print(json.dumps(audit(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
