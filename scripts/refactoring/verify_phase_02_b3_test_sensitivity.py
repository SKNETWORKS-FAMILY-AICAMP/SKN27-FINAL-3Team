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
import sys
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

from django.test.runner import DiscoverRunner

mutation = sys.argv[1]
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
                AnalysisJob.objects.filter(case_id=case_id)
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
    failures = DiscoverRunner(verbosity=1).run_tests([sys.argv[2]])
raise SystemExit(bool(failures))
'''


class SensitivityError(RuntimeError):
    """Raised when a sensitivity mutation does not prove its target contract."""


@dataclass(frozen=True)
class MutationOutcome:
    name: str
    exit_code: int
    failure_kind: str


def _evidence_head() -> str:
    return os.environ.get("PHASE_02_B3_SENSITIVITY_HEAD") or subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def failure_kind(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 0:
        raise SensitivityError("mutation unexpectedly passed")
    if "AssertionError" not in result.stdout:
        raise SensitivityError("assertion mismatch: mutation did not fail by assertion")
    return "assertion"


def _assert_clean_worktree() -> bool:
    return not _run(["git", "status", "--porcelain"]).stdout.strip()


def _run_mutation(name: str, target: str) -> MutationOutcome:
    result = _run([sys.executable, "-c", MUTATION_CHILD_SCRIPT, name, target])
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
    return {
        "contract_version": "phase_02_b3_sensitivity.v1",
        "status": "pass",
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


def _verify_controls(
    original_exit_code: int,
    mutations: tuple[MutationOutcome, ...],
    working_tree_unchanged: bool,
) -> None:
    if original_exit_code != 0:
        raise SensitivityError("original B3 characterization suite did not pass")
    if not working_tree_unchanged:
        raise SensitivityError("sensitivity runner changed the working tree")
    if tuple(mutation.name for mutation in mutations) != tuple(TARGETS):
        raise SensitivityError("mutation target set mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-path", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)

    try:
        original = _run([sys.executable, "manage.py", "test", TEST_MODULE, "--verbosity", "1"])
        mutations = tuple(_run_mutation(name, target) for name, target in TARGETS.items())
        working_tree_unchanged = _assert_clean_worktree()
        _verify_controls(original.returncode, mutations, working_tree_unchanged)
        evidence = build_evidence(
            head=_evidence_head(),
            original_exit_code=original.returncode,
            mutations=mutations,
            working_tree_unchanged=working_tree_unchanged,
        )
    except (OSError, SensitivityError) as exc:
        print(f"phase 02 B3 sensitivity failure: {exc}", file=sys.stderr)
        return 1

    args.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())