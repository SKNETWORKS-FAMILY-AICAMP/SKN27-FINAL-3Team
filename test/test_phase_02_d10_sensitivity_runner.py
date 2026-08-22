from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "refactoring" / "verify_phase_02_d10_file_read_queries_sensitivity.py"
EXPECTED = (
    "list_view_application_bypass",
    "detail_view_application_bypass",
    "list_scope_authorization_bypass",
    "detail_owner_authorization_bypass",
    "canonical_guest_policy_bypass",
    "privacy_projection_bypass",
)


def runner():
    spec = importlib.util.spec_from_file_location("phase_02_d10_sensitivity_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d10_evidence_requires_exact_mutation_set_restoration_and_fresh_head() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d10-test-head",
        actual_head="d10-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d10_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d10_targets_cover_the_file_read_contract_boundaries() -> None:
    module = runner()

    assert module.TARGETS["list_view_application_bypass"].endswith(
        "test_file_list_delegates_to_execute_list_file_attachments"
    )
    assert module.TARGETS["detail_view_application_bypass"].endswith(
        "test_file_detail_delegates_to_execute_get_file_attachment"
    )
    assert module.TARGETS["list_scope_authorization_bypass"].endswith(
        "test_valid_guest_without_session_cannot_enumerate_cross_owner_attachments"
    )
    assert module.TARGETS["detail_owner_authorization_bypass"].endswith(
        "test_foreign_owner_detail_without_optional_session_is_denied"
    )
    assert module.TARGETS["canonical_guest_policy_bypass"].endswith(
        "test_expired_guest_detail_uses_canonical_guest_identity_policy"
    )
    assert module.TARGETS["privacy_projection_bypass"].endswith(
        "test_list_and_detail_exclude_private_attachment_metadata"
    )


def test_d10_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d10",
        actual_head="d10",
        original_exit_code=0,
        mutations=valid[:-1],
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d10",
        actual_head="d10",
        original_exit_code=0,
        mutations=bad,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d10",
        actual_head="stale",
        original_exit_code=0,
        mutations=valid,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d10",
        actual_head="d10",
        original_exit_code=0,
        mutations=valid,
        source_restored=False,
        working_tree_unchanged=False,
        residual_diff_zero=False,
    )["status"] == "fail"


def test_d10_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D10")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))