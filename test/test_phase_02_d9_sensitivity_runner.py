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
    / "verify_phase_02_d9_create_chat_session_test_sensitivity.py"
)
EXPECTED = (
    "view_application_bypass",
    "trusted_identity_bypass",
    "draft_initialization_bypass",
    "history_event_bypass",
    "history_failure_semantics_bypass",
)


def runner():
    spec = importlib.util.spec_from_file_location("phase_02_d9_sensitivity_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d9_evidence_requires_exact_mutation_set_restoration_and_fresh_head() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d9-test-head",
        actual_head="d9-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        working_tree_unchanged=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d9_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d9_targets_cover_the_create_chat_session_contract_boundaries() -> None:
    module = runner()

    assert module.TARGETS["view_application_bypass"].endswith(
        "test_http_post_delegates_to_create_chat_session_application_with_trusted_identity_and_preserves_draft_response"
    )
    assert module.TARGETS["trusted_identity_bypass"].endswith(
        "test_authenticated_identity_neutralizes_all_client_owned_identity_fields"
    )
    assert module.TARGETS["history_event_bypass"].endswith(
        "test_history_event_uses_trusted_actor_subject_and_draft_metadata"
    )
    assert module.TARGETS["history_failure_semantics_bypass"].endswith(
        "test_history_database_and_os_failures_keep_the_draft_response_successful"
    )


def test_d9_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d9",
        actual_head="d9",
        original_exit_code=0,
        mutations=valid[:-1],
        working_tree_unchanged=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d9",
        actual_head="d9",
        original_exit_code=0,
        mutations=bad,
        working_tree_unchanged=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d9",
        actual_head="different-head",
        original_exit_code=0,
        mutations=valid,
        working_tree_unchanged=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d9",
        actual_head="d9",
        original_exit_code=0,
        mutations=valid,
        working_tree_unchanged=False,
    )["status"] == "fail"


def test_d9_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D9")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))
