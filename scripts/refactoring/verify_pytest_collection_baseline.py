"""Fail closed unless pytest collection matches the approved typed dependency debt."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "tmp" / "phase-01-pytest-collection-baseline.json"
CONTRACT_PATH = ROOT / "test" / "contracts" / "phase_01_pytest_collection_baseline.json"
CONTRACT_VERSION = "phase_01_pytest_collection_baseline.v2"
REQUIRED_ERROR_FIELDS = frozenset({"path", "exception_type", "missing_module"})
COLLECTION_ERROR_BLOCK_PATTERN = re.compile(
    r"^_+ ERROR collecting (?P<path>.+?\.py) _+\r?\n(?P<body>.*?)(?=^_+ ERROR collecting |\Z)",
    re.MULTILINE | re.DOTALL,
)
EXCEPTION_PATTERN = re.compile(r"^E\s+(?P<exception_type>[A-Za-z_][A-Za-z0-9_.]*Error): (?P<message>.+)$", re.MULTILINE)
MISSING_MODULE_PATTERN = re.compile(r"No module named ['\"](?P<missing_module>[^'\"]+)['\"]")
COLLECTED_COUNT_PATTERN = re.compile(r"(?P<count>\d+) tests collected")


def main() -> int:
    expected_errors = load_expected_errors(CONTRACT_PATH)
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    result = evaluate_collection_output(
        completed.stdout,
        pytest_exit_code=completed.returncode,
        expected_errors=expected_errors,
    )
    evidence = {
        "contract_version": CONTRACT_VERSION,
        "command": command,
        "pytest_exit_code": completed.returncode,
        "gate_exit_code": result["gate_exit_code"],
        "status": result["status"],
        "collected_tests": _collected_count(completed.stdout),
        "expected_collection_errors": expected_errors,
        "observed_collection_errors": result["observed_collection_errors"],
        "unexpected_collection_errors": result["unexpected_collection_errors"],
        "missing_expected_collection_errors": result["missing_expected_collection_errors"],
        "duplicate_collection_errors": result["duplicate_collection_errors"],
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))
    if result["gate_exit_code"]:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    return int(result["gate_exit_code"])


def load_expected_errors(contract_path: Path) -> list[dict[str, str]]:
    try:
        document = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid collection baseline contract: {contract_path}") from exc
    if not isinstance(document, dict) or document.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("invalid collection baseline contract version")
    raw_errors = document.get("expected_collection_errors")
    if not isinstance(raw_errors, list):
        raise ValueError("expected_collection_errors must be a list")
    expected_errors = [_normalize_error(item, source="contract") for item in raw_errors]
    if len({_error_key(item) for item in expected_errors}) != len(expected_errors):
        raise ValueError("duplicate expected collection error")
    return _sorted_errors(expected_errors)


def evaluate_collection_output(
    output: str,
    *,
    pytest_exit_code: int,
    expected_errors: list[dict[str, str]],
) -> dict[str, Any]:
    expected = [_normalize_error(item, source="expected_errors") for item in expected_errors]
    if len({_error_key(item) for item in expected}) != len(expected):
        raise ValueError("duplicate expected collection error")
    observed = parse_collection_errors(output)
    observed_counts = Counter(_error_key(item) for item in observed)
    observed_unique = _sorted_errors(_error_from_key(key) for key in observed_counts)
    expected_keys = {_error_key(item) for item in expected}
    observed_keys = set(observed_counts)
    unexpected = _sorted_errors(_error_from_key(key) for key in observed_keys - expected_keys)
    missing = _sorted_errors(_error_from_key(key) for key in expected_keys - observed_keys)
    duplicates = _sorted_errors(_error_from_key(key) for key, count in observed_counts.items() if count > 1)
    baseline_matches = not unexpected and not missing and not duplicates
    status = "known_baseline_only" if pytest_exit_code != 0 and baseline_matches else "new_collection_regression"
    return {
        "gate_exit_code": 0 if status == "known_baseline_only" else 1,
        "status": status,
        "observed_collection_errors": _sorted_errors(observed),
        "unexpected_collection_errors": unexpected,
        "missing_expected_collection_errors": missing,
        "duplicate_collection_errors": duplicates,
    }


def parse_collection_errors(output: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for match in COLLECTION_ERROR_BLOCK_PATTERN.finditer(output):
        body = match.group("body")
        exception = EXCEPTION_PATTERN.search(body)
        if exception is None:
            errors.append(
                {
                    "path": _normalize_path(match.group("path")),
                    "exception_type": "UnknownCollectionError",
                    "missing_module": "",
                }
            )
            continue
        message = exception.group("message")
        missing_module = MISSING_MODULE_PATTERN.search(message)
        errors.append(
            {
                "path": _normalize_path(match.group("path")),
                "exception_type": exception.group("exception_type"),
                "missing_module": missing_module.group("missing_module") if missing_module else "",
            }
        )
    return errors


def _normalize_error(value: object, *, source: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != REQUIRED_ERROR_FIELDS:
        raise ValueError(f"{source} error must contain exactly path, exception_type, missing_module")
    error = {field: str(value[field]).strip() for field in REQUIRED_ERROR_FIELDS}
    if not all(error.values()):
        raise ValueError(f"{source} error fields must be non-empty")
    return error


def _normalize_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    marker = "/test/"
    if marker in normalized:
        normalized = "test/" + normalized.split(marker, 1)[1]
    return normalized


def _error_key(error: dict[str, str]) -> tuple[str, str, str]:
    return error["path"], error["exception_type"], error["missing_module"]


def _error_from_key(key: tuple[str, str, str]) -> dict[str, str]:
    return {"path": key[0], "exception_type": key[1], "missing_module": key[2]}


def _sorted_errors(errors: object) -> list[dict[str, str]]:
    return sorted(list(errors), key=_error_key)


def _collected_count(output: str) -> int | None:
    match = COLLECTED_COUNT_PATTERN.search(output)
    return int(match.group("count")) if match else None


if __name__ == "__main__":
    raise SystemExit(main())
