from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPOSITORY_ROOT / "scripts" / "refactoring" / "verify_phase_02_d3_test_sensitivity.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("phase_02_d3_sensitivity_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assertion_outcomes(runner):
    return tuple(
        runner.MutationOutcome(name=name, exit_code=1, failure_kind="assertion")
        for name in runner.TARGETS
    )


def test_evidence_requires_all_d3_mutations_to_fail_by_assertion_without_tree_changes() -> None:
    runner = _load_runner()

    evidence = runner.build_evidence(
        head="phase-02-d3-test-head",
        original_exit_code=0,
        mutations=_assertion_outcomes(runner),
        working_tree_unchanged=True,
    )

    assert evidence["status"] == "pass"
    assert evidence["contract_version"] == "phase_02_d3_sensitivity.v1"
    assert [item["name"] for item in evidence["mutations"]] == list(runner.TARGETS)


def test_evidence_rejects_missing_mutation_unexpected_success_or_unrestored_tree() -> None:
    runner = _load_runner()
    outcomes = _assertion_outcomes(runner)

    missing = runner.build_evidence(
        head="phase-02-d3-test-head",
        original_exit_code=0,
        mutations=outcomes[:-1],
        working_tree_unchanged=True,
    )
    unexpected_success = runner.build_evidence(
        head="phase-02-d3-test-head",
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
        head="phase-02-d3-test-head",
        original_exit_code=0,
        mutations=outcomes,
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