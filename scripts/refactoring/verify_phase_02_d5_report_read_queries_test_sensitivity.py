#!/usr/bin/env python
"""Negative-control evidence for the Phase 2-D5 Report read-query boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-02-d5-sensitivity-evidence.json"
TEST_MODULE: Final = "chatbot.test_phase_02_report_read_queries_use_case"
TARGETS: Final = {
    "list_view_application_bypass": TEST_MODULE + ".ReportReadQueriesUseCaseCharacterizationTests.test_list_http_get_delegates_to_application_with_trusted_owner_identity",
    "detail_view_application_bypass": TEST_MODULE + ".ReportReadQueriesUseCaseCharacterizationTests.test_detail_http_get_delegates_to_application_with_trusted_owner_identity",
    "list_owner_filter_bypass": TEST_MODULE + ".ReportReadQueriesUseCaseCharacterizationTests.test_list_excludes_foreign_reports_and_preserves_session_filter",
    "detail_foreign_authorization_bypass": TEST_MODULE + ".ReportReadQueriesUseCaseCharacterizationTests.test_detail_denies_foreign_owner_without_private_report_projection",
    "detail_privacy_projection_bypass": TEST_MODULE + ".ReportReadQueriesUseCaseCharacterizationTests.test_detail_preserves_public_projection_and_worker_execution_mode",
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
application = repo_root / "app" / "application" / "reports" / "read_queries.py"
projection = repo_root / "app" / "services" / "report_query_service.py"
if mutation_name == "list_view_application_bypass":
    mutation = mutate_once(
        views,
        "            result = execute_list_reports(\n",
        "            from app.application.reports.read_queries import execute_list_reports as _direct_list\n            result = _direct_list(\n",
    )
elif mutation_name == "detail_view_application_bypass":
    mutation = mutate_once(
        views,
        "        result = execute_get_report_detail(\n",
        "        from app.application.reports.read_queries import execute_get_report_detail as _direct_detail\n        result = _direct_detail(\n",
    )
elif mutation_name == "list_owner_filter_bypass":
    mutation = mutate_once(
        application,
        '        owner_id=str(subject.get("user_id") or ""),',
        '        owner_id="",',
    )
elif mutation_name == "detail_foreign_authorization_bypass":
    mutation = mutate_once(
        application,
        '        if not access["allowed"]:',
        '        if False and not access["allowed"]:',
    )
elif mutation_name == "detail_privacy_projection_bypass":
    mutation = mutate_once(
        projection,
        """    response = ReportDetailResponse(
        api_surface=api_surface,
        execution_mode=execution_mode,
        report=report,
    )
    return response.model_dump(mode=\"json\")
""",
        """    response = ReportDetailResponse(
        api_surface=api_surface,
        execution_mode=execution_mode,
        report=report,
    )
    result = response.model_dump(mode=\"json\")
    result[\"report\"][\"metadata\"][\"report_quality\"][\"agent_status_counts\"] = _mapping(metadata.get(\"report_quality\")).get(\"agent_status_counts\")
    return result
""",
    )
else:
    raise SystemExit(f"unsupported mutation: {mutation_name}")
with mutation:
    if mutation_name == "detail_privacy_projection_bypass":
        import importlib
        import app.services.report_query_service as report_query_service
        importlib.reload(report_query_service)
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
    return subprocess.run(command, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)

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

def build_evidence(*, head: str, original_exit_code: int, mutations: tuple[MutationOutcome, ...], working_tree_unchanged: bool) -> dict[str, Any]:
    passed = (original_exit_code == 0 and tuple(item.name for item in mutations) == tuple(TARGETS) and all(item.exit_code != 0 and item.failure_kind == "assertion" for item in mutations) and working_tree_unchanged)
    return {"contract_version": "phase_02_d5_sensitivity.v1", "status": "pass" if passed else "fail", "head": head, "original": {"exit_code": original_exit_code}, "mutations": [item.__dict__ for item in mutations], "working_tree_unchanged": working_tree_unchanged}

def main() -> int:
    before = _git("status", "--porcelain")
    original_exit_code, outcomes, error = 1, (), None
    try:
        original_exit_code = _run([sys.executable, "backend/manage.py", "test", TEST_MODULE, "--verbosity", "1"]).returncode
        if original_exit_code:
            raise SensitivityError(f"original D5 characterization suite failed: {original_exit_code}")
        outcomes = tuple(_run_mutation(name, target) for name, target in TARGETS.items())
    except (OSError, SensitivityError) as exc:
        error = str(exc)
    evidence = build_evidence(head=os.environ.get("PHASE_02_D5_SENSITIVITY_HEAD", "").strip() or _git("rev-parse", "HEAD").strip(), original_exit_code=original_exit_code, mutations=outcomes, working_tree_unchanged=before == _git("status", "--porcelain"))
    if error:
        evidence["error"] = error
    path = Path(os.environ.get("PHASE_02_D5_SENSITIVITY_EVIDENCE_PATH", DEFAULT_EVIDENCE_PATH))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())