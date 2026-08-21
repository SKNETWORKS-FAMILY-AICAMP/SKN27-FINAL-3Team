#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D9 CreateChatSession boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-d9-sensitivity-evidence.json"
TEST_MODULE: Final = "chatbot.test_phase_02_create_chat_session_use_case"
TARGETS: Final = {
    "view_application_bypass": TEST_MODULE
    + ".CreateChatSessionUseCaseCharacterizationTests."
    + "test_http_post_delegates_to_create_chat_session_application_with_trusted_identity_and_preserves_draft_response",
    "trusted_identity_bypass": TEST_MODULE
    + ".CreateChatSessionUseCaseCharacterizationTests."
    + "test_authenticated_identity_neutralizes_all_client_owned_identity_fields",
    "draft_initialization_bypass": TEST_MODULE
    + ".CreateChatSessionUseCaseCharacterizationTests."
    + "test_http_post_delegates_to_create_chat_session_application_with_trusted_identity_and_preserves_draft_response",
    "history_event_bypass": TEST_MODULE
    + ".CreateChatSessionUseCaseCharacterizationTests."
    + "test_history_event_uses_trusted_actor_subject_and_draft_metadata",
    "history_failure_semantics_bypass": TEST_MODULE
    + ".CreateChatSessionUseCaseCharacterizationTests."
    + "test_history_database_and_os_failures_keep_the_draft_response_successful",
}


MUTATION_CHILD_SCRIPT: Final = r'''
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import importlib
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
from django.urls import clear_url_caches


def read_source(path):
    original = path.read_bytes()
    encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
    return original, encoding, original.decode(encoding).replace("\r\n", "\n")


@contextmanager
def mutate_once(path, old, new):
    original, encoding, source = read_source(path)
    if source.count(old) != 1:
        raise RuntimeError(f"mutation anchor was not unique: {path.name}")
    path.write_bytes(source.replace(old, new).encode(encoding))
    try:
        yield
    finally:
        path.write_bytes(original)


views = repo_root / "backend" / "chatbot" / "views.py"
application = repo_root / "app" / "application" / "chat" / "create_session.py"
if mutation_name == "view_application_bypass":
    mutation = mutate_once(
        views,
        """    result = execute_create_chat_session(
        CreateChatSessionCommand(
            identity_payload=identity_body,
            history_actor=_history_actor(request, identity_body),
            history_source=_history_source(request),
            history_recorder=partial(_record_history_safely, request),
        )
    )
    return _json_response(request, result.payload)
""",
        """    from app.services.chat_orchestration_service import create_session as _direct_create_session
    payload = _direct_create_session(
        user_id=access_subject_from_payload(identity_body)["subject"].get("user_id")
    )
    return _json_response(request, payload)
""",
    )
elif mutation_name == "trusted_identity_bypass":
    mutation = mutate_once(
        views,
        """        CreateChatSessionCommand(
            identity_payload=identity_body,
""",
        """        CreateChatSessionCommand(
            identity_payload=body,
""",
    )
elif mutation_name == "draft_initialization_bypass":
    mutation = mutate_once(
        application,
        "    payload = create_session(user_id=subject.get(\"user_id\"))\n",
        "    payload = {**create_session(user_id=subject.get(\"user_id\")), \"status\": \"issued\"}\n",
    )
elif mutation_name == "history_event_bypass":
    mutation = mutate_once(
        application,
        '        event_type="chat_session_created",\n',
        '        event_type="chat_session_opened",\n',
    )
elif mutation_name == "history_failure_semantics_bypass":
    mutation = mutate_once(
        views,
        """            history_actor=_history_actor(request, identity_body),
            history_source=_history_source(request),
            history_recorder=partial(_record_history_safely, request),
""",
        """            history_actor=_history_actor(request, identity_body),
            history_source=_history_source(request),
            history_recorder=record_history_event_record,
""",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
    import app.application.chat.create_session as create_session_application
    import chatbot.urls as chatbot_urls
    import chatbot.views as chat_views
    import config.urls as config_urls

    importlib.reload(create_session_application)
    importlib.reload(chat_views)
    importlib.reload(chatbot_urls)
    importlib.reload(config_urls)
    clear_url_caches()
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests([test_id])
raise SystemExit(0 if failures == 0 else 1)
'''


class SensitivityError(RuntimeError):
    pass


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


def _git(*args: str) -> str:
    result = _run(["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *args])
    if result.returncode:
        raise SensitivityError(f"git {' '.join(args)} failed")
    return result.stdout


def failure_kind(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 0:
        raise SensitivityError("mutation unexpectedly passed")
    if "AssertionError" not in result.stdout:
        raise SensitivityError("assertion mismatch: mutation did not fail by assertion")
    return "assertion"


def _run_mutation(name: str, target: str) -> MutationOutcome:
    result = _run(
        [sys.executable, "-c", MUTATION_CHILD_SCRIPT, str(REPO_ROOT), target, name]
    )
    return MutationOutcome(name, result.returncode, failure_kind(result))


def build_evidence(
    *,
    head: str,
    actual_head: str,
    original_exit_code: int,
    mutations: tuple[MutationOutcome, ...],
    working_tree_unchanged: bool,
) -> dict[str, Any]:
    source_restored = working_tree_unchanged
    passed = (
        bool(head)
        and head == actual_head
        and original_exit_code == 0
        and tuple(item.name for item in mutations) == tuple(TARGETS)
        and all(
            item.exit_code != 0 and item.failure_kind == "assertion"
            for item in mutations
        )
        and source_restored
        and working_tree_unchanged
    )
    return {
        "contract_version": "phase_02_d9_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "actual_head": actual_head,
        "original": {"exit_code": original_exit_code},
        "mutations": [item.__dict__ for item in mutations],
        "source_restored": source_restored,
        "working_tree_unchanged": working_tree_unchanged,
    }


def main() -> int:
    before = _git("status", "--porcelain")
    original_exit_code, outcomes, error = 1, (), None
    actual_head = _git("rev-parse", "HEAD").strip()
    requested_head = os.environ.get("PHASE_02_D9_SENSITIVITY_HEAD", "").strip()
    head = requested_head or actual_head
    try:
        if requested_head and requested_head != actual_head:
            raise SensitivityError(
                "stale D9 sensitivity head: requested evidence head does not match checkout"
            )
        original_exit_code = _run(
            [sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]
        ).returncode
        if original_exit_code:
            raise SensitivityError(
                f"original D9 characterization suite failed: {original_exit_code}"
            )
        outcomes = tuple(
            _run_mutation(name, target) for name, target in TARGETS.items()
        )
    except (OSError, SensitivityError) as exc:
        error = str(exc)
    evidence = build_evidence(
        head=head,
        actual_head=actual_head,
        original_exit_code=original_exit_code,
        mutations=outcomes,
        working_tree_unchanged=before == _git("status", "--porcelain"),
    )
    if error:
        evidence["error"] = error
    path = Path(
        os.environ.get("PHASE_02_D9_SENSITIVITY_EVIDENCE_PATH", DEFAULT_EVIDENCE_PATH)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
