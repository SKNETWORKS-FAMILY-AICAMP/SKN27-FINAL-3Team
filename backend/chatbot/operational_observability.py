"""Build privacy-safe operational health snapshots for the pilot runtime."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as datetime_timezone
import json
from pathlib import Path
import re
from typing import Any

from django.db.models import Q
from django.utils import timezone

from etl.legal.validate_run_summary import evaluate_run_summary
from chatbot.models import (
    AgentInvocation,
    AgentInvocationStatus,
    AgentWorkItem,
    AgentWorkItemStatus,
)


HEALTH_CONTRACT_VERSION = "operational_health.v1"
SAFE_PROVIDER_ROLES = {
    "supervisor_llm",
    "ocr",
    "vision",
    "legal",
    "case_search",
    "unknown",
}


def build_operational_health_snapshot(
    *,
    observed_at: datetime | None = None,
    window_minutes: int = 15,
    queue_age_warn_seconds: int = 300,
    lease_stale_seconds: int = 300,
    legal_run_summary_path: str = "",
    legal_max_age_hours: int = 168,
    legal_required_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Return a bounded snapshot without user content or runtime secrets."""

    now = observed_at or timezone.now()
    window_started_at = now - timedelta(minutes=window_minutes)
    queued = AgentWorkItem.objects.filter(status=AgentWorkItemStatus.QUEUED)
    queued_count = queued.count()
    oldest_created_at = queued.order_by("created_at").values_list(
        "created_at",
        flat=True,
    ).first()
    oldest_queued_age_seconds = (
        max(0, int((now - oldest_created_at).total_seconds()))
        if oldest_created_at
        else 0
    )
    running = AgentWorkItem.objects.filter(status=AgentWorkItemStatus.RUNNING)
    running_count = running.count()
    stale_running_count = running.filter(
        locked_at__lt=now - timedelta(seconds=lease_stale_seconds),
    ).count()
    retrying_count = AgentWorkItem.objects.filter(
        status=AgentWorkItemStatus.RETRYING,
    ).count()
    recent_failures = AgentWorkItem.objects.filter(
        status=AgentWorkItemStatus.FAILED,
        completed_at__gte=window_started_at,
        completed_at__lte=now,
    )
    recent_failure_count = recent_failures.count()
    recent_timeout_count = recent_failures.filter(
        Q(error_code__icontains="timeout")
        | Q(error_code__icontains="timedout")
        | Q(error_code__icontains="deadline"),
    ).count()
    provider_failures = AgentInvocation.objects.filter(
        status__in=[
            AgentInvocationStatus.FAILED,
            AgentInvocationStatus.PARTIAL,
        ],
        created_at__gte=window_started_at,
        created_at__lte=now,
    ).exclude(error_code="")
    provider_roles: dict[str, int] = {}
    for node_code in provider_failures.values_list("node_code", flat=True):
        role = _provider_role(node_code)
        provider_roles[role] = provider_roles.get(role, 0) + 1
    provider_roles = dict(sorted(provider_roles.items()))
    provider_failure_count = sum(provider_roles.values())
    alerts = []
    if queued_count:
        alerts.append(_alert("queue_backlog"))
    if oldest_queued_age_seconds > queue_age_warn_seconds:
        alerts.append(_alert("queue_oldest_age_exceeded"))
    if stale_running_count:
        alerts.append(_alert("worker_lease_stale"))
    if retrying_count:
        alerts.append(_alert("worker_retrying"))
    if recent_failure_count:
        alerts.append(_alert("worker_failure", severity="critical"))
    if recent_timeout_count:
        alerts.append(_alert("worker_timeout", severity="critical"))
    if provider_failure_count:
        alerts.append(_alert("provider_failure", severity="critical"))
    legal_data, legal_alerts = _legal_data_snapshot(
        path=legal_run_summary_path,
        now=now,
        max_age_hours=legal_max_age_hours,
        required_sources=legal_required_sources or [],
    )
    alerts.extend(legal_alerts)
    status = (
        "fail"
        if any(alert["severity"] == "critical" for alert in alerts)
        else ("warn" if alerts else "pass")
    )
    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "event_type": "operational_health",
        "observed_at": now.astimezone(datetime_timezone.utc).isoformat(),
        "status": status,
        "queue": {
            "queued_count": queued_count,
            "oldest_queued_age_seconds": oldest_queued_age_seconds,
            "running_count": running_count,
            "stale_running_count": stale_running_count,
        },
        "worker": {
            "retrying_count": retrying_count,
            "recent_failure_count": recent_failure_count,
            "recent_timeout_count": recent_timeout_count,
        },
        "providers": {
            "recent_failure_count": provider_failure_count,
            "roles": provider_roles,
        },
        "legal_data": legal_data,
        "alerts": alerts,
    }


def _alert(code: str, *, severity: str = "warning") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
    }


def _provider_role(node_code: Any) -> str:
    normalized = str(node_code or "").strip().lower()
    if "supervisor" in normalized:
        role = "supervisor_llm"
    elif "ocr" in normalized:
        role = "ocr"
    elif "vision" in normalized:
        role = "vision"
    elif "law" in normalized or "legal" in normalized:
        role = "legal"
    elif "case_search" in normalized:
        role = "case_search"
    else:
        role = "unknown"
    return role if role in SAFE_PROVIDER_ROLES else "unknown"


def _legal_data_snapshot(
    *,
    path: str,
    now: datetime,
    max_age_hours: int,
    required_sources: list[str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    normalized_path = str(path or "").strip()
    if not normalized_path:
        return {"status": "not_configured", "issue_count": 0}, []

    summary_path = Path(normalized_path)
    if not summary_path.is_file():
        return (
            {"status": "missing", "issue_count": 1},
            [_alert("legal_data_missing", severity="critical")],
        )

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        if not isinstance(summary, dict):
            raise TypeError("run summary must be an object")
        validation = evaluate_run_summary(
            summary,
            now=now,
            max_age_hours=max_age_hours,
            required_sources=required_sources,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return (
            {"status": "invalid", "issue_count": 1},
            [_alert("monitor_configuration_invalid", severity="critical")],
        )

    missing_count = len(validation["missing_sources"])
    failed_count = len(validation["failed_sources"])
    stale_count = len(validation["stale_sources"])
    errors = list(validation["errors"])
    legal_data = {
        "status": "success" if validation["status"] == "success" else "failed",
        "dataset_version": _safe_dataset_version(validation.get("dataset_version")),
        "missing_source_count": missing_count,
        "failed_source_count": failed_count,
        "stale_source_count": stale_count,
        "issue_count": missing_count + failed_count + stale_count,
    }
    if errors:
        legal_data["status"] = "invalid"
        legal_data["issue_count"] = max(1, legal_data["issue_count"])
        return (
            legal_data,
            [_alert("monitor_configuration_invalid", severity="critical")],
        )

    alerts = []
    if missing_count:
        alerts.append(_alert("legal_data_missing", severity="critical"))
    if stale_count:
        alerts.append(_alert("legal_data_stale"))
    if failed_count:
        alerts.append(_alert("legal_data_refresh_failed", severity="critical"))
    return legal_data, alerts


def _safe_dataset_version(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        return None
    return text if re.fullmatch(r"[A-Za-z0-9._:-]+", text) else None
