#!/usr/bin/env python3
"""Verify that Phase 0 C/G characterization assertions are sensitive.

The runner copies only the selected test modules into a temporary importable
package. It never mutates tracked source files. Each original test must pass,
and its temporary assertion mutation must fail with an AssertionError.
"""

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
DEFAULT_EVIDENCE_PATH: Final = REPO_ROOT / "tmp" / "phase-00-sensitivity-evidence.json"


class SensitivityError(RuntimeError):
    """Raised when a selected negative control is not deterministic."""


@dataclass(frozen=True)
class SensitivityTarget:
    key: str
    source_relative: Path
    module_name: str
    class_name: str
    method_name: str
    expected: str
    replacement: str

    @property
    def original_test_id(self) -> str:
        return f"chatbot.{self.module_name}.{self.class_name}.{self.method_name}"

    @property
    def mutant_test_id(self) -> str:
        return f"phase00_mutants.{self.module_name}.{self.class_name}.{self.method_name}"


TARGETS: Final = (
    SensitivityTarget(
        key="ocr_law",
        source_relative=Path("backend/chatbot/test_phase_00_ocr_law_flow.py"),
        module_name="test_phase_00_ocr_law_flow",
        class_name="Phase00OcrLawFlowTests",
        method_name="test_phase_00_short_answer_routes_real_law_worker_and_persists_retrieval",
        expected='self.assertEqual(law_result.node_code, "law_ground_search")',
        replacement='self.assertEqual(law_result.node_code, "law_ground_search_mutant")',
    ),
    SensitivityTarget(
        key="report",
        source_relative=Path("backend/chatbot/test_phase_00_report_lifecycle.py"),
        module_name="test_phase_00_report_lifecycle",
        class_name="Phase00ReportLifecycleTests",
        method_name="test_phase_00_worker_result_creates_versioned_report",
        expected="self.assertEqual(report.owner_id, self.owner_id)",
        replacement='self.assertEqual(report.owner_id, "usr_phase_00_sensitivity_impossible_owner")',
    ),
)


def _method_bounds(source: str, method_name: str) -> tuple[int, int]:
    marker = f"    def {method_name}("
    start = source.find(marker)
    if start < 0:
        raise SensitivityError(f"target method is missing: {method_name}")
    next_method = source.find("\n    def ", start + len(marker))
    return start, len(source) if next_method < 0 else next_method


def mutate_target_source(source: str, target: SensitivityTarget) -> str:
    """Change exactly one expected assertion in the selected test method."""

    start, end = _method_bounds(source, target.method_name)
    method_source = source[start:end]
    occurrences = method_source.count(target.expected)
    if occurrences != 1:
        raise SensitivityError(
            f"{target.key} mutation expected exactly one assertion occurrence, found {occurrences}"
        )
    return "".join(
        (
            source[:start],
            method_source.replace(target.expected, target.replacement, 1),
            source[end:],
        )
    )


def _run_django_test(
    test_id: str,
    *,
    pythonpath_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if pythonpath_root is not None:
        inherited = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (str(pythonpath_root), inherited) if value
        )
    return subprocess.run(
        [
            sys.executable,
            "backend/manage.py",
            "test",
            test_id,
            "--verbosity",
            "1",
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _require_original_pass(target: SensitivityTarget) -> int:
    completed = _run_django_test(target.original_test_id)
    if completed.returncode != 0:
        raise SensitivityError(
            f"{target.key} original test failed with exit code {completed.returncode}"
        )
    return completed.returncode


def _require_mutant_assertion_failure(
    target: SensitivityTarget,
    *,
    pythonpath_root: Path,
) -> tuple[int, str]:
    completed = _run_django_test(
        target.mutant_test_id,
        pythonpath_root=pythonpath_root,
    )
    if completed.returncode == 0:
        raise SensitivityError(f"{target.key} mutant unexpectedly passed")
    if "AssertionError" not in completed.stdout:
        raise SensitivityError(
            f"{target.key} mutant did not fail with an assertion mismatch"
        )
    return completed.returncode, "assertion"


def _working_tree_status() -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise SensitivityError("could not read git working-tree status")
    return completed.stdout


def _evidence_path() -> Path:
    configured = os.environ.get("PHASE_00_SENSITIVITY_EVIDENCE_PATH", "")
    return Path(configured).resolve() if configured else DEFAULT_EVIDENCE_PATH


def _write_evidence(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    before_status = _working_tree_status()
    evidence_path = _evidence_path()
    result: dict[str, object] = {
        "contract_version": "phase_00_sensitivity.v1",
        "status": "fail",
        "working_tree_unchanged": False,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="phase-00-sensitivity-") as temporary_directory:
            temporary_root = Path(temporary_directory)
            package_root = temporary_root / "phase00_mutants"
            package_root.mkdir()
            (package_root / "__init__.py").write_text("", encoding="utf-8")

            for target in TARGETS:
                original_source = (REPO_ROOT / target.source_relative).read_text(
                    encoding="utf-8"
                )
                (package_root / f"{target.module_name}.py").write_text(
                    mutate_target_source(original_source, target),
                    encoding="utf-8",
                )

            for target in TARGETS:
                original_exit_code = _require_original_pass(target)
                mutant_exit_code, failure_kind = _require_mutant_assertion_failure(
                    target,
                    pythonpath_root=temporary_root,
                )
                result[target.key] = {
                    "original_exit_code": original_exit_code,
                    "mutant_exit_code": mutant_exit_code,
                    "failure_kind": failure_kind,
                }
        result["working_tree_unchanged"] = before_status == _working_tree_status()
        if result["working_tree_unchanged"] is not True:
            raise SensitivityError("sensitivity runner changed the working tree")
        result["status"] = "pass"
    except (OSError, SensitivityError) as exc:
        result["error"] = str(exc)
        result["working_tree_unchanged"] = before_status == _working_tree_status()

    _write_evidence(evidence_path, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
