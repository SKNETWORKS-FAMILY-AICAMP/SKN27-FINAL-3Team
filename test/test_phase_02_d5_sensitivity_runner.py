from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "refactoring" / "verify_phase_02_d5_report_read_queries_test_sensitivity.py"
EXPECTED = (
    "list_view_application_bypass",
    "detail_view_application_bypass",
    "list_owner_filter_bypass",
    "detail_foreign_authorization_bypass",
    "detail_privacy_projection_bypass",
)

def runner():
    spec = importlib.util.spec_from_file_location("phase_02_d5_sensitivity_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def outcomes(module):
    return tuple(module.MutationOutcome(name, 1, "assertion") for name in module.TARGETS)

def test_d5_evidence_requires_exact_mutation_set_and_restored_tree() -> None:
    module = runner()
    evidence = module.build_evidence(head="d5-test-head", original_exit_code=0, mutations=outcomes(module), working_tree_unchanged=True)
    assert tuple(module.TARGETS) == EXPECTED
    assert evidence["contract_version"] == "phase_02_d5_sensitivity.v1"
    assert evidence["status"] == "pass"

def test_d5_evidence_rejects_missing_success_and_dirty_tree() -> None:
    module = runner()
    valid = outcomes(module)
    assert module.build_evidence(head="d5", original_exit_code=0, mutations=valid[:-1], working_tree_unchanged=True)["status"] == "fail"
    bad = valid[:-1] + (module.MutationOutcome(EXPECTED[-1], 0, "assertion"),)
    assert module.build_evidence(head="d5", original_exit_code=0, mutations=bad, working_tree_unchanged=True)["status"] == "fail"
    assert module.build_evidence(head="d5", original_exit_code=0, mutations=valid, working_tree_unchanged=False)["status"] == "fail"

def test_d5_failure_kind_requires_assertion() -> None:
    module = runner()
    assert module.failure_kind(subprocess.CompletedProcess(["test"], 1, "AssertionError: D5")) == "assertion"
    with pytest.raises(module.SensitivityError, match="assertion mismatch"):
        module.failure_kind(subprocess.CompletedProcess(["test"], 1, "ImportError"))


def test_each_d5_mutation_uses_a_unique_empty_pycache_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    module = runner()
    launches: list[tuple[str | None, bool | None, bool | None]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs.get("env")
        prefix = environment.get("PYTHONPYCACHEPREFIX") if isinstance(environment, dict) else None
        prefix_path = Path(prefix) if prefix else None
        launches.append(
            (
                prefix,
                prefix_path.exists() if prefix_path else None,
                not any(prefix_path.iterdir()) if prefix_path else None,
            )
        )
        return subprocess.CompletedProcess(command, 1, "AssertionError: D5")

    monkeypatch.setattr(module, "_run", fake_run)

    assert module._run_mutation("first_mutation", "first.target").failure_kind == "assertion"
    assert module._run_mutation("second_mutation", "second.target").failure_kind == "assertion"

    assert len(launches) == 2
    assert all(prefix is not None for prefix, _, _ in launches)
    prefixes = [Path(prefix) for prefix, _, _ in launches if prefix]
    assert all(exists is True for _, exists, _ in launches)
    assert all(is_empty is True for _, _, is_empty in launches)
    assert prefixes[0] != prefixes[1]
    assert all(not prefix.is_relative_to(module.REPO_ROOT) for prefix in prefixes)
    assert all(not prefix.exists() for prefix in prefixes)


def test_d5_failure_evidence_preserves_completed_and_failed_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = runner()
    evidence_path = tmp_path / "d5-evidence.json"
    mutation_results = iter(
        (
            subprocess.CompletedProcess(["mutation"], 1, "AssertionError: first"),
            subprocess.CompletedProcess(["mutation"], 0, "unexpected pass"),
        )
    )

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, "")
        if command[1] == "backend/manage.py":
            return subprocess.CompletedProcess(command, 0, "")
        return next(mutation_results)

    monkeypatch.setattr(
        module,
        "TARGETS",
        {
            "first_mutation": "first.target",
            "second_mutation": "second.target",
        },
    )
    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setenv("PHASE_02_D5_SENSITIVITY_HEAD", "d5-test-head")
    monkeypatch.setenv("PHASE_02_D5_SENSITIVITY_EVIDENCE_PATH", str(evidence_path))

    assert module.main() == 1

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "fail"
    assert evidence["mutations"] == [
        {
            "name": "first_mutation",
            "exit_code": 1,
            "failure_kind": "assertion",
        }
    ]
    assert evidence.get("completed_mutations") == ["first_mutation"]
    assert evidence.get("failed_mutation") == "second_mutation"
    assert evidence.get("failed_mutation_exit_code") == 0
    assert evidence.get("error") == "second_mutation: mutation unexpectedly passed"
