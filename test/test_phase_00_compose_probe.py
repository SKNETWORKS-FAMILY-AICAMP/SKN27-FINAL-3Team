"""Unit contracts for the Phase 0 Compose probe; Docker is never started here."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _probe_module():
    path = Path(__file__).parents[1] / "scripts" / "refactoring" / "phase_00_compose_probe.py"
    spec = importlib.util.spec_from_file_location("phase_00_compose_probe", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_00_probe_parser_accepts_only_the_declared_subcommands() -> None:
    """Protects the D2 probe CLI contract without invoking Docker or Django."""

    probe = _probe_module()

    parser = probe.build_parser()
    assert parser.parse_args(["seed-agent-work"]).command == "seed-agent-work"
    assert parser.parse_args(["verify-agent-work", "--job-id", "job_1", "--work-item-id", "work_1"]).command == "verify-agent-work"
    assert parser.parse_args(["verify-file-scan", "--attachment-id", "att_1"]).command == "verify-file-scan"
    assert parser.parse_args(["describe-runtime"]).command == "describe-runtime"


def test_phase_00_probe_safe_projection_removes_private_values_recursively() -> None:
    """Protects CI evidence from secret, raw input, and private storage disclosure."""

    probe = _probe_module()

    value = {
        "job_id": "job_safe",
        "raw_user_text": "must not leak",
        "token": "must not leak",
        "storage_uri": "s3://private-bucket/secret",
        "nested": {"authorization": "Bearer secret", "status": "success"},
    }

    assert probe.safe_projection(value) == {
        "job_id": "job_safe",
        "nested": {"status": "success"},
    }


def test_phase_00_probe_accepts_only_completed_internal_worker_result() -> None:
    """Protects D2 Agent Worker evidence: a claimed work item must persist one expected result."""

    probe = _probe_module()

    verdict = probe.agent_work_verdict(
        {
            "attempt_no": 1,
            "started": True,
            "completed": True,
            "work_item_status": "success",
            "job_status": "success",
            "result_node_codes": ["input_context_validation"],
            "error_code": "",
        },
        expected_node_code="input_context_validation",
    )

    assert verdict == {"status": "pass", "failed_checks": []}


def test_phase_00_probe_rejects_missing_worker_completion_or_wrong_node() -> None:
    """Protects against passing D2 from a running container or a direct mock row."""

    probe = _probe_module()

    verdict = probe.agent_work_verdict(
        {
            "attempt_no": 0,
            "started": False,
            "completed": False,
            "work_item_status": "queued",
            "job_status": "queued",
            "result_node_codes": ["law_ground_search"],
            "error_code": "",
        },
        expected_node_code="input_context_validation",
    )

    assert verdict["status"] == "fail"
    assert set(verdict["failed_checks"]) >= {"attempt", "started", "completed", "node_code"}


def test_phase_00_probe_accepts_only_clean_clamav_scan() -> None:
    """Protects D2 File Scan evidence: local/fake scanners cannot satisfy the gate."""

    probe = _probe_module()

    assert probe.file_scan_verdict(
        {
            "file_status": "ready",
            "scan_status": "clean",
            "scanner": "clamav",
            "error_code": "",
            "retry_count": 0,
        }
    ) == {"status": "pass", "failed_checks": []}
    assert probe.file_scan_verdict(
        {
            "file_status": "ready",
            "scan_status": "clean",
            "scanner": "local_policy",
            "error_code": "",
            "retry_count": 0,
        }
    )["status"] == "fail"


def test_phase_00_probe_rejects_provider_capable_worker_plans() -> None:
    """Protects the approved no-provider Agent Worker plan boundary."""

    probe = _probe_module()

    assert probe.validate_internal_plan(["input_context_validation"]) == "input_context_validation"
    try:
        probe.validate_internal_plan(["law_ground_search"])
    except ValueError as exc:
        assert str(exc) == "provider_capable_node:law_ground_search"
    else:  # pragma: no cover - explicit failure if the safety boundary is removed.
        raise AssertionError("provider-capable plan was accepted")


def test_phase_00_compose_override_shares_writable_mock_upload_root_with_file_scan_worker() -> None:
    """Protects the D2 upload fixture path used by the backend and scan worker."""

    override = Path("test/compose/docker-compose.phase-00.yml").read_text(encoding="utf-8")

    assert override.count(
        "- ./tmp/phase-00-compose-evidence/mock_uploads:/app/backend/media/mock_uploads"
    ) == 2
    assert override.count(
        "- ./tmp/phase-00-compose-evidence/object_storage:/app/backend/media/mock_object_storage"
    ) == 3
