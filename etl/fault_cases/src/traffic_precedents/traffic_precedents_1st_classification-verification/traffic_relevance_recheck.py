#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
traffic_relevance_pre_stage2_verifier.py

1차 교통사고 관련성 분류 결과를 2차 과실비율 분류에 넘기기 전에 검증하고 정리합니다.

검증 목표:
1. 기존 confirmed_traffic 중 진짜 교통사고 판례로 보기 어려운 row는 non_traffic으로 내립니다.
2. 기존 possible_traffic_review 중 교통사고 판례 근거가 강한 row는 confirmed_traffic으로 올립니다.
3. 기존 possible_traffic_review 중 확실하지 않은 row는 non_traffic으로 보냅니다.
4. 기존 non_traffic은 그대로 non_traffic에 유지합니다.

기본 입력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass/
  01_confirmed_traffic_cases.jsonl
  02_possible_traffic_review.jsonl
  03_non_traffic_cases.jsonl

기본 출력:
etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified/
  00_traffic_reclass_verification_report.json
  01_confirmed_traffic_cases.jsonl
  02_non_traffic_cases.jsonl
  03_traffic_reclassified_verified_all.jsonl
  04_demoted_from_confirmed_to_non_traffic.jsonl
  05_promoted_from_possible_to_confirmed.jsonl
  06_possible_to_non_traffic.jsonl
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_RECLASS_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass"
DEFAULT_OUT_DIR = "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_reclass_verified"

CONFIRMED_FILE = "01_confirmed_traffic_cases.jsonl"
POSSIBLE_FILE = "02_possible_traffic_review.jsonl"
NON_TRAFFIC_FILE = "03_non_traffic_cases.jsonl"


STRONG_ACCIDENT_REASONS = {
    "direct_traffic_accident_terms",
    "road_actor_and_accident_action_nearby",
    "core_actor_and_strong_accident_action_nearby",
}

STRONG_ACCIDENT_GROUPS = {
    "direct_accident_expression",
    "road_actor_action_nearby",
    "core_actor_action_nearby",
}

SUPPORTING_CONTEXT_GROUPS = {
    "traffic_legal_or_insurance_context",
    "fault_or_liability_context",
    "traffic_situation_context",
}

WEAK_OR_GENERIC_REASONS = {
    "traffic_law_terms_without_accident_context",
    "generic_traffic_reference_pattern_found",
    "case_category_disallowed_for_confirmed",
    "non_traffic_domain_without_enough_traffic_accident_signals",
}

ACCIDENT_TERMS = [
    "교통사고",
    "자동차 사고",
    "차량 사고",
    "차량 충돌",
    "충돌사고",
    "추돌사고",
    "접촉사고",
    "보행자 사고",
    "횡단보도 사고",
    "오토바이 사고",
    "자전거 사고",
    "치상",
    "치사",
    "상해",
    "사망",
    "충격",
    "역과",
    "들이받",
]

TRAFFIC_CASE_PURPOSE_TERMS = [
    "손해배상",
    "구상금",
    "보험금",
    "자동차손해배상",
    "자동차손해배상보장법",
    "교통사고처리특례법",
    "교통사고 처리 특례법",
    "과실비율",
    "과실상계",
    "책임비율",
    "주의의무",
]

LAW_ONLY_TERMS = [
    "도로교통법위반",
    "음주운전",
    "무면허운전",
    "운전면허취소",
    "운전면허정지",
    "벌점",
    "범칙금",
    "과태료",
]


@dataclass
class ReviewStats:
    confirmed_input_rows: int = 0
    confirmed_verified_rows: int = 0
    confirmed_demoted_to_non_traffic_rows: int = 0
    possible_input_rows: int = 0
    possible_promoted_to_confirmed_rows: int = 0
    possible_to_non_traffic_rows: int = 0
    non_traffic_input_rows: int = 0
    final_confirmed_traffic_rows: int = 0
    final_non_traffic_rows: int = 0
    final_all_rows: int = 0
    decision_reason_counts: Dict[str, int] = field(default_factory=dict)
    original_reason_counts: Dict[str, int] = field(default_factory=dict)


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row["_pre_stage2_input_line_no"] = line_no
            yield row


def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_output_paths(out_dir: Path, fresh: bool) -> Dict[str, Path]:
    if fresh and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "report": out_dir / "00_traffic_reclass_verification_report.json",
        "confirmed": out_dir / "01_confirmed_traffic_cases.jsonl",
        "non_traffic": out_dir / "02_non_traffic_cases.jsonl",
        "all": out_dir / "03_traffic_reclassified_verified_all.jsonl",
        "demoted_from_confirmed": out_dir / "04_demoted_from_confirmed_to_non_traffic.jsonl",
        "promoted_from_possible": out_dir / "05_promoted_from_possible_to_confirmed.jsonl",
        "possible_to_non": out_dir / "06_possible_to_non_traffic.jsonl",
    }

    if not fresh:
        for path in paths.values():
            if path.exists():
                path.unlink()

    return paths


def text_of(row: Dict[str, Any]) -> str:
    parts = [
        row.get("case_name"),
        row.get("holding"),
        row.get("summary"),
        row.get("main_text", "")[:3000],
    ]
    return " ".join(str(part) for part in parts if part)


def has_any(text: str, terms: List[str]) -> bool:
    return any(term in text for term in terms)


def row_sets(row: Dict[str, Any]) -> Tuple[set, set]:
    reasons = set(row.get("traffic_reclass_reasons") or [])
    groups = set(row.get("traffic_signal_groups") or [])
    return reasons, groups


def row_int(row: Dict[str, Any], key: str) -> int:
    value = row.get(key)
    return value if isinstance(value, int) else 0


def has_strong_accident_signal(row: Dict[str, Any]) -> bool:
    reasons, groups = row_sets(row)
    return (
        bool(reasons & STRONG_ACCIDENT_REASONS)
        or bool(groups & STRONG_ACCIDENT_GROUPS)
        or bool(row.get("has_core_accident_context"))
    )


def has_supporting_context(row: Dict[str, Any]) -> bool:
    _, groups = row_sets(row)
    return bool(groups & SUPPORTING_CONTEXT_GROUPS)


def looks_law_only(row: Dict[str, Any]) -> bool:
    text = text_of(row)
    has_law_only = has_any(text, LAW_ONLY_TERMS)
    has_accident = has_any(text, ACCIDENT_TERMS)
    has_traffic_purpose = has_any(text, TRAFFIC_CASE_PURPOSE_TERMS)
    return has_law_only and not has_accident and not has_traffic_purpose


def verify_confirmed_row(row: Dict[str, Any]) -> Tuple[str, List[str]]:
    reasons, groups = row_sets(row)
    decision_reasons: List[str] = []

    score = row_int(row, "traffic_relevance_score")
    signal_group_count = row_int(row, "traffic_signal_group_count")
    traffic_term_count = row_int(row, "traffic_term_count")

    if score < 8:
        decision_reasons.append("confirmed_score_below_original_threshold")
    if signal_group_count < 2:
        decision_reasons.append("confirmed_signal_group_count_below_2")
    if traffic_term_count < 3:
        decision_reasons.append("confirmed_traffic_term_count_below_3")
    if not has_strong_accident_signal(row):
        decision_reasons.append("no_strong_accident_signal")
    if reasons & WEAK_OR_GENERIC_REASONS:
        decision_reasons.extend(sorted(reasons & WEAK_OR_GENERIC_REASONS))
    if looks_law_only(row):
        decision_reasons.append("law_only_context_without_accident_damage")

    has_minimum_confirmed_shape = (
        score >= 8
        and signal_group_count >= 2
        and traffic_term_count >= 3
        and has_strong_accident_signal(row)
    )

    has_real_accident_shape = has_strong_accident_signal(row) and (
        has_supporting_context(row) or bool(groups & STRONG_ACCIDENT_GROUPS)
    )

    if has_minimum_confirmed_shape and has_real_accident_shape and not looks_law_only(row):
        if not decision_reasons or decision_reasons == ["generic_traffic_reference_pattern_found"]:
            return "confirmed_traffic", decision_reasons or ["verified_strong_traffic_accident_context"]

    return "non_traffic", decision_reasons or ["confirmed_demoted_requires_manual_review"]


def review_possible_row(row: Dict[str, Any]) -> Tuple[str, List[str]]:
    reasons, _ = row_sets(row)
    decision_reasons: List[str] = []

    score = row_int(row, "traffic_relevance_score")
    signal_group_count = row_int(row, "traffic_signal_group_count")
    traffic_term_count = row_int(row, "traffic_term_count")

    if has_strong_accident_signal(row):
        decision_reasons.append("strong_accident_signal")
    if has_supporting_context(row):
        decision_reasons.append("supporting_traffic_context")
    if score >= 8:
        decision_reasons.append("score_meets_confirmed_threshold")
    if signal_group_count >= 2:
        decision_reasons.append("signal_group_count_meets_confirmed_threshold")
    if traffic_term_count >= 3:
        decision_reasons.append("traffic_term_count_meets_confirmed_threshold")
    if reasons & WEAK_OR_GENERIC_REASONS:
        decision_reasons.extend(sorted(reasons & WEAK_OR_GENERIC_REASONS))
    if looks_law_only(row):
        decision_reasons.append("law_only_context_without_accident_damage")

    promote = (
        has_strong_accident_signal(row)
        and has_supporting_context(row)
        and score >= 8
        and signal_group_count >= 2
        and traffic_term_count >= 3
        and not looks_law_only(row)
        and "case_category_disallowed_for_confirmed" not in reasons
    )

    if promote:
        return "confirmed_traffic", decision_reasons

    return "non_traffic", decision_reasons or ["possible_not_enough_for_confirmed_traffic"]


def attach_review_fields(
    row: Dict[str, Any],
    source_label: str,
    final_label: str,
    decision_reasons: List[str],
) -> Dict[str, Any]:
    row = dict(row)
    row["traffic_verification_source_label"] = source_label
    row["traffic_verification_final_label"] = final_label
    row["traffic_verification_decision_reasons"] = decision_reasons
    row["traffic_label_before_verification"] = row.get("traffic_label")
    row["traffic_label"] = final_label
    return row


def run_review(args: argparse.Namespace) -> None:
    reclass_dir = Path(args.reclass_dir)
    out_dir = Path(args.out_dir)
    paths = prepare_output_paths(out_dir, fresh=args.fresh)

    confirmed_path = reclass_dir / CONFIRMED_FILE
    possible_path = reclass_dir / POSSIBLE_FILE
    non_traffic_path = reclass_dir / NON_TRAFFIC_FILE

    stats = ReviewStats()
    decision_counter: Counter[str] = Counter()
    original_reason_counter: Counter[str] = Counter()

    for row in read_jsonl(confirmed_path):
        stats.confirmed_input_rows += 1
        original_reason_counter.update(row.get("traffic_reclass_reasons") or [])

        final_label, decision_reasons = verify_confirmed_row(row)
        decision_counter.update(decision_reasons)
        reviewed = attach_review_fields(row, "confirmed_traffic", final_label, decision_reasons)

        if final_label == "confirmed_traffic":
            stats.confirmed_verified_rows += 1
            stats.final_confirmed_traffic_rows += 1
            write_jsonl(paths["confirmed"], reviewed)
        else:
            stats.confirmed_demoted_to_non_traffic_rows += 1
            stats.final_non_traffic_rows += 1
            write_jsonl(paths["non_traffic"], reviewed)
            write_jsonl(paths["demoted_from_confirmed"], reviewed)

        stats.final_all_rows += 1
        write_jsonl(paths["all"], reviewed)

    for row in read_jsonl(possible_path):
        stats.possible_input_rows += 1
        original_reason_counter.update(row.get("traffic_reclass_reasons") or [])

        final_label, decision_reasons = review_possible_row(row)
        decision_counter.update(decision_reasons)
        reviewed = attach_review_fields(row, "possible_traffic_review", final_label, decision_reasons)

        if final_label == "confirmed_traffic":
            stats.possible_promoted_to_confirmed_rows += 1
            stats.final_confirmed_traffic_rows += 1
            write_jsonl(paths["confirmed"], reviewed)
            write_jsonl(paths["promoted_from_possible"], reviewed)
        else:
            stats.possible_to_non_traffic_rows += 1
            stats.final_non_traffic_rows += 1
            write_jsonl(paths["non_traffic"], reviewed)
            write_jsonl(paths["possible_to_non"], reviewed)

        stats.final_all_rows += 1
        write_jsonl(paths["all"], reviewed)

    for row in read_jsonl(non_traffic_path):
        stats.non_traffic_input_rows += 1
        original_reason_counter.update(row.get("traffic_reclass_reasons") or [])

        reviewed = attach_review_fields(
            row,
            "non_traffic",
            "non_traffic",
            ["kept_original_non_traffic"],
        )
        stats.final_non_traffic_rows += 1
        stats.final_all_rows += 1
        decision_counter.update(["kept_original_non_traffic"])
        write_jsonl(paths["non_traffic"], reviewed)
        write_jsonl(paths["all"], reviewed)

    stats.decision_reason_counts = dict(decision_counter.most_common())
    stats.original_reason_counts = dict(original_reason_counter.most_common(100))

    report = {
        "review_goal": "2차 과실비율 분류 전에 traffic_prec_reclass 결과를 confirmed_traffic/non_traffic으로 검증 및 정리",
        "input_dir": str(reclass_dir),
        "output_dir": str(out_dir),
        "outputs": {key: str(path) for key, path in paths.items()},
        "decisions": {
            "confirmed_traffic": "교통사고 판례 근거가 충분해 2차 과실비율 분류 입력으로 유지 또는 승격",
            "non_traffic": "교통사고 판례 근거가 부족하거나 법규/면허/일반 교통 문맥에 가까워 2차 분류에서 제외",
        },
        "policy": [
            "교통 단어만으로 승격하지 않고 사고 신호와 보조 문맥을 함께 봅니다.",
            "기존 confirmed_traffic이라도 실제 사고 판례 근거가 약하면 non_traffic으로 내립니다.",
            "기존 possible_traffic_review 중 사고 신호와 손해배상/보험/책임 문맥이 강한 row만 confirmed_traffic으로 올립니다.",
            "기존 possible_traffic_review 중 confirmed로 올릴 만큼 강하지 않은 row는 non_traffic으로 보냅니다.",
            "기존 non_traffic은 최종 non_traffic에 그대로 유지합니다.",
            "최종 01_confirmed_traffic_cases.jsonl이 과실비율 2차 분류의 입력입니다.",
        ],
        "stats": asdict(stats),
    }

    with paths["report"].open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report["stats"], ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="2차 분류 전 traffic_prec_reclass 결과를 confirmed_traffic/non_traffic으로 검증 및 정리"
    )
    parser.add_argument(
        "--reclass-dir",
        default=DEFAULT_RECLASS_DIR,
        help=f"1차 재분류 결과 폴더. 기본값: {DEFAULT_RECLASS_DIR}",
    )
    parser.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"검증 결과 출력 폴더. 기본값: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="기존 출력 폴더를 삭제하고 새로 생성",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run_review(parse_args())
