import pytest

from ai.vision.run_to_supervisor import _json_object
from ai.vision.vlm_json import parse_vlm_json


VALID = """```json
{
  "summary": "Two vehicles approach.",
  "visible_objects": ["car", "truck"],
  "predicted_accident_target": "car_vs_car",
  "accident_target_evidence": "Both vehicles are visible.",
  "accident_visible": "true",
  "accident_visibility": "clear",
  "collision_moment_visible": "false",
  "accident_situation": "Vehicles approach each other.",
  "bbox_helpfulness": "helpful",
  "bbox_quality": "good",
  "scene_conditions": {"weather": "clear", "visibility": "good", "road_surface": "dry", "lighting": "day", "evidence": "Visible road"},
  "uncertainties": ["Impact is outside sampled frames."]
}
```
extra text"""


def test_parse_vlm_json_reads_one_complete_object_and_ignores_trailing_text():
    value, valid, error = parse_vlm_json(VALID)
    assert valid is True
    assert error == ""
    assert value["predicted_accident_target"] == "car_vs_car"


def test_parse_vlm_json_rejects_truncated_output():
    value, valid, error = parse_vlm_json('{"summary": "cut')
    assert value == {}
    assert valid is False
    assert error.startswith("json_incomplete:")


def test_parse_vlm_json_rejects_missing_required_field():
    raw = VALID.replace('"uncertainties": ["Impact is outside sampled frames."]', '"other": true')
    value, valid, error = parse_vlm_json(raw)
    assert value == {}
    assert valid is False
    assert error == "schema_invalid:missing:uncertainties"


def test_supervisor_parser_rejects_json_that_breaks_vlm_schema():
    with pytest.raises(ValueError, match="schema_invalid:missing:visible_objects"):
        _json_object('{"summary": "incomplete"}')
