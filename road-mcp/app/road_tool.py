from typing import Any

from app.road_analysis import analyze_road_environment
from app.road_query import find_nearby_road_environment
from app.response_builder import (
    build_location_needed_response,
    build_no_location_response,
    build_success_response,
)
from app.schemas import Coordinate, RoadEnvironmentInput
from app.vworld_client import VWorldClient


async def inspect_road_environment(payload: dict[str, Any]) -> dict[str, Any]:
    request = RoadEnvironmentInput.model_validate(payload)
    request.require_coordinate_when_confirmed()

    if request.확정좌표 is None:
        candidates = await VWorldClient().search(request.사고위치)
        if len(candidates) > 1:
            return build_location_needed_response(request, candidates)
        if len(candidates) == 0:
            return build_no_location_response(request)

        candidate = candidates[0]
        coordinate = candidate.get("좌표") or {}
        request.확정좌표 = Coordinate.model_validate(coordinate)
        request.주소 = candidate.get("주소")
        request.위치확정방식 = "검색"

    query_result = find_nearby_road_environment(
        latitude=request.확정좌표.위도,
        longitude=request.확정좌표.경도,
    )
    analysis = analyze_road_environment(query_result)
    return build_success_response(request, query_result, analysis)
