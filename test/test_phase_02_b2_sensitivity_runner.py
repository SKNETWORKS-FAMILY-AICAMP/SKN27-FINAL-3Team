from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "refactoring" / "verify_phase_02_b2_test_sensitivity.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("phase_02_b2_sensitivity_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evidence_contract_uses_observed_exit_codes() -> None:
    runner = _load_runner()

    evidence = runner.build_evidence(
        head="phase-02-b2-test-head",
        original_exit_code=0,
        mutations=(
            runner.MutationOutcome(
                name="authorization_bypass", exit_code=1, failure_kind="assertion"
            ),
            runner.MutationOutcome(
                name="validation_bypass", exit_code=1, failure_kind="assertion"
            ),
        ),
        working_tree_unchanged=True,
    )

    assert evidence == {
        "contract_version": "phase_02_b2_sensitivity.v1",
        "status": "pass",
        "head": "phase-02-b2-test-head",
        "original": {"exit_code": 0},
        "mutations": [
            {
                "name": "authorization_bypass",
                "exit_code": 1,
                "failure_kind": "assertion",
            },
            {
                "name": "validation_bypass",
                "exit_code": 1,
                "failure_kind": "assertion",
            },
        ],
        "working_tree_unchanged": True,
    }


def test_mutation_failure_kind_requires_assertion_failure() -> None:
    runner = _load_runner()
    assertion_failure = subprocess.CompletedProcess(
        args=["test"],
        returncode=1,
        stdout="AssertionError: expected 403 but received 409",
    )
    non_assertion_failure = subprocess.CompletedProcess(
        args=["test"],
        returncode=1,
        stdout="ImportError: mutation setup failed",
    )

    assert runner.failure_kind(assertion_failure) == "assertion"
    with pytest.raises(runner.SensitivityError, match="assertion mismatch"):
        runner.failure_kind(non_assertion_failure)
