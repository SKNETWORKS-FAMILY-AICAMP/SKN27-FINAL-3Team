#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D4 save-state boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-d4-sensitivity-evidence.json"
TEST_MODULE: Final = "chatbot.test_phase_02_conversation_save_state_use_case"
TARGETS: Final = {
    "view_application_bypass": (
        "chatbot.test_phase_02_conversation_save_state_use_case."
        "ConversationSaveStateUseCaseCharacterizationTests."
        "test_http_post_delegates_to_application_with_trusted_identity_and_preserves_save_state_response"
    ),
    "session_authorization_bypass": (
        "chatbot.test_phase_02_conversation_save_state_use_case."
        "ConversationSaveStateUseCaseCharacterizationTests."
        "test_foreign_owner_is_denied_before_mutation"
    ),
    "guest_saved_login_bypass": (
        "chatbot.test_phase_02_conversation_save_state_use_case."
        "ConversationSaveStateUseCaseCharacterizationTests."
        "test_guest_saved_is_rejected_without_mutation"
    ),
    "state_propagation_bypass": (
        "chatbot.test_phase_02_conversation_save_state_use_case."
        "ConversationSaveStateUseCaseCharacterizationTests."
        "test_http_post_delegates_to_application_with_trusted_identity_and_preserves_save_state_response"
    ),
    "history_event_bypass": (
        "chatbot.test_phase_02_conversation_save_state_use_case."
        "ConversationSaveStateUseCaseCharacterizationTests."
        "test_http_post_delegates_to_application_with_trusted_identity_and_preserves_save_state_response"
    ),
}


MUTATION_CHILD_SCRIPT: Final = r'''
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import sys

repo_root = Path(sys.argv[1]).resolve()
test_id = sys.argv[2]
mutation_name = sys.argv[3]
sys.path.insert(0, str(repo_root / "backend"))
sys.path.insert(0, str(repo_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test.runner import DiscoverRunner


def read_source(path: Path):
    original = path.read_bytes()
    encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
    return original, encoding, original.decode(encoding).replace("\r\n", "\n")


@contextmanager
def mutate_once(path: Path, old: str, new: str):
    original_bytes, encoding, source = read_source(path)
    if source.count(old) != 1:
        raise RuntimeError(f"mutation anchor was not unique: {path.name}")
    path.write_bytes(source.replace(old, new).encode(encoding))
    try:
        yield
    finally:
        path.write_bytes(original_bytes)


@contextmanager
def temporarily_bypass_application_in_view():
    view_path = repo_root / "backend" / "chatbot" / "views.py"
    original_bytes, encoding, source = read_source(view_path)
    import_anchor = "import logging\n"
    repository_import = "from chatbot.repositories import (\n"
    application_call = "        result = execute_update_conversation_save_state(command)"
    bypassed_call = "\n".join((
        "        result = SimpleNamespace(",
        "            conversation_save=mark_conversation_save_state(",
        "                session_id=session_id,",
        "                save_state=conversation_save_state_from_payload(body, default=\"pending\"),",
        "                owner_id=str(access_subject_from_payload(identity_body)[\"subject\"].get(\"user_id\") or \"\"),",
        "                guest_id=str(access_subject_from_payload(identity_body)[\"subject\"].get(\"guest_id\") or \"\"),",
        "                raw_payload=body,",
        "            )",
        "        )",
    ))
    if (
        source.count(import_anchor) != 1
        or source.count(repository_import) != 1
        or source.count(application_call) != 1
    ):
        raise RuntimeError("D4 view mutation anchors were not unique")
    mutated = source.replace(import_anchor, import_anchor + "from types import SimpleNamespace\n", 1)
    mutated = mutated.replace(
        repository_import,
        repository_import + "    mark_conversation_save_state,\n",
        1,
    ).replace(application_call, bypassed_call, 1)
    if mutated == source:
        raise RuntimeError("D4 view mutation did not change source")
    view_path.write_bytes(mutated.encode(encoding))
    try:
        yield
    finally:
        view_path.write_bytes(original_bytes)


application_path = repo_root / "app" / "application" / "chat" / "update_save_state.py"

if mutation_name == "view_application_bypass":
    mutation = temporarily_bypass_application_in_view()
elif mutation_name == "session_authorization_bypass":
    mutation = mutate_once(
        application_path,
        "\n".join((
            "        if not access[\"allowed\"]:",
            "            raise ConversationSaveStateAccessDenied(access)",
        )),
        "\n".join((
            "        if False and not access[\"allowed\"]:",
            "            raise ConversationSaveStateAccessDenied(access)",
        )),
    )
elif mutation_name == "guest_saved_login_bypass":
    mutation = mutate_once(
        application_path,
        "        if save_state == \"saved\" and subject.get(\"subject_type\") != \"user\":",
        "        if False and save_state == \"saved\" and subject.get(\"subject_type\") != \"user\":",
    )
elif mutation_name == "state_propagation_bypass":
    mutation = mutate_once(
        application_path,
        "\n".join((
            "    conversation_save = mark_conversation_save_state(",
            "        session_id=command.session_id,",
            "        save_state=save_state,",
            "        owner_id=str(subject.get(\"user_id\") or \"\"),",
            "        guest_id=str(subject.get(\"guest_id\") or \"\"),",
            "        raw_payload=dict(command.raw_payload),",
            "    )",
        )),
        "    conversation_save = {\"status\": \"updated\", \"conversation_save_state\": save_state}",
    )
elif mutation_name == "history_event_bypass":
    mutation = mutate_once(
        application_path,
        '        conversation_save.get("conversation_save_state") == "saved"',
        "        False",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests([test_id])

raise SystemExit(0 if failures == 0 else 1)
'''


class SensitivityError(RuntimeError):
    """Raised when a negative control does not prove its target contract."""


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
    result = _run(["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *arguments])
    if result.returncode != 0:
        raise SensitivityError(f"git {' '.join(arguments)} failed")
    return result.stdout


def _working_tree_status() -> str:
    return _git_output("status", "--porcelain")


def _evidence_head() -> str:
    configured_head = os.environ.get("PHASE_02_D4_SENSITIVITY_HEAD", "").strip()
    return configured_head or _git_output("rev-parse", "HEAD").strip()


def _evidence_path() -> Path:
    configured_path = os.environ.get("PHASE_02_D4_SENSITIVITY_EVIDENCE_PATH", "")
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
        "contract_version": "phase_02_d4_sensitivity.v1",
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
                f"original D4 characterization suite failed: {original_exit_code}"
            )
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
    _write_evidence(_evidence_path(), evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
