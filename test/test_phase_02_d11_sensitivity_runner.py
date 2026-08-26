from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "refactoring" / "verify_phase_02_d11_analysis_read_queries_sensitivity.py"
EXPECTED = (
    "list_view_application_bypass",
    "detail_view_application_bypass",
    "result_view_application_bypass",
    "list_scope_authorization_bypass",
    "job_owner_precedence_bypass",
    "canonical_guest_policy_bypass",
    "progress_cache_identity_validation_bypass",
    "public_projection_bypass",
    "pending_terminal_status_bypass",
    "access_metadata_absence_fail_open_bypass",
    "guest_session_list_scope_bypass",
)


def runner():
    spec = importlib.util.spec_from_file_location("phase_02_d11_sensitivity_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d11_evidence_requires_exact_mutation_set_restoration_and_fresh_head() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d11-test-head",
        actual_head="d11-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d11_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d11_targets_cover_each_analysis_read_boundary() -> None:
    module = runner()

    assert module.TARGETS["list_view_application_bypass"].endswith(
        "test_analysis_job_list_delegates_to_execute_list_analysis_jobs"
    )
    assert module.TARGETS["detail_view_application_bypass"].endswith(
        "test_analysis_job_detail_delegates_to_execute_get_analysis_job_detail"
    )
    assert module.TARGETS["result_view_application_bypass"].endswith(
        "test_analysis_result_delegates_to_execute_get_analysis_result"
    )
    assert module.TARGETS["list_scope_authorization_bypass"].endswith(
        "test_authenticated_owner_list_is_scoped_to_owner"
    )
    assert module.TARGETS["job_owner_precedence_bypass"].endswith(
        "test_guest_session_cannot_read_foreign_owner_analysis_job_detail_even_when_session_matches"
    )
    assert module.TARGETS["canonical_guest_policy_bypass"].endswith(
        "test_expired_guest_cannot_list_analysis_jobs"
    )
    assert module.TARGETS["progress_cache_identity_validation_bypass"].endswith(
        "test_analysis_job_detail_discards_cache_snapshot_with_mismatched_identity"
    )
    assert module.TARGETS["public_projection_bypass"].endswith(
        "test_analysis_job_detail_excludes_private_metadata"
    )
    assert module.TARGETS["pending_terminal_status_bypass"].endswith(
        "test_analysis_result_preserves_pending_and_terminal_http_status"
    )
    assert module.TARGETS["access_metadata_absence_fail_open_bypass"].endswith(
        "AnalysisReadQueriesSecurityTests"
    )
    assert module.TARGETS["guest_session_list_scope_bypass"].endswith(
        "test_valid_guest_lists_own_session_jobs_and_excludes_foreign_or_unverifiable_candidates"
    )


def test_d11_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d11",
        actual_head="d11",
        original_exit_code=0,
        mutations=valid[:-1],
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d11",
        actual_head="d11",
        original_exit_code=0,
        mutations=bad,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d11",
        actual_head="stale",
        original_exit_code=0,
        mutations=valid,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d11",
        actual_head="d11",
        original_exit_code=0,
        mutations=valid,
        source_restored=False,
        working_tree_unchanged=False,
        residual_diff_zero=False,
    )["status"] == "fail"


def test_d11_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D11")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))
