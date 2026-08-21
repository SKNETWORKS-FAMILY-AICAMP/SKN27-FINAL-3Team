#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D8 resume application boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-d8-sensitivity-evidence.json"
TEST_MODULE: Final = "chatbot.test_phase_02_resume_latest_consultation_use_case"
TARGETS: Final = {
    "view_application_bypass": TEST_MODULE
    + ".ResumeLatestConsultationUseCaseTests."
    + "test_http_get_requires_the_new_application_seam",
    "latest_owned_session_bypass": TEST_MODULE
    + ".ResumeLatestConsultationUseCaseTests."
    + "test_selects_latest_owned_session_not_newer_foreign_session",
    "latest_job_selection_bypass": TEST_MODULE
    + ".ResumeLatestConsultationUseCaseTests."
    + "test_selects_latest_job_for_the_selected_owned_session",
    "derived_resource_owner_bypass": TEST_MODULE
    + ".ResumeLatestConsultationUseCaseTests."
    + "test_excludes_foreign_derived_resources_from_the_owned_session",
    "privacy_manifest_bypass": TEST_MODULE
    + ".ResumeLatestConsultationUseCaseTests.test_projects_only_safe_resume_fields",
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
application = repo_root / "app" / "application" / "auth" / "resume_latest_consultation.py"
repository = repo_root / "backend" / "chatbot" / "repositories.py"
manifest = repo_root / "app" / "services" / "resume_manifest_service.py"
if mutation_name == "view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_resume_latest_consultation(\n",
        "        from app.application.auth.resume_latest_consultation import execute_resume_latest_consultation as _direct_resume_latest_consultation\n        result = _direct_resume_latest_consultation(\n",
    )
elif mutation_name == "latest_owned_session_bypass":
    mutation = mutate_once(
        repository,
        "        ChatSession.objects.filter(owner_id=normalized_owner_id)\n",
        "        ChatSession.objects.all()\n",
    )
elif mutation_name == "latest_job_selection_bypass":
    mutation = mutate_once(
        repository,
        "    latest_job = session.analysis_jobs.order_by(\"-updated_at\").first()",
        "    latest_job = session.analysis_jobs.order_by(\"updated_at\").first()",
    )
elif mutation_name == "derived_resource_owner_bypass":
    mutation = mutate_once(
        repository,
        "        \"attachments\": list_uploaded_files(\n            session_id=session.session_id,\n            owner_id=normalized_owner_id,\n        ),",
        "        \"attachments\": list_uploaded_files(\n            session_id=session.session_id,\n        ),",
    )
elif mutation_name == "privacy_manifest_bypass":
    mutation = mutate_once(
        manifest,
        "_ATTACHMENT_FIELDS = (\n    \"attachment_id\",\n    \"purpose\",\n    \"filename\",\n    \"status\",\n    \"scan_status\",\n)",
        "_ATTACHMENT_FIELDS = (\n    \"attachment_id\",\n    \"purpose\",\n    \"filename\",\n    \"status\",\n    \"scan_status\",\n    \"storage_uri\",\n)",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
    import app.application.auth.resume_latest_consultation as resume_application
    import app.services.resume_manifest_service as resume_manifest
    import chatbot.repositories as resume_repository
    import chatbot.urls as chatbot_urls
    import chatbot.views as resume_views
    import config.urls as config_urls

    importlib.reload(resume_manifest)
    importlib.reload(resume_repository)
    importlib.reload(resume_application)
    importlib.reload(resume_views)
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
    passed = (
        bool(head)
        and head == actual_head
        and original_exit_code == 0
        and tuple(item.name for item in mutations) == tuple(TARGETS)
        and all(
            item.exit_code != 0 and item.failure_kind == "assertion"
            for item in mutations
        )
        and working_tree_unchanged
    )
    return {
        "contract_version": "phase_02_d8_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "actual_head": actual_head,
        "original": {"exit_code": original_exit_code},
        "mutations": [item.__dict__ for item in mutations],
        "working_tree_unchanged": working_tree_unchanged,
    }


def main() -> int:
    before = _git("status", "--porcelain")
    original_exit_code, outcomes, error = 1, (), None
    actual_head = _git("rev-parse", "HEAD").strip()
    requested_head = os.environ.get("PHASE_02_D8_SENSITIVITY_HEAD", "").strip()
    head = requested_head or actual_head
    try:
        if requested_head and requested_head != actual_head:
            raise SensitivityError(
                "stale D8 sensitivity head: requested evidence head does not match checkout"
            )
        original_exit_code = _run(
            [sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]
        ).returncode
        if original_exit_code:
            raise SensitivityError(
                f"original D8 characterization suite failed: {original_exit_code}"
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
        os.environ.get("PHASE_02_D8_SENSITIVITY_EVIDENCE_PATH", DEFAULT_EVIDENCE_PATH)
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
