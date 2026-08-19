#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D6 History read boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-d6-sensitivity-evidence.json"
TEST_MODULE: Final = "chatbot.test_phase_02_history_list_events_use_case"
TARGETS: Final = {
    "view_application_bypass": TEST_MODULE
    + ".HistoryListEventsUseCaseTests.test_http_get_delegates_to_application_with_trusted_identity_and_preserves_history_response",
    "job_authorization_bypass": "chatbot.test_history_api_contract.HistoryApiContractTests.test_other_users_job_history_is_denied",
    "session_authorization_bypass": "chatbot.test_history_api_contract.HistoryApiContractTests.test_other_session_is_denied",
    "default_limit_bypass": "chatbot.test_history_api_contract.HistoryApiContractTests.test_invalid_limit_keeps_the_existing_default_of_100",
    "public_marker_projection_bypass": "chatbot.test_phase_01_legacy_marker_projection.LegacyHistoryMarkerProjectionTests.test_legacy_source_marker_is_normalized_in_the_public_dto_only",
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
application = repo_root / "app" / "application" / "history" / "list_events.py"
repository = repo_root / "backend" / "chatbot" / "repositories.py"
if mutation_name == "view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_list_history_events(\n",
        "        from app.application.history.list_events import execute_list_history_events as _direct_list_history\n        result = _direct_list_history(\n",
    )
elif mutation_name == "job_authorization_bypass":
    mutation = mutate_once(
        application,
        "    if not access[\"allowed\"]:\n        raise HistoryListAccessDenied(access)\n\n\ndef _authorize_history_query",
        "    if False and not access[\"allowed\"]:\n        raise HistoryListAccessDenied(access)\n\n\ndef _authorize_history_query",
    )
elif mutation_name == "session_authorization_bypass":
    mutation = mutate_once(
        application,
        "    if not access[\"allowed\"]:\n        raise HistoryListAccessDenied(access)\n\n\ndef _session_access(",
        "    if False and not access[\"allowed\"]:\n        raise HistoryListAccessDenied(access)\n\n\ndef _session_access(",
    )
elif mutation_name == "default_limit_bypass":
    mutation = mutate_once(
        application,
        '        "limit": _positive_int(query.limit, default=100),',
        '        "limit": _positive_int(query.limit, default=1),',
    )
elif mutation_name == "public_marker_projection_bypass":
    mutation = mutate_once(
        repository,
        "        \"source\": sanitize_history_source(event.source),",
        "        \"source\": event.source,",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")
with mutation:
    import importlib
    from django.urls import clear_url_caches
    import app.application.history.list_events as history_application
    import chatbot.repositories as history_repository
    import chatbot.urls as chatbot_urls
    import chatbot.views as history_views
    import config.urls as config_urls

    importlib.reload(history_repository)
    importlib.reload(history_application)
    importlib.reload(history_views)
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
    result = _run([sys.executable, "-c", MUTATION_CHILD_SCRIPT, str(REPO_ROOT), target, name])
    return MutationOutcome(name, result.returncode, failure_kind(result))


def build_evidence(
    *,
    head: str,
    original_exit_code: int,
    mutations: tuple[MutationOutcome, ...],
    working_tree_unchanged: bool,
) -> dict[str, Any]:
    passed = (
        bool(head)
        and original_exit_code == 0
        and tuple(item.name for item in mutations) == tuple(TARGETS)
        and all(item.exit_code != 0 and item.failure_kind == "assertion" for item in mutations)
        and working_tree_unchanged
    )
    return {
        "contract_version": "phase_02_d6_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "original": {"exit_code": original_exit_code},
        "mutations": [item.__dict__ for item in mutations],
        "working_tree_unchanged": working_tree_unchanged,
    }


def main() -> int:
    before = _git("status", "--porcelain")
    original_exit_code, outcomes, error = 1, (), None
    try:
        original_exit_code = _run(
            [sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]
        ).returncode
        if original_exit_code:
            raise SensitivityError(
                f"original D6 characterization suite failed: {original_exit_code}"
            )
        outcomes = tuple(
            _run_mutation(name, target) for name, target in TARGETS.items()
        )
    except (OSError, SensitivityError) as exc:
        error = str(exc)
    head = os.environ.get("PHASE_02_D6_SENSITIVITY_HEAD", "").strip() or _git(
        "rev-parse", "HEAD"
    ).strip()
    evidence = build_evidence(
        head=head,
        original_exit_code=original_exit_code,
        mutations=outcomes,
        working_tree_unchanged=before == _git("status", "--porcelain"),
    )
    if error:
        evidence["error"] = error
    path = Path(
        os.environ.get("PHASE_02_D6_SENSITIVITY_EVIDENCE_PATH", DEFAULT_EVIDENCE_PATH)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
