from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ..config import QWEN_MODEL_ID, QWEN_REVISION
from ..contracts import read_jsonl, write_jsonl
from .archive import sha256_file
from .qwen_embedder import embed_texts


def main() -> int:
    parser = argparse.ArgumentParser(description="Embed precedent RAG records.")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device")
    args = parser.parse_args()
    records = read_jsonl(args.records.resolve())
    vectors = embed_texts(
        (str(row.get("text") or "") for row in records),
        batch_size=args.batch_size,
        device=args.device,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    npy_path = output_dir / "01_document_embeddings_qwen3_4b.npy"
    metadata_path = output_dir / "02_document_embedding_metadata.jsonl"
    manifest_path = output_dir / "03_embedding_manifest.json"
    np.save(npy_path, vectors, allow_pickle=False)
    write_jsonl(
        metadata_path,
        ({**row, "embedding_row_index": index} for index, row in enumerate(records)),
    )
    manifest_path.write_text(
        json.dumps(
            {
                "model_name": QWEN_MODEL_ID,
                "model_revision": QWEN_REVISION,
                "row_count": len(records),
                "shape": list(vectors.shape),
                "normalized": True,
                "npy_sha256": sha256_file(npy_path),
                "metadata_sha256": sha256_file(metadata_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
