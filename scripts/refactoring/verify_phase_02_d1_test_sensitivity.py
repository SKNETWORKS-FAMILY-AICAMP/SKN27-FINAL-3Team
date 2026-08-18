#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D1 case-list boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = (
    REPO_ROOT / "tmp" / "phase-02-d1-sensitivity-evidence.json"
)
TEST_MODULE: Final = "chatbot.test_phase_02_case_list_use_case"
TARGETS: Final = {
    "identity_authority_bypass": (
        "chatbot.test_phase_02_case_list_use_case."
        "CaseListUseCaseCharacterizationTests."
        "test_application_derives_owner_from_trusted_identity_and_returns_only_owned_cases"
    ),
    "owner_filter_bypass": (
        "chatbot.test_phase_02_case_list_use_case."
        "CaseListUseCaseCharacterizationTests."
        "test_application_derives_owner_from_trusted_identity_and_returns_only_owned_cases"
    ),
    "view_application_bypass": (
        "chatbot.test_phase_02_case_list_use_case."
        "CaseListUseCaseCharacterizationTests."
        "test_z_application_has_no_http_or_mock_dependencies_and_get_view_is_an_adapter"
    ),
}


MUTATION_CHILD_SCRIPT: Final = r'''
from __future__ import annotations

from contextlib import contextmanager, nullcontext
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


def unfiltered_list_cases(*, owner_id):
    from chatbot.case_repository import case_to_api
    from chatbot.models import Case

    return [case_to_api(case) for case in Case.objects.all()]


@contextmanager
def temporarily_bypass_application_in_view():
    view_path = repo_root / "backend" / "chatbot" / "views.py"
    original_bytes = view_path.read_bytes()
    encoding = "utf-8-sig" if original_bytes.startswith(b"\xef\xbb\xbf") else "utf-8"
    source = original_bytes.decode(encoding).replace("\r\n", "\n")
    newline = "\n"
    repository_import = newline.join(
        (
            "from chatbot.case_repository import (",
            "    CaseRepositoryError,",
            "    create_case,",
            "    get_case_access_metadata,",
            ")",
        )
    )
    bypassed_repository_import = newline.join(
        (
            "from chatbot.case_repository import (",
            "    CaseRepositoryError,",
            "    create_case,",
            "    get_case_access_metadata,",
            "    list_cases,",
            ")",
        )
    )
    application_block = newline.join(
        (
            "        try:",
            "            result = execute_list_consultation_cases(",
            "                ListConsultationCasesQuery(identity_payload=identity_payload)",
            "            )",
            "        except CaseListAccessDenied as exc:",
            "            return _object_access_denied_response(request, exc.access)",
        )
    )
    bypassed_application_block = newline.join(
        (
            "        result = type(",
            "            \"_MutationListCasesResult\",",
            "            (),",
            "            {\"cases\": list_cases(owner_id=owner_id)},",
            "        )()",
        )
    )
    if source.count(repository_import) != 1 or source.count(application_block) != 1:
        raise RuntimeError("D1 view mutation anchors were not unique")
    mutated = source.replace(repository_import, bypassed_repository_import).replace(
        application_block,
        bypassed_application_block,
    )
    view_path.write_bytes(mutated.encode(encoding))
    try:
        yield
    finally:
        view_path.write_bytes(original_bytes)


if mutation_name == "identity_authority_bypass":
    mutation = patch(
        "app.application.cases.list_cases.access_subject_from_payload",
        return_value={
            "subject": {
                "subject_type": "user",
                "user_id": "usr_phase_02_d1_foreign",
            }
        },
    )
elif mutation_name == "owner_filter_bypass":
    mutation = patch(
        "app.application.cases.list_cases.list_cases",
        side_effect=unfiltered_list_cases,
    )
elif mutation_name == "view_application_bypass":
    mutation = temporarily_bypass_application_in_view()
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
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


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _git_output(*arguments: str) -> str:
    result = _run(
        ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *arguments]
    )
    if result.returncode != 0:
        raise SensitivityError(f"git {' '.join(arguments)} failed")
    return result.stdout


def _working_tree_status() -> str:
    return _git_output("status", "--porcelain")


def _evidence_head() -> str:
    configured_head = os.environ.get("PHASE_02_D1_SENSITIVITY_HEAD", "").strip()
    return configured_head or _git_output("rev-parse", "HEAD").strip()


def _evidence_path() -> Path:
    configured_path = os.environ.get("PHASE_02_D1_SENSITIVITY_EVIDENCE_PATH", "")
    return Path(configured_path).resolve() if configured_path else DEFAULT_EVIDENCE_PATH


def _run_django_test(test_id: str) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "backend/manage.py", "test", test_id, "--verbosity", "1"])


def failure_kind(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 0:
        raise SensitivityError("mutation unexpectedly passed")
    if "AssertionError" not in result.stdout:
        raise SensitivityError("assertion mismatch: mutation did not fail by assertion")
    return "assertion"


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
        "contract_version": "phase_02_d1_sensitivity.v1",
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


def main() -> int:
    before_status = _working_tree_status()
    original_exit_code = 1
    mutations: tuple[MutationOutcome, ...] = ()
    error: str | None = None
    try:
        original = _run_django_test(TEST_MODULE)
        original_exit_code = original.returncode
        if original_exit_code != 0:
            raise SensitivityError(
                f"original D1 characterization suite failed: {original_exit_code}"
            )
        mutations = tuple(
            _run_mutation(name, target) for name, target in TARGETS.items()
        )
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
    _write_evidence(_evidence_path(), evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
