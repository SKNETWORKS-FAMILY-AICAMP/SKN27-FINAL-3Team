from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.config import PROJECT_ROOT
from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import (
    get_elasticsearch_client,
    ping_elasticsearch,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.retrieval_pipeline import (
    DEFAULT_SEARCH_VARIANT,
)


DEFAULT_INPUT_PATH = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "artifacts"
    / "review_case_output"
    / "schema_search_test"
    / "text_ml_case_search_agent_input_full_optional_fields.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "artifacts"
    / "review_case_output"
    / "agent_runs"
)


def load_active_agent_inputs(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_no, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue

            payload = json.loads(line)
            agent_input = payload.get("agent_input", payload)
            if not isinstance(agent_input, dict):
                raise ValueError(f"line {line_no}: agent_input must be an object")

            inputs.append(agent_input)
            if limit is not None and len(inputs) >= limit:
                break

    return inputs


def run_full_optional_inputs(
    *,
    input_path: Path = DEFAULT_INPUT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit: int | None = 10,
    search_variant: str = DEFAULT_SEARCH_VARIANT,
    skip_ping: bool = False,
) -> dict[str, Any]:
    agent_inputs = load_active_agent_inputs(input_path, limit=limit)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = get_elasticsearch_client()
    if not skip_ping and not ping_elasticsearch(client):
        raise RuntimeError(
            "Elasticsearch ping failed. Check docker compose, host, username, and password."
        )

    started_at = datetime.now().isoformat(timespec="seconds")
    output_path = output_dir / "text_ml_case_search_full_optional_agent_outputs.jsonl"
    summary_path = output_dir / "text_ml_case_search_full_optional_agent_summary.json"

    results: list[dict[str, Any]] = []
    with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for index, agent_input in enumerate(agent_inputs, start=1):
            result = run_text_ml_case_search(
                agent_input,
                es_client=client,
                search_variant=search_variant,
            )
            structured_result = result.get("structured_result", {})
            source_summary = structured_result.get("source_summary") or {}
            source_counts = source_summary.get("source_counts") or {}
            record = {
                "run_index": index,
                "session_id": agent_input.get("session_id"),
                "message_id": agent_input.get("message_id"),
                "job_id": agent_input.get("job_id"),
                "query_text": agent_input.get("query_text"),
                "status": result.get("status"),
                "evidence_count": len(result.get("evidence") or []),
                "review_case_evidence_count": int(source_counts.get("review_case") or 0),
                "fault_ratio_precedent_evidence_count": int(
                    source_counts.get("fault_ratio_precedent") or 0
                ),
                "similar_case_count": len(
                    structured_result.get("similar_cases") or []
                ),
                "display_evidence_count": len(
                    structured_result.get("display_evidence") or []
                ),
                "ratio_range_label": structured_result.get("ratio_range_label"),
                "source_summary": source_summary,
                "insurer_claim_review_exists": bool(
                    structured_result.get("insurer_claim_review")
                ),
                "result": result,
            }
            results.append(record)
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = build_run_summary(
        started_at=started_at,
        input_path=input_path,
        output_path=output_path,
        search_variant=search_variant,
        limit=limit,
        records=results,
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["summary_path"] = str(summary_path)
    return summary


def build_run_summary(
    *,
    started_at: str,
    input_path: Path,
    output_path: Path,
    search_variant: str,
    limit: int | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": started_at,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "search_variant": search_variant,
        "limit": limit,
        "active_input_count": len(records),
        "status_counts": status_counts,
        "total_evidence_count": sum(record["evidence_count"] for record in records),
        "total_review_case_evidence_count": sum(
            record["review_case_evidence_count"] for record in records
        ),
        "total_fault_ratio_precedent_evidence_count": sum(
            record["fault_ratio_precedent_evidence_count"] for record in records
        ),
        "total_similar_case_count": sum(record["similar_case_count"] for record in records),
        "total_display_evidence_count": sum(
            record["display_evidence_count"] for record in records
        ),
        "zero_evidence_count": sum(1 for record in records if record["evidence_count"] == 0),
        "records": [
            {
                "run_index": record["run_index"],
                "session_id": record["session_id"],
                "message_id": record["message_id"],
                "job_id": record["job_id"],
                "status": record["status"],
                "evidence_count": record["evidence_count"],
                "review_case_evidence_count": record["review_case_evidence_count"],
                "fault_ratio_precedent_evidence_count": record[
                    "fault_ratio_precedent_evidence_count"
                ],
                "similar_case_count": record["similar_case_count"],
                "display_evidence_count": record["display_evidence_count"],
                "ratio_range_label": record["ratio_range_label"],
                "insurer_claim_review_exists": record["insurer_claim_review_exists"],
                "source_summary": record["source_summary"],
            }
            for record in records
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run active full optional text_ml_case_search inputs with real RAG.",
    )
    parser.add_argument("--input-jsonl", default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--search-variant", default=DEFAULT_SEARCH_VARIANT)
    parser.add_argument("--skip-ping", action="store_true")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    summary = run_full_optional_inputs(
        input_path=Path(args.input_jsonl),
        output_dir=Path(args.output_dir),
        limit=args.limit,
        search_variant=args.search_variant,
        skip_ping=args.skip_ping,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    from etl.fault_cases.src.agents.text_ml_case_search.config import load_dotenv_if_available

    load_dotenv_if_available()
    main()
