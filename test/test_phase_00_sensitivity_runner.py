from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "refactoring" / "verify_phase_00_test_sensitivity.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("phase_00_sensitivity_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_c_law_node_mutation_changes_only_the_expected_assertion() -> None:
    runner = _load_runner()
    target = runner.TARGETS[0]
    source = (REPO_ROOT / target.source_relative).read_text(encoding="utf-8")

    mutated = runner.mutate_target_source(source, target)

    assert target.expected in source
    assert target.replacement not in source
    assert target.expected not in mutated
    assert mutated.count(target.replacement) == 1


def test_g_report_owner_mutation_changes_only_the_expected_assertion() -> None:
    runner = _load_runner()
    target = runner.TARGETS[1]
    source = (REPO_ROOT / target.source_relative).read_text(encoding="utf-8")

    mutated = runner.mutate_target_source(source, target)

    assert target.expected in source
    assert target.replacement not in source
    assert target.expected not in mutated
    assert mutated.count(target.replacement) == 1


def test_mutation_rejects_an_ambiguous_expected_assertion() -> None:
    runner = _load_runner()
    target = runner.TARGETS[0]
    source = f'''\
class Example:
    def {target.method_name}(self):
        {target.expected}
        {target.expected}

    def another_test(self):
        pass
'''

    with pytest.raises(runner.SensitivityError, match="expected exactly one"):
        runner.mutate_target_source(source, target)
