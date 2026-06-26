"""Self-contained assertions check for database schemas, tag enrichment, and loader logic."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from etl.legal.ingestion.parser import enrich_metadata
from etl.legal.export_sql import export_to_sql

ROOT = Path(__file__).resolve().parents[2]


def check_enrich_metadata_tags():
    print("Checking metadata tag enrichment...")
    # Mock chunks
    mock_chunks = [
        {
            "chunk_id": "test1",
            "normalized_text": "원동기장치자전거와 전동킥보드 등 개인형 이동장치는 도로교통법 제12조에 의거한다.",
            "source_id": "test_act",
            "source_name": "테스트법",
            "source_type": "law",
            "chunk_type": "article"
        },
        {
            "chunk_id": "test2",
            "normalized_text": "음주운전 금지 및 술에 취한 상태에서의 측정 거부는 처벌을 받는다.",
            "source_id": "test_act",
            "source_name": "테스트법",
            "source_type": "law",
            "chunk_type": "article"
        },
        {
            "chunk_id": "test3",
            "normalized_text": "일반적인 조항 문장입니다. 특별한 키워드가 포함되어 있지 않습니다.",
            "source_id": "test_act",
            "source_name": "테스트법",
            "source_type": "law",
            "chunk_type": "article"
        }
    ]

    enriched = enrich_metadata(mock_chunks)
    assert len(enriched) == 3, f"Expected 3 chunks, got {len(enriched)}"

    # Check tags for PM chunk
    assert "개인형 이동장치" in enriched[0]["domain_tags"], f"Expected '개인형 이동장치' in tags: {enriched[0]['domain_tags']}"
    assert "traffic" in enriched[0]["domain_tags"], f"Expected 'traffic' in tags: {enriched[0]['domain_tags']}"

    # Check tags for Drunk driving chunk
    assert "음주운전" in enriched[1]["domain_tags"], f"Expected '음주운전' in tags: {enriched[1]['domain_tags']}"

    # Check tags for plain chunk
    assert "개인형 이동장치" not in enriched[2]["domain_tags"], f"Did not expect '개인형 이동장치' in tags: {enriched[2]['domain_tags']}"
    print("-> Metadata tag enrichment checks passed!")


def check_export_to_sql_outputs_valid_schema():
    print("Checking SQL seed generator...")
    tmp_dir = ROOT / "tmp" / "test_checks"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    chunks_path = tmp_dir / "chunks.jsonl"
    embeddings_path = tmp_dir / "embeddings.jsonl"
    sql_path = tmp_dir / "seed.sql"

    # Write mock files
    chunk_data = {
        "chunk_id": "road_traffic_act:2026:article:1",
        "source_id": "road_traffic_act",
        "source_name": "도로교통법",
        "source_type": "law",
        "chunk_type": "article",
        "article_no": "제1조",
        "provision_text": "목적 조항",
        "normalized_text": "목적 조항",
        "is_searchable": True,
        "domain_tags": ["개인형 이동장치", "safety"]
    }
    chunks_path.write_text(json.dumps(chunk_data) + "\n", encoding="utf-8")

    emb_data = {
        "chunk_id": "road_traffic_act:2026:article:1",
        "embedding_vector": [0.1] * 1024,
        "embedding_provider": "sentence-transformers"
    }
    embeddings_path.write_text(json.dumps(emb_data) + "\n", encoding="utf-8")

    code = export_to_sql(
        chunks_path=str(chunks_path),
        embeddings_path=str(embeddings_path),
        output_sql_path=str(sql_path)
    )
    assert code == 0, f"Expected exit code 0, got {code}"
    assert sql_path.exists(), "SQL seed file was not created"

    sql_content = sql_path.read_text(encoding="utf-8")
    assert "is_searchable BOOLEAN DEFAULT TRUE" in sql_content, "Missing is_searchable column in schema"
    assert "domain_tags TEXT[] DEFAULT '{}'" in sql_content, "Missing domain_tags column in schema"
    assert "idx_law_chunks_domain_tags ON law_chunks USING GIN" in sql_content, "Missing GIN index on domain_tags"
    assert "road_traffic_act:2026:article:1" in sql_content, "Missing chunk insert statement"
    
    # Clean up
    for p in [chunks_path, embeddings_path, sql_path]:
        if p.exists():
            p.unlink()
    tmp_dir.rmdir()
    print("-> SQL seed generator checks passed!")


if __name__ == "__main__":
    try:
        check_enrich_metadata_tags()
        check_export_to_sql_outputs_valid_schema()
        print("\nAll database loader checks completed successfully!")
        sys.exit(0)
    except AssertionError as exc:
        print(f"Check failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error during checks: {exc}", file=sys.stderr)
        sys.exit(1)
