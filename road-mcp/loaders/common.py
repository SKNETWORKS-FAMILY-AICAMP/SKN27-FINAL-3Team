from pathlib import Path

from app.config import Settings, get_settings


def ensure_data_dirs(settings: Settings | None = None) -> None:
    selected = settings or get_settings()
    for child in ("raw", "snapshots", "rejected"):
        (Path(selected.road_data_dir) / child).mkdir(parents=True, exist_ok=True)


def print_not_implemented(loader_name: str) -> None:
    print(f"{loader_name} scaffold is ready. Implement source-specific loading next.")
