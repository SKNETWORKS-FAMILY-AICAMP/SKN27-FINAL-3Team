from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


LocationMethod = Literal["대화입력", "검색", "지도선택"]


class Coordinate(BaseModel):
    위도: float = Field(ge=-90, le=90)
    경도: float = Field(ge=-180, le=180)


class RoadEnvironmentInput(BaseModel):
    사고위치: str
    주소: str | None = None
    확정좌표: Coordinate | None = None
    위치확정방식: LocationMethod = "대화입력"

    @field_validator("사고위치")
    @classmethod
    def accident_location_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("사고위치는 필수입니다.")
        return value.strip()

    @field_validator("확정좌표")
    @classmethod
    def coordinate_can_be_null(cls, value: Coordinate | None) -> Coordinate | None:
        return value

    def require_coordinate_when_confirmed(self) -> None:
        if self.위치확정방식 in {"검색", "지도선택"} and self.확정좌표 is None:
            raise ValueError("검색 또는 지도선택 상태에서는 확정좌표가 필요합니다.")


def default_output(
    status: str = "정보부족",
    location_status: str = "위치확인필요",
    candidates: list[dict[str, Any]] | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "스키마버전": "road_environment_output_v1",
        "조회상태": status,
        "위치확인결과": {
            "상태": location_status,
            "입력위치": None,
            "확인주소": None,
            "분석기준좌표": {"위도": None, "경도": None},
            "확인방식": "VWorld검색",
            "사용자확정여부": False,
            "검색후보": candidates or [],
            "확인필요사유": reasons or [],
        },
        "조회결과": {
            "도로안내": {
                "상태": "미확인",
                "관련표지수": 0,
                "기준도로": None,
                "도로종류": None,
                "도로노선번호": None,
                "도로노선방향": None,
                "차로수": None,
                "도로형태": None,
                "방향안내": [],
            },
            "교통시설": {
                "차량신호등": {"상태": "미확인", "관련시설수": 0, "상세": []},
                "횡단보도": {"상태": "미확인", "관련시설수": 0, "상세": []},
            },
            "보호구역": {"해당여부": "미확인", "유형": []},
            "OSM도로데이터": {
                "상태": "미조회",
                "조회방식": "PostGIS",
                "데이터원천": "대한민국 OSM PBF 적재본(OpenStreetMap)",
                "조회반경_m": None,
                "기준도로후보": [],
            },
        },
        "도로환경분석": {
            "분석상태": "미수행",
            "환경유형": [],
            "기준도로": {
                "도로명": None,
                "도로종류": None,
                "노선번호": None,
                "차로수": None,
                "일방통행": "미확인",
                "선정상태": "미확인",
                "선정근거": [],
            },
            "도로구조": {
                "교차로여부": "미확인",
                "교차로유형": None,
                "램프여부": "미확인",
                "분기합류여부": "미확인",
            },
            "확인수준": "낮음",
            "판정근거": [],
            "제한사항": [],
        },
        "도로환경요약": "",
        "사용출처": [],
    }
