"""국가법령정보센터 대량 일반 과실비율 판례 수집용 단일 핵심 질의 모듈."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchQuery:
    """일반 판례 후보 목록 수집용 검색 질의 모델."""

    query_id: str
    category: str
    query_text: str
    description: str


# 국가법령정보센터 API 인덱싱에 최적화된 핵심 질의어 묶음
GENERAL_SEARCH_QUERIES: tuple[SearchQuery, ...] = (
    # 1. 사고유형 및 장소
    SearchQuery("Q_01", "사고유형", "교통사고", "교통사고 전반 판례 후보 수집"),
    SearchQuery("Q_02", "사고유형", "자동차", "자동차 관련 판례 후보 수집"),
    SearchQuery("Q_03", "사고유형", "교차로", "교차로 사고 판례 후보 수집"),
    SearchQuery("Q_04", "사고유형", "중앙선", "중앙선 침범/관련 사고 후보 수집"),
    SearchQuery("Q_05", "사고유형", "추돌", "후방/측면 추돌 사고 후보 수집"),
    SearchQuery("Q_06", "사고유형", "차로변경", "차로변경 사고 후보 수집"),
    SearchQuery("Q_07", "사고유형", "보행자", "보행자 사고 판례 후보 수집"),

    # 2. 과실 및 책임 판단
    SearchQuery("Q_08", "과실판단", "과실", "과실 판단 전반 판례 후보 수집"),
    SearchQuery("Q_09", "과실판단", "과실상계", "과실상계 비율 판례 후보 수집"),
    SearchQuery("Q_10", "과실판단", "주의의무", "주의의무 위반 판례 후보 수집"),
    SearchQuery("Q_11", "과실판단", "책임제한", "책임 제한 판례 후보 수집"),
    SearchQuery("Q_12", "과실판단", "손해배상", "손해배상 판례 후보 수집"),

    # 3. 보험 및 구상 legal support 법리
    SearchQuery("Q_13", "보험구상", "구상금", "구상금 청구 판례 후보 수집"),
    SearchQuery("Q_14", "보험구상", "운행자책임", "자배법상 운행자책임 후보 수집"),
    SearchQuery("Q_15", "보험구상", "보험자대위", "보험자대위권 판례 후보 수집"),
)


def get_all_queries() -> list[SearchQuery]:
    """모든 일반 판례 수집 질의 리스트를 반환합니다."""
    return list(GENERAL_SEARCH_QUERIES)
