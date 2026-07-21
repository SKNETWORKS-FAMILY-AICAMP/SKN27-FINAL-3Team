from __future__ import annotations

import sys
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODULE_DIR))

from rag_eligibility import (  # noqa: E402
    RAG_EXCLUDED,
    RAG_READY,
    assess_rag_eligibility,
)
from traffic_fault_ratio_recheck import verify_fault_ratio_evidence  # noqa: E402


def classified_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "_case_id": "case-1",
        "사건명": "손해배상(자)",
        "사건번호": "2024나1",
        "사건종류명": "민사",
        "판시사항": "교차로에서 발생한 차량 충돌 사고의 과실비율",
        "판결요지": "원고 차량은 직진하고 피고 차량은 좌회전하다 충돌하였다.",
        "이유": "원고 운전자의 과실을 30%로 참작하고 피고의 책임을 70%로 제한한다.",
        "has_core_fault_ratio_context": True,
        "has_damage_or_insurance_context": True,
        "fault_ratio_signal_group_count": 3,
        "no_fault_context_without_core": False,
        "fault_ratio_damage_terms": ["손해배상"],
        "fault_ratio_explicit_terms": ["과실비율"],
        "fault_ratio_number_examples": ["원고 운전자의 과실을 30%로 참작"],
        "fault_ratio_no_fault_terms": [],
    }
    row.update(overrides)
    return row


class RagEligibilityTest(unittest.TestCase):
    def test_valid_traffic_fault_case_is_ready(self) -> None:
        row = classified_row()
        base_label, _ = verify_fault_ratio_evidence(row)
        result = assess_rag_eligibility(row, base_label)
        self.assertEqual("fault_ratio_confirmed", base_label)
        self.assertEqual(RAG_READY, result.status)
        self.assertTrue(result.evidence["traffic_core_snippets"])
        self.assertTrue(result.evidence["fault_ratio_snippets"])
        self.assertTrue(result.evidence["traffic_linked_fault_ratio_snippets"])

    def test_defamation_case_with_litigation_cost_ratio_is_excluded(self) -> None:
        row = classified_row(
            사건명="명예훼손에 따른 손해배상",
            판시사항=None,
            판결요지=None,
            이유=(
                "5·18 회고록의 출판 금지와 인격권 침해 여부를 판단한다. "
                "소송총비용 중 원고들이 10%, 피고가 90%를 부담한다. "
                "다른 증거에는 음주운전 교통사고라는 표현이 인용되어 있다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_EXCLUDED, result.status)
        self.assertIn("explicit_non_traffic_case_title", result.reasons)

    def test_labor_case_with_road_patrol_terms_is_excluded(self) -> None:
        row = classified_row(
            사건명="근로자지위확인등",
            판시사항=None,
            판결요지=None,
            이유=(
                "도로 안전순찰원의 근로자파견과 직접고용 의무가 쟁점이다. "
                "피고의 손해배상책임을 80%로 제한한다. 순찰 차량을 운행하였다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_EXCLUDED, result.status)
        self.assertIn("employment_status_case", result.reasons)

    def test_traffic_evidence_only_late_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항=None,
            판결요지=None,
            이유=(
                "절차 경과와 당사자 주장을 판단한다. " * 300
                + "교차로에서 원고 차량과 피고 차량이 충돌하였다. "
                + "원고의 과실비율을 30%로 판단한다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "traffic_evidence_outside_high_signal_fields",
            result.review_flags,
        )

    def test_litigation_cost_is_not_fault_ratio_evidence(self) -> None:
        row = classified_row(
            판시사항="교차로에서 발생한 차량 충돌 사고",
            판결요지="원고 차량과 피고 차량이 교차로에서 충돌하였다.",
            이유="소송총비용 중 원고가 30%, 피고가 70%를 부담한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn("fault_ratio_evidence_requires_review", result.review_flags)
        self.assertIn("contains_ratio_noise", result.review_flags)

    def test_spaced_fault_ratio_beats_nearby_interest_noise(self) -> None:
        row = classified_row(
            이유=(
                "원고 차량과 피고 택시가 교차로에서 충돌하였다. "
                "피고 택시의 과실 비율 20%에 해당하는 구상금 및 이에 대한 "
                "지연손해금을 지급할 의무가 있다."
            )
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)

    def test_medical_issue_with_traffic_background_is_retained_with_flag(self) -> None:
        row = classified_row(
            사건명="항소",
            판시사항="의사가 교통사고 환자에게 필요한 검사를 하지 않은 진단상 과실",
            판결요지="교통사고 후 복부통증 환자에 대한 의료기관의 진료와 전원 의무",
            이유=(
                "피해 차량 충돌 후 병원에 내원한 환자에 대하여 의사가 검사를 하지 않았다. "
                "의료기관의 책임을 30%로 제한한다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn("medical_malpractice", result.evidence["non_traffic_indicators"])
        self.assertIn(
            "suspected_non_traffic_issue:medical_malpractice",
            result.review_flags,
        )

    def test_explicit_family_driver_coverage_title_is_excluded(self) -> None:
        row = classified_row(
            사건명="가족운전자한정특약부존재확인",
            판시사항="자동차보험 가족운전자 한정특약의 적용범위",
            판결요지="피보험차량을 가족이 운전한 경우 보험금 지급사유",
            이유="자동차를 운행하였고 보험자의 책임을 70%로 제한한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_EXCLUDED, result.status)
        self.assertIn("explicit_non_traffic_case_title", result.reasons)

    def test_explicit_traffic_fault_title_is_ready(self) -> None:
        row = classified_row(
            사건명="손해배상(기)[쌍방과실로 교통사고가 발생한 사건]",
            판시사항=None,
            판결요지=None,
            이유="쌍방과실로 교통사고가 발생하여 원고의 과실비율을 30%로 본다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)

    def test_unrelated_liability_issue_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항="교통사고 조사 후 경찰관이 구호조치를 하지 않은 직무위반 사건",
            판결요지="원고 차량이 교차로에서 다른 차량과 충돌한 뒤 경찰서에서 조사받았다.",
            이유=(
                "원고 차량과 상대 차량이 교차로에서 충돌하였다. "
                + "진료 경과와 형집행 절차를 검토한다. " * 100
                + "경찰관의 구호조치 위반을 이유로 국가의 책임을 60%로 제한한다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "suspected_non_traffic_issue:public_custody_or_enforcement",
            result.review_flags,
        )

    def test_travel_contract_bus_accident_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            사건명="손해배상(기)",
            판시사항=None,
            판결요지=None,
            이유=(
                "여행업자가 체결한 패키지 여행계약에 따라 관광객들이 버스로 이동하던 중 "
                "버스가 도로에서 미끄러져 다른 차량과 충돌하였다. "
                "여행업자의 계약상 책임과 과실상계 여부를 판단한다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn("suspected_non_traffic_issue:travel_contract", result.review_flags)

    def test_legal_malpractice_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항="교통사고 손해배상 판결에 대한 변호사의 항소 누락",
            판결요지="원고 차량과 피고 차량이 교차로에서 충돌한 선행 사건",
            이유=(
                "선행 교통사고에서 원고의 과실비율은 70%로 판단되었다. "
                "변호사가 항소기간을 도과한 과실로 손해배상책임을 부담한다."
            ),
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn("suspected_non_traffic_issue:legal_malpractice", result.review_flags)

    def test_bollard_trip_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항=(
                "보행자가 인도에 설치된 자동차 진입억제용 말뚝에 걸려 넘어져 "
                "지방자치단체의 책임이 문제된 사건"
            ),
            판결요지="보행자가 자동차 진입억제용 말뚝에 부딪혀 상해를 입었다.",
            이유="시설 관리상 과실을 고려하여 지방자치단체의 책임을 60%로 제한한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "suspected_non_traffic_issue:pedestrian_facility_accident",
            result.review_flags,
        )

    def test_weather_traffic_disruption_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항="폭설로 차량과 운전자가 고속도로에 장시간 고립된 사건",
            판결요지="고속도로에서 차량들이 미끄러져 교통정체가 발생하였다.",
            이유="도로 관리상 과실과 이용자의 과실상계 여부를 판단한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "suspected_non_traffic_issue:weather_traffic_disruption",
            result.review_flags,
        )

    def test_insurance_exclusion_issue_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            사건명="보험금",
            판시사항="무보험자동차상해 약관의 음주운전 면책조항 효력",
            판결요지="피보험차량이 다른 차량과 충돌한 보험사고에 관한 면책약관",
            이유="중대한 과실이 있더라도 자기신체사고 보험금을 지급할 의무가 있다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "suspected_non_traffic_issue:insurance_coverage_only",
            result.review_flags,
        )

    def test_retrial_issue_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항="차량 충돌 사건의 재심대상판결에서 형사재판이 변경된 경우",
            판결요지="교차로 차량 충돌 후 민사소송법상 재심사유가 문제되었다.",
            이유="선행 판결의 과실비율은 30%였으나 이 사건은 재심사유를 판단한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn("suspected_non_traffic_issue:civil_procedure_only", result.review_flags)

    def test_pension_offset_issue_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항="교통사고 사망자의 퇴직연금과 직무상유족연금 공제 순서",
            판결요지="택시가 오토바이와 충돌한 사고의 유족연금 공제 범위",
            이유="택시 운전자의 과실로 사고가 발생하였고 직무상유족연금을 공제한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "suspected_non_traffic_issue:pension_or_benefit_offset",
            result.review_flags,
        )

    def test_crane_operation_accident_is_retained_with_review_flag(self) -> None:
        row = classified_row(
            판시사항="크레인차량의 조작방법을 가르치던 중 발생한 사고",
            판결요지="크레인 아웃트리거를 고정하지 않아 차량이 전복되었다.",
            이유="크레인 조작상 과실을 고려하여 작업자의 책임을 30%로 제한한다.",
        )
        result = assess_rag_eligibility(row, "fault_ratio_confirmed")
        self.assertEqual(RAG_READY, result.status)
        self.assertIn(
            "suspected_non_traffic_issue:workplace_or_leisure_accident",
            result.review_flags,
        )

    def test_unconfirmed_fault_evidence_is_excluded_before_rag_gate(self) -> None:
        result = assess_rag_eligibility(classified_row(), "traffic_but_no_fault_ratio")
        self.assertEqual(RAG_EXCLUDED, result.status)
        self.assertEqual(["fault_ratio_evidence_not_confirmed"], result.reasons)


if __name__ == "__main__":
    unittest.main()
