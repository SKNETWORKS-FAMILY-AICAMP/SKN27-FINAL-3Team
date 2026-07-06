from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from ..search_config import RETRIEVAL_AB_EXPORT_ROOT, ensure_parent


DEFAULT_SCORE_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_reranker_scores.jsonl"
DEFAULT_SUMMARY_PATH = RETRIEVAL_AB_EXPORT_ROOT / "retrieval_ab_score_summary.json"
DEFAULT_MD_DIR = Path("etl/fault_cases/Fault_cases_MD/판례")
DEFAULT_SCORE_MD_PATH = DEFAULT_MD_DIR / "판례 검색 A-B 정량 점수표.md"
DEFAULT_REPORT_MD_PATH = DEFAULT_MD_DIR / "판례 검색 A-B 평가 결과 보고서.md"


@dataclass(frozen=True)
class GroupMetrics:
    count: int
    top1_score: float | None
    avg_score_at_5: float
    max_score_at_5: float
    min_score_at_5: float
    std_score_at_5: float
    top_chunk_type: str | None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
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


def group_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(key) for key in keys)].append(row)
    return grouped


def compute_metrics(rows: list[dict[str, Any]]) -> GroupMetrics:
    sorted_rows = sorted(rows, key=lambda row: int(row.get("rank") or 9999))
    scores = [float(row["local_reranker_score"]) for row in sorted_rows]
    top1 = next((float(row["local_reranker_score"]) for row in sorted_rows if row.get("rank") == 1), None)
    chunk_counts = Counter(row.get("chunk_type") or "" for row in sorted_rows)
    top_chunk_type = chunk_counts.most_common(1)[0][0] if chunk_counts else None
    return GroupMetrics(
        count=len(scores),
        top1_score=top1,
        avg_score_at_5=mean(scores) if scores else 0,
        max_score_at_5=max(scores) if scores else 0,
        min_score_at_5=min(scores) if scores else 0,
        std_score_at_5=pstdev(scores) if len(scores) > 1 else 0,
        top_chunk_type=top_chunk_type,
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    query_retriever_groups = group_rows(rows, ("query_id", "dataset", "query", "retriever"))
    query_retriever_metrics = []
    for (query_id, dataset, query, retriever), group in sorted(query_retriever_groups.items()):
        metrics = compute_metrics(group)
        query_retriever_metrics.append(
            {
                "query_id": query_id,
                "dataset": dataset,
                "query": query,
                "retriever": retriever,
                "count": metrics.count,
                "top1_score": metrics.top1_score,
                "avg_score_at_5": metrics.avg_score_at_5,
                "max_score_at_5": metrics.max_score_at_5,
                "min_score_at_5": metrics.min_score_at_5,
                "std_score_at_5": metrics.std_score_at_5,
                "top_chunk_type": metrics.top_chunk_type,
            }
        )

    retriever_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dataset_retriever_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for metric in query_retriever_metrics:
        retriever_groups[metric["retriever"]].append(metric)
        dataset_retriever_groups[(metric["dataset"], metric["retriever"])].append(metric)

    retriever_summary = []
    for retriever, metrics in sorted(retriever_groups.items()):
        retriever_summary.append(
            {
                "retriever": retriever,
                "query_count": len(metrics),
                "avg_top1_score": mean(m["top1_score"] for m in metrics if m["top1_score"] is not None),
                "avg_score_at_5": mean(m["avg_score_at_5"] for m in metrics),
                "avg_max_score_at_5": mean(m["max_score_at_5"] for m in metrics),
                "avg_min_score_at_5": mean(m["min_score_at_5"] for m in metrics),
                "avg_std_score_at_5": mean(m["std_score_at_5"] for m in metrics),
            }
        )

    dataset_retriever_summary = []
    for (dataset, retriever), metrics in sorted(dataset_retriever_groups.items()):
        dataset_retriever_summary.append(
            {
                "dataset": dataset,
                "retriever": retriever,
                "query_count": len(metrics),
                "avg_top1_score": mean(m["top1_score"] for m in metrics if m["top1_score"] is not None),
                "avg_score_at_5": mean(m["avg_score_at_5"] for m in metrics),
                "avg_max_score_at_5": mean(m["max_score_at_5"] for m in metrics),
                "avg_min_score_at_5": mean(m["min_score_at_5"] for m in metrics),
            }
        )

    winners_by_query = []
    for query_id, group in group_rows(query_retriever_metrics, ("query_id",)).items():
        winner = max(group, key=lambda row: row["avg_score_at_5"])
        winners_by_query.append(
            {
                "query_id": query_id[0],
                "dataset": winner["dataset"],
                "query": winner["query"],
                "winner_retriever": winner["retriever"],
                "winner_avg_score_at_5": winner["avg_score_at_5"],
                "winner_top1_score": winner["top1_score"],
            }
        )

    chunk_type_counts = Counter(row.get("chunk_type") or "" for row in rows)

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(rows),
        "query_count": len({row["query_id"] for row in rows}),
        "retriever_count": len({row["retriever"] for row in rows}),
        "reranker_model": rows[0].get("reranker_model") if rows else None,
        "reranker_input_field": rows[0].get("reranker_input_field") if rows else None,
        "retriever_summary": retriever_summary,
        "dataset_retriever_summary": dataset_retriever_summary,
        "query_retriever_metrics": query_retriever_metrics,
        "winners_by_query": winners_by_query,
        "winner_counts": dict(Counter(row["winner_retriever"] for row in winners_by_query)),
        "chunk_type_counts": dict(chunk_type_counts),
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
            fmt(row["avg_top1_score"]),
            fmt(row["avg_score_at_5"]),
            fmt(row["avg_max_score_at_5"]),
            fmt(row["avg_min_score_at_5"]),
            fmt(row["avg_std_score_at_5"]),
        ]
        for row in summary["retriever_summary"]
    ]
    dataset_rows = [
        [
            row["dataset"],
            row["retriever"],
            str(row["query_count"]),
            fmt(row["avg_top1_score"]),
            fmt(row["avg_score_at_5"]),
            fmt(row["avg_max_score_at_5"]),
            fmt(row["avg_min_score_at_5"]),
        ]
        for row in summary["dataset_retriever_summary"]
    ]
    query_rows = [
        [
            row["query_id"],
            row["dataset"],
            row["query"],
            row["retriever"],
            fmt(row["top1_score"]),
            fmt(row["avg_score_at_5"]),
            fmt(row["max_score_at_5"]),
            row["top_chunk_type"] or "",
        ]
        for row in summary["query_retriever_metrics"]
    ]
    winner_rows = [
        [
            row["query_id"],
            row["dataset"],
            row["query"],
            row["winner_retriever"],
            fmt(row["winner_avg_score_at_5"]),
            fmt(row["winner_top1_score"]),
        ]
        for row in summary["winners_by_query"]
    ]

    return "\n\n".join(
        [
            "# 판례 검색 A-B 정량 점수표",
            f"생성일: {summary['created_at']}",
            f"reranker_model: `{summary['reranker_model']}`",
            f"reranker_input_field: `{summary['reranker_input_field']}`",
            "## 전체 평균",
            md_table(
                ["Retriever", "Query Count", "Avg Top1", "Avg@5", "Avg Max@5", "Avg Min@5", "Avg Std@5"],
                retriever_rows,
            ),
            "## Dataset별 평균",
            md_table(
                ["Dataset", "Retriever", "Query Count", "Avg Top1", "Avg@5", "Avg Max@5", "Avg Min@5"],
                dataset_rows,
            ),
            "## Query별 점수",
            md_table(
                ["Query ID", "Dataset", "Query", "Retriever", "Top1", "Avg@5", "Max@5", "Top Chunk Type"],
                query_rows,
            ),
            "## Query별 Winner",
            md_table(
                ["Query ID", "Dataset", "Query", "Winner", "Winner Avg@5", "Winner Top1"],
                winner_rows,
            ),
        ]
    )


def build_report_markdown(summary: dict[str, Any]) -> str:
    best_by_avg = max(summary["retriever_summary"], key=lambda row: row["avg_score_at_5"])
    best_by_top1 = max(summary["retriever_summary"], key=lambda row: row["avg_top1_score"])
    winner_counts = summary["winner_counts"]
    winner_rows = [[retriever, str(count)] for retriever, count in sorted(winner_counts.items())]
    chunk_rows = [[chunk_type, str(count)] for chunk_type, count in sorted(summary["chunk_type_counts"].items())]

    return "\n\n".join(
        [
            "# 판례 검색 A-B 평가 결과 보고서",
            f"생성일: {summary['created_at']}",
            "## 실험 개요",
            "\n".join(
                [
                    f"- 후보 수: {summary['candidate_count']}",
                    f"- query 수: {summary['query_count']}",
                    f"- retriever 수: {summary['retriever_count']}",
                    f"- reranker_model: `{summary['reranker_model']}`",
                    f"- reranker_input_field: `{summary['reranker_input_field']}`",
                ]
            ),
            "## 전체 결과 요약",
            "\n".join(
                [
                    f"- Avg@5 기준 1위: `{best_by_avg['retriever']}` ({fmt(best_by_avg['avg_score_at_5'])})",
                    f"- Top1 기준 1위: `{best_by_top1['retriever']}` ({fmt(best_by_top1['avg_top1_score'])})",
                    "- reranker는 검색 결과를 재정렬하지 않고 평가 점수만 부여했다.",
                    "- retriever_score는 검색기 내부 점수이므로 직접 비교하지 않았다.",
                ]
            ),
            "## Query별 Winner 수",
            md_table(["Retriever", "Winner Count"], winner_rows),
            "## Chunk Type 분포",
            md_table(["Chunk Type", "Count"], chunk_rows),
            "## 해석 기준",
            "\n".join(
                [
                    "- BM25/Nori는 명시 키워드가 강한 질의에서 유리할 수 있다.",
                    "- vector 계열은 표현이 달라도 의미가 가까운 후보를 찾는 데 유리할 수 있다.",
                    "- hybrid는 BM25와 vector 양쪽에서 함께 잡힌 후보를 RRF로 우대한다.",
                    "- metadata chunk가 많이 이기는 경우, 법리 설명 근거로 충분한지 별도 검수가 필요하다.",
                ]
            ),
            "## 다음 검수 항목",
            "\n".join(
                [
                    "1. query별 winner 후보의 chunk_preview를 사람이 확인한다.",
                    "2. metadata chunk가 실제 답변 근거로 충분한지 확인한다.",
                    "3. 필요하면 query set을 20개 이상으로 확장한다.",
                    "4. RRF k=10/30/60 비교를 후속 실험으로 진행한다.",
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

    ensure_parent(summary_path)
    ensure_parent(score_md_path)
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
    parser = argparse.ArgumentParser(description="Build markdown and JSON summaries for local reranker A/B scores.")
    parser.add_argument("--scores", type=Path, default=DEFAULT_SCORE_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--score-md", type=Path, default=DEFAULT_SCORE_MD_PATH)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD_PATH)
    return parser.parse_args()


def main() -> None:
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
