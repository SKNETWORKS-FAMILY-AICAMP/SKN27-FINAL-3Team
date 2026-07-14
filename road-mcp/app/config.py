from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    road_mcp_host: str = Field(default="0.0.0.0", alias="ROAD_MCP_HOST")
    road_mcp_port: int = Field(default=8001, alias="ROAD_MCP_PORT")
    road_mcp_transport: str = Field(default="stdio", alias="ROAD_MCP_TRANSPORT")
    road_log_level: str = Field(default="INFO", alias="ROAD_LOG_LEVEL")

    vworld_api_key: str = Field(default="", alias="VWORLD_API_KEY")
    vworld_search_url: str = Field(
        default="https://api.vworld.kr/req/search",
        alias="VWORLD_SEARCH_URL",
    )
    vworld_request_timeout_seconds: int = Field(
        default=10,
        alias="VWORLD_REQUEST_TIMEOUT_SECONDS",
    )

    road_db_host: str = Field(default="localhost", alias="ROAD_DB_HOST")
    road_db_port: int = Field(default=5433, alias="ROAD_DB_PORT")
    road_db_name: str = Field(default="road_environment", alias="ROAD_DB_NAME")
    road_db_user: str = Field(default="road_user", alias="ROAD_DB_USER")
    road_db_password: str = Field(default="change-me", alias="ROAD_DB_PASSWORD")

    road_data_dir: Path = Field(default=Path("./data"), alias="ROAD_DATA_DIR")
    osm_pbf_url: str = Field(
        default="https://download.geofabrik.de/asia/south-korea-latest.osm.pbf",
        alias="OSM_PBF_URL",
    )
    public_data_api_key: str = Field(default="", alias="PUBLIC_DATA_API_KEY")
    public_data_default_num_of_rows: int = Field(
        default=100,
        alias="PUBLIC_DATA_DEFAULT_NUM_OF_ROWS",
    )
    public_data_request_timeout_seconds: int = Field(
        default=30,
        alias="PUBLIC_DATA_REQUEST_TIMEOUT_SECONDS",
    )
    road_signs_api_url: str = Field(default="", alias="ROAD_SIGNS_API_URL")
    traffic_signals_api_url: str = Field(default="", alias="TRAFFIC_SIGNALS_API_URL")
    crosswalks_api_url: str = Field(default="", alias="CROSSWALKS_API_URL")
    protection_zones_api_url: str = Field(default="", alias="PROTECTION_ZONES_API_URL")
    protection_zone_sgg_codes: str = Field(default="", alias="PROTECTION_ZONE_SGG_CODES")
    protection_zone_sgg_codes_csv: Path = Field(
        default=Path("./data/raw/reference/sgg_codes.csv"),
        alias="PROTECTION_ZONE_SGG_CODES_CSV",
    )
    protection_zone_assign_type: str = Field(default="", alias="PROTECTION_ZONE_ASSIGN_TYPE")
    protection_zone_call_date: str = Field(default="", alias="PROTECTION_ZONE_CALL_DATE")

    @property
    def protection_zone_sgg_code_list(self) -> list[str]:
        return [code.strip() for code in self.protection_zone_sgg_codes.split(",") if code.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.road_db_user}:{self.road_db_password}"
            f"@{self.road_db_host}:{self.road_db_port}/{self.road_db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
