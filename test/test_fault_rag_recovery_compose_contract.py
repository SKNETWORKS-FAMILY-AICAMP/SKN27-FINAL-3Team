from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_compose_removes_search_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  kibana:" not in compose
    assert "ELASTICSEARCH_HOSTS=http://elasticsearch:9200" not in compose
    assert "ELASTICSEARCH_PORT" not in compose
