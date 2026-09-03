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
    / "verify_phase_02_d13_issue_guest_session_sensitivity.py"
)
EXPECTED = (
    "view_application_bypass",
    "expired_guest_reactivation_bypass",
    "merged_guest_reactivation_bypass",
    "raw_audit_payload_bypass",
    "non_object_transport_normalization_bypass",
    "invalid_credential_unbound_contract_bypass",
    "foreign_session_binding_authorization_bypass",
    "guest_state_401_mapping_bypass",
    "session_binding_403_mapping_bypass",
    "persistence_503_mapping_bypass",
    "credential_subject_authority_bypass",
    "auth_event_bypass",
    "history_event_bypass",
    "public_projection_bypass",
)
REVIEW_REQUIRED_TARGETS = EXPECTED[-4:]


def runner():
    spec = importlib.util.spec_from_file_location(
        "phase_02_d13_sensitivity_runner",
        RUNNER_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d13_evidence_requires_exact_fourteen_controls_restoration_and_fresh_head() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d13-test-head",
        actual_head="d13-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert len(module.TARGETS) == 14
    assert evidence["contract_version"] == "phase_02_d13_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d13_review_invariant_targets_are_present_before_directness_checks() -> None:
    module = runner()

    assert set(REVIEW_REQUIRED_TARGETS).issubset(module.TARGETS)
    assert len(module.TARGETS) == len(EXPECTED)


def test_d13_targets_cover_each_issue_guest_session_boundary() -> None:
    module = runner()

    assert module.TARGETS["view_application_bypass"].endswith(
        "test_guest_session_delegates_to_issue_guest_session_application"
    )
    assert module.TARGETS["expired_guest_reactivation_bypass"].endswith(
        "test_expired_persisted_guest_is_not_reactivated"
    )
    assert module.TARGETS["merged_guest_reactivation_bypass"].endswith(
        "test_merged_persisted_guest_is_not_reactivated"
    )
    assert module.TARGETS["raw_audit_payload_bypass"].endswith(
        "test_guest_session_does_not_persist_request_secret_markers"
    )
    assert module.TARGETS["non_object_transport_normalization_bypass"].endswith(
        "test_truthy_non_object_json_normalizes_to_a_new_unbound_guest"
    )
    assert module.TARGETS["invalid_credential_unbound_contract_bypass"].endswith(
        "test_invalid_credential_issues_a_new_unbound_guest_without_adopting_body_identity"
    )
    assert module.TARGETS["foreign_session_binding_authorization_bypass"].endswith(
        "test_foreign_guest_session_binding_remains_forbidden"
    )
    assert module.TARGETS["guest_state_401_mapping_bypass"].endswith(
        "test_expired_persisted_guest_is_not_reactivated"
    )
    assert module.TARGETS["session_binding_403_mapping_bypass"].endswith(
        "test_foreign_guest_session_binding_remains_forbidden"
    )
    assert module.TARGETS["persistence_503_mapping_bypass"].endswith(
        "test_guest_session_returns_structured_503_when_persistence_store_is_unavailable"
    )


def test_d13_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d13",
        actual_head="d13",
        original_exit_code=0,
        mutations=valid[:-1],
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d13",
        actual_head="d13",
        original_exit_code=0,
        mutations=bad,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d13",
        actual_head="stale",
        original_exit_code=0,
        mutations=valid,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d13",
        actual_head="d13",
        original_exit_code=0,
        mutations=valid,
        source_restored=False,
        working_tree_unchanged=False,
        residual_diff_zero=False,
    )["status"] == "fail"


def test_d13_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D13")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))


def test_d13_workflow_uses_runtime_checkout_sha_for_sensitivity_authority() -> None:
    workflow = (ROOT / ".github" / "workflows" / "production-gate.yml").read_text(
        encoding="utf-8"
    )
    d13_sensitivity_block = workflow.split(
        "      - name: Phase 2 D13 sensitivity negative controls\n", 1
    )[1].split("      - name: Upload Phase 2 D13 sensitivity evidence\n", 1)[0]

    assert "PHASE_02_D13_SENSITIVITY_HEAD: ${{ github.sha }}" in d13_sensitivity_block
    assert (
        "PHASE_02_D13_SENSITIVITY_HEAD: "
        "${{ github.event.pull_request.head.sha }}"
    ) not in d13_sensitivity_block
