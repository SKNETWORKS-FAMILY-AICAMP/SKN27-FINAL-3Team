"""Export Vision/DL results as table, figure source, and appendix artifacts."""
from pathlib import Path
import argparse
import csv
import json


DEFAULT_ROOT = Path(".")
DEFAULT_OUTPUT = Path("storage/vision/reports")


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def best_row(rows: list[dict], metric: str) -> dict:
    def value(row: dict) -> float:
        try:
            return float(row.get(metric) or 0)
        except ValueError:
            return 0.0

    return max(rows, key=value, default={})


def collect_model_runs(root: Path) -> list[dict]:
    rows = []
    for config_path in sorted((root / "storage/vision/models").rglob("run_config.json")):
        run_dir = config_path.parent
        config = json.loads(config_path.read_text(encoding="utf-8"))
        history_path = run_dir / "training_history.csv"
        history = read_csv(history_path) if history_path.exists() else []
        best_val = best_row(history, "val_accuracy")
        best_test = best_row(history, "test_accuracy")
        rows.append({
            "run_id": config.get("run_id", run_dir.name),
            "model_name": config.get("model_name", ""),
            "freeze_backbone": config.get("freeze_backbone", ""),
            "epochs": config.get("epochs", ""),
            "batch_size": config.get("batch_size", ""),
            "learning_rate": config.get("learning_rate", ""),
            "weight_decay": config.get("weight_decay", ""),
            "frame_count": config.get("frame_count", ""),
            "train_rows": config.get("train_rows", ""),
            "val_rows": config.get("val_rows", ""),
            "test_rows": config.get("test_rows", ""),
            "best_val_epoch": best_val.get("epoch", ""),
            "best_val_accuracy": best_val.get("val_accuracy", ""),
            "best_test_epoch": best_test.get("epoch", ""),
            "best_test_accuracy": best_test.get("test_accuracy", ""),
            "run_dir": run_dir.as_posix(),
        })
    return rows


def collect_qwen_outputs(root: Path) -> list[dict]:
    rows = []
    for path in sorted((root / "storage/vision/outputs").rglob("qwen_vl_analysis_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        row = data.get("row") or {}
        parsed = data.get("parsed_output") or {}
        conditions = parsed.get("scene_conditions") or {}
        rows.append({
            "file": path.as_posix(),
            "asset_id": row.get("asset_id", ""),
            "coarse_label": row.get("coarse_label", ""),
            "qwen_json_valid": data.get("qwen_json_valid", ""),
            "summary": parsed.get("summary", ""),
            "accident_situation": parsed.get("accident_situation", ""),
            "weather": conditions.get("weather", ""),
            "visibility": conditions.get("visibility", ""),
            "road_surface": conditions.get("road_surface", ""),
            "lighting": conditions.get("lighting", ""),
            "confidence": conditions.get("confidence", ""),
        })
    return rows


def collect_clip_candidates(root: Path) -> list[dict]:
    rows = []
    for path in sorted((root / "storage/vision/datasets/classification/manifests").glob("*clip*manifest*.csv")):
        for row in read_csv(path):
            rows.append({
                "manifest": path.name,
                "asset_id": row.get("asset_id", ""),
                "coarse_label": row.get("coarse_label", ""),
                "clip_status": row.get("clip_status", ""),
                "clip_basis": row.get("clip_basis", ""),
                "clip_start_sec": row.get("clip_start_sec", ""),
                "clip_end_sec": row.get("clip_end_sec", ""),
                "accident_candidate_sec": row.get("accident_candidate_sec", ""),
                "accident_candidate_score": row.get("accident_candidate_score", ""),
                "accident_candidate_iou": row.get("accident_candidate_iou", ""),
                "accident_candidate_object_pair": row.get("accident_candidate_object_pair", ""),
                "local_path": row.get("local_path", ""),
            })
    return rows


def write_appendix(path: Path, title: str, rows: list[dict], limit: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    for idx, row in enumerate(rows[:limit], 1):
        lines.append(f"## {idx}. {row.get('run_id') or row.get('asset_id') or row.get('file') or 'item'}")
        for key, value in row.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Vision/DL analysis artifacts.")
    parser.add_argument("--root-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    root = args.root_dir
    output = args.output_dir
    tables = output / "tables"
    figures = output / "figures"
    appendix = output / "appendix"

    model_rows = collect_model_runs(root)
    qwen_rows = collect_qwen_outputs(root)
    clip_rows = collect_clip_candidates(root)

    write_csv(tables / "model_runs_summary.csv", model_rows)
    write_csv(tables / "qwen_outputs_summary.csv", qwen_rows)
    write_csv(tables / "clip_accident_candidates.csv", clip_rows)

    # Figure source tables: plotting can be done from these without rerunning models.
    write_csv(figures / "model_accuracy_figure_source.csv", [
        {
            "run_id": row.get("run_id", ""),
            "best_val_accuracy": row.get("best_val_accuracy", ""),
            "best_test_accuracy": row.get("best_test_accuracy", ""),
            "model_name": row.get("model_name", ""),
        }
        for row in model_rows
    ])
    write_csv(figures / "clip_score_figure_source.csv", [
        {
            "asset_id": row.get("asset_id", ""),
            "coarse_label": row.get("coarse_label", ""),
            "accident_candidate_score": row.get("accident_candidate_score", ""),
            "accident_candidate_iou": row.get("accident_candidate_iou", ""),
            "object_pair": row.get("accident_candidate_object_pair", ""),
        }
        for row in clip_rows
    ])

    write_appendix(appendix / "model_runs_appendix.md", "Model Runs Appendix", model_rows)
    write_appendix(appendix / "qwen_outputs_appendix.md", "Qwen Outputs Appendix", qwen_rows)
    write_appendix(appendix / "clip_candidates_appendix.md", "Clip Candidates Appendix", clip_rows)

    print(f"tables: {tables}")
    print(f"figures: {figures}")
    print(f"appendix: {appendix}")


if __name__ == "__main__":
    main()
