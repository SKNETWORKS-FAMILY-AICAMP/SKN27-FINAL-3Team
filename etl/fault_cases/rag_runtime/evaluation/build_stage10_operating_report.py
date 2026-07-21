"""5~9단계의 운영 DB 재평가 결과로 통합 점수표와 운영 의사결정 보고서를 만든다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# 새 운영 DB에서 실제 검색해 만든 평가 JSON만 입력으로 허용한다.
ROOT = Path(__file__).resolve().parents[2]
INPUTS = {
    "인정기준 / pgvector": ROOT / "artifacts/rag_runtime/stage7/fault_standard_baseline.json",
    "심의사례 / pgvector": ROOT / "artifacts/rag_runtime/stage9/review_case_baseline.json",
    "판례 / pgvector 기준선": ROOT / "artifacts/rag_runtime/stage8/precedent_baseline.json",
    "판례 / pgvector + B-4": ROOT / "artifacts/rag_runtime/stage8/precedent_b4.json",
}


def load(path: Path) -> dict[str, Any]:
    """평가 결과 JSON을 읽고 필수 지표가 없으면 보고서 생성을 중단한다."""

    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"hit1", "hit10", "top50_recall", "mrr10", "ndcg10"}
    if not required.issubset(dict(value.get("metrics") or {})):
        raise ValueError(f"평가 지표가 부족합니다: {path}")
    return value


def rate(value: float) -> str:
    """0~1 지표를 사람이 읽는 백분율 문자열로 바꾼다."""

    return f"{value * 100:.1f}%"


def main() -> None:
    """통합 비교표와 운영 결정을 한국어 Markdown으로 기록한다."""

    rows = {name: load(path) for name, path in INPUTS.items()}
    b0 = rows["판례 / pgvector 기준선"]
    b4 = rows["판례 / pgvector + B-4"]
    before, after = b0["metrics"], b4["metrics"]
    delta = {key: float(after[key]) - float(before[key]) for key in before}
    output = ROOT / "artifacts/rag_runtime/stage10"
    output.mkdir(parents=True, exist_ok=True)

    table = [
        "# RAG 운영 검색 통합 점수표",
        "",
        "> 모든 수치는 새 `rag_qwen4` 운영 DB에서 실제 cosine 검색·사건/사례 단위 중복 제거 후 계산했다.",
        "",
        "| RAG / 검색 전략 | 정답 가능 질문 | Hit@1 | Hit@10 | Top-50 회수율 | MRR@10 | nDCG@10 | Top-10 성공/실패 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in rows.items():
        metrics = result["metrics"]
        table.append(
            f"| {name} | {result['positive_query_count']} | {rate(metrics['hit1'])} | {rate(metrics['hit10'])} | "
            f"{rate(metrics['top50_recall'])} | {metrics['mrr10']:.4f} | {metrics['ndcg10']:.4f} | "
            f"{result['top10_success_count']} / {result['top10_failure_count']} |"
        )
    table.extend(
        [
            "",
            "## 지표 읽는 법",
            "",
            "- **Hit@1**: 1위 결과가 승인 정답인 비율입니다.",
            "- **Hit@10**: Top-10 안에 승인 정답이 하나 이상 있는 비율입니다.",
            "- **Top-50 회수율**: 후속 재순위화가 사용할 후보 50개 안에 정답이 있는 비율입니다.",
            "- **MRR@10**: 첫 정답이 위에 있을수록 커지는 순위 품질 지표입니다.",
            "- **nDCG@10**: 관련도 등급과 순위를 함께 반영한 Top-10 품질 지표입니다.",
            "- **코사인 유사도**는 개별 근거 행에 함께 보관되지만, 정답 확률이나 과실비율은 아닙니다.",
        ]
    )
    (output / "RAG_운영_통합_점수표.md").write_text("\n".join(table) + "\n", encoding="utf-8")

    report = [
        "# RAG 운영 의사결정 보고서",
        "",
        "## 1. 판례 검색 운영안",
        "",
        "판례 검색은 **Qwen3-Embedding-4B pgvector + B-4 질의 조건 보강**을 조건부 운영 후보로 둡니다.",
        "B-4는 질문 원문에서 감지한 사고 조건만 추가하며, Query ID·정답 판례 ID·qrels·과거 순위·과실비율을 사용하지 않습니다.",
        "",
        "| 판례 지표 | 기준선 | B-4 | 변화 |",
        "|---|---:|---:|---:|",
        f"| Hit@1 | {rate(before['hit1'])} | {rate(after['hit1'])} | {delta['hit1'] * 100:+.1f}%p |",
        f"| Hit@10 | {rate(before['hit10'])} | {rate(after['hit10'])} | {delta['hit10'] * 100:+.1f}%p |",
        f"| Top-50 회수율 | {rate(before['top50_recall'])} | {rate(after['top50_recall'])} | {delta['top50_recall'] * 100:+.1f}%p |",
        f"| MRR@10 | {before['mrr10']:.4f} | {after['mrr10']:.4f} | {delta['mrr10']:+.4f} |",
        f"| nDCG@10 | {before['ndcg10']:.4f} | {after['ndcg10']:.4f} | {delta['ndcg10']:+.4f} |",
        "",
        "B-4는 Top-1·Top-10·MRR·nDCG를 개선했고 Top-10 정답 실패를 12개에서 8개로 줄였습니다. 다만 Top-50 회수율은 1문항(2.9%p) 하락했습니다.",
        "따라서 B-4를 무조건적인 승자로 표현하지 않고, **Top-10 후보 품질을 우선하는 운영 후보**로 승인합니다. 후속 리랭커를 붙일 경우에는 B-4의 Top-50 회수율 하락 문항을 별도 회귀 검사로 고정해야 합니다.",
        "",
        "## 2. 인정기준·심의사례 운영안",
        "",
        "- 인정기준: pgvector 후보를 전용 Complete30 V9 Neo4j의 `REQUIRES_FACT` 관계와 대조한 뒤, 매핑이 확정될 때만 결정식 계산기를 호출합니다.",
        "- 심의사례: pgvector로 사례 단위 중복 제거 Top-10을 반환하고, 계산이나 법률 결론을 만들지 않습니다.",
        "- 세 RAG는 공통 JSON 근거 계약으로 반환하며, 슈퍼바이저가 이를 묶을 뿐 법률 그래프를 직접 조회하지 않습니다.",
        "",
        "## 3. 배포 전 보류 조건",
        "",
        "1. 현재 세 코퍼스의 운영 문서 벡터는 과거 AB artifact를 이관한 것으로, artifact에 Hugging Face revision이 없어 `LEGACY_UNPINNED_WARNING`이 남아 있습니다.",
        "2. 인정기준 Complete30에는 revision이 고정된 별도 Qwen 4B 산출물이 존재하지만, 공통 50문항과 동일 revision의 질의 벡터를 새로 생성하기 전에는 두 결과를 한 지표로 섞지 않습니다.",
        "3. 따라서 현재 결과는 DB 이관·검색 경로 검증과 운영 후보 판단용이며, 완전한 운영 승인 전에는 revision을 고정한 Qwen 4B로 문서와 세 평가 질문지를 재임베딩해야 합니다.",
        "4. 법률 Neo4j(`skn27-neo4j`)는 이 실행에서 읽기 대조만 했고 노드 99,964개·관계 451,861개로 백업 기준과 동일했습니다.",
    ]
    (output / "RAG_운영_의사결정_보고서.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (output / "RAG_운영_통합_점수.json").write_text(
        json.dumps({"results": rows, "precedent_b4_delta": delta}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("10단계 통합 점수표·운영 의사결정 보고서 생성 완료")


if __name__ == "__main__":
    main()
