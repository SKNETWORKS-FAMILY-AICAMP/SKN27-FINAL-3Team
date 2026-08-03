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


def test_normalizes_registered_accident_and_objection_phrases() -> None:
    service = _service()

    result = service.normalize_supervisor_input(
        user_text="제가 직진했고 상대 차량은 좌해전했어요. 이의 재기하고 싶어요.",
        source_message_id="msg_normalize_1",
    )

    projected = {
        (item["field"], item["value"]): item
        for item in result["candidates"]
    }
    assert projected[("vehicle_actions.self", "straight")]["decision"] == (
        "auto_applied"
    )
    assert projected[("vehicle_actions.other", "left_turn")][
        "normalized_expression"
    ] == "좌회전"
    assert projected[("requested_action", "objection")]["rule_id"] == (
        "objection.requested_action.objection.typo_01"
    )
    assert all(
        item["source_message_id"] == "msg_normalize_1"
        for item in projected.values()
    )


def test_normalizes_notice_typo_and_preserves_source_span() -> None:
    service = _service()
    text = "1챠 고지서를 받고 의견 제출을 준비 중입니다."

    result = service.normalize_supervisor_input(
        user_text=text,
        source_message_id="msg_normalize_2",
    )

    stage = next(
        item for item in result["candidates"] if item["field"] == "notice_stage"
    )
    assert stage["value"] == "first_notice"
    assert stage["decision"] == "auto_applied"
    assert text[stage["source_span"]["start"]:stage["source_span"]["end"]] == (
        stage["source_text"]
    )


def test_negated_action_is_never_auto_applied() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text="상대 차량은 좌회전하지 않았습니다.",
        source_message_id="msg_negated",
    )
    action = next(
        item for item in result["candidates"] if item["value"] == "left_turn"
    )

    assert action["negated"] is True
    assert action["decision"] == "clarification_required"
    assert result["clarifications"][0]["field"] == "vehicle_actions.other"


def test_uncertain_action_requires_confirmation() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text="상대가 좌회전한 것 같아요.",
        source_message_id="msg_uncertain",
    )
    action = next(
        item for item in result["candidates"] if item["value"] == "left_turn"
    )

    assert action["uncertain"] is True
    assert action["decision"] == "confirmation_required"


def test_unique_unregistered_typo_is_confirmation_only() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text="상대 차량이 좌회잔했어요.",
        source_message_id="msg_fuzzy",
    )
    action = next(
        item for item in result["candidates"] if item["value"] == "left_turn"
    )

    assert action["match_kind"] == "fuzzy"
    assert action["decision"] == "confirmation_required"


def test_bare_notice_does_not_guess_legal_stage() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text="고지서를 받았습니다.",
        source_message_id="msg_ambiguous",
    )

    assert not any(
        item["field"] == "notice_stage" and item["decision"] == "auto_applied"
        for item in result["candidates"]
    )
    assert any(
        item["field"] == "notice_stage" for item in result["clarifications"]
    )


def test_extracts_only_limited_authority_amount_and_due_date_patterns() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text="서울시청 과태료 50,000원 납부기한은 2026-08-07까지입니다.",
        source_message_id="msg_limited_patterns",
    )

    projected = {
        (item["field"], item["value"]): item for item in result["candidates"]
    }
    assert projected[("issuing_authority", "서울시청")]["decision"] == (
        "auto_applied"
    )
    assert projected[("amount", "50,000원")]["decision"] == "auto_applied"
    assert projected[("due_date", "2026-08-07")]["decision"] == "auto_applied"


def test_accepts_seoul_city_alias_without_inventing_official_authority_name() -> None:
    service = _service()

    result = service.normalize_supervisor_input(
        user_text="사전통지서, 서울시, 2026-08-10, 첨부 가능",
        source_message_id="msg_seoul_city_alias",
    )

    authorities = [
        item
        for item in result["candidates"]
        if item["field"] == "issuing_authority"
    ]
    assert [(item["value"], item["decision"]) for item in authorities] == [
        ("서울시", "auto_applied")
    ]
    assert "서울특별시" not in repr(authorities)


def test_extracts_browser_fine_notice_fields_from_natural_sentence() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text=(
            "과태료 사전통지서고 서울특별시에서 발급했습니다. "
            "의견제출 기한은 2026년 8월 10일이고 문서 첨부도 가능해요."
        ),
        source_message_id="msg_browser_fine_notice",
    )

    projected = {
        (item["field"], item["value"]): item for item in result["candidates"]
    }

    assert projected[("issuing_authority", "서울특별시")]["decision"] == (
        "auto_applied"
    )
    assert projected[("due_date", "2026년 8월 10일")]["decision"] == (
        "auto_applied"
    )
    assert projected[("attachment_available", "yes")]["decision"] == (
        "auto_applied"
    )
    assert not any(item["field"] == "notice_date" for item in result["candidates"])


def test_extracts_observed_browser_attachment_availability_phrase() -> None:
    service = _service()

    result = service.normalize_supervisor_input(
        user_text="고지서 첨부가 가능합니다.",
        source_message_id="msg_observed_attachment_phrase",
    )

    attachment = next(
        item
        for item in result["candidates"]
        if item["field"] == "attachment_available"
    )
    assert attachment["value"] == "yes"
    assert attachment["decision"] == "auto_applied"


def test_observed_attachment_phrase_keeps_negation_and_uncertainty_guards() -> None:
    service = _service()

    negated = service.normalize_supervisor_input(
        user_text="고지서 첨부가 가능하지 않습니다.",
        source_message_id="msg_negated_attachment_phrase",
    )
    uncertain = service.normalize_supervisor_input(
        user_text="아마 첨부가 가능합니다.",
        source_message_id="msg_uncertain_attachment_phrase",
    )

    negated_attachment = next(
        item
        for item in negated["candidates"]
        if item["field"] == "attachment_available"
    )
    uncertain_attachment = next(
        item
        for item in uncertain["candidates"]
        if item["field"] == "attachment_available"
    )
    assert negated_attachment["decision"] == "clarification_required"
    assert uncertain_attachment["decision"] == "confirmation_required"


def test_single_unqualified_date_requires_confirmation() -> None:
    service = _service()
    result = service.normalize_supervisor_input(
        user_text="문서에는 2026-08-07이라고 적혀 있습니다.",
        source_message_id="msg_unqualified_date",
    )

    date = next(item for item in result["candidates"] if item["field"] == "notice_date")
    assert date["decision"] == "confirmation_required"
    assert any(item["field"] == "notice_date" for item in result["clarifications"])
