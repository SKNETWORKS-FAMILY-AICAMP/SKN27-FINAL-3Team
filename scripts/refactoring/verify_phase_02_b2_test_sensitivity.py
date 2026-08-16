#!/usr/bin/env python3
"""Verify P2-B2 confirmation-boundary assertions with runtime negative controls."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-b2-sensitivity-evidence.json"


class SensitivityError(RuntimeError):
    """Raised when a P2-B2 negative control is not deterministic."""


@dataclass(frozen=True)
class MutationTarget:
    name: str
    test_id: str


@dataclass(frozen=True)
class MutationOutcome:
    name: str
    exit_code: int
    failure_kind: str


TARGETS: Final = (
    MutationTarget(
        name="authorization_bypass",
        test_id=(
            "chatbot.test_phase_02_case_fact_confirmation_use_case."
            "CaseFactConfirmationUseCaseCharacterizationTests."
            "test_foreign_owner_invalid_payload_is_denied_before_validation"
        ),
    ),
    MutationTarget(
        name="validation_bypass",
        test_id=(
            "chatbot.test_phase_02_case_fact_confirmation_use_case."
            "CaseFactConfirmationUseCaseCharacterizationTests."
            "test_owner_invalid_payload_preserves_validation_error_contract"
        ),
    ),
)


MUTATION_CHILD_SCRIPT: Final = r'''
from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch

repo_root = Path(sys.argv[1]).resolve()
test_id = sys.argv[2]
mutation_name = sys.argv[3]
sys.path.insert(0, str(repo_root / "backend"))
sys.path.insert(0, str(repo_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test.runner import DiscoverRunner


class BypassedValidationPayload:
    def model_dump(self, *, mode: str) -> dict[str, object]:
        return {"facts": {"mutation": "validation_bypass"}}


if mutation_name == "authorization_bypass":
    mutation = patch(
        "app.application.cases.confirm_facts.authorize_resource_access",
        return_value={"allowed": True},
    )
elif mutation_name == "validation_bypass":
    mutation = patch(
        "app.application.cases.confirm_facts.ConfirmCaseFactsRequest.model_validate",
        return_value=BypassedValidationPayload(),
    )
else:
    raise RuntimeError(f"unknown mutation: {mutation_name}")

with mutation:
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests([test_id])

raise SystemExit(0 if failures == 0 else 1)
'''


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _run_django_test(test_id: str) -> subprocess.CompletedProcess[str]:
    return _run_command(
        [
            sys.executable,
            "backend/manage.py",
            "test",
            test_id,
            "--verbosity",
            "1",
        ]
    )


def _run_mutated_test(target: MutationTarget) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        prefix="phase-02-b2-sensitivity-",
        delete=False,
    ) as script_file:
        script_path = Path(script_file.name)
        script_file.write(MUTATION_CHILD_SCRIPT)
    try:
        return _run_command(
            [
                sys.executable,
                str(script_path),
                str(REPO_ROOT),
                target.test_id,
                target.name,
            ]
        )
    finally:
        script_path.unlink(missing_ok=True)


def failure_kind(completed: subprocess.CompletedProcess[str]) -> str:
    if completed.returncode == 0:
        raise SensitivityError("mutation unexpectedly passed")
    if "AssertionError" not in completed.stdout:
        raise SensitivityError("mutation did not fail with an assertion mismatch")
    return "assertion"


def _git_output(*arguments: str) -> str:
    completed = _run_command(
        [
            "git",
            "-c",
            f"safe.directory={REPO_ROOT.as_posix()}",
            *arguments,
        ]
    )
    if completed.returncode != 0:
        raise SensitivityError(f"git {' '.join(arguments)} failed")
    return completed.stdout


def _working_tree_status() -> str:
    return _git_output("status", "--porcelain")


def _head() -> str:
    return _git_output("rev-parse", "HEAD").strip()


def _evidence_path() -> Path:
    configured = os.environ.get("PHASE_02_B2_SENSITIVITY_EVIDENCE_PATH", "")
    return Path(configured).resolve() if configured else DEFAULT_EVIDENCE_PATH


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_evidence(
    *,
    head: str,
    original_exit_code: int | None,
    mutations: tuple[MutationOutcome, ...],
    working_tree_unchanged: bool,
) -> dict[str, object]:
    expected_names = tuple(target.name for target in TARGETS)
    outcome_names = tuple(outcome.name for outcome in mutations)
    passed = (
        original_exit_code == 0
        and outcome_names == expected_names
        and all(
            outcome.exit_code != 0 and outcome.failure_kind == "assertion"
            for outcome in mutations
        )
        and working_tree_unchanged
    )
    return {
        "contract_version": "phase_02_b2_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "original": {"exit_code": original_exit_code},
        "mutations": [
            {
                "name": outcome.name,
                "exit_code": outcome.exit_code,
                "failure_kind": outcome.failure_kind,
            }
            for outcome in mutations
        ],
        "working_tree_unchanged": working_tree_unchanged,
    }


def main() -> int:
    before_status = _working_tree_status()
    head = _head()
    original_exit_code: int | None = None
    outcomes: list[MutationOutcome] = []
    error: str | None = None
    try:
        original = _run_django_test("chatbot.test_phase_02_case_fact_confirmation_use_case")
        original_exit_code = original.returncode
        if original.returncode != 0:
            raise SensitivityError(
                f"original P2-B2 test failed with exit code {original.returncode}"
            )
        for target in TARGETS:
            mutated = _run_mutated_test(target)
            outcomes.append(
                MutationOutcome(
                    name=target.name,
                    exit_code=mutated.returncode,
                    failure_kind=failure_kind(mutated),
                )
            )
    except (OSError, SensitivityError) as exc:
        error = str(exc)

    working_tree_unchanged = before_status == _working_tree_status()
    evidence = build_evidence(
        head=head,
        original_exit_code=original_exit_code,
        mutations=tuple(outcomes),
        working_tree_unchanged=working_tree_unchanged,
    )
    if error is not None:
        evidence["error"] = error
    _write_evidence(_evidence_path(), evidence)
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
