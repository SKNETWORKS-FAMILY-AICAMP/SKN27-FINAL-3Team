from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (
    ROOT
    / "scripts"
    / "refactoring"
    / "verify_phase_02_d8_resume_latest_consultation_test_sensitivity.py"
)
EXPECTED = (
    "view_application_bypass",
    "latest_owned_session_bypass",
    "latest_job_selection_bypass",
    "derived_resource_owner_bypass",
    "privacy_manifest_bypass",
)


def runner():
    spec = importlib.util.spec_from_file_location("phase_02_d8_sensitivity_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d8_evidence_requires_exact_mutation_set_restoration_and_fresh_head() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d8-test-head",
        actual_head="d8-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        working_tree_unchanged=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d8_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d8_targets_cover_the_resume_authority_and_projection_boundaries() -> None:
    module = runner()

    assert module.TARGETS["latest_owned_session_bypass"].endswith(
        "test_selects_latest_owned_session_not_newer_foreign_session"
    )
    assert module.TARGETS["latest_job_selection_bypass"].endswith(
        "test_selects_latest_job_for_the_selected_owned_session"
    )
    assert module.TARGETS["derived_resource_owner_bypass"].endswith(
        "test_excludes_foreign_derived_resources_from_the_owned_session"
    )
    assert module.TARGETS["privacy_manifest_bypass"].endswith(
        "test_projects_only_safe_resume_fields"
    )


def test_d8_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d8",
        actual_head="d8",
        original_exit_code=0,
        mutations=valid[:-1],
        working_tree_unchanged=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d8",
        actual_head="d8",
        original_exit_code=0,
        mutations=bad,
        working_tree_unchanged=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d8",
        actual_head="d8",
        original_exit_code=0,
        mutations=valid,
        working_tree_unchanged=False,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d8",
        actual_head="different-head",
        original_exit_code=0,
        mutations=valid,
        working_tree_unchanged=True,
    )["status"] == "fail"


def test_d8_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D8")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))
