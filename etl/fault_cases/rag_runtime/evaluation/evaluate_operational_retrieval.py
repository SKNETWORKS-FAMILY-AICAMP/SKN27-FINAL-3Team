"""운영 `rag_qwen4` 인덱스의 공통 50문항 검색 품질을 평가한다.

이 평가는 새 DB에서 실제 cosine 검색을 수행한다. 따라서 과거 AB 보고서의 숫자를
복사하지 않으며, 적재된 Qwen 4B 벡터·ID·사건 단위 중복 제거가 정상인지 함께 검증한다.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from etl.fault_cases.rag_runtime.shared.qwen4_retrieval import (
    FAULT_CASES_ROOT,
    precomputed_query_vectors,
    search_by_vector,
)


# 공통 50문항과 세 승인 정답지의 경로·정답 식별자 필드를 한 계약으로 고정한다.
QUERY_PATH = FAULT_CASES_ROOT / "evaluation/common/embedding_ab/v1/common_fault_queries_v1.jsonl"
QREL_PATHS = {
    "fault_standard": (
        FAULT_CASES_ROOT / "evaluation/fault_standard/embedding_ab/v1/ground_truth/fault_standard_qrels_v1.2.jsonl",
        "rule_id",
    ),
    "review_case": (
        FAULT_CASES_ROOT / "evaluation/review_case/embedding_ab/v1/ground_truth/review_case_qrels_v1.jsonl",
        "review_case_id",
    ),
    "precedent": (
        FAULT_CASES_ROOT / "evaluation/precedent/embedding_ab/v1/ground_truth/precedent_qrels_v1.jsonl",
        "case_id",
    ),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """UTF-8 JSONL을 읽고 빈 줄은 제외한다."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dcg(relevances: list[int]) -> float:
    """검색 순서의 relevance 목록으로 DCG@10을 계산한다."""

    return sum((2**value - 1) / math.log2(index + 2) for index, value in enumerate(relevances[:10]))


def labels_for(corpus: str, query_ids: set[str]) -> tuple[dict[str, dict[str, int]], set[str]]:
    """승인 정답지를 Query별 대상 ID·관련도와 무정답 집합으로 변환한다."""

    path, target_field = QREL_PATHS[corpus]
    labels: dict[str, dict[str, int]] = {}
    no_relevant: set[str] = set()
    for row in read_jsonl(path):
        query_id = str(row.get("query_id") or "")
        if not query_id:
            raise ValueError(f"{corpus}: qrels에 query_id가 없습니다.")
        if row.get("judgment_status") == "no_relevant_document":
            no_relevant.add(query_id)
            continue
        target_id = str(row.get(target_field) or "")
        relevance = int(row.get("relevance") or 0)
        if relevance > 0 and target_id:
            labels.setdefault(query_id, {})[target_id] = max(relevance, labels.setdefault(query_id, {}).get(target_id, 0))
    if set(labels).union(no_relevant) != query_ids:
        missing = sorted(query_ids.difference(set(labels).union(no_relevant)))
        extra = sorted(set(labels).union(no_relevant).difference(query_ids))
        raise ValueError(f"{corpus}: qrels 50문항 범위가 다릅니다. missing={missing[:3]}, extra={extra[:3]}")
    return labels, no_relevant


def evaluate(corpus: str, strategy: str) -> dict[str, Any]:
    """한 코퍼스·전략에 대해 실제 DB 검색과 Top-1/10/50 지표를 계산한다."""

    queries = read_jsonl(QUERY_PATH)
    if len(queries) != 50 or any(row.get("annotation_status") != "approved" for row in queries):
        raise ValueError("공식 공통 질문지 50개가 승인 상태가 아닙니다.")
    query_ids = {str(row["query_id"]) for row in queries}
    vectors = precomputed_query_vectors(corpus, strategy)
    if set(vectors) != query_ids:
        raise ValueError(f"{corpus}/{strategy}: Parquet 질의 벡터가 공식 50문항과 일치하지 않습니다.")
    labels, no_relevant = labels_for(corpus, query_ids)

    scored: list[dict[str, Any]] = []
    values: dict[str, list[float]] = {"hit1": [], "hit10": [], "top50_recall": [], "mrr10": [], "ndcg10": []}
    for query in queries:
        query_id = str(query["query_id"])
        # Top-50 평가를 위해 사건/사례 단위 고유 후보 50개를 실제 DB에서 만든다.
        rows = search_by_vector(corpus, vectors[query_id], top_k=50, candidate_k=500)
        if len(rows) < 50:
            raise ValueError(f"{corpus}/{strategy}: 고유 Top-50 후보가 부족합니다: {query_id}/{len(rows)}")
        relevant = labels.get(query_id, {})
        is_negative = query_id in no_relevant
        ranked_ids = [str(row["document_id"]) for row in rows]
        relevance_at_10 = [int(relevant.get(item, 0)) for item in ranked_ids[:10]]
        first_rank = next((index + 1 for index, item in enumerate(ranked_ids[:10]) if relevant.get(item, 0) > 0), None)
        top50_has = any(relevant.get(item, 0) > 0 for item in ranked_ids)
        ideal = dcg(sorted(relevant.values(), reverse=True))
        ndcg10 = None if is_negative else (dcg(relevance_at_10) / ideal if ideal else 0.0)
        record = {
            "query_id": query_id,
            "is_no_relevant_query": is_negative,
            "first_relevant_rank": first_rank,
            "top1_is_relevant": bool(first_rank == 1),
            "top10_has_relevant": first_rank is not None,
            "top50_has_relevant": top50_has,
            "mrr_at_10": None if is_negative else (1.0 / first_rank if first_rank else 0.0),
            "ndcg_at_10": ndcg10,
            "top10": [
                {
                    "rank": item["rank"],
                    "document_id": item["document_id"],
                    "chunk_id": item["chunk_id"],
                    "title": item["title"],
                    "cosine_similarity": item["cosine_similarity"],
                    "is_relevant": bool(relevant.get(str(item["document_id"]), 0) > 0),
                }
                for item in rows[:10]
            ],
        }
        scored.append(record)
        if not is_negative:
            values["hit1"].append(float(record["top1_is_relevant"]))
            values["hit10"].append(float(record["top10_has_relevant"]))
            values["top50_recall"].append(float(top50_has))
            values["mrr10"].append(float(record["mrr_at_10"]))
            values["ndcg10"].append(float(ndcg10))

    positive_count = len(values["hit1"])
    if not positive_count:
        raise ValueError(f"{corpus}: 평가 가능한 정답 질문이 없습니다.")
    metrics = {key: sum(value) / len(value) for key, value in values.items()}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus,
        "strategy": strategy,
        "query_count": len(queries),
        "positive_query_count": positive_count,
        "no_relevant_query_count": len(no_relevant),
        "metrics": metrics,
        "top10_success_count": int(sum(item["top10_has_relevant"] for item in scored if not item["is_no_relevant_query"])),
        "top10_failure_count": int(sum(not item["top10_has_relevant"] for item in scored if not item["is_no_relevant_query"])),
        "details": scored,
        "notice": "cosine_similarity는 벡터 방향 유사도이며, 정답 확률 또는 법률적 결론의 신뢰도는 아닙니다.",
    }


def write_report(result: dict[str, Any], path: Path) -> None:
    """기계 판독 JSON과 사람이 읽는 Markdown을 함께 기록한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = result["metrics"]
    lines = [
        f"# {result['corpus']} 운영 검색 평가 — {result['strategy']}",
        "",
        "| 지표 | 값 | 의미 |",
        "|---|---:|---|",
        f"| Hit@1 | {metrics['hit1']:.4f} | 정답 가능 질문에서 1위가 정답인 비율 |",
        f"| Hit@10 | {metrics['hit10']:.4f} | 정답 가능 질문에서 Top-10 안에 정답이 있는 비율 |",
        f"| Top-50 회수율 | {metrics['top50_recall']:.4f} | 정답 가능 질문에서 사건/사례 Top-50 안에 정답이 있는 비율 |",
        f"| MRR@10 | {metrics['mrr10']:.4f} | 첫 정답의 순위 역수 평균. 위에 있을수록 큼 |",
        f"| nDCG@10 | {metrics['ndcg10']:.4f} | 관련도와 순위를 함께 반영한 Top-10 품질 |",
        "",
        f"- 정답 가능 질문: {result['positive_query_count']}개",
        f"- Top-10 정답 성공/실패: {result['top10_success_count']}개 / {result['top10_failure_count']}개",
        f"- 무정답 통제 질문: {result['no_relevant_query_count']}개",
        "- 코사인 유사도는 검색 후보 간 의미적 근접성일 뿐, 정답 판정 기준으로 단독 사용하지 않는다.",
    ]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """명령행에서 한 코퍼스의 baseline 또는 B-4 운영 DB 평가를 실행한다."""

    parser = argparse.ArgumentParser(description="Qwen 4B 운영 검색 평가")
    parser.add_argument("--corpus", choices=sorted(QREL_PATHS), required=True)
    parser.add_argument("--strategy", choices=("baseline", "b4"), default="baseline")
    parser.add_argument("--report-path", required=True)
    args = parser.parse_args()
    if args.strategy == "b4" and args.corpus != "precedent":
        parser.error("B-4 전략은 판례 코퍼스에서만 사용할 수 있습니다.")
    result = evaluate(args.corpus, args.strategy)
    write_report(result, Path(args.report_path))
    print(f"운영 검색 평가 완료: {args.corpus}/{args.strategy}")


if __name__ == "__main__":
    main()
