from types import SimpleNamespace

from etl.fault_cases.src.review_case.preprocessing.quality_validator import (
    _header_warning_flags,
    build_summary,
)
from etl.fault_cases.src.review_case.preprocessing.section_parser import parse_header
from etl.fault_cases.src.review_case.preprocessing.standard_scenario_parser import (
    parse_standard_scenario,
)


def test_parse_header_splits_only_an_explicit_context_separator() -> None:
    result = parse_header(
        """092
1. 자동차와 자동차의 사고
차대차 직진 대 직진 사고 - 사거리 교차로(도로폭 기준)
직진 대 직진 사고
(기본과실)
참고기준
심의번호
2019-000001
"""
    )

    assert result.party_type == "차대차"
    assert result.header_accident_group == "직진 대 직진 사고"
    assert result.header_road_context == "사거리 교차로(도로폭 기준)"
    assert result.header_parse_method == "hyphen_split"


def test_parse_header_uses_position_after_chapter_heading_without_title_vocabulary() -> None:
    text = """448
3. 고속도로의 사고
고속도로 합류도로 사고
합류도로 사고
(기본과실)
참고기준
501
신호등 없음
고속도로
본선차
합류차
사례 개요
심의번호
2019-018393
"""

    header = parse_header(text)
    scenario = parse_standard_scenario(text, header.header_title_raw)

    assert header.party_type is None
    assert header.header_title_raw == "고속도로 합류도로 사고"
    assert header.header_accident_group == "고속도로 합류도로 사고"
    assert header.header_road_context is None
    assert header.header_parse_method == "chapter_anchor_single_group"
    assert scenario.case_title == "합류도로 사고"


def test_single_group_without_explicit_context_is_not_a_missing_field_warning() -> None:
    single_group = SimpleNamespace(
        header_title_raw="차대차 기타 도로유형 사고",
        header_accident_group="기타 도로유형 사고",
        header_road_context=None,
        header_parse_method="single_group",
    )
    malformed_split = SimpleNamespace(
        header_title_raw="차대차 직진 사고 - 사거리 교차로",
        header_accident_group="직진 사고",
        header_road_context=None,
        header_parse_method="hyphen_split",
    )
    missing_header = SimpleNamespace(
        header_title_raw=None,
        header_accident_group=None,
        header_road_context=None,
        header_parse_method=None,
    )

    assert _header_warning_flags(single_group) == []
    assert _header_warning_flags(malformed_split) == ["header_road_context_missing"]
    assert _header_warning_flags(missing_header) == ["header_parse_failed"]


def test_optional_context_null_is_reported_as_coverage_not_a_warning() -> None:
    documents = [
        SimpleNamespace(parse_status="valid", header_road_context=None),
        SimpleNamespace(parse_status="valid", header_road_context="사거리 교차로"),
    ]

    summary = build_summary(
        documents=documents,
        source_chunks=[],
        chunks=[],
        quality_rows=[],
        toc_count=0,
        toc_link_count=0,
    )

    assert summary["warning_flag_counts"] == {}
    assert summary["optional_field_null_counts"] == {"header_road_context": 1}
