from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PIPELINE_STAGES = (
    "collect",
    "validate-collection",
    "preprocess",
    "semantic-blocks",
    "classify",
    "validate-classification",
    "build-rag-records",
    "embed",
    "load",
)
CLI_STAGES = (*PIPELINE_STAGES, "all")
BASE_DIR = Path(__file__).resolve().parent
STAGE_MODULES = {
    "collect": "collection.run",
    "validate-collection": "collection.run_validation",
    "preprocess": "preprocessing.run",
    "semantic-blocks": "semantic_blocks.run",
    "classify": "classification.run_classification",
    "validate-classification": "classification.run_validation",
    "build-rag-records": "rag_records.run",
    "embed": "precedent_embedding.build_embeddings",
    "load": "precedent_db_loading.run",
}


def run_stage(stage: str, remaining: list[str]) -> None:
    module = (
        "etl.fault_cases.src.traffic_precedents."
        + STAGE_MODULES[stage]
    )
    result = subprocess.run([sys.executable, "-m", module, *remaining], check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the precedent RAG pipeline.")
    parser.add_argument("--stage", choices=CLI_STAGES, default="all")
    parser.add_argument(
        "--pipeline-config",
        type=Path,
        help="JSON object mapping each stage to its CLI argument list.",
    )
    args, remaining = parser.parse_known_args()
    stages = PIPELINE_STAGES if args.stage == "all" else (args.stage,)
    stage_arguments: dict[str, list[str]] = {}
    if args.pipeline_config:
        raw = json.loads(
            args.pipeline_config.expanduser().resolve().read_text(encoding="utf-8")
        )
        if not isinstance(raw, dict):
            raise ValueError("pipeline config must be a JSON object")
        stage_arguments = {
            str(stage): [str(value) for value in values]
            for stage, values in raw.items()
        }
    if args.stage == "all" and not stage_arguments:
        raise ValueError("--pipeline-config is required for --stage all")
    for stage in stages:
        run_stage(stage, stage_arguments.get(stage, remaining))


if __name__ == "__main__":
    main()
