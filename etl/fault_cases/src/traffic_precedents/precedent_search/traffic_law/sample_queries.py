from __future__ import annotations

from typing import TypedDict


class TrafficLawSampleQuery(TypedDict):
    query_id: str
    query: str
    issue_tags: list[str]
    purpose: str


TRAFFIC_LAW_SAMPLE_QUERIES: list[TrafficLawSampleQuery] = [
    {
        "query_id": "traffic_law_q001",
        "query": "신호위반 교통사고 판례",
        "issue_tags": ["신호위반", "교차로", "주의의무"],
        "purpose": "신호위반 사고에서 운전자 주의의무와 책임 판단 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q002",
        "query": "중앙선 침범 사고 운전자 책임",
        "issue_tags": ["중앙선 침범", "반대차선", "주의의무"],
        "purpose": "중앙선 침범 또는 역주행 사고의 책임 판단 근거를 찾는다.",
    },
    {
        "query_id": "traffic_law_q003",
        "query": "횡단보도 보행자 사고 운전자 주의의무",
        "issue_tags": ["횡단보도", "보행자 보호의무", "전방주시의무"],
        "purpose": "횡단보도 보행자 사고에서 운전자의 보호의무 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q004",
        "query": "음주운전 교통사고 형사 책임",
        "issue_tags": ["음주운전", "형사책임", "위험운전"],
        "purpose": "음주운전 사고의 형사책임 또는 법률상 책임 판단 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q005",
        "query": "뺑소니 사고 후 미조치 판례",
        "issue_tags": ["뺑소니", "사고 후 미조치", "도주차량"],
        "purpose": "사고 후 미조치 또는 도주 관련 교통사고 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q006",
        "query": "전동킥보드 교통사고 법적 책임",
        "issue_tags": ["전동킥보드", "개인형 이동장치", "교통사고 책임"],
        "purpose": "전동킥보드 또는 개인형 이동장치 사고 책임 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q007",
        "query": "오토바이와 자동차 충돌 사고 책임",
        "issue_tags": ["오토바이", "이륜차", "차량 충돌"],
        "purpose": "이륜차와 자동차 충돌 사고의 주의의무와 책임 판단 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q008",
        "query": "후방추돌 사고 안전거리 주의의무",
        "issue_tags": ["후방추돌", "안전거리", "전방주시의무"],
        "purpose": "후방추돌 사고에서 안전거리 확보와 전방주시의무 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q009",
        "query": "어린이보호구역 사고 처벌 판례",
        "issue_tags": ["어린이보호구역", "보호의무", "처벌"],
        "purpose": "어린이보호구역 사고의 법적 책임 또는 처벌 관련 판례를 찾는다.",
    },
    {
        "query_id": "traffic_law_q010",
        "query": "교차로 좌회전 직진 충돌 주의의무",
        "issue_tags": ["교차로", "좌회전", "직진", "주의의무"],
        "purpose": "교차로 좌회전/직진 충돌 사고의 통행방법과 주의의무 판례를 찾는다.",
    },
]


def get_traffic_law_sample_queries() -> list[TrafficLawSampleQuery]:
    return list(TRAFFIC_LAW_SAMPLE_QUERIES)

