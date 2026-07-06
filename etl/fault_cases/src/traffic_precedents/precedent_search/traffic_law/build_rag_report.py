from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from etl.fault_cases.src.traffic_precedents.precedent_db_loading.config import PROJECT_ROOT
from etl.fault_cases.src.traffic_precedents.precedent_search.traffic_law.run_bm25_sample_queries import (
    DEFAULT_OUTPUT_JSON,
    DEFAULT_SUMMARY_JSON,
)


DEFAULT_REPORT_MD = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "Fault_cases_MD"
    / "판례"
    / "교통사고 관련 판례 RAG"
    / "교통사고_일반판례_RAG_검색_평가_보고서.md"
)
DEFAULT_REPORT_JSON = DEFAULT_OUTPUT_JSON.parent / "traffic_law_bm25_report.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def preview_text(value: Any, *, max_len: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def preview_list(values: Any, *, max_items: int = 2, max_len: int = 120) -> str:
    if not isinstance(values, list):
        return preview_text(values, max_len=max_len)
    previews = [preview_text(value, max_len=max_len) for value in values if str(value or "").strip()]
    return " / ".join(previews[:max_items])


def markdown_table_row(values: list[Any]) -> str:
    return "| " + " | ".join(str(value).replace("\n", " ") for value in values) + " |"


def collect_query_report(query_result: dict[str, Any]) -> dict[str, Any]:
    results = query_result.get("results") or []
    top1 = results[0] if results else {}

    return {
        "query_id": query_result.get("query_id") or "",
        "query": query_result.get("query") or "",
        "issue_tags": query_result.get("issue_tags") or [],
        "purpose": query_result.get("purpose") or "",
        "result_count": len(results),
        "top1_case_name": top1.get("case_name") or "",
        "top1_case_number": top1.get("case_number") or "",
        "top1_court_name": top1.get("court_name") or "",
        "top1_decision_date": top1.get("decision_date") or "",
        "top1_source_reference": top1.get("source_reference") or "",
        "top1_score": top1.get("retriever_score") or 0,
        "top1_chunk_type": top1.get("chunk_type") or "",
        "top1_chunk_preview": top1.get("chunk_preview") or "",
        "top1_matched_snippets": top1.get("matched_snippets") or [],
        "top5": results[:5],
    }


def build_report(sample_report: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    query_reports = [collect_query_report(row) for row in sample_report.get("queries", [])]
    zero_result_queries = [row["query_id"] for row in query_reports if row["result_count"] == 0]
    top1_missing_snippet = [
        row["query_id"] for row in query_reports if row["result_count"] > 0 and not row["top1_matched_snippets"]
    ]

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_summary": summary,
        "query_count": len(query_reports),
        "total_result_count": summary.get("total_result_count", 0),
        "zero_result_query_ids": zero_result_queries,
        "top1_missing_snippet_query_ids": top1_missing_snippet,
        "conclusion": (
            "CHECK: BM25/Nori returned candidates for every traffic law query."
            if not zero_result_queries
            else "REVIEW: one or more traffic law queries returned zero candidates."
        ),
        "queries": query_reports,
    }


def build_markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("source_summary") or {}
    queries = report.get("queries") or []

    lines: list[str] = [
        "# 교통사고 일반판례 RAG/Search BM25+Nori 검색 평가 보고서",
        "",
        "## 목적",
        "",
        "`traffic_precedent`를 대상으로 교통사고 일반 법률/주의의무/책임 판단에 필요한 판례가 BM25+Nori로 검색되는지 확인한다.",
        "",
        "이번 보고서는 Agent output 평가가 아니라, 교통사고 일반판례 RAG/Search V1의 검색 품질을 사람이 검수하기 위한 보고서다.",
        "",
        "## 실행 요약",
        "",
        markdown_table_row(["항목", "값"]),
        markdown_table_row(["---", "---"]),
        markdown_table_row(["생성 시각", report.get("created_at", "")]),
        markdown_table_row(["retriever", summary.get("retriever", "")]),
        markdown_table_row(["source_type", summary.get("source_type", "")]),
        markdown_table_row(["elasticsearch_index", summary.get("elasticsearch_index", "")]),
        markdown_table_row(["query_count", summary.get("query_count", 0)]),
        markdown_table_row(["top_k", summary.get("top_k", 0)]),
        markdown_table_row(["total_result_count", summary.get("total_result_count", 0)]),
        markdown_table_row(["zero_result_query_ids", report.get("zero_result_query_ids", [])]),
        markdown_table_row(["top1_missing_snippet_query_ids", report.get("top1_missing_snippet_query_ids", [])]),
        markdown_table_row(["결론", report.get("conclusion", "")]),
        "",
        "## Query별 Top1 대표 판례",
        "",
        markdown_table_row([
            "query_id",
            "query",
            "result_count",
            "case_name",
            "case_number",
            "court",
            "decision_date",
            "score",
            "source_reference",
            "matched_snippets",
        ]),
        markdown_table_row(["---", "---", "---:", "---", "---", "---", "---", "---:", "---", "---"]),
    ]

    for row in queries:
        lines.append(
            markdown_table_row([
                row.get("query_id", ""),
                preview_text(row.get("query"), max_len=38),
                row.get("result_count", 0),
                preview_text(row.get("top1_case_name"), max_len=35),
                preview_text(row.get("top1_case_number"), max_len=20),
                row.get("top1_court_name", ""),
                row.get("top1_decision_date", ""),
                round(float(row.get("top1_score") or 0), 4),
                preview_text(row.get("top1_source_reference"), max_len=55),
                preview_list(row.get("top1_matched_snippets"), max_items=2, max_len=85),
            ])
        )

    lines.extend([
        "",
        "## Query별 Top1 본문 Preview",
        "",
    ])

    for row in queries:
        lines.extend([
            f"### {row.get('query_id')} - {row.get('query')}",
            "",
            markdown_table_row(["항목", "값"]),
            markdown_table_row(["---", "---"]),
            markdown_table_row(["목적", row.get("purpose", "")]),
            markdown_table_row(["issue_tags", ', '.join(row.get("issue_tags") or [])]),
            markdown_table_row(["대표 판례", row.get("top1_case_name", "")]),
            markdown_table_row(["source_reference", row.get("top1_source_reference", "")]),
            markdown_table_row(["matched_snippets", preview_list(row.get("top1_matched_snippets"), max_items=3, max_len=160)]),
            "",
            "```text",
            preview_text(row.get("top1_chunk_preview"), max_len=700),
            "```",
            "",
        ])

    lines.extend([
        "## 검수 기준",
        "",
        "사람이 확인할 기준은 다음과 같다.",
        "",
        "```text",
        "1. top1 판례가 query의 사고 유형과 맞는가",
        "2. top5 안에 사용할 만한 판례가 있는가",
        "3. matched_snippets가 실제 법률 쟁점을 보여주는가",
        "4. 과실비율 직접 근거로 오해될 위험은 없는가",
        "5. traffic_precedent가 주의의무/책임 판단 근거로 적절한가",
        "```",
        "",
        "## 다음 단계",
        "",
        "```text",
        "1. 이 보고서의 query별 Top1과 preview를 사람이 검수한다.",
        "2. BM25+Nori 단독으로 충분하면 traffic_precedent RAG/Search V1 기준으로 유지한다.",
        "3. 결과가 부족한 query가 많으면 hint/vector/hybrid 확장을 별도 단계에서 검토한다.",
        "```",
    ])

    return "\n".join(lines) + "\n"


def write_report(
    *,
    sample_json: Path = DEFAULT_OUTPUT_JSON,
    summary_json: Path = DEFAULT_SUMMARY_JSON,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
) -> dict[str, Any]:
    sample_report = load_json(sample_json)
    summary = load_json(summary_json)
    report = build_report(sample_report, summary)

    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(build_markdown_report(report), encoding="utf-8")

    return {
        "report_json": str(report_json),
        "report_md": str(report_md),
        "query_count": report["query_count"],
        "total_result_count": report["total_result_count"],
        "zero_result_query_ids": report["zero_result_query_ids"],
        "conclusion": report["conclusion"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build BM25/Nori traffic law RAG report.")
    parser.add_argument("--sample-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT_MD))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    result = write_report(
        sample_json=Path(args.sample_json),
        summary_json=Path(args.summary_json),
        report_json=Path(args.report_json),
        report_md=Path(args.report_md),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

