from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_source_vectors(
    source_vectors: np.ndarray,
    source_metadata: Iterable[dict[str, Any]],
    rag_records: Iterable[dict[str, Any]],
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    metadata = list(source_metadata)
    if source_vectors.shape[0] != len(metadata):
        raise ValueError("source vector and metadata row counts differ")
    source_index: dict[str, int] = {}
    for index, row in enumerate(metadata):
        if row.get("enabled_in_general_accident_search") is True:
            block_id = str(row.get("block_id") or row.get("retrieval_document_id") or "")
            if not block_id or block_id in source_index:
                raise ValueError(f"invalid or duplicate source block_id: {block_id}")
            source_index[block_id] = index
    selected: list[np.ndarray] = []
    row_map: list[dict[str, Any]] = []
    seen: set[str] = set()
    for new_index, row in enumerate(rag_records):
        block_id = str(row.get("block_id") or "")
        if not block_id or block_id in seen or block_id not in source_index:
            raise ValueError(f"RAG block cannot be aligned: {block_id}")
        seen.add(block_id)
        index = source_index[block_id]
        selected.append(source_vectors[index])
        row_map.append(
            {"new_index": new_index, "source_index": index, "block_id": block_id}
        )
    return np.asarray(selected, dtype=np.float32), row_map


def create_tar_gz(source_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as archive:
        for path in sorted(source_dir.iterdir(), key=lambda item: item.name):
            archive.add(path, arcname=path.name, recursive=False)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
