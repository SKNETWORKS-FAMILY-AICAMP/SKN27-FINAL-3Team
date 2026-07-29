from ai.vision.impact_frames import grouped_impact_frame_indices
from ai.vision.vlm_json import enforce_confirmed_accident_context, parse_vlm_json


def test_grouped_selector_returns_verified_4_by_4_layout():
    scores = [0.0] * 99
    scores[49] = 10.0
    selected = grouped_impact_frame_indices(scores, 100)
    assert len(selected) == 16
    assert len({index for index, _ in selected}) == 16
    assert {role for _, role in selected} == {
        "context",
        "pre_impact",
        "impact",
        "post_impact",
    }
    assert all(
        sum(role == expected for _, role in selected) == 4
        for expected in ("context", "pre_impact", "impact", "post_impact")
    )


def test_vlm_json_rejects_unknown_frame_reference():
    raw = """{
      "schema_version": "vision-qwen-explanation-v1",
      "narrative": "Vehicles converge.",
      "evidence_sentences": [{"frame_refs": ["frame_17"], "sentence": "A car is visible."}],
      "conflict": false,
      "conflict_reason": null,
      "uncertainties": []
    }"""
    _, valid, error = parse_vlm_json(raw, {"frame_01"})
    assert valid is False
    assert error == "schema_invalid:frame_ref:frame_17"


def test_qwen_denial_cannot_change_confirmed_accident_or_label():
    value = {
        "narrative": "There is no collision.",
        "impact_visibility": "not_visible",
    }
    result = enforce_confirmed_accident_context(value, "car_vs_pedestrian")
    assert result["confirmed_accident"] is True
    assert result["canonical_label"] == "car_vs_pedestrian"
    assert result["accident_type"] == "car_vs_pedestrian"
    assert result["narrative"].startswith("Confirmed accident")
