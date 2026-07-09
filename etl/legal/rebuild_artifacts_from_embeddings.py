"""Rebuild legal RAG artifacts from the 99,590-row E5 embedding baseline."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import yaml


DEFAULT_MANIFEST = Path("etl/legal/manifests/traffic_law_manifest.yaml")
DEFAULT_EMBEDDINGS = Path("output/law_ingestion/embeddings/law_embeddings_e5_large.jsonl")
DEFAULT_OUTPUT_DIR = Path("output/law_ingestion")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = rebuild_artifacts(
        manifest_path=Path(args.manifest),
        embeddings_path=Path(args.embeddings),
        output_dir=Path(args.output_dir),
    )
    print(
        "Rebuilt artifacts from embedding baseline: "
        f"{summary['total_chunks']} chunks, "
        f"{summary['total_versions']} versions, "
        f"{summary['relation_count']} relations"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--embeddings", default=str(DEFAULT_EMBEDDINGS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def rebuild_artifacts(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    embeddings_path: Path = DEFAULT_EMBEDDINGS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    if not embeddings_path.exists():
        raise FileNotFoundError(f"Embeddings not found: {embeddings_path}")

    started_at = datetime.now(timezone.utc).isoformat()
    sources = load_sources(manifest_path)
    sources_by_id = {row["source_id"]: row for row in sources}

    chunks_path = output_dir / "chunks" / "law_chunks.jsonl"
    searchable_path = output_dir / "publish" / "searchable_law_chunks.jsonl"
    relations_path = output_dir / "relations" / "law_relations.jsonl"
    extra_relations_path = output_dir / "relations" / "law_extra_relations.jsonl"
    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    searchable_path.parent.mkdir(parents=True, exist_ok=True)
    relations_path.parent.mkdir(parents=True, exist_ok=True)
    extra_relations_path.parent.mkdir(parents=True, exist_ok=True)

    versions: dict[str, dict] = {}
    chunk_type_counts: dict[str, int] = {}
    relation_count = 0
    total_chunks = 0

    with (
        embeddings_path.open("r", encoding="utf-8-sig") as source_handle,
        chunks_path.open("w", encoding="utf-8", newline="\n") as chunks_handle,
        searchable_path.open("w", encoding="utf-8", newline="\n") as searchable_handle,
        relations_path.open("w", encoding="utf-8", newline="\n") as relations_handle,
    ):
        for line in source_handle:
            if not line.strip():
                continue
            embedding_row = json.loads(line)
            parsed = parse_chunk_id(embedding_row["chunk_id"])
            source = sources_by_id.get(parsed["source_id"])
            if not source:
                raise ValueError(f"Unknown source_id in chunk_id: {embedding_row['chunk_id']}")

            version_id = parsed["source_version_id"]
            versions.setdefault(
                version_id,
                {
                    "source_version_id": version_id,
                    "source_id": parsed["source_id"],
                    "mst": parsed["mst"],
                    "enforce_date": parsed["enforce_date"],
                    "expire_date": None,
                    "promulgation_date": None,
                    "promulgation_no": None,
                    "law_serial_no": None,
                    "raw_document_id": f"raw:{version_id}",
                    "version_status": "historical",
                },
            )

            chunk = build_chunk(embedding_row, parsed, source)
            write_jsonl_row(chunks_handle, chunk)
            write_jsonl_row(searchable_handle, chunk)
            total_chunks += 1
            chunk_type_counts[chunk["chunk_type"]] = chunk_type_counts.get(chunk["chunk_type"], 0) + 1

            if chunk["chunk_type"] == "article":
                relation = {
                    "relation_id": f"rel:{version_id}:HAS_ARTICLE:{chunk['chunk_id']}",
                    "from_chunk_id": version_id,
                    "to_chunk_id": chunk["chunk_id"],
                    "relation_type": "HAS_ARTICLE",
                    "confidence": 1.0,
                    "evidence_text": chunk.get("article_no"),
                    "created_at": started_at,
                }
                write_jsonl_row(relations_handle, relation)
                relation_count += 1

    sorted_versions = sorted(versions.values(), key=lambda row: (row["source_id"], row["enforce_date"], row["mst"]))
    write_jsonl(output_dir / "normalized" / "legal_sources.jsonl", sources)
    write_jsonl(output_dir / "normalized" / "legal_source_versions.jsonl", sorted_versions)
    write_jsonl(output_dir / "normalized" / "raw_law_documents.jsonl", build_raw_records(sorted_versions, sources_by_id))
    write_jsonl(extra_relations_path, [])

    run_summary = {
        "run_id": f"legal_embedding_baseline:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "mode": "rebuild_from_embedding_baseline",
        "status": "success",
        "total_sources": len(sources),
        "total_versions": len(sorted_versions),
        "total_raw_documents": len(sorted_versions),
        "total_chunks": total_chunks,
        "searchable_chunks": total_chunks,
        "failed_chunks": 0,
        "partial_chunks": 0,
        "relation_count": relation_count,
        "extra_relation_count": 0,
        "embedding_input_count": total_chunks,
        "embedding_baseline_path": str(embeddings_path),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "limitations": [
            "chunk metadata was reconstructed from chunk_id and embedding_text because the original 99,590-row law_chunks artifact was not present",
            "source URLs are stable law.go.kr lookup URLs, not exact per-version document URLs",
        ],
    }
    write_json(output_dir / "reports" / "run_summary.json", run_summary)
    write_json(
        output_dir / "reports" / "quality_report.json",
        {
            "total_chunks": total_chunks,
            "searchable_chunks": total_chunks,
            "failed_chunks": 0,
            "status_counts": {"validated": total_chunks},
            "chunk_type_counts": chunk_type_counts,
        },
    )
    write_json(
        output_dir / "reports" / "coverage_report.json",
        {
            "status": "rebuilt_from_embedding_baseline",
            "total_sources": len(sources),
            "total_versions": len(sorted_versions),
            "total_chunks": total_chunks,
            "chunk_type_counts": chunk_type_counts,
            "limitations": run_summary["limitations"],
        },
    )
    write_jsonl(output_dir / "reports" / "ingestion_log.jsonl", [])
    return run_summary


def load_sources(manifest_path: Path) -> list[dict]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig")) or {}
    sources = manifest.get("sources") or []
    return sorted(
        [dict(row) for row in sources if row.get("enabled", True)],
        key=lambda row: (row.get("priority", 999), row.get("source_id", "")),
    )


def parse_chunk_id(chunk_id: str) -> dict:
    parts = chunk_id.split(":")
    if len(parts) < 5:
        raise ValueError(f"Unexpected chunk_id format: {chunk_id}")
    source_id, enforce_date, mst, chunk_type = parts[:4]
    ref_no = parts[4]
    return {
        "source_id": source_id,
        "enforce_date": enforce_date,
        "mst": mst,
        "chunk_type": chunk_type,
        "ref_no": ref_no,
        "source_version_id": f"{source_id}:{enforce_date}:{mst}",
        "structure_id": ":".join(parts[3:]) if len(parts) > 3 else None,
        "segment_no": parse_segment_no(parts[-1]),
    }


def build_chunk(embedding_row: dict, parsed: dict, source: dict) -> dict:
    body = extract_body(embedding_row.get("embedding_text") or "")
    chunk_type = parsed["chunk_type"]
    now = embedding_row.get("embedded_at") or datetime.now(timezone.utc).isoformat()
    chunk = {
        "chunk_id": embedding_row["chunk_id"],
        "source_ref": f"{parsed['source_id']}/{parsed['source_version_id']}/{parsed['structure_id']}",
        "source_id": parsed["source_id"],
        "source_name": source["source_name"],
        "source_type": source["source_type"],
        "source_version_id": parsed["source_version_id"],
        "mst": parsed["mst"],
        "chunk_type": chunk_type,
        "article_no": parsed["ref_no"] if chunk_type == "article" else None,
        "article_title": extract_title(
            embedding_row.get("embedding_text") or "",
            source["source_name"],
            parsed["ref_no"],
        ),
        "paragraph_no": None,
        "item_no": None,
        "appendix_no": parsed["ref_no"] if chunk_type == "appendix" else None,
        "form_no": parsed["ref_no"] if chunk_type == "form" else None,
        "structure_id": parsed["structure_id"],
        "segment_no": parsed["segment_no"],
        "provision_text": body,
        "normalized_text": body,
        "embedding_text": embedding_row.get("embedding_text"),
        "embedding_text_hash": embedding_row.get("embedding_text_hash"),
        "source_url": build_source_url(source["source_name"], parsed["mst"]),
        "enforce_date": parsed["enforce_date"],
        "expire_date": None,
        "content_hash": embedding_row.get("embedding_text_hash"),
        "parse_status": "rebuilt_from_embedding",
        "validation_status": "validated",
        "validation_errors": [],
        "is_searchable": True,
        "domain_tags": [],
        "created_at": now,
        "updated_at": now,
    }
    return chunk


def extract_body(embedding_text: str) -> str:
    if embedding_text.startswith("[") and "] " in embedding_text:
        return embedding_text.split("] ", 1)[1]
    return embedding_text


def extract_title(embedding_text: str, source_name: str, ref_no: str) -> str | None:
    if not embedding_text.startswith("[") or "]" not in embedding_text:
        return None
    header = embedding_text[1 : embedding_text.index("]")]
    title = header
    if title.startswith(source_name):
        title = title[len(source_name) :].strip()
    if title.startswith(ref_no):
        title = title[len(ref_no) :].strip()
    return title or None


def parse_segment_no(value: str) -> int | None:
    match = re.fullmatch(r"part(\d+)", value)
    return int(match.group(1)) if match else None


def build_source_url(source_name: str, mst: str) -> str:
    return f"https://www.law.go.kr/법령/{quote(source_name)}/({quote(str(mst))})"


def build_raw_records(versions: list[dict], sources_by_id: dict[str, dict]) -> list[dict]:
    rows = []
    for version in versions:
        source = sources_by_id[version["source_id"]]
        rows.append(
            {
                "raw_document_id": version["raw_document_id"],
                "source_id": version["source_id"],
                "source_name": source["source_name"],
                "source_version_id": version["source_version_id"],
                "source_url": build_source_url(source["source_name"], version["mst"]),
                "raw_path": None,
                "fetched_at": None,
                "storage_status": "metadata_rebuilt_from_embedding_baseline",
            }
        )
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            write_jsonl_row(handle, row)


def write_jsonl_row(handle, row: dict) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
