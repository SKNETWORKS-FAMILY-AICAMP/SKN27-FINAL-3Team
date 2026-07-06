from __future__ import annotations

COMMON_SEARCH_FIELDS = [
    ("심의번호", "review_no"),
    ("청구/피청구 구분", "party_type"),
    ("사고유형", "case_title"),
    ("사고조건", "case_condition"),
    ("과실유형", "fault_type"),
    ("참고기준", "reference_chart_key"),
    ("결정비율", "decision_fault_ratio"),
    ("신호조건", "signal_condition"),
    ("도로특징", "road_feature"),
    ("A 표준행동", "standard_a_behavior"),
    ("B 표준행동", "standard_b_behavior"),
    ("청구인 표준행동", "claimant_standard_behavior"),
    ("피청구인 표준행동", "respondent_standard_behavior"),
    ("목차 대분류", "toc_large_category"),
    ("목차 중분류", "toc_middle_category"),
]

CHUNK_TYPE_LABELS = {
    "case_overview": "사례 개요",
    "arguments": "당사자 주장",
    "evidence_issue": "입증자료 및 쟁점",
    "decision": "결정근거 및 결정이유",
}

COMMON_EXTRA_LABELS = {
    "chunk_type": "청크유형",
    "standard_scenario_keywords": "참고기준 키워드",
    "claimant_final_ratio": "청구인 최종비율",
    "respondent_final_ratio": "피청구인 최종비율",
    "body": "본문",
}

TYPE_SPECIFIC_SEARCH_FIELDS = {
    "case_overview": [
        ("사고내용", "accident_content"),
        ("기본과실비율", "base_fault_ratio_text"),
        ("참고기준 원문", "standard_scenario_raw"),
    ],
    "arguments": [
        ("청구인 주장", "claimant_argument"),
        ("피청구인 주장", "respondent_argument"),
    ],
    "evidence_issue": [
        ("입증자료", "evidence_text"),
        ("쟁점", "main_issue"),
    ],
    "decision": [
        ("결정근거", "decision_basis"),
        ("결정이유", "decision_reason"),
        ("최종비율", "final_ratio_text"),
    ],
}
