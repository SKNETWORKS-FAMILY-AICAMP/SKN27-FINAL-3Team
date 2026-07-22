from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_compose_retains_kibana_service_for_existing_development_contract() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  kibana:" in compose
    assert "ELASTICSEARCH_HOSTS=http://elasticsearch:9200" in compose
    assert "KIBANA_PORT" in compose
