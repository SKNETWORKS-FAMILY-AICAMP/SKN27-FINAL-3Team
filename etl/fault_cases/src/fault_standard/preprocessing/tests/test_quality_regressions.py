from etl.fault_cases.src.fault_standard.preprocessing.nontypical.classifiers import (
    build_road_context,
)
from etl.fault_cases.src.fault_standard.preprocessing.nontypical.extractors import (
    extract_claim_respondent_ratio_info,
)
from etl.fault_cases.src.fault_standard.preprocessing.nontypical.summary_parser import (
    should_use_detail_title,
)
from etl.fault_cases.src.fault_standard.preprocessing.official_2023.rule_splitter import (
    finalize_rule_section,
)
from etl.fault_cases.src.fault_standard.preprocessing.roundabout.extractors import (
    build_lane_path_context,
    extract_parties,
)


def test_roundabout_title_direction_and_narrative_lane_change_are_connected() -> None:
    text = """회전-99
진입 2개 차로에서 진입한 차량 간 12시 진출부 사고
레드(A) : 진입1차로 진입, 회전1차로 회전중 점선구간 진로변경
블루(B) : 회전2차로 회전, 진출1차로 진출
기본 과실비율
레드 70 : 블루 30
사고 상황
같은 방향에서 진입한 차량이 회전1차로에 진입하여 회전하다가 점선구간에서
회전2차로로 차로를 변경하던 중 회전2차로 차량과 충돌한 사고이다.
기본 과실비율 해설
"""

    parties = extract_parties(text, "roundabout_test_회전-99")
    red = next(party for party in parties if party["party_key"] == "A")
    blue = next(party for party in parties if party["party_key"] == "B")
    lane_context = build_lane_path_context(parties, text)

    assert red["lane_change_from"] == "회전1차로"
    assert red["lane_change_to"] == "회전2차로"
    assert "회전2차로" in lane_context["red_path"]
    assert blue["exit_direction"] == "12시 방향"
    assert lane_context["conflict_direction"] == "12시 방향"
    assert lane_context["conflict_direction_source"] == "explicit_rule_title"


def test_official_rule_stops_at_next_chapter_banner_before_page_limit() -> None:
    header = {
        "rule_code": "보99",
        "rule_prefix": "보",
        "rule_number": "99",
        "rule_title": "경계 검증용 보행자 사고",
    }
    block = """__PAGE_START__ 10
보99
경계 검증용 보행자 사고
기본 과실비율
A 80 : B 20
관련 법규
도로교통법 제1조
참고 판례
판례 본문

자동차
(이륜차 포함)의
과실비율 적용기준(사고유형별)
제2장

1. 적용 범위
다음 장 본문
__PAGE_START__ 11
다음 장 계속
"""

    section = finalize_rule_section(header, block)

    assert section["page_start"] == 10
    assert section["page_end"] == 10
    assert section["boundary_quality"]["page_span_limited"] is False
    assert section["boundary_quality"]["chapter_boundary_truncated"] is True
    assert "다음 장 본문" not in section["raw_text"]


def test_road_context_prefers_rule_title_and_understands_non_intersection() -> None:
    parking = build_road_context(
        "선행 주차진행차량과 후행 추월차량간 사고",
        "뒤쪽 판례에 교차로라는 단어가 등장한다.",
    )
    lane_change = build_road_context(
        "정차후 출발차량과 진로변경차량간 사고(교차로 아닌 곳)",
        "관련 법규에서 교차로를 설명한다.",
    )
    narrow_four_way = build_road_context(
        "중앙선 없는 이면도로 사거리에서 우회전차량과 직진차량간 사고",
        "동일폭 도로에서 양 차량이 충돌한 사고이다.",
    )

    assert parking["road_area"] == "주차장"
    assert parking["intersection_type"] is None
    assert lane_change["road_area"] == "동일차로"
    assert lane_change["intersection_type"] is None
    assert narrow_four_way["road_area"] == "교차로"
    assert narrow_four_way["intersection_type"] == "four_way_intersection"


def test_review_ratio_repairs_split_label_and_derives_single_missing_side() -> None:
    split_label = extract_claim_respondent_ratio_info(
        "청구차량 과 실 40%, 피청구차량 과실 60%"
    )
    one_side = extract_claim_respondent_ratio_info("청구차량 과실 30%는 적정함")

    assert (split_label["claim_ratio"], split_label["respondent_ratio"]) == (40, 60)
    assert split_label["inference_applied"] is False
    assert (one_side["claim_ratio"], one_side["respondent_ratio"]) == (30, 70)
    assert one_side["respondent_source"] == "derived_complement"
    assert one_side["inference_applied"] is True


def test_semantically_equal_summary_typo_uses_detail_title_as_canonical() -> None:
    assert should_use_detail_title(
        "추월 직진 차량과 선행 좌회전 차량과 사고",
        "추월 직진 차량과 선행 좌회전 차량 간 사고",
    ) is True
