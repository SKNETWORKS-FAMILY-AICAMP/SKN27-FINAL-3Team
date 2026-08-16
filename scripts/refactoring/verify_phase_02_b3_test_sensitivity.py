#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-B3 analysis application boundary."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = REPO_ROOT / "tmp" / "phase-02-b3-sensitivity-evidence.json"
TEST_MODULE = "chatbot.test_phase_02_case_analysis_use_case"
TARGETS = {
    "authorization_bypass": (
        "chatbot.test_phase_02_case_analysis_use_case."
        "CaseAnalysisUseCaseCharacterizationTests."
        "test_foreign_owner_invalid_payload_is_denied_before_validation_without_queue_rows"
    ),
    "validation_bypass": (
        "chatbot.test_phase_02_case_analysis_use_case."
        "CaseAnalysisUseCaseCharacterizationTests."
        "test_owner_invalid_extra_field_preserves_validation_contract_without_queue_rows"
    ),
    "reusable_job_bypass": (
        "chatbot.test_phase_02_case_analysis_use_case."
        "CaseAnalysisUseCaseCharacterizationTests."
        "test_exact_duplicate_reuses_job_and_work_item_for_same_fact_version"
    ),
}


MUTATION_CHILD_SCRIPT = r'''
import os
from pathlib import Path
import sys
from unittest.mock import patch

repo_root = Path(sys.argv[1]).resolve()
test_id = sys.argv[2]
mutation = sys.argv[3]
sys.path.insert(0, str(repo_root / "backend"))
sys.path.insert(0, str(repo_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.test.runner import DiscoverRunner

if mutation == "authorization_bypass":
    context = patch(
        "app.application.cases.start_analysis.authorize_resource_access",
        return_value={"allowed": True},
    )
elif mutation == "validation_bypass":
    class BypassedValidationPayload:
        def model_dump(self, *, mode):
            return {}

    context = patch(
        "app.application.cases.start_analysis.StartCaseAnalysisRequest.model_validate",
        return_value=BypassedValidationPayload(),
    )
elif mutation == "reusable_job_bypass":
    from app.application.cases import start_analysis
    from chatbot.models import AnalysisJob

    original_start_case_analysis = start_analysis.start_case_analysis
    calls = 0

    def force_new_job(case_id, **kwargs):
        global calls
        calls += 1
        if calls > 1:
            existing_job = (
                AnalysisJob.objects.filter(case__case_id=case_id)
                .order_by("-created_at")
                .first()
            )
            if existing_job is not None:
                existing_job.status = "failed"
                existing_job.save(update_fields=["status"])
        return original_start_case_analysis(case_id, **kwargs)

    context = patch(
        "app.application.cases.start_analysis.start_case_analysis",
        side_effect=force_new_job,
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation}")

with context:
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests([test_id])
raise SystemExit(0 if failures == 0 else 1)
'''


class SensitivityError(RuntimeError):
    """Raised when a sensitivity mutation does not prove its target contract."""


@dataclass(frozen=True)
class MutationOutcome:
    name: str
    exit_code: int
    failure_kind: str


def _evidence_head() -> str:
    return os.environ.get("PHASE_02_B3_SENSITIVITY_HEAD", "").strip() or _git_output(
        "rev-parse", "HEAD"
    ).strip()

def _evidence_path(configured: str = "") -> Path:
    return Path(configured).resolve() if configured else DEFAULT_EVIDENCE_PATH


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _run_django_test(test_id: str) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "backend/manage.py", "test", test_id, "--verbosity", "1"])


def failure_kind(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 0:
        raise SensitivityError("mutation unexpectedly passed")
    if "AssertionError" not in result.stdout:
        raise SensitivityError("assertion mismatch: mutation did not fail by assertion")
    return "assertion"


def _git_output(*arguments: str) -> str:
    result = _run(
        ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *arguments]
    )
    if result.returncode != 0:
        raise SensitivityError(f"git {' '.join(arguments)} failed")
    return result.stdout


def _working_tree_status() -> str:
    return _git_output("status", "--porcelain")

def _run_mutation(name: str, target: str) -> MutationOutcome:
    result = _run(
        [
            sys.executable,
            "-c",
            MUTATION_CHILD_SCRIPT,
            str(REPO_ROOT),
            target,
            name,
        ]
    )
    return MutationOutcome(
        name=name,
        exit_code=result.returncode,
        failure_kind=failure_kind(result),
    )


def build_evidence(
    *,
    head: str,
    original_exit_code: int,
    mutations: tuple[MutationOutcome, ...],
    working_tree_unchanged: bool,
) -> dict[str, Any]:
    expected_names = tuple(TARGETS)
    passed = (
        original_exit_code == 0
        and tuple(mutation.name for mutation in mutations) == expected_names
        and all(
            mutation.exit_code != 0 and mutation.failure_kind == "assertion"
            for mutation in mutations
        )
        and working_tree_unchanged
    )
    return {
        "contract_version": "phase_02_b3_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "original": {"exit_code": original_exit_code},
        "mutations": [
            {
                "name": mutation.name,
                "exit_code": mutation.exit_code,
                "failure_kind": mutation.failure_kind,
            }
            for mutation in mutations
        ],
        "working_tree_unchanged": working_tree_unchanged,
    }


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-path", type=Path, default=None)
    args = parser.parse_args(argv)

    before_status = _working_tree_status()
    original_exit_code = 1
    mutations: tuple[MutationOutcome, ...] = ()
    error: str | None = None
    try:
        original = _run_django_test(TEST_MODULE)
        original_exit_code = original.returncode
        if original_exit_code != 0:
            raise SensitivityError(f"original B3 characterization suite failed: {original_exit_code}")
        mutations = tuple(_run_mutation(name, target) for name, target in TARGETS.items())
    except (OSError, SensitivityError) as exc:
        error = str(exc)

    working_tree_unchanged = before_status == _working_tree_status()
    evidence = build_evidence(
        head=_evidence_head(),
        original_exit_code=original_exit_code,
        mutations=mutations,
        working_tree_unchanged=working_tree_unchanged,
    )
    if error is not None:
        evidence["error"] = error

    evidence_path = args.evidence_path or _evidence_path(
        os.environ.get("PHASE_02_B3_SENSITIVITY_EVIDENCE_PATH", "")
    )
    _write_evidence(evidence_path, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())