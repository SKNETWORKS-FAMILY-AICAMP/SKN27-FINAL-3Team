from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from etl.fault_cases.src.review_case.db_loading.db_config import RETRIEVAL_AB_EXPORT_ROOT, REVIEW_CASE_MD_ROOT


DEFAULT_SCORE_PATH = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_reranker_scores.jsonl"
DEFAULT_SUMMARY_PATH = RETRIEVAL_AB_EXPORT_ROOT / "review_case_retrieval_ab_score_summary.json"
DEFAULT_SCORE_MD_PATH = REVIEW_CASE_MD_ROOT / "심의사례 검색 A-B 정량 점수표.md"
DEFAULT_REPORT_MD_PATH = REVIEW_CASE_MD_ROOT / "심의사례 검색 A-B 평가 결과 보고서.md"


@dataclass(frozen=True)
class GroupMetrics:
    count: int
    top1_score: float | None
    avg_score_at_5: float
    max_score_at_5: float
    min_score_at_5: float
    std_score_at_5: float
    top_chunk_type: str | None
    reference_chart_top1_hit: bool | None
    reference_chart_hit_at_5: bool | None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def group_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in keys)].append(row)
    return grouped


def expected_chart_hit(row: dict[str, Any]) -> bool | None:
    expected = row.get("expected_reference_chart_key")
    if not expected:
        return None
    return row.get("reference_chart_key") == expected


def compute_metrics(rows: list[dict[str, Any]]) -> GroupMetrics:
    sorted_rows = sorted(rows, key=lambda row: int(row.get("rank") or 9999))
    scores = [float(row["local_reranker_score"]) for row in sorted_rows]
    top1_row = next((row for row in sorted_rows if row.get("rank") == 1), None)
    top1 = float(top1_row["local_reranker_score"]) if top1_row else None
    chunk_counts = Counter(row.get("chunk_type") or "" for row in sorted_rows)
    top_chunk_type = chunk_counts.most_common(1)[0][0] if chunk_counts else None
    expected_hits = [expected_chart_hit(row) for row in sorted_rows]
    expected_hits = [hit for hit in expected_hits if hit is not None]

    return GroupMetrics(
        count=len(scores),
        top1_score=top1,
        avg_score_at_5=mean(scores) if scores else 0,
        max_score_at_5=max(scores) if scores else 0,
        min_score_at_5=min(scores) if scores else 0,
        std_score_at_5=pstdev(scores) if len(scores) > 1 else 0,
        top_chunk_type=top_chunk_type,
        reference_chart_top1_hit=expected_chart_hit(top1_row) if top1_row else None,
        reference_chart_hit_at_5=any(expected_hits) if expected_hits else None,
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    query_retriever_groups = group_rows(rows, ("query_id", "query", "retriever"))
    query_retriever_metrics = []
    for (query_id, query, retriever), group in sorted(query_retriever_groups.items()):
        metrics = compute_metrics(group)
        query_retriever_metrics.append(
            {
                "query_id": query_id,
                "query": query,
                "retriever": retriever,
                "count": metrics.count,
                "top1_score": metrics.top1_score,
                "avg_score_at_5": metrics.avg_score_at_5,
                "max_score_at_5": metrics.max_score_at_5,
                "min_score_at_5": metrics.min_score_at_5,
                "std_score_at_5": metrics.std_score_at_5,
                "top_chunk_type": metrics.top_chunk_type,
                "reference_chart_top1_hit": metrics.reference_chart_top1_hit,
                "reference_chart_hit_at_5": metrics.reference_chart_hit_at_5,
            }
        )

    retriever_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in query_retriever_metrics:
        retriever_groups[metric["retriever"]].append(metric)

    retriever_summary = []
    for retriever, metrics in sorted(retriever_groups.items()):
        top1_hit_values = [m["reference_chart_top1_hit"] for m in metrics if m["reference_chart_top1_hit"] is not None]
        hit_at_5_values = [m["reference_chart_hit_at_5"] for m in metrics if m["reference_chart_hit_at_5"] is not None]
        retriever_summary.append(
            {
                "retriever": retriever,
                "query_count": len(metrics),
                "candidate_count": sum(m["count"] for m in metrics),
                "avg_top1_score": mean(m["top1_score"] for m in metrics if m["top1_score"] is not None),
                "avg_score_at_5": mean(m["avg_score_at_5"] for m in metrics),
                "avg_max_score_at_5": mean(m["max_score_at_5"] for m in metrics),
                "avg_min_score_at_5": mean(m["min_score_at_5"] for m in metrics),
                "avg_std_score_at_5": mean(m["std_score_at_5"] for m in metrics),
                "reference_chart_top1_hit_rate": mean(top1_hit_values) if top1_hit_values else None,
                "reference_chart_hit_at_5_rate": mean(hit_at_5_values) if hit_at_5_values else None,
            }
        )

    winners_by_query = []
    for (query_id,), group in group_rows(query_retriever_metrics, ("query_id",)).items():
        winner = max(group, key=lambda row: row["avg_score_at_5"])
        winners_by_query.append(
            {
                "query_id": query_id,
                "query": winner["query"],
                "winner_retriever": winner["retriever"],
                "winner_avg_score_at_5": winner["avg_score_at_5"],
                "winner_top1_score": winner["top1_score"],
            }
        )

    chunk_type_counts = Counter(row.get("chunk_type") or "" for row in rows)
    chunk_type_by_retriever: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        chunk_type_by_retriever[row["retriever"]][row.get("chunk_type") or ""] += 1

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(rows),
        "query_count": len({row["query_id"] for row in rows}),
        "retriever_count": len({row["retriever"] for row in rows}),
        "top_k": max(int(row.get("rank") or 0) for row in rows) if rows else 0,
        "reranker_model": rows[0].get("reranker_model") if rows else None,
        "reranker_input_field": rows[0].get("reranker_input_field") if rows else None,
        "retriever_summary": retriever_summary,
        "query_retriever_metrics": query_retriever_metrics,
        "winners_by_query": winners_by_query,
        "winner_counts": dict(Counter(row["winner_retriever"] for row in winners_by_query)),
        "chunk_type_counts": dict(chunk_type_counts),
        "chunk_type_counts_by_retriever": {
            retriever: dict(counter)
            for retriever, counter in sorted(chunk_type_by_retriever.items())
        },
    }


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def build_score_markdown(summary: dict[str, Any]) -> str:
    retriever_rows = [
        [
            row["retriever"],
            str(row["query_count"]),
            str(row["candidate_count"]),
            fmt(row["avg_top1_score"]),
            fmt(row["avg_score_at_5"]),
            fmt(row["avg_max_score_at_5"]),
            fmt(row["avg_min_score_at_5"]),
            fmt(row["avg_std_score_at_5"]),
            pct(row["reference_chart_top1_hit_rate"]),
            pct(row["reference_chart_hit_at_5_rate"]),
        ]
        for row in summary["retriever_summary"]
    ]
    query_rows = [
        [
            row["query_id"],
            row["query"],
            row["retriever"],
            fmt(row["top1_score"]),
            fmt(row["avg_score_at_5"]),
            fmt(row["max_score_at_5"]),
            row["top_chunk_type"] or "",
            str(row["reference_chart_top1_hit"]),
            str(row["reference_chart_hit_at_5"]),
        ]
        for row in summary["query_retriever_metrics"]
    ]
    winner_rows = [
        [
            row["query_id"],
            row["query"],
            row["winner_retriever"],
            fmt(row["winner_avg_score_at_5"]),
            fmt(row["winner_top1_score"]),
        ]
        for row in summary["winners_by_query"]
    ]
    chunk_type_rows = [
        [chunk_type, str(count)]
        for chunk_type, count in sorted(summary["chunk_type_counts"].items())
    ]

    return "\n\n".join(
        [
            "# 심의사례 검색 A-B 정량 점수표",
            f"생성일시: {summary['created_at']}",
            f"reranker_model: `{summary['reranker_model']}`",
            f"reranker_input_field: `{summary['reranker_input_field']}`",
            "## 1. 평가 개요",
            "\n".join(
                [
                    f"- query_count: {summary['query_count']}",
                    f"- retriever_count: {summary['retriever_count']}",
                    f"- top_k: {summary['top_k']}",
                    f"- candidate_count: {summary['candidate_count']}",
                    "- 후보 수 계산: 5 queries x 4 retrievers x top5 = 100 candidates",
                ]
            ),
            "## 2. Retriever별 평균 점수",
            md_table(
                [
                    "Retriever",
                    "Query Count",
                    "Candidate Count",
                    "Avg Top1",
                    "Avg@5",
                    "Avg Max@5",
                    "Avg Min@5",
                    "Avg Std@5",
                    "Chart Top1 Hit",
                    "Chart Hit@5",
                ],
                retriever_rows,
            ),
            "## 3. Query별 Retriever 점수",
            md_table(
                [
                    "Query ID",
                    "Query",
                    "Retriever",
                    "Top1",
                    "Avg@5",
                    "Max@5",
                    "Top Chunk Type",
                    "Chart Top1",
                    "Chart@5",
                ],
                query_rows,
            ),
            "## 4. Query별 Winner",
            md_table(["Query ID", "Query", "Winner", "Winner Avg@5", "Winner Top1"], winner_rows),
            "## 5. 전체 Chunk Type 분포",
            md_table(["Chunk Type", "Count"], chunk_type_rows),
        ]
    )


def build_report_markdown(summary: dict[str, Any]) -> str:
    best_by_avg = max(summary["retriever_summary"], key=lambda row: row["avg_score_at_5"])
    best_by_top1 = max(summary["retriever_summary"], key=lambda row: row["avg_top1_score"])
    winner_rows = [[retriever, str(count)] for retriever, count in sorted(summary["winner_counts"].items())]
    chunk_by_retriever_rows = []
    for retriever, counts in summary["chunk_type_counts_by_retriever"].items():
        chunk_by_retriever_rows.append(
            [
                retriever,
                str(counts.get("case_overview", 0)),
                str(counts.get("arguments", 0)),
                str(counts.get("evidence_issue", 0)),
                str(counts.get("decision", 0)),
            ]
        )

    return "\n\n".join(
        [
            "# 심의사례 검색 A-B 평가 결과 보고서",
            f"생성일시: {summary['created_at']}",
            "## 1. 실험 개요",
            "\n".join(
                [
                    f"- 후보 수: {summary['candidate_count']}",
                    f"- query 수: {summary['query_count']}",
                    f"- retriever 수: {summary['retriever_count']}",
                    f"- top_k: {summary['top_k']}",
                    f"- reranker_model: `{summary['reranker_model']}`",
                    f"- reranker_input_field: `{summary['reranker_input_field']}`",
                ]
            ),
            "## 2. 왜 후보가 100개인가",
            "\n".join(
                [
                    "현재 실험은 최종 평가가 아니라 smoke evaluation이다.",
                    "5개 심의사례 샘플 query를 4개 retriever가 각각 top5로 검색했기 때문에 후보 수는 100개다.",
                    "",
                    "```text",
                    "5 queries x 4 retrievers x top5 = 100 candidates",
                    "```",
                    "",
                    "여기서 4개 retriever는 실험 분석 관점의 구분이다. 서비스 후보 관점에서는 pgvector, BM25/Nori, hybrid의 3개 축으로 볼 수 있고, Elasticsearch vector는 hybrid 구성요소를 검증하기 위한 중간 비교군이다.",
                ]
            ),
            "## 3. 전체 결과 요약",
            "\n".join(
                [
                    f"- Avg@5 기준 1위: `{best_by_avg['retriever']}` ({fmt(best_by_avg['avg_score_at_5'])})",
                    f"- Top1 기준 1위: `{best_by_top1['retriever']}` ({fmt(best_by_top1['avg_top1_score'])})",
                    "- retriever_score는 검색기 내부 점수이므로 직접 비교하지 않았다.",
                    "- 공통 비교 점수는 local_reranker_score를 사용했다.",
                ]
            ),
            "## 4. Query별 Winner 수",
            md_table(["Retriever", "Winner Count"], winner_rows),
            "## 5. Chunk Type 관점 분석",
            md_table(["Retriever", "case_overview", "arguments", "evidence_issue", "decision"], chunk_by_retriever_rows),
            "## 6. 해석 기준",
            "\n".join(
                [
                    "- BM25/Nori는 신호위반, 중앙선 침범, 참고기준 번호처럼 명시 키워드가 강한 질의에서 유리할 수 있다.",
                    "- pgvector와 Elasticsearch vector는 사용자 표현이 문서 표현과 달라도 의미가 가까운 후보를 찾는 데 유리할 수 있다.",
                    "- hybrid는 BM25와 vector가 동시에 상위권으로 찾은 후보를 RRF로 올리는 방식이다.",
                    "- case_overview는 검색에는 강하지만, 답변 근거로는 decision chunk 보강이 필요할 수 있다.",
                ]
            ),
            "## 7. 다음 검토 사항",
            "\n".join(
                [
                    "1. query별 winner 후보의 chunk_preview를 사람이 확인한다.",
                    "2. case_overview가 top1일 때 같은 review_no의 decision chunk 보강 규칙이 필요한지 확인한다.",
                    "3. query set을 30개 이상으로 확장한다.",
                    "4. RRF k=10/30/60 비교는 후속 실험으로 분리한다.",
                ]
            ),
        ]
    )


def write_reports(
    score_path: Path = DEFAULT_SCORE_PATH,
    summary_path: Path = DEFAULT_SUMMARY_PATH,
    score_md_path: Path = DEFAULT_SCORE_MD_PATH,
    report_md_path: Path = DEFAULT_REPORT_MD_PATH,
) -> dict[str, Any]:
    rows = load_jsonl(score_path)
    summary = summarize(rows)

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    score_md_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    score_md_path.write_text(build_score_markdown(summary), encoding="utf-8")
    report_md_path.write_text(build_report_markdown(summary), encoding="utf-8")

    return {
        "summary_path": str(summary_path),
        "score_md_path": str(score_md_path),
        "report_md_path": str(report_md_path),
        **summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build review_case local reranker score reports.")
    parser.add_argument("--scores", type=Path, default=DEFAULT_SCORE_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--score-md", type=Path, default=DEFAULT_SCORE_MD_PATH)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD_PATH)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = write_reports(
        score_path=args.scores,
        summary_path=args.summary,
        score_md_path=args.score_md,
        report_md_path=args.report_md,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
