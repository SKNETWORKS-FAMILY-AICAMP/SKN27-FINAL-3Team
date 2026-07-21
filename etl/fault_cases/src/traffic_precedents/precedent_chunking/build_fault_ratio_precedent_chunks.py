from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .fault_ratio_precedent_chunker import (
    DEFAULT_CHUNK_CONFIG,
    ChunkConfig,
    build_case_chunks,
    case_quality_flags,
    config_as_dict,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "artifacts"
    / "traffic_precedents_output"
    / "traffic_prec_fault_ratio_rag_verified"
    / "01_fault_ratio_rag_ready_cases.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "artifacts"
    / "traffic_precedents_output"
    / "precedent_chunking_v2"
)


def read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            yield line_no, json.loads(line)


def write_jsonl_row(handle: Any, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_chunks(input_path: Path, output_dir: Path, config: ChunkConfig) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = output_dir / "fault_ratio_precedent_chunks_v2.jsonl"
    review_path = output_dir / "fault_ratio_precedent_cases_review_v2.jsonl"
    report_path = output_dir / "fault_ratio_precedent_chunking_v2_report.json"

    case_count = 0
    chunk_count = 0
    review_case_count = 0
    chunk_type_counts: Counter[str] = Counter()
    quality_flag_counts: Counter[str] = Counter()
    chunk_lengths: list[int] = []
    embedding_lengths: list[int] = []

    with chunks_path.open("w", encoding="utf-8", newline="\n") as chunks_handle, review_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as review_handle:
        for line_no, row in read_jsonl(input_path):
            case_count += 1
            flags = case_quality_flags(row)
            quality_flag_counts.update(flags)
            if "needs_traffic_case_review" in flags:
                review_case_count += 1
                write_jsonl_row(
                    review_handle,
                    {
                        "input_line_no": line_no,
                        "case_id": row.get("_case_id"),
                        "case_name": row.get("사건명"),
                        "case_number": row.get("사건번호"),
                        "quality_flags": flags,
                        "holding": row.get("판시사항"),
                        "summary": row.get("판결요지"),
                        "reason_preview": str(row.get("이유") or "")[:1000],
                    },
                )

            for chunk in build_case_chunks(row, config=config):
                write_jsonl_row(chunks_handle, chunk)
                chunk_count += 1
                chunk_type_counts[chunk["chunk_type"]] += 1
                chunk_lengths.append(chunk["char_count"])
                embedding_lengths.append(chunk["embedding_char_count"])

    def percentile(values: list[int], ratio: float) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        return ordered[int((len(ordered) - 1) * ratio)]

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(input_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "chunks_path": str(chunks_path.resolve()),
        "review_path": str(review_path.resolve()),
        "config": config_as_dict(config),
        "case_count": case_count,
        "chunk_count": chunk_count,
        "review_case_count": review_case_count,
        "chunk_type_counts": dict(sorted(chunk_type_counts.items())),
        "quality_flag_counts": dict(sorted(quality_flag_counts.items())),
        "chunk_char_stats": {
            "min": min(chunk_lengths, default=0),
            "median": percentile(chunk_lengths, 0.5),
            "p90": percentile(chunk_lengths, 0.9),
            "p95": percentile(chunk_lengths, 0.95),
            "max": max(chunk_lengths, default=0),
        },
        "embedding_char_stats": {
            "min": min(embedding_lengths, default=0),
            "median": percentile(embedding_lengths, 0.5),
            "p90": percentile(embedding_lengths, 0.9),
            "p95": percentile(embedding_lengths, 0.95),
            "max": max(embedding_lengths, default=0),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build precedent-only chunks from final verified fault-ratio precedent JSONL."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--target-chars", type=int, default=DEFAULT_CHUNK_CONFIG.target_chars)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_CHUNK_CONFIG.max_chars)
    parser.add_argument("--overlap-units", type=int, default=DEFAULT_CHUNK_CONFIG.overlap_units)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ChunkConfig(
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        overlap_units=args.overlap_units,
    )
    report = build_chunks(args.input, args.output_dir, config)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
