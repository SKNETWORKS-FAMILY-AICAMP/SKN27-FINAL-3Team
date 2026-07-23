from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from etl.fault_cases.src.agents.text_ml_case_search.config import PROJECT_ROOT
from etl.fault_cases.src.agents.text_ml_case_search.run_full_optional_inputs import (
    DEFAULT_OUTPUT_DIR,
)


DEFAULT_OUTPUTS_JSONL = DEFAULT_OUTPUT_DIR / "text_ml_case_search_full_optional_agent_outputs.jsonl"
DEFAULT_SUMMARY_JSON = DEFAULT_OUTPUT_DIR / "text_ml_case_search_full_optional_agent_summary.json"
DEFAULT_REPORT_JSON = DEFAULT_OUTPUT_DIR / "text_ml_case_search_full_optional_agent_report.json"
DEFAULT_REPORT_MD = (
    PROJECT_ROOT
    / "etl"
    / "fault_cases"
    / "Fault_cases_MD"
    / "에이전트"
    / "text_ml_case_search_active_10_실행_결과_보고서.md"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_no, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}: {path}") from exc
    return records


def preview_text(value: Any, *, max_len: int = 80) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def preview_list(values: Any, *, max_items: int = 2, max_len: int = 160) -> str:
    if not isinstance(values, list):
        return preview_text(values, max_len=max_len)
    snippets = [preview_text(value, max_len=max_len) for value in values if str(value or "").strip()]
    return " / ".join(snippets[:max_items])


def looks_like_encoding_issue(value: Any) -> bool:
    text = str(value or "")
    if not text:
        return False
    markers = ("?좏", "?꾨", "?쇱", "?곷", "?ш", "泥?", "濡?", "援?", "怨?")
    marker_count = sum(1 for marker in markers if marker in text)
    has_non_ascii = any(ord(char) > 127 for char in text)
    return marker_count >= 1 or (has_non_ascii and text.count("?") >= 3)


def display_evidence_items(record: dict[str, Any]) -> list[dict[str, Any]]:
    result = record.get("result") or {}
    structured = result.get("structured_result") or {}
    items = structured.get("display_evidence") or []
    return [item for item in items if isinstance(item, dict)]


def first_display_evidence(record: dict[str, Any]) -> dict[str, Any]:
    items = display_evidence_items(record)
    return items[0] if items else {}


def first_display_evidence_by_source(record: dict[str, Any], *, source_type: str) -> dict[str, Any]:
    for item in display_evidence_items(record):
        if item.get("source_type") == source_type:
            return item
    return {}


def collect_record_report(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") or {}
    structured = result.get("structured_result") or {}
    source_summary = structured.get("source_summary") or record.get("source_summary") or {}
    source_counts = source_summary.get("source_counts") or {}

    top_item = first_display_evidence(record)
    review_item = first_display_evidence_by_source(record, source_type="review_case")
    precedent_item = first_display_evidence_by_source(
        record,
        source_type="fault_ratio_precedent",
    )
    display_warnings = top_item.get("display_warnings") or []
    text_values_to_check = [
        record.get("query_text"),
        record.get("ratio_range_label"),
        top_item.get("title"),
        top_item.get("summary"),
        top_item.get("ratio_label"),
        precedent_item.get("title"),
        precedent_item.get("summary"),
    ]

    return {
        "run_index": record.get("run_index"),
        "session_id": record.get("session_id"),
        "message_id": record.get("message_id"),
        "job_id": record.get("job_id"),
        "query_preview": preview_text(record.get("query_text"), max_len=90),
        "contract_version": result.get("contract_version") or "",
        "status": record.get("status"),
        "evidence_count": int(record.get("evidence_count") or 0),
        "review_case_evidence_count": int(source_counts.get("review_case") or 0),
        "fault_ratio_precedent_evidence_count": int(source_counts.get("fault_ratio_precedent") or 0),
        "similar_case_count": int(record.get("similar_case_count") or 0),
        "display_evidence_count": int(record.get("display_evidence_count") or 0),
        "ratio_range_label": record.get("ratio_range_label") or "",
        "insurer_claim_review_exists": bool(record.get("insurer_claim_review_exists")),
        "top_source_type": top_item.get("source_type") or "",
        "top_source_reference": top_item.get("source_reference") or "",
        "top_title": top_item.get("title") or "",
        "top_ratio_label": top_item.get("ratio_label") or "",
        "top_summary_preview": preview_text(top_item.get("summary"), max_len=120),
        "top_review_title": review_item.get("title") or "",
        "top_review_source_reference": review_item.get("source_reference") or "",
        "top_review_ratio_label": review_item.get("ratio_label") or "",
        "top_precedent_title": precedent_item.get("title") or "",
        "top_precedent_source_reference": precedent_item.get("source_reference") or "",
        "top_precedent_case_number": precedent_item.get("case_number") or "",
        "top_precedent_court_name": precedent_item.get("court_name") or "",
        "top_precedent_decision_date": precedent_item.get("decision_date") or "",
        "top_precedent_ratio_label": precedent_item.get("ratio_label") or "",
        "top_precedent_summary_preview": preview_text(precedent_item.get("summary"), max_len=180),
        "top_precedent_matched_snippets_preview": preview_list(
            precedent_item.get("matched_snippets"),
            max_items=2,
            max_len=160,
        ),
        "display_warning_count": len(display_warnings),
        "display_warnings": display_warnings,
        "encoding_review_recommended": any(
            looks_like_encoding_issue(value) for value in text_values_to_check
        ),
        "source_summary": source_summary,
        "limitation_count": len(result.get("limitations") or []),
        "next_action_count": len(result.get("next_actions") or []),
        "structured_keys": sorted((structured or {}).keys()),
    }


def build_report(summary: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    record_reports = [collect_record_report(record) for record in records]
    not_success = [item for item in record_reports if item["status"] != "success"]
    zero_evidence = [item for item in record_reports if item["evidence_count"] == 0]
    zero_review_case = [item for item in record_reports if item["review_case_evidence_count"] == 0]
    zero_precedent = [
        item for item in record_reports if item["fault_ratio_precedent_evidence_count"] == 0
    ]
    missing_ratio = [item for item in record_reports if not item["ratio_range_label"]]
    display_warnings = [item for item in record_reports if item["display_warning_count"] > 0]
    encoding_reviews = [item for item in record_reports if item["encoding_review_recommended"]]
    non_v2_contract = [
        item for item in record_reports if item["contract_version"] != "text_ml_case_search_v2"
    ]

    all_success = not not_success
    has_evidence_for_all = not zero_evidence
    has_display_for_all = all(item["display_evidence_count"] > 0 for item in record_reports)
    has_both_sources_for_all = not zero_review_case and not zero_precedent
    has_v2_contract_for_all = not non_v2_contract

    conclusion = (
        "PASS: active 10 inputs returned stable Agent V2 JSON with both review_case "
        "and fault_ratio_precedent evidence."
        if all_success
        and has_evidence_for_all
        and has_display_for_all
        and has_both_sources_for_all
        and has_v2_contract_for_all
        else "REVIEW: one or more active inputs need follow-up before locking V2 behavior."
    )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_summary": summary,
        "record_count": len(record_reports),
        "status_counts": summary.get("status_counts") or {},
        "total_evidence_count": summary.get("total_evidence_count", 0),
        "total_review_case_evidence_count": summary.get("total_review_case_evidence_count", 0),
        "total_fault_ratio_precedent_evidence_count": summary.get(
            "total_fault_ratio_precedent_evidence_count", 0
        ),
        "total_similar_case_count": summary.get("total_similar_case_count", 0),
        "total_display_evidence_count": summary.get("total_display_evidence_count", 0),
        "zero_evidence_count": summary.get("zero_evidence_count", 0),
        "checks": {
            "all_success": all_success,
            "has_evidence_for_all": has_evidence_for_all,
            "has_display_evidence_for_all": has_display_for_all,
            "has_both_sources_for_all": has_both_sources_for_all,
            "has_v2_contract_for_all": has_v2_contract_for_all,
            "not_success_run_indexes": [item["run_index"] for item in not_success],
            "zero_evidence_run_indexes": [item["run_index"] for item in zero_evidence],
            "zero_review_case_run_indexes": [item["run_index"] for item in zero_review_case],
            "zero_fault_ratio_precedent_run_indexes": [
                item["run_index"] for item in zero_precedent
            ],
            "missing_ratio_run_indexes": [item["run_index"] for item in missing_ratio],
            "display_warning_run_indexes": [item["run_index"] for item in display_warnings],
            "encoding_review_run_indexes": [item["run_index"] for item in encoding_reviews],
            "non_v2_contract_run_indexes": [item["run_index"] for item in non_v2_contract],
        },
        "conclusion": conclusion,
        "records": record_reports,
    }


def markdown_table_row(values: list[Any]) -> str:
    return "| " + " | ".join(str(value).replace("\n", " ") for value in values) + " |"


def build_markdown_report(report: dict[str, Any]) -> str:
    source_summary = report.get("source_summary") or {}
    checks = report.get("checks") or {}
    records = report.get("records") or []

    lines: list[str] = [
        "# text_ml_case_search active 10 실행 결과 보고서",
        "",
        "## 목적",
        "",
        "active 10개 full optional input을 unified pgvector RAG와 연결해 실행하고, "
        "Agent V2 출력 JSON이 Supervisor가 받을 수 있는 형태로 안정적으로 생성되는지 확인한다.",
        "",
        "이번 확인의 핵심은 `review_case` 심의사례 근거와 "
        "`fault_ratio_precedent` 과실비율 판례 근거가 같은 output schema 안에 함께 들어오는지이다.",
        "",
        "## 입력 및 산출물",
        "",
        markdown_table_row(["항목", "경로"]),
        markdown_table_row(["---", "---"]),
        markdown_table_row(["입력 JSONL", source_summary.get("input_path", "")]),
        markdown_table_row(["Agent 출력 JSONL", source_summary.get("output_path", "")]),
        markdown_table_row(["검색 입력 variant", source_summary.get("search_variant", "")]),
        "",
        "## 전체 요약",
        "",
        markdown_table_row(["항목", "값"]),
        markdown_table_row(["---", "---"]),
        markdown_table_row(["생성 시각", report.get("created_at", "")]),
        markdown_table_row(["active input 수", source_summary.get("active_input_count", report.get("record_count", 0))]),
        markdown_table_row(["status_counts", json.dumps(report.get("status_counts", {}), ensure_ascii=False)]),
        markdown_table_row(["evidence 총합", report.get("total_evidence_count", 0)]),
        markdown_table_row(["review_case evidence 총합", report.get("total_review_case_evidence_count", 0)]),
        markdown_table_row([
            "fault_ratio_precedent evidence 총합",
            report.get("total_fault_ratio_precedent_evidence_count", 0),
        ]),
        markdown_table_row(["similar_cases 총합", report.get("total_similar_case_count", 0)]),
        markdown_table_row(["display_evidence 총합", report.get("total_display_evidence_count", 0)]),
        markdown_table_row(["zero_evidence_count", report.get("zero_evidence_count", 0)]),
        markdown_table_row(["결론", report.get("conclusion", "")]),
        "",
        "## 케이스별 결과",
        "",
        markdown_table_row([
            "run",
            "contract",
            "status",
            "evidence",
            "review",
            "precedent",
            "display",
            "ratio",
            "top_review_reference",
            "top_precedent_reference",
            "top_precedent_case",
        ]),
        markdown_table_row(["---", "---", "---", "---:", "---:", "---:", "---:", "---", "---", "---", "---"]),
    ]

    for item in records:
        lines.append(
            markdown_table_row([
                item.get("run_index", ""),
                item.get("contract_version", ""),
                item.get("status", ""),
                item.get("evidence_count", 0),
                item.get("review_case_evidence_count", 0),
                item.get("fault_ratio_precedent_evidence_count", 0),
                item.get("display_evidence_count", 0),
                preview_text(item.get("ratio_range_label"), max_len=45),
                preview_text(item.get("top_review_source_reference"), max_len=55),
                preview_text(item.get("top_precedent_source_reference"), max_len=55),
                preview_text(item.get("top_precedent_case_number"), max_len=30),
            ])
        )

    lines.extend([
        "",
        "## 판례 대표 근거 확인",
        "",
        "아래 표는 각 run에서 `fault_ratio_precedent` source_type으로 들어온 대표 판례 근거를 따로 보여준다. "
        "기존 보고서에서 판례가 안 보였던 이유는 첫 번째 display_evidence만 표기했기 때문이며, "
        "병합 순서상 review_case가 먼저 표시됐기 때문이다.",
        "",
        markdown_table_row([
            "run",
            "case_number",
            "court",
            "decision_date",
            "precedent_reference",
            "precedent_title",
            "summary",
            "matched_snippets",
        ]),
        markdown_table_row(["---", "---", "---", "---", "---", "---", "---", "---"]),
    ])

    for item in records:
        lines.append(
            markdown_table_row([
                item.get("run_index", ""),
                item.get("top_precedent_case_number", ""),
                item.get("top_precedent_court_name", ""),
                item.get("top_precedent_decision_date", ""),
                preview_text(item.get("top_precedent_source_reference"), max_len=70),
                preview_text(item.get("top_precedent_title"), max_len=50),
                preview_text(item.get("top_precedent_summary_preview"), max_len=120),
                preview_text(item.get("top_precedent_matched_snippets_preview"), max_len=160),
            ])
        )

    lines.extend([
        "",
        "## 안전 점검",
        "",
        markdown_table_row(["점검 항목", "결과"]),
        markdown_table_row(["---", "---"]),
        markdown_table_row(["전체 success 여부", checks.get("all_success")]),
        markdown_table_row(["모든 입력 evidence 보유", checks.get("has_evidence_for_all")]),
        markdown_table_row(["모든 입력 display_evidence 보유", checks.get("has_display_evidence_for_all")]),
        markdown_table_row(["모든 입력 양쪽 source 보유", checks.get("has_both_sources_for_all")]),
        markdown_table_row(["모든 입력 V2 계약 버전", checks.get("has_v2_contract_for_all")]),
        markdown_table_row(["success 아닌 run", checks.get("not_success_run_indexes", [])]),
        markdown_table_row(["evidence 0개 run", checks.get("zero_evidence_run_indexes", [])]),
        markdown_table_row(["review_case 0개 run", checks.get("zero_review_case_run_indexes", [])]),
        markdown_table_row(["fault_ratio_precedent 0개 run", checks.get("zero_fault_ratio_precedent_run_indexes", [])]),
        markdown_table_row(["ratio 없음 run", checks.get("missing_ratio_run_indexes", [])]),
        markdown_table_row(["display warning run", checks.get("display_warning_run_indexes", [])]),
        markdown_table_row(["인코딩 점검 필요 run", checks.get("encoding_review_run_indexes", [])]),
        markdown_table_row(["V2 계약 아닌 run", checks.get("non_v2_contract_run_indexes", [])]),
        "",
        "## 해석",
        "",
        "- `review_case`와 `fault_ratio_precedent`가 모두 1개 이상이면 V2 통합 RAG가 실제 Agent 출력에 반영된 것이다.",
        "- `evidence_count`는 최종 병합 결과이며, 기본 전략은 5+5 source quota, final_top_k=10이다.",
        "- cosine similarity는 source 간 직접 비교 기준이 아니다. V2는 source별 quota로 병합해 두 근거 유형을 함께 노출한다.",
        "- 특정 run에서 한쪽 source가 0개라면 검색 실패라기보다 해당 질의에서 해당 source의 후보가 부족했거나 validator에서 제거됐을 수 있다.",
        "",
        "## 다음 단계",
        "",
        "1. 상위 display_evidence가 사용자에게 보여줄 근거로 충분한지 샘플 검수한다.",
        "2. Supervisor 계약 V2 문서의 source_summary와 multi-source evidence 설명에 맞게 실제 연결한다.",
        "3. 추후 traffic_precedent 또는 standard 인정기준 확장 여부를 결정한다.",
    ])

    return "\n".join(lines) + "\n"


def write_report(
    *,
    outputs_jsonl: Path = DEFAULT_OUTPUTS_JSONL,
    summary_json: Path = DEFAULT_SUMMARY_JSON,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
) -> dict[str, Any]:
    summary = load_json(summary_json)
    records = load_jsonl(outputs_jsonl)
    report = build_report(summary, records)

    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(build_markdown_report(report), encoding="utf-8")

    return {
        "report_json": str(report_json),
        "report_md": str(report_md),
        "record_count": report["record_count"],
        "conclusion": report["conclusion"],
        "checks": report["checks"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build JSON and MD reports for active full optional Agent outputs.",
    )
    parser.add_argument("--outputs-jsonl", default=str(DEFAULT_OUTPUTS_JSONL))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT_MD))
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    result = write_report(
        outputs_jsonl=Path(args.outputs_jsonl),
        summary_json=Path(args.summary_json),
        report_json=Path(args.report_json),
        report_md=Path(args.report_md),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
