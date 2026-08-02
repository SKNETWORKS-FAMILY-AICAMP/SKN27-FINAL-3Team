import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "test" / "fixtures" / "pilot_ocr_scenarios.json"


def test_pilot_ocr_manifest_contains_only_approved_sanitized_scenarios() -> None:
    scenarios = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"]

    assert [item["id"] for item in scenarios] == [
        "OCR-A-01",
        "OCR-A-02",
        "OCR-F-01",
        "OCR-F-02",
    ]
    assert [item["filename"] for item in scenarios] == [
        "22-11-18-_.png",
        "15-07-18-.jpg",
        "form2_별지154_위반사실통지및과태료사전통지서.pdf",
        "form3_별지152_과태료납부고지서원부_운전자.pdf",
    ]

    serialized = json.dumps(scenarios, ensure_ascii=False)
    for forbidden in (
        "absolute_path",
        "expected_raw_text",
        "resident_registration_number",
        "driver_license_number",
        "phone_number",
        "home_address",
        "storage_uri",
    ):
        assert forbidden not in serialized

    assert scenarios[0]["purpose"] == "traffic_accident_confirmation"
    assert scenarios[0]["allowed_statuses"] == ["success", "partial"]
    assert scenarios[0]["required_safe_fields"] == [
        "accident_datetime",
        "accident_location",
        "accident_type",
        "accident_cause",
    ]
    assert scenarios[1]["purpose"] == "traffic_accident_confirmation"
    assert scenarios[1]["allowed_statuses"] == ["partial", "failed"]
    assert scenarios[1]["required_next_action"] == "reupload_complete_page"
    assert scenarios[2]["purpose"] == "fine_notice"
    assert scenarios[2]["expected_notice_stage"] == "사전통지"
    assert scenarios[3]["purpose"] == "fine_notice"
    assert scenarios[3]["expected_notice_stage"] == "1차 고지서"


def test_each_manifest_scenario_has_only_one_expected_classification() -> None:
    scenarios = json.loads(MANIFEST.read_text(encoding="utf-8"))["scenarios"]

    for scenario in scenarios:
        assert scenario["expected_classification"] == scenario["purpose"]
        assert len(scenario["allowed_statuses"]) == len(
            set(scenario["allowed_statuses"])
        )
