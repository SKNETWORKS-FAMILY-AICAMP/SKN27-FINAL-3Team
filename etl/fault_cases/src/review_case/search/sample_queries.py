from __future__ import annotations


SAMPLE_QUERIES: list[dict[str, str]] = [
    {
        "query_id": "review_q001",
        "query": "신호등 없는 중앙선 설치 도로에서 중앙선을 침범한 역주행 사고",
        "expected_reference_chart_key": "249",
    },
    {
        "query_id": "review_q002",
        "query": "신호등 있는 사거리 교차로에서 녹색 직진 차량과 적색 직진 차량 충돌",
        "expected_reference_chart_key": "",
    },
    {
        "query_id": "review_q003",
        "query": "차로 변경 중 후행 직진 차량과 충돌한 사고의 과실비율",
        "expected_reference_chart_key": "",
    },
    {
        "query_id": "review_q004",
        "query": "비보호 좌회전 차량과 녹색 신호 직진 차량 사이 교차로 사고",
        "expected_reference_chart_key": "",
    },
    {
        "query_id": "review_q005",
        "query": "주차장 또는 이면도로에서 출차 차량과 직진 차량이 충돌한 사고",
        "expected_reference_chart_key": "",
    },
]
