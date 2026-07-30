from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from ..config import EXPECTED_RAG_BLOCKS, EXPECTED_RAG_CASES, QWEN_DIMENSION
from ..contracts import read_jsonl, write_jsonl
from ..rag_records.contracts import ALLOWED_GRADES, FORBIDDEN_ROLES
from .archive import create_tar_gz, select_source_vectors, sha256_file, write_json


SOURCE_NPY_SHA256 = "bc4bc1146b76784f2ba95f9287e7f1b8d0280e41fa249d0154c94789d453126c"
SOURCE_METADATA_SHA256 = "ab6ab0bedafd3152f9b5ee668b503c35d28288e0c6b421e872866b2f014ff9ff"
SOURCE_MANIFEST_SHA256 = "54c781f713f35aa725e8ec214a69c1e831c910821258733e79692502007baf88"


def _bootstrap_records(metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [
        {
            **row,
            "retrieval_document_id": row.get("retrieval_document_id")
            or row.get("block_id"),
        }
        for row in metadata
        if row.get("enabled_in_general_accident_search") is True
    ]
    if any(row.get("internal_grade") not in ALLOWED_GRADES for row in records):
        raise ValueError("bootstrap metadata contains a disallowed grade")
    if any(row.get("semantic_role") in FORBIDDEN_ROLES for row in records):
        raise ValueError("bootstrap metadata contains a forbidden semantic role")
    if any(row.get("validator_status") != "PASSED" for row in records):
        raise ValueError("bootstrap metadata contains an unvalidated record")
    return records


def build_bootstrap_package(
    *,
    source_embeddings: Path,
    source_metadata: Path,
    source_manifest: Path,
    output_path: Path,
    rag_records: Path | None = None,
    expected_blocks: int = EXPECTED_RAG_BLOCKS,
    expected_cases: int = EXPECTED_RAG_CASES,
    expected_dimension: int = QWEN_DIMENSION,
    enforce_source_hashes: bool = True,
) -> dict[str, Any]:
    source_embeddings = source_embeddings.resolve()
    source_metadata = source_metadata.resolve()
    source_manifest = source_manifest.resolve()
    output_path = output_path.resolve()
    hashes = {
        "source_embeddings": sha256_file(source_embeddings),
        "source_metadata": sha256_file(source_metadata),
        "source_manifest": sha256_file(source_manifest),
    }
    if enforce_source_hashes and hashes != {
        "source_embeddings": SOURCE_NPY_SHA256,
        "source_metadata": SOURCE_METADATA_SHA256,
        "source_manifest": SOURCE_MANIFEST_SHA256,
    }:
        raise ValueError(f"source hashes do not match the frozen assets: {hashes}")

    source_vectors = np.load(source_embeddings, mmap_mode="r")
    metadata = read_jsonl(source_metadata)
    source_info = json.loads(source_manifest.read_text(encoding="utf-8"))
    records = read_jsonl(rag_records.resolve()) if rag_records else _bootstrap_records(metadata)
    vectors, row_map = select_source_vectors(source_vectors, metadata, records)
    case_count = len({str(row.get("record_id") or "") for row in records})
    if len(records) != expected_blocks or case_count != expected_cases:
        raise ValueError(
            f"release gate mismatch: blocks={len(records)}, cases={case_count}"
        )
    if vectors.shape != (expected_blocks, expected_dimension):
        raise ValueError(f"derived vector shape mismatch: {vectors.shape}")
    if vectors.dtype != np.float32 or not np.isfinite(vectors).all():
        raise ValueError("derived vectors must be finite float32")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-4):
        raise ValueError("derived vectors are not L2-normalized")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_dir = output_path.parent / f".{output_path.name}.{uuid4().hex}.build"
    build_dir.mkdir()
    try:
        records_path = build_dir / "precedent_newplusplus_retrieval_blocks.jsonl"
        vectors_path = build_dir / "qwen3_document_embeddings.npy"
        row_map_path = build_dir / "source_row_map.jsonl"
        manifest_path = build_dir / "embedding_manifest.json"
        checksums_path = build_dir / "SHA256SUMS"
        write_jsonl(records_path, records)
        np.save(vectors_path, vectors, allow_pickle=False)
        write_jsonl(row_map_path, row_map)
        manifest = {
            "artifact_version": "precedent_newplusplus_bge_bootstrap_v1",
            "block_count": len(records),
            "case_count": case_count,
            "embedding_shape": list(vectors.shape),
            "embedding_dtype": str(vectors.dtype),
            "embedding_normalized": True,
            "model_name": source_info.get("model_name"),
            "model_revision": source_info.get("model_revision"),
            "source_hashes": hashes,
            "source_rows": int(source_vectors.shape[0]),
            "files": {},
        }
        for path in (records_path, vectors_path, row_map_path):
            manifest["files"][path.name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        write_json(manifest_path, manifest)
        checksum_paths = (records_path, vectors_path, row_map_path, manifest_path)
        checksums_path.write_text(
            "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksum_paths),
            encoding="utf-8",
        )
        create_tar_gz(build_dir, output_path)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
    return {
        "archive": str(output_path),
        "archive_sha256": sha256_file(output_path),
        "block_count": len(records),
        "case_count": case_count,
        "embedding_shape": list(vectors.shape),
        "source_hashes": hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the fixed precedent NEW++ bootstrap tar.gz."
    )
    parser.add_argument("--source-embeddings", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--rag-records", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_bootstrap_package(
        source_embeddings=args.source_embeddings,
        source_metadata=args.source_metadata,
        source_manifest=args.source_manifest,
        rag_records=args.rag_records,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
