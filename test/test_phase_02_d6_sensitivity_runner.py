from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "refactoring" / "verify_phase_02_d6_history_list_events_test_sensitivity.py"
EXPECTED = (
    "view_application_bypass",
    "job_authorization_bypass",
    "session_authorization_bypass",
    "default_limit_bypass",
    "public_marker_projection_bypass",
)


def runner():
    spec = importlib.util.spec_from_file_location("phase_02_d6_sensitivity_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d6_evidence_requires_exact_mutation_set_and_restored_tree() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d6-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        working_tree_unchanged=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d6_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d6_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d6",
        original_exit_code=0,
        mutations=valid[:-1],
        working_tree_unchanged=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d6",
        original_exit_code=0,
        mutations=bad,
        working_tree_unchanged=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d6",
        original_exit_code=0,
        mutations=valid,
        working_tree_unchanged=False,
    )["status"] == "fail"
    assert module.build_evidence(
        head="",
        original_exit_code=0,
        mutations=valid,
        working_tree_unchanged=True,
    )["status"] == "fail"


def test_d6_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D6")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))
