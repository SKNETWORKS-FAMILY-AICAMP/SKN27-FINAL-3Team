from typing import Any


def analyze_road_environment(query_result: dict[str, Any]) -> dict[str, Any]:
    candidates = query_result.get("road_candidates", [])
    if not candidates:
        return {
            "analysis_status": "정보부족",
            "base_road": None,
            "evidence": ["반경 내 OSM 도로 후보가 없습니다."],
            "limitations": ["도로 데이터 적재 상태 또는 위치 좌표를 확인해야 합니다."],
        }

    base_road = candidates[0]
    return {
        "analysis_status": "성공",
        "base_road": base_road,
        "evidence": ["가장 가까운 OSM 도로 후보를 기준도로로 선택했습니다."],
        "limitations": ["V1 초기 뼈대에서는 교차로·램프 세부 판정은 아직 미구현입니다."],
    }
