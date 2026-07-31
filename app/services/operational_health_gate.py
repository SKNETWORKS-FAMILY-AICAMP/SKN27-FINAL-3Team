"""Privacy-safe release gates for operational health snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal


HEALTH_GATE_CONTRACT_VERSION = "operational_health_gate.v1"
ALLOWED_TRANSACTION_WARNINGS = frozenset({"queue_backlog"})
GateMode = Literal["transaction", "acceptance"]


def evaluate_operational_health_gate(
    snapshot: object,
    *,
    expected_dataset_version: str,
    expected_release_version: str,
    mode: GateMode | str,
) -> dict[str, Any]:
    """Return a fixed-code release decision without reflecting snapshot data."""

    if mode not in {"transaction", "acceptance"}:
        raise ValueError("unsupported operational health gate mode")

    reasons: list[str] = []
    if not isinstance(snapshot, Mapping):
        reasons.append("snapshot_invalid")
        snapshot = {}

    if (
        snapshot.get("contract_version") != "operational_health.v1"
        or snapshot.get("event_type") != "operational_health"
    ):
        reasons.append("snapshot_contract_invalid")

    status = snapshot.get("status")
    if status not in {"pass", "warn", "fail"}:
        reasons.append("snapshot_status_invalid")

    legal_data = snapshot.get("legal_data")
    if not isinstance(legal_data, Mapping):
        reasons.append("legal_data_invalid")
        legal_data = {}
    if (
        legal_data.get("status") != "success"
        or legal_data.get("issue_count") != 0
    ):
        reasons.append("legal_data_not_ready")
    if legal_data.get("dataset_version") != expected_dataset_version:
        reasons.append("dataset_version_mismatch")
    if legal_data.get("release_version") != expected_release_version:
        reasons.append("release_version_mismatch")

    alerts_value = snapshot.get("alerts")
    if not isinstance(alerts_value, list) or any(
        not _valid_alert(item) for item in alerts_value
    ):
        reasons.append("alerts_invalid")
        alerts: list[Mapping[str, object]] = []
    else:
        alerts = alerts_value

    if reasons:
        decision = "fail"
    elif mode == "transaction":
        queue_backlog_only = bool(alerts) and all(
            item.get("code") in ALLOWED_TRANSACTION_WARNINGS
            and item.get("severity") == "warning"
            for item in alerts
        )
        decision = (
            "pass"
            if (status == "pass" and not alerts)
            or (status == "warn" and queue_backlog_only)
            else "fail"
        )
        if decision == "fail":
            reasons.append("transaction_gate_rejected")
    elif status == "pass" and not alerts:
        decision = "pass"
    elif status == "fail" or any(
        item.get("severity") == "critical" for item in alerts
    ):
        decision = "fail"
        reasons.append("acceptance_critical")
    else:
        decision = "reset"
        reasons.append("acceptance_window_reset")

    return {
        "contract_version": HEALTH_GATE_CONTRACT_VERSION,
        "mode": mode,
        "decision": decision,
        "reason_codes": sorted(set(reasons)),
    }


def _valid_alert(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    code = value.get("code")
    severity = value.get("severity")
    return (
        isinstance(code, str)
        and bool(code)
        and severity in {"warning", "critical"}
    )
