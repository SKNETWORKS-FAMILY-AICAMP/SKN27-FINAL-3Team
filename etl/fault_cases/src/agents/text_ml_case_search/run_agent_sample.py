from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.agent import run_text_ml_case_search
from etl.fault_cases.src.agents.text_ml_case_search.config import NODE_CODE
from etl.fault_cases.src.agents.text_ml_case_search.rag.es_client import (
    get_elasticsearch_client,
    ping_elasticsearch,
)
from etl.fault_cases.src.agents.text_ml_case_search.rag.retrieval_pipeline import (
    DEFAULT_SEARCH_VARIANT,
)


def build_sample_agent_input() -> dict[str, Any]:
    return {
        "session_id": "sample_session",
        "message_id": "sample_message",
        "job_id": "sample_job",
        "node_code": NODE_CODE,
        "raw_user_text": (
            "신호 없는 교차로에서 제 차량은 직진 중이었고, 상대 차량은 우측에서 진입해 "
            "충돌했습니다. 보험사는 제 과실이 더 크다고 설명했습니다."
        ),
        "query_text": "신호 없는 교차로 직진 차량과 우측 진입 차량 충돌 사고",
        "vision_evidence": None,
        "ocr_evidence": {
            "document_type": "traffic_accident_fact_confirmation",
            "accident_type": "신호 없는 교차로 차량 간 충돌 사고",
            "accident_cause": "우측 차량 진입, 교차로 진입 순서, 선진입 여부",
            "accident_description": "신호 없는 교차로에서 직진 차량과 우측 진입 차량이 충돌한 사고",
        },
        "insurer_claim": {
            "claimed_ratio": "사용자 70 : 상대 30",
            "reason_text": "보험사는 우측 차량 진입 상황 때문에 사용자 과실이 높다고 설명함",
            "source_type": "user_text",
            "source_text": "보험사는 제 과실을 70으로 봤습니다.",
            "source_reference": None,
        },
        "required_outputs": [
            "normalized_description",
            "issue_tags",
            "similar_cases",
            "evidence",
            "ratio_range_label",
            "insurer_claim_review",
            "recommended_evidence",
        ],
    }


def load_agent_input(path: str | None) -> dict[str, Any]:
    if not path:
        return build_sample_agent_input()

    with Path(path).open(encoding="utf-8") as file:
        payload = json.load(file)

    return payload.get("agent_input", payload)


def run_agent_sample(
    *,
    agent_input: dict[str, Any],
    search_variant: str = DEFAULT_SEARCH_VARIANT,
    skip_ping: bool = False,
) -> dict[str, Any]:
    client = get_elasticsearch_client()
    if not skip_ping and not ping_elasticsearch(client):
        raise RuntimeError(
            "Elasticsearch ping failed. Check docker compose, host, username, and password."
        )

    return run_text_ml_case_search(
        agent_input,
        es_client=client,
        search_variant=search_variant,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run text_ml_case_search with real Elasticsearch BM25/Nori RAG.",
    )
    parser.add_argument(
        "--input-json",
        help="Path to a JSON file containing agent_input. If omitted, built-in sample is used.",
    )
    parser.add_argument(
        "--search-variant",
        default=DEFAULT_SEARCH_VARIANT,
        help="Search text variant to use. Default: schema_search_text.",
    )
    parser.add_argument(
        "--skip-ping",
        action="store_true",
        help="Skip Elasticsearch ping before running the Agent.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of pretty JSON.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    agent_input = load_agent_input(args.input_json)
    result = run_agent_sample(
        agent_input=agent_input,
        search_variant=args.search_variant,
        skip_ping=args.skip_ping,
    )

    indent = None if args.compact else 2
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    from etl.fault_cases.src.agents.text_ml_case_search.config import load_dotenv_if_available

    load_dotenv_if_available()
    main()
