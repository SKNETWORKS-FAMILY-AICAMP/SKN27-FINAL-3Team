from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_FILE = ROOT / "docs" / "api" / "openapi-v0.yaml"
GUIDE_FILE = ROOT / "docs" / "api" / "openapi-v0-distribution-guide.md"
NOTES_FILE = ROOT / "docs" / "api" / "openapi-v0-notes.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_openapi() -> dict:
    return yaml.safe_load(read_text(OPENAPI_FILE))


def test_openapi_v0_distribution_files_exist():
    assert OPENAPI_FILE.exists()
    assert GUIDE_FILE.exists()
    assert NOTES_FILE.exists()


def test_openapi_v0_uses_3_2_and_status_markers():
    document = load_openapi()

    assert document["openapi"] == "3.2.0"
    assert document["info"]["x-contract-version"] == "pm-api-json-schema.v0"
    assert document["info"]["x-distribution-date"] == "2026-06-29"
    assert document["info"]["x-contract-status-policy"]["confirmed"]
    assert document["info"]["x-contract-status-policy"]["review_required"]


def test_openapi_v0_exposes_auth_history_and_agent_contracts():
    document = load_openapi()
    paths = document["paths"]
    schemas = document["components"]["schemas"]

    for path in [
        "/api/auth/guest-session/",
        "/api/auth/me/",
        "/api/chat/messages/",
        "/api/history/",
        "/api/mock/history/",
        "/api/agents/nodes/run/",
        "/api/agents/plans/run/",
    ]:
        assert path in paths

    assert paths["/api/auth/guest-session/"]["post"]["x-contract-status"] == "confirmed"
    assert paths["/api/history/"]["get"]["x-contract-status"] == "confirmed"
    assert schemas["HistoryEvent"]["x-contract-status"] == "confirmed"
    assert "auth_context" in schemas["ChatMessageRequest"]["properties"]
    assert "auth_context" in schemas["ReportActionRequest"]["properties"]


def test_openapi_v0_reflects_latest_agent_output_schema_updates():
    schemas = load_openapi()["components"]["schemas"]

    structured_result_refs = {
        item["$ref"].split("/")[-1]
        for item in schemas["AgentAdapterOutput"]["properties"]["structured_result"]["oneOf"]
        if "$ref" in item
    }

    assert "traffic_accident_confirmation_ocr" in schemas["NodeCode"]["enum"]
    assert "TrafficAccidentConfirmationOcrResult" in structured_result_refs
    assert "missing_fields" in schemas["AgentAdapterOutput"]["properties"]

    text_ml_properties = schemas["TextMlCaseSearchResult"]["properties"]
    assert text_ml_properties["reliability_score"]["type"] == ["number", "null"]
    assert "insurer_claim_review" in text_ml_properties
    assert "missing_fields" in text_ml_properties

    vision_properties = schemas["VisionMediaAnalysisResult"]["properties"]
    assert "event_window" in vision_properties
    assert "object_change_evidence" in vision_properties
    assert "candidate_scores" in vision_properties
    assert vision_properties["confidence_label"]["deprecated"] is True

    evidence_properties = schemas["Evidence"]["properties"]
    assert "review_case" in evidence_properties["source_type"]["enum"]
    assert evidence_properties["source_ref"]["deprecated"] is True


def test_openapi_v0_distribution_guide_routes_team_roles():
    guide = read_text(GUIDE_FILE)

    for section in ["Frontend", "Django Backend", "Supervisor", "Agent 담당자"]:
        assert section in guide
    assert "구현 금지" in guide
    assert "x-contract-status: review_required" in guide
