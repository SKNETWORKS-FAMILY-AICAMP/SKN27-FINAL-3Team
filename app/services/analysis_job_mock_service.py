"""Legacy compatibility shim for Explicit Mock analysis jobs."""

from app.mock_runtime.analysis_jobs import (
    create_analysis_job,
    get_analysis_job,
    get_analysis_result,
    list_analysis_jobs,
)

__all__ = [
    "create_analysis_job",
    "get_analysis_job",
    "get_analysis_result",
    "list_analysis_jobs",
]
