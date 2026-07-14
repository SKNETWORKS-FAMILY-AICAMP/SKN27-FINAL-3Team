from app.response_builder import build_no_location_response
from app.schemas import RoadEnvironmentInput


def test_no_location_response_keeps_v1_schema_version() -> None:
    request = RoadEnvironmentInput.model_validate({"사고위치": "없는 장소명"})
    output = build_no_location_response(request)
    assert output["스키마버전"] == "road_environment_output_v1"
    assert output["조회상태"] == "정보부족"
    assert output["위치확인결과"]["상태"] == "위치정보부족"
