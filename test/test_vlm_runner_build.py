from pathlib import Path
import csv

from ai.vision.vlm_json import (
    adaptive_retry_prompt,
    completed_vlm_asset_ids,
    retry_token_limit,
)


def _build_notebook():
    runner = Path("scripts/vision/run_vlm32_independent.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(Path("scripts/vision/run_vlm32_independent.py").resolve())}
    exec(runner.split("parser = argparse.ArgumentParser()", 1)[0], namespace)
    source = Path(
        "scripts/vision/vision_category_yolo_qwen_car_vs_car_known_label_runpod.ipynb"
    )
    return namespace["build_notebook"](source, "qwen")


def test_qwen_job_uses_cached_yolo_and_one_metadata_model():
    notebook = _build_notebook()
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])

    assert "cached_summary_rows:" in source
    assert "for model_name in YOLO_MODELS" not in source
    assert "if row['yolo_model'] not in _metadata_yolo_models:" in source
    assert "_metadata_yolo_models.setdefault" not in source
    assert "build_qwen_content(used_paths, used_metadata" in source
    assert "qwen_retry_pending:" in source


def test_qwen_pilot_uses_existing_invalid_rows():
    runner = Path("scripts/vision/run_vlm32_independent.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(Path("scripts/vision/run_vlm32_independent.py").resolve())}
    exec(runner.split("parser = argparse.ArgumentParser()", 1)[0], namespace)
    notebook = namespace["build_notebook"](
        Path("scripts/vision/vision_category_yolo_qwen_car_vs_car_known_label_runpod.ipynb"),
        "qwen",
        30,
    )
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])

    assert "qwen_invalid_pilot:" in source
    assert "[:30]" in source


def test_yolo_job_prepares_all_300_rows_without_loading_vlm():
    runner = Path("scripts/vision/run_vlm32_independent.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(Path("scripts/vision/run_vlm32_independent.py").resolve())}
    exec(runner.split("parser = argparse.ArgumentParser()", 1)[0], namespace)
    notebook = namespace["build_notebook"](
        Path("scripts/vision/vision_category_yolo_qwen_car_vs_car_known_label_runpod.ipynb"),
        "yolo",
    )
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])

    assert "for model_name in YOLO_MODELS" in source
    assert "write_csv(summary_rows" in source
    assert "qwen_results = []" not in source
    assert "llava_results = []" not in source
    assert "YOLO_QWEN_MODEL" not in source
    assert "Expected 300 prepared 32-frame directories" in source
    assert "if len(raw_paths) != 32:" in source
    assert "if len(raw_paths) != frame_count:" not in source


def test_yolo_summary_count_prefers_new_300_row_output(tmp_path):
    runner = Path("scripts/vision/run_vlm32_independent.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(Path("scripts/vision/run_vlm32_independent.py").resolve())}
    exec(runner.split("parser = argparse.ArgumentParser()", 1)[0], namespace)
    namespace["ROOT"] = tmp_path
    base = tmp_path / "storage/vision/outputs/category_yolo_qwen_compare/car_vs_car"
    for path, count in (
        (base / "yolo_summary.csv", 100),
        (base / "known_label_adaptive_32frames/yolo_summary.csv", 300),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["asset_id"])
            writer.writeheader()
            writer.writerows({"asset_id": f"asset-{index}"} for index in range(count))

    assert namespace["yolo_summary_count"]("car_vs_car") == 300


def test_adaptive_retry_matches_failure_type():
    assert "scene_conditions.evidence" in adaptive_retry_prompt(
        "schema_invalid:missing:scene_conditions.evidence"
    )
    assert retry_token_limit("json_incomplete:Unterminated string") == 1024
    assert retry_token_limit("schema_invalid:enum:bbox_quality") == 512


def test_resume_skips_every_existing_result_including_invalid():
    rows = [
        {"asset_id": "valid", "qwen_json_valid": "True"},
        {"asset_id": "invalid", "qwen_json_valid": "False"},
    ]

    assert completed_vlm_asset_ids(rows) == {"valid", "invalid"}


def test_processed_count_includes_persisted_invalid_32_frame_result(tmp_path):
    runner = Path("scripts/vision/run_vlm32_independent.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(Path("scripts/vision/run_vlm32_independent.py").resolve())}
    exec(runner.split("parser = argparse.ArgumentParser()", 1)[0], namespace)
    namespace["ROOT"] = tmp_path
    output = (
        tmp_path
        / "storage/vision/outputs/category_yolo_qwen_compare/car_vs_car"
        / "known_label_adaptive_32frames"
    )
    output.mkdir(parents=True)
    with (output / "qwen_yolo_compare_results.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "asset_id",
                "qwen_json_valid",
                "qwen_input_frame_count",
                "raw_output_text",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "asset_id": "valid",
                    "qwen_json_valid": "True",
                    "qwen_input_frame_count": "32",
                    "raw_output_text": "{}",
                },
                {
                    "asset_id": "invalid",
                    "qwen_json_valid": "False",
                    "qwen_input_frame_count": "32",
                    "raw_output_text": "{",
                },
            ]
        )

    assert namespace["processed_count"]("car_vs_car", "qwen") == 2
    assert namespace["result_count"]("car_vs_car", "qwen") == 1
