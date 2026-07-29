import pytest

from ai.vision.run_to_supervisor import _json_object
from ai.vision.vlm_json import parse_vlm_json


VALID = """```json
{
  "schema_version": "vision-qwen-explanation-v1",
  "narrative": "The locked VideoMAE classification is supported by the visible vehicles.",
  "evidence_sentences": [
    {"frame_refs": ["frame_01"], "sentence": "Two vehicles are visible near the event."}
  ],
  "conflict": false,
  "conflict_reason": null,
  "uncertainties": ["Impact is outside sampled frames."]
}
```
extra text"""


def test_parse_vlm_json_reads_one_complete_object_and_ignores_trailing_text():
    value, valid, error = parse_vlm_json(VALID)
    assert valid is True
    assert error == ""
    assert value["schema_version"] == "vision-qwen-explanation-v1"


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
    with pytest.raises(ValueError, match="schema_invalid:missing:narrative"):
        _json_object('{"schema_version": "vision-qwen-explanation-v1"}')


def test_parse_vlm_json_rejects_frame_reference_not_in_input():
    value, valid, error = parse_vlm_json(VALID, allowed_frame_refs={"frame_02"})

    assert value == {}
    assert valid is False
    assert error == "schema_invalid:frame_ref:frame_01"


def test_parse_vlm_json_enforces_compact_array_limits():
    raw = VALID.replace(
        '"uncertainties": ["Impact is outside sampled frames."]',
        '"uncertainties": ["one", "two", "three", "four"]',
    )

    assert parse_vlm_json(raw)[2] == "schema_invalid:max_items:uncertainties"


def test_parse_vlm_json_requires_conflict_reason_only_for_conflict():
    raw = VALID.replace('"conflict": false', '"conflict": true')

    assert parse_vlm_json(raw)[2] == "schema_invalid:conflict_reason"
