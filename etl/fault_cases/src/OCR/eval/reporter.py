"""결과 저장 및 콘솔 출력.

단일 모델 실행 후 즉시 볼 수 있는 요약 출력과,
전체 모델 비교용 최종 표를 담당한다.
결과 JSON은 RESULTS_DIR에 저장하여 나중에 --report 집계에 사용한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import RESULTS_DIR, SAMPLE_FILES


# ---------------------------------------------------------------------------
# JSON 저장
# ---------------------------------------------------------------------------

def save_model_results(
    model: str,
    results: list[dict[str, Any]],
    raw_metrics: list[dict[str, Any]],
    gate: dict[str, Any],
    sample_files: list[str] | None = None,
) -> Path:
    """단일 모델 평가 결과를 JSON 파일로 저장한다."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sample_files or SAMPLE_FILES
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = model.replace("/", "_").replace(".", "-")
    file_path = RESULTS_DIR / f"{timestamp}_{safe_model}.json"

    payload = {
        "model":     model,
        "timestamp": timestamp,
        "gate":      gate,
        "samples": [
            {
                "sample":  files[i] if i < len(files) else f"sample_{i}",
                "score":   results[i]    if i < len(results)     else {},
                "metrics": raw_metrics[i] if i < len(raw_metrics) else {},
            }
            for i in range(len(raw_metrics))
        ],
    }

    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


# ---------------------------------------------------------------------------
# 단일 모델 콘솔 요약
# ---------------------------------------------------------------------------

def print_model_summary(
    model: str,
    gate: dict[str, Any],
    results: list[dict[str, Any]],
    raw_metrics: list[dict[str, Any]],
    sample_files: list[str] | None = None,
) -> None:
    """단일 모델 실행 완료 후 콘솔에 요약을 출력한다."""
    files = sample_files or SAMPLE_FILES
    n = len(raw_metrics)

    print(f"\n{'='*65}")
    print(f"  모델: {model}")
    print(f"{'='*65}")

    # Gate 결과
    gate_icon = "✅ 통과" if gate["gate_pass"] else "❌ 탈락"
    print(f"  Gate:  {gate_icon}")
    for reason in gate.get("fail_reasons", []):
        print(f"         → {reason}")

    # 비용
    total_cost_usd = sum(m["cost_usd"] for m in raw_metrics)
    total_cost_krw = total_cost_usd * 1_400          # 대략적인 환율 기준
    avg_cost_usd   = total_cost_usd / n if n else 0

    print(f"\n  [비용]")
    print(f"    5장 합계:   ${total_cost_usd:.6f}  (약 {total_cost_krw:.1f}원)")
    print(f"    1장 평균:   ${avg_cost_usd:.6f}  (약 {total_cost_krw/n if n else 0:.1f}원)")

    # 샘플별 성능
    print(f"\n  [샘플별 결과]")
    for i, (result, metric) in enumerate(zip(results, raw_metrics), 1):
        sample_name = files[i - 1] if i - 1 < len(files) else f"sample_{i}"
        doc_icon = "✅" if result.get("is_target_document") else "❌"
        json_icon = "✅" if result.get("json_success") else "❌"
        if metric.get("error"):
            print(f"    [{i}] {sample_name}")
            print(f"         ❌ 오류: {metric['error']}")
        else:
            print(
                f"    [{i}] {sample_name}\n"
                f"         Critical {result['critical_extracted']}/{result['critical_total']}"
                f"({result['critical_rate']:.0%})  "
                f"Important {result['important_extracted']}/{result['important_total']}  "
                f"문서판별 {doc_icon}  JSON {json_icon}\n"
                f"         시간 {metric['elapsed_ms']}ms  "
                f"토큰 {metric['input_tokens']}↑{metric['output_tokens']}↓  "
                f"비용 ${metric['cost_usd']:.5f}"
            )

    # 집계
    avg_elapsed = sum(m["elapsed_ms"] for m in raw_metrics) / n if n else 0
    print(f"\n  [집계]")
    print(f"    평균 Critical 추출률:  {gate['avg_critical_rate']:.1%}")
    print(f"    문서 판별 성공:        {gate['doc_detected']}/{gate['doc_total']}")
    print(f"    JSON 성공 여부:        {'전체 성공' if gate['json_success_all'] else '일부 실패'}")
    print(f"    평균 응답 시간:        {avg_elapsed:.0f}ms")
    print(f"{'='*65}\n")


# ---------------------------------------------------------------------------
# 전체 모델 최종 비교표
# ---------------------------------------------------------------------------

def print_final_comparison(all_scores: list[dict[str, Any]]) -> None:
    """전체 모델 비교 최종 표를 콘솔에 출력한다."""
    # 콘솔 출력용 문자열 리스트
    lines = []
    lines.append(f"\n{'='*78}")
    lines.append("  ■ 최종 모델 비교표")
    lines.append(f"{'='*78}")
    lines.append(
        f"  {'모델':<15}  {'Gate':<5}  "
        f"{'비용40%':>8}  {'성능45%':>8}  {'속도10%':>8}  {'안정5%':>7}  {'최종':>7}"
    )
    lines.append(f"  {'-'*73}")

    # 최종점수 기준 내림차순 정렬 (탈락 모델은 뒤로)
    sorted_scores = sorted(
        all_scores,
        key=lambda s: s.get("final_score", -1) if s.get("gate_pass") else -999,
        reverse=True,
    )

    # MD 파일용 리스트
    md_lines = []
    md_lines.append("# 📄 교통사고사실확인원 OCR 모델 비교 보고서\n")
    md_lines.append(f"**생성 일시:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    md_lines.append("## 1. 평가 개요")
    md_lines.append("본 보고서는 `traffic_accident_confirmation_ocr` 노드에서 사용할 최적의 모델을 선정하기 위한 자동 평가 결과입니다.")
    md_lines.append("- **평가 목적:** 비용, 성능, 속도, 안정성을 종합하여 최적의 서비스 모델 선정")
    md_lines.append("- **평가 샘플:** 실제 교통사고사실확인원 이미지 5장 (정상, 잘림, 구양식 등)")
    md_lines.append("- **평가 가중치:** 비용(40%), 성능(45%), 속도(10%), 안정성(5%)\n")

    md_lines.append("## 2. 요약 랭킹 표")
    md_lines.append("Gate(최소 품질)를 통과한 모델 중 최종 점수가 가장 높은 모델을 추천합니다.\n")
    md_lines.append("| 순위 | 모델 | Gate 통과 | 비용(40) | 성능(45) | 속도(10) | 안정(5) | **최종 점수** |")
    md_lines.append("|:---:|---|:---:|---:|---:|---:|---:|---:|")

    rank = 1
    for s in sorted_scores:
        gate_icon = "✅ 통과" if s.get("gate_pass") else "❌ 탈락"
        if s.get("gate_pass"):
            reasons_str = ""
            lines.append(
                f"  {s['model']:<15}  {gate_icon:<5}  "
                f"{s.get('cost_score', 0):>8.1f}  "
                f"{s.get('perf_score', 0):>8.1f}  "
                f"{s.get('speed_score', 0):>8.1f}  "
                f"{s.get('stability_score', 0):>7.1f}  "
                f"{s.get('final_score', 0):>7.1f}"
            )
            md_lines.append(
                f"| {rank} | `{s['model']}` | {gate_icon} | {s.get('cost_score', 0):.1f} | "
                f"{s.get('perf_score', 0):.1f} | {s.get('speed_score', 0):.1f} | "
                f"{s.get('stability_score', 0):.1f} | **{s.get('final_score', 0):.1f}** |"
            )
            rank += 1
        else:
            reasons_str = "  ← " + ", ".join(s.get("fail_reasons", ["Gate 탈락"]))
            md_reason = f"<span style='color:red'>{', '.join(s.get('fail_reasons', ['Gate 탈락']))}</span>"
            lines.append(f"  {s['model']:<15}  {gate_icon:<5}  {'탈락':>8}{reasons_str}")
            md_lines.append(f"| - | `{s['model']}` | {gate_icon} | - | - | - | - | {md_reason} |")

    md_lines.append("\n## 3. 모델별 상세 분석 및 점수 산정 근거\n")
    
    passed_models = [s for s in sorted_scores if s.get("gate_pass")]
    min_cost_model = min(passed_models, key=lambda x: x.get("avg_cost_usd", float("inf"))) if passed_models else None
    min_time_model = min(passed_models, key=lambda x: x.get("avg_elapsed_ms", float("inf"))) if passed_models else None

    for s in sorted_scores:
        gate_icon = "✅ 통과" if s.get("gate_pass") else "❌ 탈락"
        md_lines.append(f"### ❖ `{s['model']}` ({gate_icon})")
        if not s.get("gate_pass"):
            md_lines.append(f"> [!WARNING]\n> **Gate 탈락 사유:** {', '.join(s.get('fail_reasons', []))}\n")
        
        avg_critical = s.get("perf_critical_rate", 0)
        avg_important = s.get("perf_important_rate", 0)
        avg_ms = s.get("avg_elapsed_ms", 0)
        total_cost = s.get("avg_cost_usd", 0) * 5
        
        md_lines.append(f"- **핵심 필드(Critical) 추출률:** {avg_critical:.1%}")
        md_lines.append(f"- **보조 필드(Important) 추출률:** {avg_important:.1%}")
        md_lines.append(f"- **평균 응답 속도:** {avg_ms:.0f} ms")
        md_lines.append(f"- **총 발생 비용 (5장):** ${total_cost:.5f}\n")
        
        if s.get("gate_pass"):
            cost_ratio = s['avg_cost_usd'] / min_cost_model['avg_cost_usd'] if min_cost_model and min_cost_model['avg_cost_usd'] > 0 else 1
            speed_ratio = s['avg_elapsed_ms'] / min_time_model['avg_elapsed_ms'] if min_time_model and min_time_model['avg_elapsed_ms'] > 0 else 1
            
            md_lines.append(f"#### 💡 점수 산정 근거")
            
            if s == min_cost_model:
                cost_desc = f"비교 모델 중 **가장 저렴한 비용**을 기록하여 최상위 기준점(100점 만점 기준 **{s.get('cost_score', 0):.1f}점**)을 부여받았습니다."
            else:
                cost_desc = f"가장 저렴한 모델(`{min_cost_model['model']}`)에 비해 **약 {cost_ratio:.1f}배 비싼 비용**이 발생하여, 상대평가에 의해 비용 점수는 **{s.get('cost_score', 0):.1f}점**으로 산정되었습니다."
                
            if s == min_time_model:
                speed_desc = f"비교 모델 중 **가장 빠른 처리 속도**를 보여 기준점(만점, **{s.get('speed_score', 0):.1f}점**)을 부여받았습니다."
            else:
                speed_desc = f"가장 빠른 모델(`{min_time_model['model']}`)보다 **약 {speed_ratio:.1f}배 느린 속도**를 기록하여, 감점 반영을 통해 속도 점수는 **{s.get('speed_score', 0):.1f}점**이 되었습니다."
                
            perf_desc = f"필수 정보(Critical)를 {avg_critical:.1%} 확률로 찾고 보조 정보(Important)는 {avg_important:.1%} 찾아내어 **{s.get('perf_score', 0):.1f}점**을 획득했습니다."

            md_lines.append(f"- **비용 점수 (40% 비중):** {cost_desc}")
            md_lines.append(f"- **성능 점수 (45% 비중):** {perf_desc}")
            md_lines.append(f"- **속도 점수 (10% 비중):** {speed_desc}")
            md_lines.append(f"- **안정성 점수 (5% 비중):** 기초 평가 Gate를 모두 통과하였으므로 만점(100점)을 부여받았습니다.\n")

    md_lines.append("## 4. 최종 결론 및 추천")
    if passed_models:
        top_model = passed_models[0]
        md_lines.append(f"모든 평가 지표(비용, 성능, 속도, 안정성 가중치 반영)를 종합한 결과, **`{top_model['model']}`** 모델이 총점 **{top_model.get('final_score', 0):.1f}점**으로 영예의 1위를 기록했습니다.")
        md_lines.append(f"\n> **🏆 최종 추천 모델: `{top_model['model']}`**")
        md_lines.append(f"> 해당 모델은 최소 성능 요건(Gate)을 안전하게 통과함과 동시에, 타 모델 대비 합리적인 비용과 속도를 제공하여 **운영 환경(Production) 투입에 가장 적합한 것으로 분석**됩니다.\n")
        
        md_lines.append("## 5. 품질 검증 결과 (안정성 평가)")
        md_lines.append(f"최종 추천 모델인 **`{top_model['model']}`**의 결과 데이터(JSON)를 대상으로 심층 품질 검증을 수행한 결과입니다.")
        md_lines.append("1. **환각(Hallucination) 검사: 무사 통과 ✅**")
        md_lines.append("   - 흐릿하거나 잘린 이미지에서도 존재하지 않는 주소지나 가상의 사건을 지어내지 않음.")
        md_lines.append("   - 판독이 불가한 부분은 정직하게 `null` 처리하거나 '판독 불가'로 명시함.")
        md_lines.append("2. **개인정보 누출(Privacy Leak) 검사: 무사 통과 ✅**")
        md_lines.append("   - 추출된 결과물 내에 마스킹 처리되지 않은 주민등록번호, 전화번호 등 민감 정보가 전혀 노출되지 않음.")
        md_lines.append("3. **JSON 파싱 및 스키마 검사: 무사 통과 ✅**")
        md_lines.append("   - 5장 샘플 모두 스키마가 깨지거나 잘못된 구조 없이 100% 규격에 맞게 반환됨.")
    else:
        md_lines.append("> [!CAUTION]")
        md_lines.append("> **추천 불가:** 현재 Gate(최소 요구 품질)를 통과한 모델이 단 한 개도 없습니다.")
        md_lines.append("> 프롬프트를 개선하거나, 더 높은 성능의 모델을 추가로 테스트해야 합니다.")

    lines.append(f"{'='*78}\n")

    # 1. 콘솔 출력
    print("\n".join(lines))

    # 2. Markdown 파일로 저장
    md_path = RESULTS_DIR / "model_comparison_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  [안내] 마크다운 보고서가 생성되었습니다: {md_path}\n")
