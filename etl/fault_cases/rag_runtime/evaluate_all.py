"""세 RAG 공통 평가 스크립트."""

import json
from pathlib import Path
from etl.fault_cases.rag_runtime.contracts import RagRequest
from etl.fault_cases.rag_runtime.fault_standard.service import handle_request as fs_handle
from etl.fault_cases.rag_runtime.precedent.service import handle_request as pr_handle
from etl.fault_cases.rag_runtime.review_case.service import handle_request as rc_handle

def main():
    dataset_path = Path("C:/dev/project/SKN27-FINAL-3Team/etl/fault_cases/evaluation/fault_standard/complete30_v9/v1/complete30_consumer_questions_v1.jsonl")
    if not dataset_path.exists():
        print(f"데이터셋을 찾을 수 없습니다: {dataset_path}")
        return

    questions = []
    with dataset_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    print(f"총 {len(questions)}건의 평가 질문을 테스트합니다.")

    # 각 RAG 통과 기준 검증 변수
    fs_pass = True
    pr_pass = True
    rc_pass = True
    b4_fired_count = 0

    for q in questions:
        req: RagRequest = {
            "contract_version": "v1",
            "message_id": q["case_id"],
            "evaluation_query_id": q["case_id"],
            "query_text": q["query_text"],
            "structured_facts": q["structured_facts"]
        }

        fs_res = fs_handle(req)
        calc = fs_res.get("calculation_result") or {}
        if fs_res["status"] == "failed" or calc.get("status") != "calculated":
            reason = calc.get('reason') if calc else fs_res.get('limitations')
            print(f"인정기준 실패 ({q['case_id']}): {reason}")
            fs_pass = False

        # 2. 판례 RAG
        pr_res = pr_handle(req)
        if pr_res["status"] == "failed":
            print(f"판례 실패 ({q['case_id']})")
            pr_pass = False
        limitations = " ".join(pr_res.get("limitations", []))
        if "B-4=" in limitations and not "B-4=없음" in limitations:
            b4_fired_count += 1

        # 3. 심의사례 RAG
        rc_res = rc_handle(req)
        if rc_res["status"] == "failed":
            print(f"심의사례 실패 ({q['case_id']})")
            rc_pass = False

    print("=== 테스트 결과 ===")
    print(f"인정기준 RAG: {'PASS' if fs_pass else 'FAIL'}")
    print(f"판례 RAG: {'PASS' if pr_pass and b4_fired_count == 9 else 'FAIL'} (B-4 발동: {b4_fired_count}/9)")
    print(f"심의사례 RAG: {'PASS' if rc_pass else 'FAIL'}")

if __name__ == "__main__":
    main()
