from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY_ROOT / "scripts" / "refactoring" / "verify_phase_02_d2_test_sensitivity.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("phase_02_d2_sensitivity_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evidence_requires_all_d2_mutations_to_fail_by_assertion_without_tree_changes() -> None:
    runner = _load_runner()

    evidence = runner.build_evidence(
        head="phase-02-d2-test-head",
        original_exit_code=0,
        mutations=(
            runner.MutationOutcome(
                name="trusted_identity_bypass", exit_code=1, failure_kind="assertion"
            ),
            runner.MutationOutcome(
                name="typed_validation_bypass", exit_code=1, failure_kind="assertion"
            ),
            runner.MutationOutcome(
                name="promotion_fence_bypass", exit_code=1, failure_kind="assertion"
            ),
            runner.MutationOutcome(
                name="view_application_bypass", exit_code=1, failure_kind="assertion"
            ),
        ),
        working_tree_unchanged=True,
    )

    assert evidence["status"] == "pass"
    assert evidence["contract_version"] == "phase_02_d2_sensitivity.v1"
    assert [item["name"] for item in evidence["mutations"]] == list(runner.TARGETS)


def test_evidence_rejects_missing_mutation_unexpected_success_or_unrestored_tree() -> None:
    runner = _load_runner()
    assertion_outcome = runner.MutationOutcome(
        name="trusted_identity_bypass", exit_code=1, failure_kind="assertion"
    )

    missing = runner.build_evidence(
        head="phase-02-d2-test-head",
        original_exit_code=0,
        mutations=(assertion_outcome,),
        working_tree_unchanged=True,
    )
    unexpected_success = runner.build_evidence(
        head="phase-02-d2-test-head",
        original_exit_code=0,
        mutations=tuple(
            runner.MutationOutcome(
                name=name,
                exit_code=0 if name == "typed_validation_bypass" else 1,
                failure_kind="assertion",
            )
            for name in runner.TARGETS
        ),
        working_tree_unchanged=True,
    )
    unrestored_tree = runner.build_evidence(
        head="phase-02-d2-test-head",
        original_exit_code=0,
        mutations=tuple(
            runner.MutationOutcome(name=name, exit_code=1, failure_kind="assertion")
            for name in runner.TARGETS
        ),
        working_tree_unchanged=False,
    )

    assert missing["status"] == "fail"
    assert unexpected_success["status"] == "fail"
    assert unrestored_tree["status"] == "fail"


def test_failure_kind_requires_assertion_failure() -> None:
    runner = _load_runner()
    assertion_failure = subprocess.CompletedProcess(
        args=["test"],
        returncode=1,
        stdout="AssertionError: expected Application boundary",
    )
    setup_failure = subprocess.CompletedProcess(
        args=["test"],
        returncode=1,
        stdout="ImportError: mutation setup failed",
    )

    assert runner.failure_kind(assertion_failure) == "assertion"
    with pytest.raises(runner.SensitivityError, match="assertion mismatch"):
        runner.failure_kind(setup_failure)
