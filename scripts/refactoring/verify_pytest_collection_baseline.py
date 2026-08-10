"""Verify that pytest collection adds no errors beyond the approved dependency debt."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "tmp" / "phase-01-pytest-collection-baseline.json"
KNOWN_BASELINE_ERROR_MODULES = frozenset(
    {
        "test/test_evaluate_videomae_classifier.py",
        "test/test_prepare_benchmark_manifest.py",
        "test/test_supervisor_acceptance_fixture_pdf.py",
        "test/test_videomae_frame_directory.py",
    }
)
COLLECTION_ERROR_PATTERN = re.compile(r"ERROR collecting (?P<path>[^\s]+\.py)")
COLLECTED_COUNT_PATTERN = re.compile(r"(?P<count>\d+) tests collected")


def main() -> int:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = completed.stdout
    observed = _collection_error_modules(output)
    unexpected = sorted(observed - KNOWN_BASELINE_ERROR_MODULES)
    missing_baseline = sorted(KNOWN_BASELINE_ERROR_MODULES - observed)
    collected = _collected_count(output)

    if completed.returncode == 0 and not observed:
        status = "clean_collection"
        exit_code = 0
    elif observed == KNOWN_BASELINE_ERROR_MODULES and completed.returncode != 0:
        status = "known_baseline_only"
        exit_code = 0
    else:
        status = "new_collection_regression"
        exit_code = 1

    evidence = {
        "contract_version": "phase_01_pytest_collection_baseline.v1",
        "command": command,
        "pytest_exit_code": completed.returncode,
        "gate_exit_code": exit_code,
        "status": status,
        "collected_tests": collected,
        "known_baseline_error_modules": sorted(KNOWN_BASELINE_ERROR_MODULES),
        "observed_error_modules": sorted(observed),
        "unexpected_error_modules": unexpected,
        "missing_baseline_error_modules": missing_baseline,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    if exit_code:
        print(output, end="" if output.endswith("\n") else "\n")
    return exit_code


def _collection_error_modules(output: str) -> set[str]:
    return {
        match.group("path").replace("\\", "/")
        for match in COLLECTION_ERROR_PATTERN.finditer(output)
    }


def _collected_count(output: str) -> int | None:
    match = COLLECTED_COUNT_PATTERN.search(output)
    return int(match.group("count")) if match else None


if __name__ == "__main__":
    raise SystemExit(main())
