"""Explicit Mock analysis-job compatibility entrypoints.

These functions are for mock URL, local demo, and test consumers only. They
must not be imported by canonical production modules.
"""

from __future__ import annotations

from typing import Any


def create_analysis_job(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.analysis_job_mock_service import create_analysis_job as _create_analysis_job

    return _create_analysis_job(payload)


def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    from app.services.analysis_job_mock_service import get_analysis_job as _get_analysis_job

    return _get_analysis_job(job_id)
