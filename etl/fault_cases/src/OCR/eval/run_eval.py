"""OCR 모델 비교 평가 실행 진입점.

사용 방법:

  # 단일 모델 평가 (5장 샘플 순서대로)
  python -m etl.fault_cases.src.OCR.eval.run_eval --model gpt-5.4-mini

  # 지원 모델 목록 확인
  python -m etl.fault_cases.src.OCR.eval.run_eval --list

  # 저장된 결과 전체 집계 후 비교표 출력
  python -m etl.fault_cases.src.OCR.eval.run_eval --report

한 모델씩 실행하면 비용과 품질을 확인한 뒤 다음 모델로 넘어갈 수 있다.
전체 모델을 한 번에 돌리고 싶다면 --model all 을 사용한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# sys.path 설정: OCR 디렉터리를 최상위 패키지 기준으로 추가
# ---------------------------------------------------------------------------
_OCR_DIR = Path(__file__).resolve().parents[1]   # .../OCR/
if str(_OCR_DIR) not in sys.path:
    sys.path.insert(0, str(_OCR_DIR))

from eval.config import EVAL_MODELS, RESULTS_DIR, SAMPLE_DIR, SAMPLE_FILES  # noqa: E402
from eval.ocr_caller import call_ocr_with_metrics                              # noqa: E402
from eval.scorer import (                                                       # noqa: E402
    check_gates,
    compute_model_scores,
    normalize_scores,
    score_single_call,
)
from eval.reporter import (                                                     # noqa: E402
    print_final_comparison,
    print_model_summary,
    save_model_results,
)
from traffic_accident_confirmation_ocr.masking import mask_sensitive_fields     # noqa: E402
from traffic_accident_confirmation_ocr.prompts import (                         # noqa: E402
    TRAFFIC_ACCIDENT_CONFIRMATION_OCR_PROMPT,
)
from traffic_accident_confirmation_ocr.verification import verify_document      # noqa: E402


# ---------------------------------------------------------------------------
# 단일 모델 평가
# ---------------------------------------------------------------------------

def run_single_model(model: str) -> None:
    """지정한 모델로 5장 샘플을 순서대로 평가한다."""
    print(f"\n▶ 모델 [{model}] 평가 시작 — 샘플 {len(SAMPLE_FILES)}장")
    print(f"  샘플 폴더: {SAMPLE_DIR}\n")

    results: list[dict] = []
    raw_metrics: list[dict] = []

    for idx, sample_file in enumerate(SAMPLE_FILES, 1):
        image_path = SAMPLE_DIR / sample_file
        print(f"  [{idx}/{len(SAMPLE_FILES)}] {sample_file}", end="  ", flush=True)

        # 파일 존재 확인
        if not image_path.exists():
            print(f"❌ 파일 없음: {image_path}")
            raw_metrics.append(_empty_metric("파일 없음"))
            results.append(_failed_score())
            continue

        # OCR 호출 (timing + usage 포함)
        metric = call_ocr_with_metrics(
            image_path=image_path,
            model=model,
            prompt=TRAFFIC_ACCIDENT_CONFIRMATION_OCR_PROMPT,
        )
        raw_metrics.append(metric)

        # 오류/JSON 실패 처리
        if metric["error"] or not metric["json_success"]:
            print(f"❌ 오류: {metric['error'] or 'JSON 파싱 실패'}")
            results.append({**_failed_score(), "json_success": metric["json_success"]})
            continue

        # 개인정보 마스킹
        masked, _ = mask_sensitive_fields(metric["parsed"])

        # 문서 판별
        doc_check = verify_document(
            document_name=masked.get("document_name"),
            detected_labels=masked.get("detected_labels") or [],
            issuer_labels=masked.get("issuer_labels") or [],
        )

        # 단건 채점
        score = score_single_call(
            parsed=masked,
            is_target_document=doc_check["is_target_document"],
            ocr_status="success" if doc_check["is_target_document"] else "partial",
            json_success=metric["json_success"],
        )
        results.append(score)

        # 진행 상황 한 줄 출력
        doc_icon = "✅" if doc_check["is_target_document"] else "❌"
        print(
            f"Critical {score['critical_extracted']}/4  "
            f"문서 {doc_icon}  "
            f"{metric['elapsed_ms']}ms  "
            f"${metric['cost_usd']:.5f}"
        )

    # Gate 판정
    gate = check_gates(results)

    # 콘솔 요약 출력
    print_model_summary(model, gate, results, raw_metrics, SAMPLE_FILES)

    # JSON 저장
    saved_path = save_model_results(model, results, raw_metrics, gate, SAMPLE_FILES)
    print(f"  💾 결과 저장: {saved_path}\n")


# ---------------------------------------------------------------------------
# 전체 결과 집계 및 비교표 출력
# ---------------------------------------------------------------------------

def run_report() -> None:
    """저장된 결과 JSON을 불러와 최종 모델 비교표를 출력한다."""
    if not RESULTS_DIR.exists() or not list(RESULTS_DIR.glob("*.json")):
        print("\n⚠  아직 평가 결과가 없습니다.")
        print("   먼저 --model 옵션으로 모델을 평가하세요.")
        print("   예: python -m etl.fault_cases.src.OCR.eval.run_eval --model gpt-5.4-mini\n")
        return

    # 모델별 최신 결과 파일 사용
    model_data: dict[str, dict] = {}
    for f in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        model = data.get("model", "unknown")
        model_data[model] = data   # 파일명 정렬 기준 최신 덮어씌움

    print(f"\n  집계 모델: {list(model_data.keys())}")

    all_scores: list[dict] = []
    for model, data in model_data.items():
        gate    = data.get("gate", {})
        samples = data.get("samples", [])
        scores  = compute_model_scores(
            model=model,
            gate=gate,
            results=[s.get("score", {}) for s in samples],
            raw_metrics=[s.get("metrics", {}) for s in samples],
        )
        all_scores.append(scores)

    normalized = normalize_scores(all_scores)
    print_final_comparison(normalized)


# ---------------------------------------------------------------------------
# CLI 진입점
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="교통사고사실확인원 OCR 모델 비교 평가",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python -m etl.fault_cases.src.OCR.eval.run_eval --model gpt-5.4-mini
  python -m etl.fault_cases.src.OCR.eval.run_eval --model gpt-4o
  python -m etl.fault_cases.src.OCR.eval.run_eval --model all
  python -m etl.fault_cases.src.OCR.eval.run_eval --report
  python -m etl.fault_cases.src.OCR.eval.run_eval --list
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--model",
        metavar="MODEL",
        help=f"평가할 모델명 또는 'all'. 선택 가능: {', '.join(EVAL_MODELS + ['all'])}",
    )
    group.add_argument(
        "--report",
        action="store_true",
        help="저장된 결과로 최종 비교표 출력",
    )
    group.add_argument(
        "--list",
        action="store_true",
        help="평가 가능한 모델 목록 출력",
    )

    args = parser.parse_args()

    if args.list:
        print("\n평가 가능한 모델:")
        for m in EVAL_MODELS:
            print(f"  {m}")
        print()
        return

    if args.report:
        run_report()
        return

    if args.model == "all":
        for model in EVAL_MODELS:
            run_single_model(model)
        run_report()
    elif args.model in EVAL_MODELS:
        run_single_model(args.model)
    else:
        print(f"\n❌ 알 수 없는 모델: '{args.model}'")
        print(f"   선택 가능한 모델: {', '.join(EVAL_MODELS)}\n")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _empty_metric(error_msg: str) -> dict:
    return {
        "input_tokens": 0, "output_tokens": 0,
        "elapsed_ms": 0, "cost_usd": 0.0,
        "json_success": False, "error": error_msg,
    }


def _failed_score() -> dict:
    return {
        "critical_extracted": 0, "critical_total": 4, "critical_rate": 0.0,
        "important_extracted": 0, "important_total": 6, "important_rate": 0.0,
        "is_target_document": False, "ocr_status": "failed",
        "status_match": False, "json_success": False,
        "privacy_leak": 0, "hallucination_count": 0,
    }

if __name__ == "__main__":
    main()

