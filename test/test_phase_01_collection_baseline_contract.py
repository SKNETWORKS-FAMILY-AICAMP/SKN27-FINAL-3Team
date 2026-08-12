from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "refactoring" / "verify_pytest_collection_baseline.py"
EXPECTED = [
    {"path": "test/test_evaluate_videomae_classifier.py", "exception_type": "ModuleNotFoundError", "missing_module": "cv2"},
    {"path": "test/test_prepare_benchmark_manifest.py", "exception_type": "ModuleNotFoundError", "missing_module": "cv2"},
    {"path": "test/test_supervisor_acceptance_fixture_pdf.py", "exception_type": "ModuleNotFoundError", "missing_module": "pypdf"},
    {"path": "test/test_videomae_frame_directory.py", "exception_type": "ModuleNotFoundError", "missing_module": "cv2"},
]


def _module():
    spec = importlib.util.spec_from_file_location("phase_01_collection_baseline", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collection_error(path: str, exception_type: str, missing_module: str) -> str:
    return (
        f"________ ERROR collecting {path} ________\n"
        "Traceback (most recent call last):\n"
        "  File \"importlib.py\", line 1, in import_module\n"
        f"E   {exception_type}: No module named '{missing_module}'\n"
    )


def test_collection_baseline_accepts_only_the_exact_typed_expected_set() -> None:
    output = "\n".join(
        _collection_error(item["path"], item["exception_type"], item["missing_module"]) for item in EXPECTED
    )

    result = _module().evaluate_collection_output(output, pytest_exit_code=2, expected_errors=EXPECTED)

    assert result["status"] == "known_baseline_only"
    assert result["unexpected_collection_errors"] == []
    assert result["missing_expected_collection_errors"] == []
    assert result["duplicate_collection_errors"] == []


@pytest.mark.parametrize(
    ("exception_type", "missing_module"),
    [("ImportError", "cv2"), ("ModuleNotFoundError", "numpy")],
)
def test_collection_baseline_rejects_wrong_exception_type_or_missing_module(
    exception_type: str, missing_module: str
) -> None:
    output = _collection_error("test/test_evaluate_videomae_classifier.py", exception_type, missing_module)

    result = _module().evaluate_collection_output(output, pytest_exit_code=2, expected_errors=EXPECTED)

    assert result["status"] == "new_collection_regression"
    assert result["unexpected_collection_errors"] == [
        {
            "path": "test/test_evaluate_videomae_classifier.py",
            "exception_type": exception_type,
            "missing_module": missing_module,
        }
    ]
    assert result["missing_expected_collection_errors"][0] == EXPECTED[0]


def test_collection_baseline_rejects_a_missing_expected_error_and_an_unexpected_path() -> None:
    output = _collection_error("test/test_new_dependency.py", "ModuleNotFoundError", "cv2")

    result = _module().evaluate_collection_output(output, pytest_exit_code=2, expected_errors=EXPECTED)

    assert result["status"] == "new_collection_regression"
    assert result["unexpected_collection_errors"] == [
        {"path": "test/test_new_dependency.py", "exception_type": "ModuleNotFoundError", "missing_module": "cv2"}
    ]
    assert result["missing_expected_collection_errors"] == EXPECTED


def test_collection_baseline_rejects_duplicate_multiline_tracebacks() -> None:
    duplicate = _collection_error("test/test_videomae_frame_directory.py", "ModuleNotFoundError", "cv2")
    output = duplicate + "interleaved traceback detail\n" + duplicate

    result = _module().evaluate_collection_output(output, pytest_exit_code=2, expected_errors=EXPECTED)

    assert result["status"] == "new_collection_regression"
    assert result["duplicate_collection_errors"] == [
        {"path": "test/test_videomae_frame_directory.py", "exception_type": "ModuleNotFoundError", "missing_module": "cv2"}
    ]


def test_collection_baseline_contract_rejects_duplicate_expected_entries(tmp_path) -> None:
    contract_path = tmp_path / "collection.json"
    contract_path.write_text(
        json.dumps({"contract_version": "phase_01_pytest_collection_baseline.v2", "expected_collection_errors": [EXPECTED[0], EXPECTED[0]]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate"):
        _module().load_expected_errors(contract_path)
