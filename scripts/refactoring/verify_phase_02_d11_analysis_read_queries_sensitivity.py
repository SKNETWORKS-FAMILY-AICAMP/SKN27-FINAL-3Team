#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D11 AnalysisReadQueries boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-d11-sensitivity-evidence.json"
TEST_MODULE: Final = "chatbot.test_phase_02_analysis_read_queries_use_case"
TARGETS: Final = {
    "list_view_application_bypass": TEST_MODULE
    + ".AnalysisReadQueriesApplicationSeamTests."
    + "test_analysis_job_list_delegates_to_execute_list_analysis_jobs",
    "detail_view_application_bypass": TEST_MODULE
    + ".AnalysisReadQueriesApplicationSeamTests."
    + "test_analysis_job_detail_delegates_to_execute_get_analysis_job_detail",
    "result_view_application_bypass": TEST_MODULE
    + ".AnalysisReadQueriesApplicationSeamTests."
    + "test_analysis_result_delegates_to_execute_get_analysis_result",
    "list_scope_authorization_bypass": TEST_MODULE
    + ".AnalysisReadQueriesContractTests."
    + "test_authenticated_owner_list_is_scoped_to_owner",
    "job_owner_precedence_bypass": TEST_MODULE
    + ".AnalysisReadQueriesSecurityTests."
    + "test_guest_session_cannot_read_foreign_owner_analysis_job_detail_even_when_session_matches",
    "canonical_guest_policy_bypass": TEST_MODULE
    + ".AnalysisReadQueriesGuestPolicyTests."
    + "test_expired_guest_cannot_list_analysis_jobs",
    "progress_cache_identity_validation_bypass": TEST_MODULE
    + ".AnalysisReadQueriesSecurityTests."
    + "test_analysis_job_detail_discards_cache_snapshot_with_mismatched_identity",
    "public_projection_bypass": TEST_MODULE
    + ".AnalysisReadQueriesContractTests."
    + "test_analysis_job_detail_excludes_private_metadata",
    "pending_terminal_status_bypass": TEST_MODULE
    + ".AnalysisReadQueriesContractTests."
    + "test_analysis_result_preserves_pending_and_terminal_http_status",
}


MUTATION_CHILD_SCRIPT: Final = r'''
from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path

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
application = repo_root / "app" / "application" / "analysis" / "read_queries.py"
query_service = repo_root / "app" / "services" / "analysis_job_query_service.py"
if mutation_name == "list_view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_list_analysis_jobs(\n",
        "        from app.application.analysis.read_queries import execute_list_analysis_jobs as _direct_list\n            result = _direct_list(\n",
    )
elif mutation_name == "detail_view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_get_analysis_job_detail(\n",
        "        from app.application.analysis.read_queries import execute_get_analysis_job_detail as _direct_detail\n            result = _direct_detail(\n",
    )
elif mutation_name == "result_view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_get_analysis_result(\n",
        "        from app.application.analysis.read_queries import execute_get_analysis_result as _direct_result\n            result = _direct_result(\n",
    )
elif mutation_name == "list_scope_authorization_bypass":
    mutation = mutate_once(
        application,
        '                owner_id=str(subject.get("user_id") or ""),\n',
        '                owner_id="usr_d11_other_owner",\n',
    )
elif mutation_name == "job_owner_precedence_bypass":
    mutation = mutate_once(
        application,
        "    if owner_id:\n        return authorize_resource_access(dict(metadata), identity_payload)\n",
        "    if False:\n        return authorize_resource_access(dict(metadata), identity_payload)\n",
    )
elif mutation_name == "canonical_guest_policy_bypass":
    mutation = mutate_once(
        application,
        "    if canonical_request:\n        violation = guest_violation_resolver(subject)\n",
        "    if False:\n        violation = guest_violation_resolver(subject)\n",
    )
elif mutation_name == "progress_cache_identity_validation_bypass":
    mutation = mutate_once(
        query_service,
        "    if not identity_mismatch:\n        return _project_public_progress_cache(progress_cache)\n",
        "    if True:\n        return _project_public_progress_cache(progress_cache)\n",
    )
elif mutation_name == "public_projection_bypass":
    mutation = mutate_once(
        query_service,
        '_DETAIL_SCALAR_FIELDS = (\n    "contract_version",\n',
        '_DETAIL_SCALAR_FIELDS = (\n    "contract_version",\n    "metadata",\n',
    )
elif mutation_name == "pending_terminal_status_bypass":
    mutation = mutate_once(
        application,
        '        pending=outcome.kind == "pending",\n',
        "        pending=True,\n",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")

with mutation:
    import app.services.analysis_job_query_service as analysis_job_query_service
    import app.application.analysis.read_queries as analysis_read_queries
    import chatbot.urls as chatbot_urls
    import chatbot.views as chat_views
    import config.urls as config_urls

    importlib.reload(analysis_job_query_service)
    importlib.reload(analysis_read_queries)
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
    result = _run([sys.executable, "-c", MUTATION_CHILD_SCRIPT, str(REPO_ROOT), target, name])
    return MutationOutcome(name, result.returncode, failure_kind(result))


def build_evidence(
    *,
    head: str,
    actual_head: str,
    original_exit_code: int,
    mutations: tuple[MutationOutcome, ...],
    source_restored: bool,
    working_tree_unchanged: bool,
    residual_diff_zero: bool,
) -> dict[str, Any]:
    passed = (
        bool(head)
        and head == actual_head
        and original_exit_code == 0
        and tuple(item.name for item in mutations) == tuple(TARGETS)
        and all(item.exit_code != 0 and item.failure_kind == "assertion" for item in mutations)
        and source_restored
        and working_tree_unchanged
        and residual_diff_zero
    )
    return {
        "contract_version": "phase_02_d11_sensitivity.v1",
        "status": "pass" if passed else "fail",
        "head": head,
        "actual_head": actual_head,
        "original": {"exit_code": original_exit_code},
        "mutations": [item.__dict__ for item in mutations],
        "source_restored": source_restored,
        "working_tree_unchanged": working_tree_unchanged,
        "residual_diff_zero": residual_diff_zero,
    }


def main() -> int:
    before = _git("status", "--porcelain")
    original_exit_code, outcomes, error = 1, (), None
    actual_head = _git("rev-parse", "HEAD").strip()
    requested_head = os.environ.get("PHASE_02_D11_SENSITIVITY_HEAD", "").strip()
    head = requested_head or actual_head
    try:
        if requested_head and requested_head != actual_head:
            raise SensitivityError("stale D11 sensitivity head: requested evidence head does not match checkout")
        original_exit_code = _run([sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]).returncode
        if original_exit_code:
            raise SensitivityError(f"original D11 characterization suite failed: {original_exit_code}")
        outcomes = tuple(_run_mutation(name, target) for name, target in TARGETS.items())
    except (OSError, SensitivityError) as exc:
        error = str(exc)
    after = _git("status", "--porcelain")
    residual_diff_zero = _run(["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", "diff", "--no-ext-diff", "--exit-code"]).returncode == 0
    evidence = build_evidence(
        head=head,
        actual_head=actual_head,
        original_exit_code=original_exit_code,
        mutations=outcomes,
        source_restored=before == after,
        working_tree_unchanged=before == after,
        residual_diff_zero=residual_diff_zero,
    )
    if error:
        evidence["error"] = error
    path = Path(os.environ.get("PHASE_02_D11_SENSITIVITY_EVIDENCE_PATH", DEFAULT_EVIDENCE_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
