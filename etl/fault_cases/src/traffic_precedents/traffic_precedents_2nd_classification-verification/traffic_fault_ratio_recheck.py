#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from rag_eligibility import (
    RAG_READY,
    RagEligibilityResult,
    assess_rag_eligibility,
)


REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_FAULT_RATIO_DIR = REPO_ROOT / (
    "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio"
)
DEFAULT_OUT_DIR = REPO_ROOT / (
    "etl/fault_cases/artifacts/traffic_precedents_output/traffic_prec_fault_ratio_rag_verified"
)

CONFIRMED_FILE = "01_fault_ratio_confirmed_cases.jsonl"
POSSIBLE_FILE = "02_fault_ratio_possible_review.jsonl"
NO_FAULT_RATIO_FILE = "03_traffic_but_no_fault_ratio_cases.jsonl"


@dataclass
class VerificationStats:
    fault_confirmed_input_rows: int = 0
    possible_input_rows: int = 0
    no_fault_input_rows: int = 0
    base_fault_ratio_confirmed_rows: int = 0
    base_no_fault_ratio_rows: int = 0
    base_confirmed_rag_ready_rows: int = 0
    base_confirmed_rag_excluded_rows: int = 0
    base_confirmed_review_flagged_rows: int = 0
    final_rag_ready_rows: int = 0
    final_rag_excluded_rows: int = 0
    final_review_flagged_rows: int = 0
    confirmed_source_rag_ready_rows: int = 0
    confirmed_source_rag_excluded_rows: int = 0
    confirmed_source_review_flagged_rows: int = 0
    possible_source_rag_ready_rows: int = 0
    possible_source_rag_excluded_rows: int = 0
    possible_source_review_flagged_rows: int = 0
    final_all_rows: int = 0
    decision_reason_counts: dict[str, int] = field(default_factory=dict)
    rag_reason_counts: dict[str, int] = field(default_factory=dict)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            row["_recheck_input_line_no"] = line_no
            yield row


def write_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _remove_output_dir(out_dir: Path) -> None:
    resolved = out_dir.resolve()
    workspace = REPO_ROOT.resolve()
    if resolved == workspace or workspace not in resolved.parents:
        raise ValueError(f"refusing to remove output outside workspace: {resolved}")
    shutil.rmtree(resolved)


def prepare_output_paths(out_dir: Path, fresh: bool) -> dict[str, Path]:
    if fresh and out_dir.exists():
        _remove_output_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "report": out_dir / "00_fault_ratio_rag_verification_report.json",
        "rag_ready": out_dir / "01_fault_ratio_rag_ready_cases.jsonl",
        "rag_excluded": out_dir / "02_fault_ratio_rag_excluded_cases.jsonl",
        "review_flagged": out_dir / "03_fault_ratio_review_flagged_cases.jsonl",
        "all": out_dir / "04_fault_ratio_rag_verified_all.jsonl",
        "demoted_from_confirmed": out_dir / "05_demoted_from_confirmed.jsonl",
        "promoted_from_possible": out_dir / "06_promoted_from_possible.jsonl",
        "possible_excluded": out_dir / "07_possible_excluded.jsonl",
        "rag_gate_rejected": out_dir / "08_rag_gate_rejected.jsonl",
    }
    for path in paths.values():
        if path.exists():
            path.unlink()
    return paths


def first_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return str(value)
    return ""


def check_spurious_signals(row: dict[str, Any]) -> tuple[bool, str]:
    number_examples = row.get("fault_ratio_number_examples", []) or []
    explicit_terms = row.get("fault_ratio_explicit_terms", []) or []
    if explicit_terms:
        return False, ""

    if not number_examples:
        return False, ""

    spurious_reason = ""
    for example in number_examples:
        text = str(example)
        has_real_context = any(
            term in text for term in ["과실비율", "과실상계", "책임제한", "책임비율"]
        ) or (
            any(term in text for term in ["과실", "책임", "분담"])
            and not any(term in text for term in ["지연손해", "장해", "노동능력", "이자", "연 "])
        )
        if has_real_context:
            return False, ""
        if any(term in text for term in ["연", "지연손해금", "지연이자", "법정이율", "소송촉진", "이율"]):
            spurious_reason = "interest_rate_only"
            continue
        if any(term in text for term in ["장해율", "상실률", "노동능력", "장해"]):
            spurious_reason = "disability_rate_only"
            continue
        return False, ""
    return True, spurious_reason or "ratio_noise_only"


def check_case_type(row: dict[str, Any]) -> tuple[bool, str]:
    case_category = first_value(row, "사건종류명", "case_category")
    case_number = first_value(row, "사건번호", "case_number")
    case_name = first_value(row, "사건명", "case_name")

    is_criminal_no = any(term in case_number for term in ["고단", "고합", "노", "도", "초"])
    is_admin_no = any(term in case_number for term in ["구", "누", "두"])
    is_criminal = "형사" in case_category or any(
        term in case_name
        for term in ["도로교통법", "교통사고처리특례법", "특례법위반", "도주치상", "위험운전", "음주운전", "무면허운전", "도주차량"]
    )
    is_admin = "행정" in case_category or "특허" in case_category or any(
        term in case_name
        for term in ["면허취소", "면허정지", "요양급여", "유족급여", "요양불승인", "해고", "징계", "진료수가"]
    )
    if is_criminal_no or (is_criminal and "민사" not in case_category):
        return True, "criminal_case"
    if is_admin_no or (is_admin and "민사" not in case_category):
        return True, "administrative_or_labor_case"
    return False, ""


def verify_fault_ratio_evidence(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    has_core = bool(row.get("has_core_fault_ratio_context", False))
    has_damage = bool(row.get("has_damage_or_insurance_context", False))
    signal_group_count = int(row.get("fault_ratio_signal_group_count", 0) or 0)
    no_fault_without_core = bool(row.get("no_fault_context_without_core", False))

    is_spurious, spurious_reason = check_spurious_signals(row)
    if is_spurious:
        reasons.append(f"spurious_ratio_apportionment_{spurious_reason}")
        has_core = False
        if row.get("fault_ratio_no_fault_terms", []):
            no_fault_without_core = True

    is_non_civil, non_civil_reason = check_case_type(row)
    if is_non_civil:
        reasons.append(f"non_civil_case_type_{non_civil_reason}")

    has_damage_terms = bool(row.get("fault_ratio_damage_terms", []))
    has_explicit = bool(row.get("fault_ratio_explicit_terms", []))
    has_numerical = bool(row.get("fault_ratio_number_examples", [])) and not is_spurious
    is_damage_only = has_damage_terms and not has_explicit and not has_numerical
    if is_damage_only:
        reasons.append("damage_calculation_only_without_fault_ratio")

    adjusted_groups = max(0, signal_group_count - 1) if is_spurious else signal_group_count
    confirmed = (
        has_core
        and has_damage
        and adjusted_groups >= 2
        and not no_fault_without_core
        and not is_non_civil
        and not is_damage_only
    )
    if confirmed:
        return "fault_ratio_confirmed", reasons or ["verified_fault_ratio_evidence"]
    return "traffic_but_no_fault_ratio", reasons or ["insufficient_fault_ratio_evidence"]


def final_label_for(base_label: str, rag_result: RagEligibilityResult) -> str:
    if base_label != "fault_ratio_confirmed":
        return "traffic_but_no_fault_ratio"
    if rag_result.status == RAG_READY:
        return "fault_ratio_confirmed"
    return "fault_ratio_rag_excluded"


def attach_verification_fields(
    row: dict[str, Any],
    source_label: str,
    base_label: str,
    final_label: str,
    decision_reasons: list[str],
    rag_result: RagEligibilityResult,
) -> dict[str, Any]:
    updated = dict(row)
    updated["fault_ratio_label_before_verification"] = row.get("fault_ratio_label")
    updated["fault_ratio_verification_source_label"] = source_label
    updated["fault_ratio_evidence_verification_label"] = base_label
    updated["fault_ratio_verification_final_label"] = final_label
    updated["fault_ratio_label"] = final_label
    updated["fault_ratio_verification_decision_reasons"] = sorted(decision_reasons)
    updated["rag_eligibility"] = rag_result.status
    updated["rag_eligibility_reasons"] = rag_result.reasons
    updated["rag_review_flags"] = rag_result.review_flags
    updated["rag_eligibility_evidence"] = rag_result.evidence
    return updated


def _record_result(
    verified_row: dict[str, Any],
    source_label: str,
    base_label: str,
    final_label: str,
    paths: dict[str, Path],
    stats: VerificationStats,
) -> None:
    if base_label == "fault_ratio_confirmed":
        stats.base_fault_ratio_confirmed_rows += 1
    else:
        stats.base_no_fault_ratio_rows += 1

    if final_label == "fault_ratio_confirmed":
        stats.final_rag_ready_rows += 1
        if base_label == "fault_ratio_confirmed":
            stats.base_confirmed_rag_ready_rows += 1
        write_jsonl(paths["rag_ready"], verified_row)
        if source_label == "fault_ratio_confirmed":
            stats.confirmed_source_rag_ready_rows += 1
        elif source_label == "fault_ratio_possible_review":
            stats.possible_source_rag_ready_rows += 1
            write_jsonl(paths["promoted_from_possible"], verified_row)
    else:
        stats.final_rag_excluded_rows += 1
        write_jsonl(paths["rag_excluded"], verified_row)
        if base_label == "fault_ratio_confirmed":
            stats.base_confirmed_rag_excluded_rows += 1
            write_jsonl(paths["rag_gate_rejected"], verified_row)
        if source_label == "fault_ratio_confirmed":
            stats.confirmed_source_rag_excluded_rows += 1
            write_jsonl(paths["demoted_from_confirmed"], verified_row)
        elif source_label == "fault_ratio_possible_review":
            stats.possible_source_rag_excluded_rows += 1
            write_jsonl(paths["possible_excluded"], verified_row)

    if final_label == "fault_ratio_confirmed" and verified_row["rag_review_flags"]:
        stats.final_review_flagged_rows += 1
        stats.base_confirmed_review_flagged_rows += 1
        if source_label == "fault_ratio_confirmed":
            stats.confirmed_source_review_flagged_rows += 1
        elif source_label == "fault_ratio_possible_review":
            stats.possible_source_review_flagged_rows += 1
        write_jsonl(paths["review_flagged"], verified_row)

    stats.final_all_rows += 1
    write_jsonl(paths["all"], verified_row)


def run_verification(args: argparse.Namespace) -> dict[str, Any]:
    fault_ratio_dir = Path(args.fault_ratio_dir)
    out_dir = Path(args.out_dir)
    inputs = {
        "fault_ratio_confirmed": fault_ratio_dir / CONFIRMED_FILE,
        "fault_ratio_possible_review": fault_ratio_dir / POSSIBLE_FILE,
        "traffic_but_no_fault_ratio": fault_ratio_dir / NO_FAULT_RATIO_FILE,
    }
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing required input files: {missing}")

    paths = prepare_output_paths(out_dir, fresh=args.fresh)
    stats = VerificationStats()
    decision_counter: Counter[str] = Counter()
    rag_counter: Counter[str] = Counter()

    for source_label, input_path in inputs.items():
        for row in read_jsonl(input_path):
            if source_label == "fault_ratio_confirmed":
                stats.fault_confirmed_input_rows += 1
                base_label, decision_reasons = verify_fault_ratio_evidence(row)
            elif source_label == "fault_ratio_possible_review":
                stats.possible_input_rows += 1
                base_label, decision_reasons = verify_fault_ratio_evidence(row)
            else:
                stats.no_fault_input_rows += 1
                base_label = "traffic_but_no_fault_ratio"
                decision_reasons = ["kept_original_no_fault_ratio"]

            rag_result = assess_rag_eligibility(row, base_label)
            final_label = final_label_for(base_label, rag_result)
            decision_counter.update(decision_reasons)
            rag_counter.update(rag_result.reasons)
            verified_row = attach_verification_fields(
                row,
                source_label,
                base_label,
                final_label,
                decision_reasons,
                rag_result,
            )
            _record_result(
                verified_row,
                source_label,
                base_label,
                final_label,
                paths,
                stats,
            )

    stats.decision_reason_counts = dict(decision_counter.most_common())
    stats.rag_reason_counts = dict(rag_counter.most_common())
    report = {
        "verification_goal": "2차 과실비율 증거 검증과 recall-first 판례 RAG 코퍼스 확정",
        "input_dir": str(fault_ratio_dir),
        "output_dir": str(out_dir),
        "outputs": {key: str(path) for key, path in paths.items()},
        "policy": [
            "과실비율 증거 검증을 통과한 row만 RAG 적합성 평가 대상으로 사용합니다.",
            "1,006건의 과실비율 확인 판례를 기본 코퍼스로 유지합니다.",
            "소송비용, 이자율, 장해율, 근무비율 등 숫자 노이즈를 사고 당사자 과실비율과 분리합니다.",
            "사건명 자체가 명백한 비교통 사건일 때만 excluded로 판정합니다.",
            "약한 교통 표현, 부수 쟁점, 과실 문장 연결성은 제외하지 않고 rag_review_flags로 기록합니다.",
            "review_flagged 파일은 rag_ready에 포함된 부분집합이며 후속 청킹과 임베딩에서 제외하지 않습니다.",
        ],
        "stats": asdict(stats),
    }
    with paths["report"].open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify fault-ratio evidence and road-traffic RAG eligibility."
    )
    parser.add_argument("--fault-ratio-dir", default=DEFAULT_FAULT_RATIO_DIR)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--fresh", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run_verification(parse_args())
