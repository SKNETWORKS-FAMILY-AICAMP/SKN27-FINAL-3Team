from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


QWEN_MODEL_ID = "Qwen/Qwen3-Embedding-4B"
QWEN_REVISION = "5cf2132abc99cad020ac570b19d031efec650f2b"
QWEN_DIMENSION = 2560
BGE_MODEL_ID = "BAAI/bge-reranker-v2-m3"
BGE_REVISION = "324cc40576b08b305b9c65a867c26c173a477ae2"
BGE_MAX_LENGTH = 2048
EXPECTED_RAG_BLOCKS = 3339
EXPECTED_RAG_CASES = 825


@dataclass(frozen=True, slots=True)
class PipelinePaths:
    work_dir: Path
    input_dir: Path
    output_dir: Path

    def resolved(self) -> "PipelinePaths":
        return PipelinePaths(
            self.work_dir.expanduser().resolve(),
            self.input_dir.expanduser().resolve(),
            self.output_dir.expanduser().resolve(),
        )
