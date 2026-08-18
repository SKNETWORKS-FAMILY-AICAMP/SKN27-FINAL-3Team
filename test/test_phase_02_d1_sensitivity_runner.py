from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "refactoring" / "verify_phase_02_d1_test_sensitivity.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("phase_02_d1_sensitivity_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_evidence_contract_uses_observed_exit_codes_for_all_d1_mutations() -> None:
    runner = _load_runner()

    evidence = runner.build_evidence(
        head="phase-02-d1-test-head",
        original_exit_code=0,
        mutations=(
            runner.MutationOutcome(
                name="identity_authority_bypass", exit_code=1, failure_kind="assertion"
            ),
            runner.MutationOutcome(
                name="owner_filter_bypass", exit_code=1, failure_kind="assertion"
            ),
            runner.MutationOutcome(
                name="view_application_bypass", exit_code=1, failure_kind="assertion"
            ),
        ),
        working_tree_unchanged=True,
    )

    assert evidence == {
        "contract_version": "phase_02_d1_sensitivity.v1",
        "status": "pass",
        "head": "phase-02-d1-test-head",
        "original": {"exit_code": 0},
        "mutations": [
            {
                "name": "identity_authority_bypass",
                "exit_code": 1,
                "failure_kind": "assertion",
            },
            {
                "name": "owner_filter_bypass",
                "exit_code": 1,
                "failure_kind": "assertion",
            },
            {
                "name": "view_application_bypass",
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
        stdout="AssertionError: expected owner-isolated result",
    )
    non_assertion_failure = subprocess.CompletedProcess(
        args=["test"],
        returncode=1,
        stdout="ImportError: mutation setup failed",
    )

    assert runner.failure_kind(assertion_failure) == "assertion"
    with pytest.raises(runner.SensitivityError, match="assertion mismatch"):
        runner.failure_kind(non_assertion_failure)


def test_evidence_head_prefers_ci_pull_request_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()

    monkeypatch.setenv(
        "PHASE_02_D1_SENSITIVITY_HEAD",
        "phase-02-d1-pull-request-head",
    )

    assert runner._evidence_head() == "phase-02-d1-pull-request-head"
