"""Shared configuration for category VLM evaluation notebooks."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class CategoryConfig:
    key: str
    label: str
    prefix: str


@dataclass(frozen=True)
class ExperimentConfig:
    max_videos: int
    analysis_sample_count: int
    frame_count: int
    vlm_input_frame_count: int
    yolo_conf: float
    yolo_imgsz: int
    yolo_models: tuple[str, ...]
    qwen_model_id: str
    qwen_model_revision: str
    llava_model_id: str
    qwen_yolo_model: str | None
    drive_folder_url: str
    run_gdown_download: bool
    run_model_comparison: bool
    force_preprocess: bool


CATEGORIES = {
    "car_vs_car": CategoryConfig("car_vs_car", "차대차", "TS_차대차_영상_"),
    "car_vs_pedestrian": CategoryConfig("car_vs_pedestrian", "차대보행자", "TS_차대보행자_영상_"),
    "car_vs_motorcycle": CategoryConfig("car_vs_motorcycle", "차대이륜차", "TS_차대이륜차_영상_"),
    "car_vs_bicycle": CategoryConfig("car_vs_bicycle", "차대자전거", "TS_차대자전거_영상_"),
}

BEST_YOLO_MODELS = {
    "car_vs_car": "yolov8m.pt",
    "car_vs_pedestrian": "yolo11n.pt",
    "car_vs_motorcycle": "yolov8m.pt",
    "car_vs_bicycle": "yolo11s.pt",
}


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def get_category_config(key: str) -> CategoryConfig:
    try:
        return CATEGORIES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported vision category: {key}") from exc


def load_experiment_config(category_key: str) -> ExperimentConfig:
    models = tuple(
        item.strip()
        for item in os.getenv(
            "VISION_YOLO_MODELS",
            "yolov8n.pt,yolov8s.pt,yolov8m.pt,yolo11n.pt,yolo11s.pt",
        ).split(",")
        if item.strip()
    )
    if not models:
        raise ValueError("VISION_YOLO_MODELS must contain at least one model")
    confidence = float(os.getenv("VISION_YOLO_CONF", "0.25"))
    if not 0 < confidence <= 1:
        raise ValueError("VISION_YOLO_CONF must be in (0, 1]")

    selected_model = os.getenv("VISION_QWEN_YOLO_MODEL", BEST_YOLO_MODELS[category_key])
    run_model_comparison = _boolean("VISION_RUN_MODEL_COMPARISON")
    if not run_model_comparison:
        models = (selected_model,)

    return ExperimentConfig(
        max_videos=_positive_int("VISION_MAX_VIDEOS", 100),
        analysis_sample_count=_positive_int("VISION_ANALYSIS_SAMPLE_COUNT", 100),
        frame_count=_positive_int("VISION_FRAME_COUNT", 16),
        vlm_input_frame_count=_positive_int("VISION_VLM_INPUT_FRAME_COUNT", 16),
        yolo_conf=confidence,
        yolo_imgsz=_positive_int("VISION_YOLO_IMGSZ", 960),
        yolo_models=models,
        qwen_model_id=os.getenv(
            "VISION_QWEN_MODEL_ID", "Qwen/Qwen3-VL-4B-Instruct"
        ),
        qwen_model_revision=os.getenv(
            "VISION_QWEN_MODEL_REVISION",
            "",
        ),
        llava_model_id=os.getenv(
            "VISION_LLAVA_MODEL_ID", "llava-hf/llava-onevision-qwen2-7b-ov-hf"
        ),
        qwen_yolo_model=selected_model,
        drive_folder_url=os.getenv("VISION_DRIVE_FOLDER_URL", ""),
        run_gdown_download=_boolean("VISION_RUN_GDOWN_DOWNLOAD"),
        run_model_comparison=run_model_comparison,
        force_preprocess=_boolean("VISION_FORCE_PREPROCESS"),
    )


def find_project_root(start: Path | None = None) -> Path:
    configured = os.getenv("VISION_PROJECT_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not (root / "ai" / "vision").is_dir():
            raise FileNotFoundError(f"VISION_PROJECT_ROOT is not a project root: {root}")
        return root

    current = (start or Path.cwd()).resolve()
    candidates = [current, *current.parents]
    if current.is_dir():
        candidates.extend(path for path in current.iterdir() if path.is_dir())
    for candidate in candidates:
        if (candidate / "ai" / "vision").is_dir() and (candidate / "storage").is_dir():
            return candidate
    raise FileNotFoundError("Project root not found. Set VISION_PROJECT_ROOT.")
