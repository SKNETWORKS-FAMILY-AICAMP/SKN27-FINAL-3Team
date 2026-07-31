from __future__ import annotations

import pytest

from app.services.operational_health_gate import evaluate_operational_health_gate


EXPECTED_DATASET_VERSION = "dataset-v1"
EXPECTED_RELEASE_VERSION = "818199aee975"


def _snapshot(
    *,
    status: str = "pass",
    alerts: object = None,
    dataset_version: str = EXPECTED_DATASET_VERSION,
    release_version: str = EXPECTED_RELEASE_VERSION,
    legal_status: str = "success",
    issue_count: int = 0,
) -> dict[str, object]:
    return {
        "contract_version": "operational_health.v1",
        "event_type": "operational_health",
        "status": status,
        "legal_data": {
            "status": legal_status,
            "issue_count": issue_count,
            "dataset_version": dataset_version,
            "release_version": release_version,
        },
        "alerts": [] if alerts is None else alerts,
    }


def _evaluate(snapshot: object, *, mode: str = "transaction") -> dict[str, object]:
    return evaluate_operational_health_gate(
        snapshot,
        expected_dataset_version=EXPECTED_DATASET_VERSION,
        expected_release_version=EXPECTED_RELEASE_VERSION,
        mode=mode,
    )


def test_transaction_gate_accepts_clean_pass_snapshot() -> None:
    result = _evaluate(_snapshot())

    assert result == {
        "contract_version": "operational_health_gate.v1",
        "mode": "transaction",
        "decision": "pass",
        "reason_codes": [],
    }


def test_transaction_gate_accepts_only_transient_queue_backlog_warning() -> None:
    result = _evaluate(
        _snapshot(
            status="warn",
            alerts=[{"code": "queue_backlog", "severity": "warning"}],
        )
    )

    assert result["decision"] == "pass"
    assert result["reason_codes"] == []


@pytest.mark.parametrize(
    "code",
    (
        "queue_oldest_age_exceeded",
        "worker_lease_stale",
        "worker_retrying",
        "legal_data_stale",
    ),
)
def test_transaction_gate_rejects_every_other_warning(code: str) -> None:
    result = _evaluate(
        _snapshot(
            status="warn",
            alerts=[{"code": code, "severity": "warning"}],
        )
    )

    assert result["decision"] == "fail"
    assert result["reason_codes"] == ["transaction_gate_rejected"]


def test_acceptance_gate_resets_on_warning() -> None:
    result = _evaluate(
        _snapshot(
            status="warn",
            alerts=[{"code": "queue_backlog", "severity": "warning"}],
        ),
        mode="acceptance",
    )

    assert result["decision"] == "reset"
    assert result["reason_codes"] == ["acceptance_window_reset"]


def test_acceptance_gate_fails_on_critical_alert() -> None:
    result = _evaluate(
        _snapshot(
            status="fail",
            alerts=[{"code": "provider_failure", "severity": "critical"}],
        ),
        mode="acceptance",
    )

    assert result["decision"] == "fail"
    assert result["reason_codes"] == ["acceptance_critical"]


@pytest.mark.parametrize(
    ("snapshot", "reason_code"),
    (
        (None, "snapshot_invalid"),
        (
            {**_snapshot(), "contract_version": "unexpected.v1"},
            "snapshot_contract_invalid",
        ),
        ({**_snapshot(), "status": "degraded"}, "snapshot_status_invalid"),
        ({**_snapshot(), "legal_data": None}, "legal_data_invalid"),
        ({**_snapshot(), "alerts": "queue_backlog"}, "alerts_invalid"),
    ),
)
def test_gate_rejects_malformed_snapshot_contracts(
    snapshot: object,
    reason_code: str,
) -> None:
    result = _evaluate(snapshot)

    assert result["decision"] == "fail"
    assert reason_code in result["reason_codes"]


@pytest.mark.parametrize(
    ("snapshot", "reason_code"),
    (
        (
            _snapshot(dataset_version="dataset-v2"),
            "dataset_version_mismatch",
        ),
        (
            _snapshot(release_version="ffffffffffff"),
            "release_version_mismatch",
        ),
        (
            _snapshot(legal_status="failed", issue_count=1),
            "legal_data_not_ready",
        ),
    ),
)
def test_gate_rejects_non_exact_legal_provenance(
    snapshot: object,
    reason_code: str,
) -> None:
    result = _evaluate(snapshot)

    assert result["decision"] == "fail"
    assert reason_code in result["reason_codes"]


def test_gate_rejects_unsupported_mode_without_echoing_snapshot() -> None:
    with pytest.raises(ValueError, match="unsupported operational health gate mode"):
        _evaluate(_snapshot(), mode="unknown")
