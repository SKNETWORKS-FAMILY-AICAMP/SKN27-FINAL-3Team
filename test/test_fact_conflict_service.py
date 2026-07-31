from __future__ import annotations

import math

import pytest


def _valid_conflict() -> dict[str, object]:
    return {
        "field": "signal_priority",
        "candidates": [
            {
                "value": "녹색 신호에 직진했다는 진술",
                "source_message_id": "msg_e2e_13",
                "confidence": 0.9,
            },
            {
                "value": "빨간불에 진입한 것으로 보일 수 있다는 진술",
                "source_message_id": "msg_e2e_13",
                "confidence": 0.8,
            },
        ],
    }


def test_normalize_fact_conflicts_preserves_exact_safe_shape() -> None:
    from app.services.fact_conflict_service import normalize_fact_conflicts

    assert normalize_fact_conflicts([_valid_conflict()]) == [_valid_conflict()]


@pytest.mark.parametrize(
    "invalid",
    [
        {"field": "unknown", "candidates": _valid_conflict()["candidates"]},
        {
            "field": "signal_priority",
            "candidates": [_valid_conflict()["candidates"][0]],
        },
        {
            "field": "signal_priority",
            "candidates": [
                _valid_conflict()["candidates"][0],
                {**_valid_conflict()["candidates"][1], "value": " "},
            ],
        },
        {
            "field": "signal_priority",
            "candidates": [
                _valid_conflict()["candidates"][0],
                {
                    **_valid_conflict()["candidates"][1],
                    "value": " 녹색  신호에 직진했다는 진술 ",
                },
            ],
        },
        {
            "field": "signal_priority",
            "candidates": [
                _valid_conflict()["candidates"][0],
                {
                    **_valid_conflict()["candidates"][1],
                    "confidence": math.nan,
                },
            ],
        },
        {
            "field": "signal_priority",
            "candidates": [
                _valid_conflict()["candidates"][0],
                {
                    **_valid_conflict()["candidates"][1],
                    "confidence": 1.1,
                },
            ],
        },
        {
            "field": "signal_priority",
            "candidates": [
                {
                    **_valid_conflict()["candidates"][0],
                    "reasoning": "private chain of thought",
                },
                _valid_conflict()["candidates"][1],
            ],
        },
        {**_valid_conflict(), "raw_reasoning": "private"},
    ],
)
def test_normalize_fact_conflicts_rejects_entire_invalid_conflict(
    invalid: dict[str, object],
) -> None:
    from app.services.fact_conflict_service import normalize_fact_conflicts

    assert normalize_fact_conflicts([invalid]) == []


def test_normalize_fact_conflicts_rebinds_sources_and_orders_core_fields() -> None:
    from app.services.fact_conflict_service import normalize_fact_conflicts

    collision = {
        "field": "collision_location",
        "candidates": [
            {"value": "앞범퍼", "source_message_id": "model:fake", "confidence": 0.7},
            {"value": "뒷문", "source_message_id": "model:fake", "confidence": 0.6},
        ],
    }
    normalized = normalize_fact_conflicts(
        [collision, _valid_conflict()],
        default_source_message_id="msg_current",
    )

    assert [item["field"] for item in normalized] == [
        "signal_priority",
        "collision_location",
    ]
    assert all(
        candidate["source_message_id"] == "msg_current"
        for conflict in normalized
        for candidate in conflict["candidates"]
    )


def test_detects_id13_same_message_signal_conflict() -> None:
    from app.services.fact_conflict_service import (
        detect_same_message_fact_conflicts,
    )

    conflicts = detect_same_message_fact_conflicts(
        "저는 녹색 신호에 직진했고 상대는 신호위반 좌회전이었습니다. "
        "그런데 블랙박스에는 제가 빨간불에 진입한 것처럼 보일 수도 있습니다. "
        "과실이 몇 대 몇인가요?",
        "msg_e2e_13",
    )

    assert [item["field"] for item in conflicts] == ["signal_priority"]
    assert len(conflicts[0]["candidates"]) == 2
    assert all(
        candidate["source_message_id"] == "msg_e2e_13"
        for candidate in conflicts[0]["candidates"]
    )
    assert conflicts[0]["candidates"][1]["value"] == (
        "빨간불에 진입한 것으로 보일 수 있다는 진술"
    )


@pytest.mark.parametrize(
    "user_text",
    [
        "저는 녹색 신호에 직진했습니다.",
        "제가 빨간불에 진입했습니다.",
        "블랙박스에서 신호가 잘 안 보입니다.",
        "상대는 녹색 신호였고 저는 직진했습니다.",
    ],
)
def test_signal_detector_does_not_invent_conflicts(user_text: str) -> None:
    from app.services.fact_conflict_service import (
        detect_same_message_fact_conflicts,
    )

    assert detect_same_message_fact_conflicts(user_text, "msg_safe") == []
