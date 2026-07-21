"""전용 운영 RAG를 Complete30 질문·정답지로 검증한다.

Complete30 Qwen 4B artifact는 revision이 명시된 30개 질문 벡터를 제공한다. 이 도구는
각 질문의 실제 `structured_facts`와 벡터를 운영 RAG에 전달해 Rule·계산 결과·근거
trace를 검증하며, 정답지를 검색이나 선택 로직에 전달하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from etl.fault_cases.rag_runtime.fault_standard.retriever import search_fault_standard


ROOT = Path(__file__).resolve().parents[2]
COMPLETE30_ROOT = ROOT / "NEW_ABC_TEST_V6/artifacts/v7_complete30_abc/01_common_candidates"
EVAL_ROOT = ROOT / "evaluation/fault_standard/complete30_v9/v1"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """UTF-8 JSONL을 읽고 빈 줄은 제외한다."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    """입력 동결 여부를 남기기 위해 파일 SHA-256을 계산한다."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def vectors() -> dict[str, list[float]]:
    """revision 고정 Complete30 질문 벡터 30개를 ID별로 읽는다."""

    path = COMPLETE30_ROOT / "query_embeddings.parquet"
    output = {str(row["id"]): [float(value) for value in row["vector"]] for row in pq.read_table(path).to_pylist()}
    if len(output) != 30:
        raise ValueError(f"Complete30 질문 벡터가 30개가 아닙니다: {len(output)}")
    return output


def main() -> None:
    """30문항을 실제 운영 RAG로 실행하고 결과 JSON·Markdown을 생성한다."""

    questions_path = EVAL_ROOT / "complete30_consumer_questions_v1.jsonl"
    answers_path = EVAL_ROOT / "complete30_answer_key_with_explanations_v1.jsonl"
    questions = {str(row["case_id"]): row for row in read_jsonl(questions_path)}
    answers = {str(row["case_id"]): row for row in read_jsonl(answers_path)}
    query_vectors = vectors()
    if len(questions) != 30 or set(questions) != set(answers) or set(questions) != set(query_vectors):
        raise ValueError("Complete30 질문·정답지·질문 벡터의 case_id 집합이 정확히 30개로 일치하지 않습니다.")

    details: list[dict[str, Any]] = []
    for case_id in sorted(questions):
        question, answer = questions[case_id], answers[case_id]
        result = search_fault_standard(
            {
                "contract_version": "v1",
                "message_id": case_id,
                "query_vector": query_vectors[case_id],
                "accident_facts": {"structured_facts": question.get("structured_facts") or {}},
            }
        )
        calculation = result.get("calculation_result") or {}
        evidence = result.get("evidence") or []
        selected = dict(calculation.get("selection_trace") or {})
        expected_ratio = answer.get("final_ratio")
        actual_ratio = calculation.get("final_ratio")
        details.append(
            {
                "case_id": case_id,
                "runtime_status": result.get("status"),
                "expected_rule_id": answer.get("rule_id"),
                "selected_rule_id": calculation.get("rule_id"),
                "rule_match": calculation.get("rule_id") == answer.get("rule_id"),
                "expected_status": answer.get("expected_status"),
                "calculation_status": calculation.get("status"),
                "ratio_match": actual_ratio == expected_ratio,
                "ratio_sum_is_100": isinstance(actual_ratio, dict) and sum(actual_ratio.values()) == 100,
                "top1_rule_id": evidence[0]["chunk_id"] if evidence else None,
                "top10_rule_ids": [row["chunk_id"] for row in evidence],
                "top10_has_expected_rule": str(answer.get("rule_id")) in [row["chunk_id"] for row in evidence],
                "selection_state": selected.get("selection_state"),
                "selection_trace": selected.get("decision_trace", []),
                "missing_fields": result.get("missing_fields", []),
            }
        )
    rule_matches = sum(bool(row["rule_match"]) for row in details)
    ratio_matches = sum(bool(row["ratio_match"]) for row in details)
    top10 = sum(bool(row["top10_has_expected_rule"]) for row in details)
    sum100_failures = [row["case_id"] for row in details if not row["ratio_sum_is_100"] and row["calculation_status"] == "calculated"]
    result = {
        "status": "PASS" if not sum100_failures else "FAIL",
        "question_count": 30,
        "rule_exact_match_count": rule_matches,
        "rule_exact_match_rate": rule_matches / 30,
        "top10_expected_rule_count": top10,
        "top10_expected_rule_rate": top10 / 30,
        "ratio_exact_match_count": ratio_matches,
        "ratio_exact_match_rate": ratio_matches / 30,
        "calculated_ratio_sum_100_failure_case_ids": sum100_failures,
        "inputs": {
            "questions_sha256": sha256(questions_path),
            "answers_sha256": sha256(answers_path),
            "query_embedding_manifest": json.loads((COMPLETE30_ROOT / "runpod_all_embeddings_manifest.json").read_text(encoding="utf-8")),
        },
        "details": details,
    }
    output = ROOT / "artifacts/rag_runtime/stage7"
    output.mkdir(parents=True, exist_ok=True)
    (output / "fault_standard_complete30_runtime_evaluation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 인정기준 운영 RAG Complete30 검증",
        "",
        "| 항목 | 결과 |",
        "|---|---:|",
        f"| 질문 수 | {result['question_count']} |",
        f"| Rule 정확 일치 | {rule_matches}/30 ({result['rule_exact_match_rate']:.1%}) |",
        f"| 정답 Rule Top-10 포함 | {top10}/30 ({result['top10_expected_rule_rate']:.1%}) |",
        f"| 최종 비율 정확 일치 | {ratio_matches}/30 ({result['ratio_exact_match_rate']:.1%}) |",
        f"| 계산된 비율 합계 100 실패 | {len(sum100_failures)}건 |",
        "",
        "- 이 평가는 revision이 기록된 Complete30 Qwen 4B 질문 벡터와 동일 Rule 벡터의 수치 동등성 검증 뒤 수행한다.",
        "- 정답지는 실행 입력이 아니라 실행 결과 비교에만 사용했다.",
        "- 각 case의 `selection_trace`에는 Qwen 후보 순위와 V9 `REQUIRES_FACT` 조건 대조 결과를 보관한다.",
    ]
    (output / "인정기준_운영RAG_Complete30_검증표.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Complete30 운영 RAG 검증 완료: Rule={rule_matches}/30, 비율={ratio_matches}/30")


if __name__ == "__main__":
    main()
