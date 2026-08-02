from __future__ import annotations

import importlib
import importlib.util
import json
import re
from pathlib import Path

import pytest


MODULE_NAME = "app.services.supervisor_input_normalization_service"


def _service():
    spec = importlib.util.find_spec(MODULE_NAME)
    assert spec is not None, "supervisor input normalization service must exist"
    return importlib.import_module(MODULE_NAME)


def test_default_normalization_policy_is_versioned_and_loadable() -> None:
    service = _service()
    service.clear_normalization_policy_cache()

    policy = service.normalization_policy()

    assert policy["contract_version"] == "supervisor_input_normalization_policy.v1"
    assert set(policy["domains"]) == {"accident", "fine_notice", "objection"}
    assert service.normalization_policy_metadata()["source"].replace("\\", "/").endswith(
        "app/config/supervisor_input_normalization_policy.v1.json"
    )


@pytest.mark.parametrize(
    "mutation,error_code",
    [
        (
            lambda value: value.update(contract_version="wrong.v1"),
            "unsupported_normalization_policy_version",
        ),
        (
            lambda value: value["rules"].append(dict(value["rules"][0])),
            "duplicate_normalization_rule_id",
        ),
        (
            lambda value: value["rules"][0].update(field="unknown"),
            "normalization_policy_contains_unknown_field",
        ),
        (
            lambda value: value["rules"][0].update(decision="accept_anything"),
            "normalization_policy_contains_invalid_decision",
        ),
    ],
)
def test_normalization_policy_rejects_invalid_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation,
    error_code: str,
) -> None:
    service = _service()
    policy = json.loads(service.DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    mutation(policy)
    path = tmp_path / "invalid-policy.json"
    path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SUPERVISOR_INPUT_NORMALIZATION_POLICY_PATH", str(path))
    service.clear_normalization_policy_cache()

    with pytest.raises(ValueError, match=error_code):
        service.normalization_policy()

    service.clear_normalization_policy_cache()


def test_policy_rules_and_wiki_rule_ids_are_bidirectionally_synchronized() -> None:
    service = _service()
    service.clear_normalization_policy_cache()
    policy_ids = {rule["rule_id"] for rule in service.normalization_policy()["rules"]}
    wiki_root = Path("docs/policies/supervisor-input-normalization")
    documented = "\n".join(
        path.read_text(encoding="utf-8") for path in wiki_root.glob("*.md")
    )
    documented_ids = set(
        re.findall(r"`([a-z0-9_.]+(?:exact|alias|typo)_[0-9]+)`", documented)
    )

    assert documented_ids == policy_ids
