from typing import Any

from app.schemas import RoadEnvironmentInput, default_output


def build_location_needed_response(
    request: RoadEnvironmentInput,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    output = default_output(
        status="위치확인필요",
        location_status="위치확인필요",
        candidates=candidates,
        reasons=["검색 후보가 여러 개이므로 사용자 선택이 필요합니다."],
    )
    output["위치확인결과"]["입력위치"] = request.사고위치
    return output


def build_no_location_response(request: RoadEnvironmentInput) -> dict[str, Any]:
    output = default_output(
        status="정보부족",
        location_status="위치정보부족",
        reasons=["VWorld 검색 후보가 없고 확정좌표도 없습니다."],
    )
    output["위치확인결과"]["입력위치"] = request.사고위치
    return output


def build_success_response(
    request: RoadEnvironmentInput,
    query_result: dict[str, Any],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    output = default_output(status="성공", location_status="분석가능")
    coord = request.확정좌표
    output["위치확인결과"].update(
        {
            "입력위치": request.사고위치,
            "확인주소": request.주소,
            "분석기준좌표": {"위도": coord.위도 if coord else None, "경도": coord.경도 if coord else None},
            "확인방식": request.위치확정방식,
            "사용자확정여부": request.위치확정방식 in {"검색", "지도선택"},
        }
    )
    output["조회결과"]["OSM도로데이터"].update(
        {
            "상태": "조회완료",
            "조회반경_m": query_result.get("radius_m"),
            "기준도로후보": query_result.get("road_candidates", []),
        }
    )

    base_road = analysis.get("base_road") or {}
    output["도로환경분석"]["분석상태"] = analysis.get("analysis_status", "미수행")
    output["도로환경분석"]["기준도로"].update(
        {
            "도로명": base_road.get("road_name"),
            "도로종류": base_road.get("highway_type"),
            "노선번호": base_road.get("road_ref"),
            "차로수": base_road.get("lane_count"),
            "일방통행": base_road.get("oneway") or "미확인",
            "선정상태": "선정" if base_road else "미확인",
            "선정근거": analysis.get("evidence", []),
        }
    )
    output["도로환경분석"]["판정근거"] = analysis.get("evidence", [])
    output["도로환경분석"]["제한사항"] = analysis.get("limitations", [])
    output["도로환경요약"] = "사고좌표 주변 도로환경 조회를 수행했습니다."
    output["사용출처"] = ["Road PostGIS - OpenStreetMap"]
    return output
