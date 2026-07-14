import pytest

from app.schemas import RoadEnvironmentInput


def test_accepts_initial_dialog_input() -> None:
    payload = {
        "사고위치": "중앙사거리",
        "주소": None,
        "확정좌표": None,
        "위치확정방식": "대화입력",
    }
    parsed = RoadEnvironmentInput.model_validate(payload)
    assert parsed.사고위치 == "중앙사거리"


def test_rejects_blank_accident_location() -> None:
    with pytest.raises(ValueError):
        RoadEnvironmentInput.model_validate({"사고위치": "   "})


def test_confirmed_search_requires_coordinate() -> None:
    parsed = RoadEnvironmentInput.model_validate(
        {"사고위치": "중앙사거리", "위치확정방식": "검색"}
    )
    with pytest.raises(ValueError):
        parsed.require_coordinate_when_confirmed()
