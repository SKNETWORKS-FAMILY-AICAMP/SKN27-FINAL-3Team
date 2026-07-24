import argparse
import csv
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(os.environ.get("VISION_PROJECT_ROOT", "/workspace/SKN27-FINAL-3Team"))
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ("car_vs_car", "car_vs_pedestrian", "car_vs_motorcycle", "car_vs_bicycle")
TARGET_PER_CATEGORY = 300


def language_valid(text: str) -> bool:
    return not any(
        char.isalpha()
        and not (
            "A" <= char <= "Z"
            or "a" <= char <= "z"
            or "\u1100" <= char <= "\u11ff"
            or "\u3130" <= char <= "\u318f"
            or "\uac00" <= char <= "\ud7ff"
        )
        for char in text
    )


def build_notebook(source: Path, model_name: str) -> dict:
    notebook = json.loads(source.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    for cell in cells:
        source_text = "".join(cell.get("source", []))
        source_text = source_text.replace(
            "RUN_INSTALL_REQUIREMENTS = True", "RUN_INSTALL_REQUIREMENTS = False"
        )
        source_text = source_text.replace("use_cache=False", "use_cache=True")
        source_text = source_text.replace(
            "for prompt_text in (VLM_JSON_PROMPT, VLM_JSON_RETRY_PROMPT):",
            "for prompt_text in (\n"
            "        VLM_JSON_PROMPT + '\\nIMPORTANT: Use English only for every JSON text value. Do not use Chinese characters or Japanese kana.',\n"
            "        VLM_JSON_RETRY_PROMPT + '\\nIMPORTANT: Use English only for every JSON text value. Do not use Chinese characters or Japanese kana.',\n"
            "    ):",
        )
        source_text = source_text.replace(
            "parsed, valid, last_error = parse_vlm_json(last_output)",
            "parsed, valid, last_error = parse_vlm_json(last_output)\n"
            "            if valid and any(char.isalpha() and not ('A' <= char <= 'Z' or 'a' <= char <= 'z' or '\\u1100' <= char <= '\\u11ff' or '\\u3130' <= char <= '\\u318f' or '\\uac00' <= char <= '\\ud7ff') for char in last_output):\n"
            "                valid = False\n"
            "                last_error = 'language_invalid:non_korean_or_english_script'",
        )
        source_text = source_text.replace(
            "frame_dir = OUTPUT_DIR / 'annotated_frames' / model_key / row['asset_id']",
            "frame_dir = OUTPUT_DIR / 'annotated_frames' / model_key / row['asset_id']\n"
            "    if not frame_dir.exists():\n"
            "        frame_dir = OUTPUT_DIR.parent / 'annotated_frames' / model_key / row['asset_id']",
        )
        source_text = source_text.replace(
            "paths = category_video_paths()",
            "target_manifest = PROJECT_ROOT / 'storage/vision/staging/per_label_300/unique_300_manifest.csv'\n"
            "paths = sorted({\n"
            "    (Path(row['local_path']) if Path(row['local_path']).is_absolute() else PROJECT_ROOT / row['local_path']).resolve()\n"
            "    for row in read_csv(target_manifest)\n"
            "    if row.get('category') == CATEGORY_KEY\n"
            "})\n"
            "paths = [path for path in paths if path.is_file()]\n"
            "if len(paths) != 300:\n"
            "    raise RuntimeError(f'Expected 300 unique videos for {CATEGORY_KEY}, found {len(paths)}')",
            1,
        )
        cell["source"] = source_text.splitlines(keepends=True)
    qwen_index = next(i for i, cell in enumerate(cells) if "qwen_results = []" in "".join(cell["source"]))
    llava_index = next(i for i, cell in enumerate(cells) if "llava_results = []" in "".join(cell["source"]))
    if model_name == "qwen":
        notebook["cells"] = cells[:llava_index]
    else:
        setup = "".join(cells[qwen_index]["source"])
        trained = setup[setup.index("from ai.vision.trained_category_classifier") : setup.index("qwen_results = []")]
        notebook["cells"] = cells[:qwen_index] + [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": trained.splitlines(keepends=True)}] + cells[llava_index:]
    return notebook
    cached_summary = """summary_path = OUTPUT_DIR / 'yolo_summary.csv'
if not summary_path.exists():
    summary_path = OUTPUT_DIR.parent / 'yolo_summary.csv'
with summary_path.open(encoding='utf-8-sig', newline='') as file:
    summary_rows = list(csv.DictReader(file))
if len({row['asset_id'] for row in summary_rows}) < 100:
    raise RuntimeError(f'Incomplete cached YOLO summary: {summary_path}')
for row in summary_rows:
    row['frames_with_relevant_detection'] = int(row['frames_with_relevant_detection'])
    row['avg_conf'] = float(row['avg_conf'])
print('cached_summary_rows:', len(summary_rows))
"""
    skipped = (
        "def video_duration_sec",
        "BOX_COLORS =",
        "summary_rows = []",
        "for model_name in YOLO_MODELS",
        "print('## YOLO model summary')",
        "## OpenCV 전처리",
        "## YOLO 5개 모델 비교",
    )
    optimized = []
    for cell in notebook["cells"]:
        text = "".join(cell.get("source", []))
        if any(marker in text for marker in skipped):
            continue
        if text.startswith("def write_csv"):
            optimized.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": cached_summary.splitlines(keepends=True)})
            cell["source"] = text[: text.index("write_csv(summary_rows")].splitlines(keepends=True)
        optimized.append(cell)
    notebook["cells"] = optimized
    return notebook


def result_count(category: str, model_name: str) -> int:
    output = ROOT / "storage/vision/outputs/category_yolo_qwen_compare" / category / "known_label_adaptive_32frames"
    path = output / ("qwen_yolo_compare_results.csv" if model_name == "qwen" else "llava_onevision_results.csv")
    if not path.exists():
        return 0
    valid_field = "qwen_json_valid" if model_name == "qwen" else "llava_json_valid"
    with path.open(encoding="utf-8-sig", newline="") as file:
        return len({
            row["asset_id"]
            for row in csv.DictReader(file)
            if str(row.get(valid_field, "")).lower() == "true"
            and row.get(
                "qwen_input_frame_count" if model_name == "qwen" else "llava_input_frame_count"
            ) == "32"
            and language_valid(row.get("raw_output_text", ""))
        })


parser = argparse.ArgumentParser()
parser.add_argument("model", choices=("qwen", "llava"))
parser.add_argument("--check", action="store_true")
args = parser.parse_args()

source = ROOT / "scripts/vision/vision_category_yolo_qwen_car_vs_car_known_label_runpod.ipynb"
if args.check:
    for category in CATEGORIES:
        source = ROOT / "scripts/vision" / f"vision_category_yolo_qwen_{category}_known_label_runpod.ipynb"
        qwen = "\n".join("".join(c.get("source", [])) for c in build_notebook(source, "qwen")["cells"])
        llava = "\n".join("".join(c.get("source", [])) for c in build_notebook(source, "llava")["cells"])
        print("check", category)
        assert "qwen_results = []" in qwen and "llava_results = []" not in qwen
        assert "llava_results = []" in llava and "qwen_results = []" not in llava
        assert "RUN_INSTALL_REQUIREMENTS = True" not in qwen + llava
        assert "for model_name in YOLO_MODELS" in qwen + llava
        assert "Expected 300 unique videos" in qwen + llava
        assert "max_new_tokens=512, do_sample=False, use_cache=True" in qwen + llava
        assert "OUTPUT_DIR.parent / 'annotated_frames'" in qwen + llava
        assert "Use English only for every JSON text value" in qwen
        assert "language_invalid:non_korean_or_english_script" in qwen
    print("independent notebook split: ok")
    raise SystemExit

work = Path(f"/workspace/vlm32_{args.model}_jobs")
work.mkdir(exist_ok=True)
environment = os.environ.copy()
environment.update(
    VISION_PROJECT_ROOT=str(ROOT),
    VISION_MAX_VIDEOS=str(TARGET_PER_CATEGORY),
    VISION_ANALYSIS_SAMPLE_COUNT=str(TARGET_PER_CATEGORY),
    VISION_VLM_INPUT_FRAME_COUNT="32",
    VISION_FORCE_PREPROCESS="0",
    VISION_RUN_GDOWN_DOWNLOAD="0",
    VISION_RUN_MODEL_COMPARISON="0",
    PYTHONUNBUFFERED="1",
)

for category in CATEGORIES:
    source = ROOT / "scripts/vision" / f"vision_category_yolo_qwen_{category}_known_label_runpod.ipynb"
    job = work / f"{category}.ipynb"
    job.write_text(json.dumps(build_notebook(source, args.model), ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(1, 4):
        before = result_count(category, args.model)
        if before >= TARGET_PER_CATEGORY:
            print(f"SKIP {args.model} {category} {before}/{TARGET_PER_CATEGORY}", flush=True)
            break
        print(f"START {args.model} {category} {before}/{TARGET_PER_CATEGORY} attempt={attempt}", flush=True)
        subprocess.run(
            [
                "jupyter",
                "nbconvert",
                "--to",
                "notebook",
                "--execute",
                str(job),
                "--output",
                f"{category}_executed.ipynb",
                "--output-dir",
                str(work),
                "--ExecutePreprocessor.timeout=-1",
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        after = result_count(category, args.model)
        print(f"DONE {args.model} {category} {after}/{TARGET_PER_CATEGORY}", flush=True)
        if after <= before:
            raise RuntimeError(
                f"{args.model} {category} schema-valid count stalled at "
                f"{after}/{TARGET_PER_CATEGORY}"
            )
    else:
        raise RuntimeError(
            f"{args.model} {category} did not reach {TARGET_PER_CATEGORY} schema-valid rows"
        )
