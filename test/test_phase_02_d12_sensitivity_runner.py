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
    / "verify_phase_02_d12_get_current_auth_identity_sensitivity.py"
)
EXPECTED = (
    "view_application_bypass",
    "anonymous_transport_contract_bypass",
    "guest_identity_source_mismatch_bypass",
    "persisted_guest_state_bypass",
    "persisted_auth_session_bypass",
    "session_binding_authorization_bypass",
    "persistence_failure_mapping_bypass",
    "history_event_bypass",
    "private_projection_bypass",
)


def runner():
    spec = importlib.util.spec_from_file_location(
        "phase_02_d12_sensitivity_runner",
        RUNNER_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)


def test_d12_evidence_requires_exact_mutation_set_restoration_and_fresh_head() -> None:
    module = runner()
    evidence = module.build_evidence(
        head="d12-test-head",
        actual_head="d12-test-head",
        original_exit_code=0,
        mutations=outcomes(module),
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )

    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d12_sensitivity.v1"
    assert evidence["status"] == "pass"


def test_d12_targets_cover_each_get_current_auth_identity_boundary() -> None:
    module = runner()

    assert module.TARGETS["view_application_bypass"].endswith(
        "test_auth_me_delegates_to_execute_get_current_auth_identity"
    )
    assert module.TARGETS["anonymous_transport_contract_bypass"].endswith(
        "test_openapi_requires_bearer_or_signed_guest_credential"
    )
    assert module.TARGETS["guest_identity_source_mismatch_bypass"].endswith(
        "test_conflicting_header_and_query_guest_ids_fail_closed"
    )
    assert module.TARGETS["persisted_guest_state_bypass"].endswith(
        "test_existing_expired_guest_identity_fails_closed"
    )
    assert module.TARGETS["persisted_auth_session_bypass"].endswith(
        "test_application_rejects_unpersisted_jwt_before_public_projection"
    )
    assert module.TARGETS["session_binding_authorization_bypass"].endswith(
        "test_persisted_session_binding_error_maps_to_forbidden"
    )
    assert module.TARGETS["persistence_failure_mapping_bypass"].endswith(
        "test_persistence_database_error_maps_to_retryable_provider_unavailable"
    )
    assert module.TARGETS["history_event_bypass"].endswith(
        "test_successful_persistence_records_auth_me_checked_history_after_auth_event"
    )
    assert module.TARGETS["private_projection_bypass"].endswith(
        "test_public_response_excludes_credentials_and_raw_claims"
    )


def test_d12_openapi_mutation_remains_a_valid_non_anonymous_route_spec() -> None:
    module = runner()

    assert (
        '        security_requirements=(\n'
        '            {"bearerAuth": ()},\n'
        '        ),\n'
        '    ),\n'
        '    RouteSpec(\n'
        '        operation_id="getResumeManifest",\n'
    ) in module.MUTATION_CHILD_SCRIPT


def test_d12_evidence_rejects_missing_success_dirty_or_stale_results() -> None:
    module = runner()
    valid = outcomes(module)

    assert module.build_evidence(
        head="d12",
        actual_head="d12",
        original_exit_code=0,
        mutations=valid[:-1],
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(
        head="d12",
        actual_head="d12",
        original_exit_code=0,
        mutations=bad,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d12",
        actual_head="stale",
        original_exit_code=0,
        mutations=valid,
        source_restored=True,
        working_tree_unchanged=True,
        residual_diff_zero=True,
    )["status"] == "fail"
    assert module.build_evidence(
        head="d12",
        actual_head="d12",
        original_exit_code=0,
        mutations=valid,
        source_restored=False,
        working_tree_unchanged=False,
        residual_diff_zero=False,
    )["status"] == "fail"


def test_d12_failure_kind_requires_assertion() -> None:
    module = runner()

    assert module.failure_kind(
        subprocess.CompletedProcess(["test"], 1, "AssertionError: D12")
    ) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))

