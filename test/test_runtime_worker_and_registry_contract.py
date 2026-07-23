from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.services import agent_node_service


ROOT = Path(__file__).resolve().parents[1]


def test_compose_runs_the_canonical_agent_worker_continuously() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    worker = compose["services"].get("agent-worker")
    assert worker is not None, "queued Agent work has no long-running Compose consumer"
    assert worker["image"] == compose["services"]["backend"]["image"]
    assert worker["command"] == (
        "sh -c \"python backend/manage.py migrate --check && "
        "exec python backend/manage.py process_agent_work_items --loop --limit 10\""
    )
    assert worker["restart"] == "unless-stopped"
    assert worker["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_public_agent_registry_is_typed_and_never_exposes_mock_execution() -> None:
    assert hasattr(agent_node_service, "list_public_agent_nodes"), (
        "the public Agent catalog must be separate from the legacy test registry"
    )

    nodes = agent_node_service.list_public_agent_nodes()
    assert {node["node_code"] for node in nodes} == {
        "appeal_decision_flow",
        "attachment_document_classification",
        "fine_notice_analysis",
        "law_ground_search",
        "objection_report_generation",
        "text_ml_case_search",
        "traffic_accident_confirmation_ocr",
        "vision_media_analysis",
    }
    for node in nodes:
        assert node["contract_version"] == "agent_capability.v1"
        assert node["capability_status"] == "available"
        assert node["execution_modes"] == ["sync"]
        assert node["input_schema"] == "agent_input.v1"
        assert node["output_schema"] == "agent_output.v1"
        assert isinstance(node["timeout_seconds"], int)
        assert node["timeout_seconds"] > 0
        assert "mock" not in json.dumps(node, ensure_ascii=False).lower()


def test_vision_is_a_public_sync_agent_without_mock_mode() -> None:
    public_nodes = {
        node["node_code"]: node for node in agent_node_service.list_public_agent_nodes()
    }
    registry_nodes = {node["node_code"]: node for node in agent_node_service.list_agent_nodes()}
    vision = public_nodes["vision_media_analysis"]

    assert vision["execution_modes"] == ["sync"]
    assert registry_nodes["vision_media_analysis"]["adapter_contract"]["execution_modes"] == ["sync"]
    assert "mock" not in json.dumps(vision, ensure_ascii=False).lower()
