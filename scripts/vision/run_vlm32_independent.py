import argparse
import csv
import json
import os
import re
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


def build_notebook(source: Path, model_name: str, pilot_qwen_invalid: int = 0) -> dict:
    notebook = json.loads(source.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    for cell in cells:
        source_text = "".join(cell.get("source", []))
        source_text = source_text.replace(
            "RUN_INSTALL_REQUIREMENTS = True", "RUN_INSTALL_REQUIREMENTS = False"
        )
        source_text = source_text.replace("use_cache=False", "use_cache=True")
        source_text = source_text.replace(
            "from ai.vision.vlm_json import VLM_JSON_PROMPT, VLM_JSON_RETRY_PROMPT, parse_vlm_json",
            "from ai.vision.vlm_json import VLM_JSON_PROMPT, VLM_JSON_RETRY_PROMPT, adaptive_retry_prompt, completed_vlm_asset_ids, parse_vlm_json, retry_token_limit",
        )
        source_text = source_text.replace(
            "QWEN_OUTPUT_CSV = OUTPUT_DIR / 'qwen_yolo_compare_results.csv'",
            "QWEN_OUTPUT_CSV = OUTPUT_DIR / 'qwen_explanation_v1_results.csv'",
        )
        source_text = re.sub(
            r"(?m)^(\s*)for prompt_text in \(VLM_JSON_PROMPT, VLM_JSON_RETRY_PROMPT\):$",
            lambda match: (
                f"{match.group(1)}for prompt_index in range(2):\n"
                f"{match.group(1)}    prompt_text = (VLM_JSON_PROMPT if prompt_index == 0 else adaptive_retry_prompt(last_error))\n"
                f"{match.group(1)}    prompt_text += '\\nIMPORTANT: Use English only for every JSON text value. Do not use Chinese characters or Japanese kana.'"
            ),
            source_text,
        )
        source_text = source_text.replace(
            "max_new_tokens=512, do_sample=False, use_cache=True",
            "max_new_tokens=(512 if prompt_index == 0 else retry_token_limit(last_error)), do_sample=False, use_cache=True",
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
        prepared_input = (
            "frames_base = PROJECT_ROOT / 'storage/vision/staging/per_label_300/frames32' / CATEGORY_KEY\n"
            "paths = sorted(path for path in frames_base.iterdir() if path.is_dir() and len(list(path.glob('frame_*.jpg'))) == 32)\n"
            "if len(paths) != 300:\n"
            "    raise RuntimeError(f'Expected 300 prepared 32-frame directories for {CATEGORY_KEY}, found {len(paths)}')\n"
            "print('prepared_frame_directory_count:', len(paths))\n"
        )
        if "existing_video_count_before_download:" in source_text:
            source_text = prepared_input
        else:
            source_text = source_text.replace(
                "paths = category_video_paths()", prepared_input, 1
            )
        source_text = source_text.replace(
            "def extract_frames(video_path, frame_dir, preprocess_dir, frame_count):\n",
            "def extract_frames(video_path, frame_dir, preprocess_dir, frame_count):\n"
            "    if video_path.is_dir():\n"
            "        raw_paths = sorted(video_path.glob('frame_*.jpg'))\n"
            "        if len(raw_paths) != 32:\n"
            "            raise RuntimeError(f'Expected 32 prepared frames: {video_path}')\n"
            "        return raw_paths, raw_paths\n",
        )
        source_text = source_text.replace(
            "'preprocess_frame_dir': prep_frame_dir.as_posix(),",
            "'preprocess_frame_dir': (path if path.is_dir() else prep_frame_dir).as_posix(),",
        )
        source_text = source_text.replace(
            "'qwen_json_valid': str(valid),",
            "'qwen_json_valid': str(valid),\n"
            "        'model_json_valid': str(valid),\n"
            "        'handoff_json_valid': 'True',\n"
            "        'status': 'complete' if valid else 'partial',\n"
            "        'requires_review': str(not valid),\n"
            "        'error_code': '' if valid else 'VLM_SCHEMA_INVALID',\n"
            "        'raw_output_preserved': 'True',",
        )
        source_text = source_text.replace(
            "completed_ids = {row['asset_id'] for row in qwen_results} - qwen_retry_ids",
            "completed_ids = completed_vlm_asset_ids(qwen_results)",
        )
        source_text = source_text.replace(
            "        for frame_path in frames:\n",
            "        for frame_order, frame_path in enumerate(frames, 1):\n",
        )
        source_text = source_text.replace(
            "            annotated_paths.append(ann_path)\n",
            "            annotated_paths.append(ann_path)\n"
            "            objects = [{\n"
            "                'class_name': result.names[int(box.cls[0])],\n"
            "                'confidence': round(float(box.conf[0]), 6),\n"
            "                'bbox_xyxy': [round(float(value), 2) for value in box.xyxy[0].tolist()],\n"
            "            } for box in relevant_boxes]\n"
            "            detail_rows.append({\n"
            "                'asset_id': row['asset_id'], 'yolo_model': model_name,\n"
            "                'frame_order': frame_order,\n"
            "                'timestamp_sec': round((frame_order - 1) * float(row.get('duration_sec', 0)) / max(len(frames) - 1, 1), 3),\n"
            "                'objects_json': json.dumps(objects, ensure_ascii=False),\n"
            "            })\n",
        )
        source_text = source_text.replace(
            "def qwen_analyze_images(image_paths, model, processor):\n",
            "from ai.vision.vlm_input import build_qwen_content\n\n"
            "_metadata_yolo_models = {}\n\n"
            "def yolo_frame_metadata(row, image_paths):\n"
            "    matches = {int(item['frame_order']): item for item in detail_rows\n"
            "               if item['asset_id'] == row['asset_id'] and item['yolo_model'] == row['yolo_model']}\n"
            "    if len(matches) == len(image_paths):\n"
            "        return [{'frame_order': frame_number(path),\n"
            "                 'timestamp_sec': float(matches[frame_number(path)]['timestamp_sec']),\n"
            "                 'objects': json.loads(matches[frame_number(path)]['objects_json'])}\n"
            "                for path in image_paths]\n"
            "    if row['yolo_model'] not in _metadata_yolo_models:\n"
            "        _metadata_yolo_models[row['yolo_model']] = YOLO(row['yolo_model'])\n"
            "    detector = _metadata_yolo_models[row['yolo_model']]\n"
            "    metadata = []\n"
            "    for order, path in enumerate(image_paths, 1):\n"
            "        result = detector.predict(str(path), conf=YOLO_CONF, imgsz=YOLO_IMGSZ, verbose=False)[0]\n"
            "        objects = []\n"
            "        for box in list(result.boxes) if result.boxes is not None else []:\n"
            "            class_name = result.names[int(box.cls[0])]\n"
            "            if class_name in RELEVANT_CLASSES:\n"
            "                objects.append({'class_name': class_name, 'confidence': round(float(box.conf[0]), 6),\n"
            "                                'bbox_xyxy': [round(float(value), 2) for value in box.xyxy[0].tolist()]})\n"
            "        metadata.append({'frame_order': frame_number(path), 'timestamp_sec': round((order - 1) * float(row.get('duration_sec', 0)) / max(len(image_paths) - 1, 1), 3), 'objects': objects})\n"
            "    return metadata\n\n"
            "def qwen_analyze_images(image_paths, frame_metadata, classification_context, model, processor):\n",
        )
        source_text = source_text.replace(
            "    used_paths = select_collision_aware_frames(image_paths, QWEN_INPUT_FRAME_COUNT)\n"
            "    last_output, last_error = '', 'json_incomplete:no_attempt'\n",
            "    used_paths = select_collision_aware_frames(image_paths, QWEN_INPUT_FRAME_COUNT)\n"
            "    metadata_by_order = {item['frame_order']: item for item in frame_metadata}\n"
            "    used_metadata = [metadata_by_order[frame_number(path)] for path in used_paths]\n"
            "    last_output, last_error = '', 'json_incomplete:no_attempt'\n",
        )
        source_text = source_text.replace(
            "            content = [{'type': 'image', 'image': str(path), 'max_pixels': 640 * 360} for path in used_paths]\n"
            "            content.append({'type': 'text', 'text': prompt_text})\n",
            "            content = build_qwen_content(used_paths, used_metadata, prompt_text, QWEN_INPUT_FRAME_COUNT, classification_context)\n",
        )
        source_text = source_text.replace(
            "            annotated_frame_paths(row), model, processor\n",
            "            annotated_frame_paths(row), yolo_frame_metadata(row, annotated_frame_paths(row)), classification_context, model, processor\n",
        )
        source_text = source_text.replace(
            "            parsed, valid, last_error = parse_vlm_json(last_output)\n",
            "            allowed_frame_refs = {f\"frame_{frame_number(path):02d}\" for path in used_paths}\n"
            "            parsed, valid, last_error = parse_vlm_json(last_output, allowed_frame_refs)\n",
        )
        source_text = source_text.replace(
            "TRAINED_CLASSIFIER = TrainedCategoryClassifier(TRAINED_CHECKPOINT)\n",
            "TRAINED_CLASSIFIER = TrainedCategoryClassifier(TRAINED_CHECKPOINT)\n\n"
            "def classification_context_for_row(row):\n"
            "    trained = TRAINED_CLASSIFIER.predict(row['local_path'])\n"
            "    return {\n"
            "        'canonical_label': trained['label'],\n"
            "        'confidence': trained['confidence'],\n"
            "        'top2_margin': trained.get('top2_margin'),\n"
            "        'requires_review': trained['confidence'] < 0.5,\n"
            "        'model_version': Path(trained['checkpoint']).name,\n"
            "        'checkpoint_hash': None,\n"
            "    }\n",
        )
        source_text = source_text.replace(
            "    try:\n"
            "        parsed, raw_output, valid, error, used_frame_count = qwen_analyze_images(\n",
            "    classification_context = classification_context_for_row(row)\n"
            "    try:\n"
            "        parsed, raw_output, valid, error, used_frame_count = qwen_analyze_images(\n",
        )
        source_text = source_text.replace(
            "    decision = resolve_accident_target(parsed.get('predicted_accident_target'))\n",
            "",
        )
        source_text = source_text.replace(
            "'predicted_accident_target': decision['final_accident_target'],",
            "'predicted_accident_target': classification_context['canonical_label'],",
        )
        source_text = source_text.replace(
            "'needs_user_input': str(decision['needs_user_input']),\n"
            "        'user_question': decision['user_question'],",
            "'needs_user_input': 'False',\n"
            "        'user_question': '',",
        )
        source_text = source_text.replace(
            "'accident_situation': parsed.get('accident_situation', ''),",
            "'accident_situation': '',\n"
            "        'qwen_schema_version': parsed.get('schema_version', 'vision-qwen-explanation-v1'),\n"
            "        'narrative': parsed.get('narrative', f\"VideoMAE classified the event as {classification_context['canonical_label']} with confidence {classification_context['confidence']:.2%}.\"),\n"
            "        'evidence_sentences': json.dumps(parsed.get('evidence_sentences', []), ensure_ascii=False),\n"
            "        'conflict': str(parsed.get('conflict', False)),\n"
            "        'conflict_reason': parsed.get('conflict_reason') or '',\n"
            "        'fallback_used': str(not valid),\n"
            "        'canonical_label_preserved': 'True',",
        )
        cell["source"] = source_text.splitlines(keepends=True)
    qwen_index = next(i for i, cell in enumerate(cells) if "qwen_results = []" in "".join(cell["source"]))
    llava_index = next(i for i, cell in enumerate(cells) if "llava_results = []" in "".join(cell["source"]))
    if model_name == "qwen":
        notebook["cells"] = cells[:llava_index]
        if pilot_qwen_invalid:
            for cell in notebook["cells"]:
                text = "".join(cell.get("source", []))
                if "qwen_retry_pending:" not in text:
                    continue
                marker = "print('resume_completed:', len(completed_ids), '/', len(best_rows))\n"
                pilot = (
                    f"pilot_ids = [row['asset_id'] for row in qwen_results if str(row.get('qwen_json_valid', '')).lower() != 'true'][:{pilot_qwen_invalid}]\n"
                    "best_rows = [row for row in best_rows if row['asset_id'] in set(pilot_ids)]\n"
                    "completed_ids -= set(pilot_ids)\n"
                    "print('qwen_invalid_pilot:', len(best_rows))\n"
                )
                cell["source"] = text.replace(marker, marker + pilot).splitlines(keepends=True)
                break
    elif model_name == "llava":
        setup = "".join(cells[qwen_index]["source"])
        trained = setup[setup.index("from ai.vision.trained_category_classifier") : setup.index("qwen_results = []")]
        notebook["cells"] = cells[:qwen_index] + [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": trained.splitlines(keepends=True)}] + cells[llava_index:]
        if pilot_qwen_invalid:
            for cell in notebook["cells"]:
                text = "".join(cell.get("source", []))
                if "llava_results = []" not in text:
                    continue
                pilot = (
                    "with (OUTPUT_DIR / 'qwen_yolo_compare_results.csv').open(encoding='utf-8-sig', newline='') as f:\n"
                    "    qwen_rows = list(csv.DictReader(f))\n"
                    "pilot_ids = [row['asset_id'] for row in qwen_rows if str(row.get('qwen_json_valid', '')).lower() != 'true']"
                    f"[:{pilot_qwen_invalid}]\n"
                    "best_rows = [row for row in best_rows if row['asset_id'] in set(pilot_ids)]\n"
                    "print('llava_qwen_invalid_pilot:', len(best_rows))\n"
                )
                cell["source"] = (pilot + text).splitlines(keepends=True)
                break
    else:
        yolo_end = next(
            i
            for i, cell in enumerate(cells)
            if "YOLO_QWEN_MODEL =" in "".join(cell.get("source", []))
        )
        notebook["cells"] = cells[:yolo_end]
        return notebook
    cached_summary = """summary_path = OUTPUT_DIR / 'yolo_summary.csv'
if not summary_path.exists():
    summary_path = OUTPUT_DIR.parent / 'yolo_summary.csv'
with summary_path.open(encoding='utf-8-sig', newline='') as file:
    summary_rows = list(csv.DictReader(file))
if len({row['asset_id'] for row in summary_rows}) < 300:
    raise RuntimeError(f'Incomplete cached YOLO summary: {summary_path}')
for row in summary_rows:
    row['frames_with_relevant_detection'] = int(row['frames_with_relevant_detection'])
    row['avg_conf'] = float(row['avg_conf'])
detail_rows = []
print('cached_summary_rows:', len(summary_rows))
"""
    skipped = (
        "summary_rows = []",
        "for model_name in YOLO_MODELS",
        "print('## YOLO model summary')",
        "LLAVA_MISSED_CSV =",
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
    path = output / ("qwen_explanation_v1_results.csv" if model_name == "qwen" else "llava_onevision_results.csv")
    if not path.exists():
        return 0
    valid_field = "qwen_json_valid" if model_name == "qwen" else "json_valid"
    with path.open(encoding="utf-8-sig", newline="") as file:
        return len({
            row["asset_id"]
            for row in csv.DictReader(file)
            if str(row.get(valid_field, "")).lower() == "true"
            and row.get(
                "qwen_input_frame_count" if model_name == "qwen" else "llava_input_frame_count"
            ) == ("12" if model_name == "qwen" else "32")
            and language_valid(row.get("raw_output_text", ""))
        })


def processed_count(category: str, model_name: str) -> int:
    output = ROOT / "storage/vision/outputs/category_yolo_qwen_compare" / category / "known_label_adaptive_32frames"
    path = output / ("qwen_explanation_v1_results.csv" if model_name == "qwen" else "llava_onevision_results.csv")
    if not path.exists():
        return 0
    frame_field = "qwen_input_frame_count" if model_name == "qwen" else "llava_input_frame_count"
    with path.open(encoding="utf-8-sig", newline="") as file:
        return len({
            row["asset_id"]
            for row in csv.DictReader(file)
            if row.get(frame_field) == ("12" if model_name == "qwen" else "32")
        })


def yolo_summary_count(category: str) -> int:
    base = (
        ROOT
        / "storage/vision/outputs/category_yolo_qwen_compare"
        / category
    )
    for path in (
        base / "known_label_adaptive_32frames/yolo_summary.csv",
        base / "yolo_summary.csv",
    ):
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as file:
                return len({row["asset_id"] for row in csv.DictReader(file)})
    return 0


parser = argparse.ArgumentParser()
parser.add_argument("model", choices=("qwen", "llava"))
parser.add_argument("--check", action="store_true")
parser.add_argument("--category", choices=CATEGORIES)
parser.add_argument("--pilot-qwen-invalid", type=int, default=0)
args = parser.parse_args()
if args.pilot_qwen_invalid < 0:
    parser.error("--pilot-qwen-invalid must be non-negative")

source = ROOT / "scripts/vision/vision_category_yolo_qwen_car_vs_car_known_label_runpod.ipynb"
if args.check:
    for category in CATEGORIES:
        source = ROOT / "scripts/vision" / f"vision_category_yolo_qwen_{category}_known_label_runpod.ipynb"
        qwen_notebook = build_notebook(source, "qwen", args.pilot_qwen_invalid)
        llava_notebook = build_notebook(source, "llava", args.pilot_qwen_invalid)
        qwen = "\n".join("".join(c.get("source", [])) for c in qwen_notebook["cells"])
        llava = "\n".join(
            "".join(c.get("source", []))
            for c in llava_notebook["cells"]
        )
        print("check", category)
        assert "qwen_results = []" in qwen and "llava_results = []" not in qwen
        assert "llava_results = []" in llava and "qwen_results = []" not in llava
        assert "RUN_INSTALL_REQUIREMENTS = True" not in qwen + llava
        assert "for model_name in YOLO_MODELS" not in qwen + llava
        assert "cached_summary_rows:" in qwen + llava
        assert "Expected 300 prepared 32-frame directories" in qwen + llava
        assert "Expected 300 unique videos" not in qwen + llava
        assert "return raw_paths, raw_paths" in qwen + llava
        assert "(path if path.is_dir() else prep_frame_dir)" in qwen + llava
        assert "adaptive_retry_prompt(last_error)" in qwen
        assert "retry_token_limit(last_error)" in qwen
        assert "'handoff_json_valid': 'True'" in qwen
        assert "OUTPUT_DIR.parent / 'annotated_frames'" in qwen + llava
        assert "Use English only for every JSON text value" in qwen
        assert "language_invalid:non_korean_or_english_script" in qwen
        assert "build_qwen_content(used_paths, used_metadata" in qwen
        assert "classification_context_for_row" in qwen
        assert "qwen_explanation_v1_results.csv" in qwen
        assert "parsed.get('predicted_accident_target')" not in qwen
        for model_name, notebook in (("qwen", qwen_notebook), ("llava", llava_notebook)):
            for index, cell in enumerate(notebook["cells"]):
                if cell.get("cell_type") == "code":
                    compile("".join(cell.get("source", [])), f"{category}_{model_name}_{index}", "exec")
        if args.pilot_qwen_invalid:
            assert "llava_qwen_invalid_pilot:" in llava
            assert "qwen_invalid_pilot:" in qwen
    print("independent notebook split: ok")
    raise SystemExit

work = Path(f"/workspace/vlm32_{args.model}_jobs")
work.mkdir(exist_ok=True)
environment = os.environ.copy()
environment.update(
    VISION_PROJECT_ROOT=str(ROOT),
    VISION_MAX_VIDEOS=str(TARGET_PER_CATEGORY),
    VISION_ANALYSIS_SAMPLE_COUNT=str(TARGET_PER_CATEGORY),
    VISION_VLM_INPUT_FRAME_COUNT="12",
    VISION_FORCE_PREPROCESS="0",
    VISION_RUN_GDOWN_DOWNLOAD="0",
    VISION_RUN_MODEL_COMPARISON="0",
    PYTHONUNBUFFERED="1",
)

for category in (args.category,) if args.category else CATEGORIES:
    source = ROOT / "scripts/vision" / f"vision_category_yolo_qwen_{category}_known_label_runpod.ipynb"
    if yolo_summary_count(category) < TARGET_PER_CATEGORY:
        yolo_job = work / f"{category}_yolo.ipynb"
        yolo_job.write_text(
            json.dumps(build_notebook(source, "yolo"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"PREPARE yolo {category} {yolo_summary_count(category)}/"
            f"{TARGET_PER_CATEGORY}",
            flush=True,
        )
        subprocess.run(
            [
                "jupyter",
                "nbconvert",
                "--to",
                "notebook",
                "--execute",
                str(yolo_job),
                "--output",
                f"{category}_yolo_executed.ipynb",
                "--output-dir",
                str(work),
                "--ExecutePreprocessor.timeout=-1",
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        if yolo_summary_count(category) < TARGET_PER_CATEGORY:
            raise RuntimeError(
                f"YOLO preparation incomplete for {category}: "
                f"{yolo_summary_count(category)}/{TARGET_PER_CATEGORY}"
            )
    job = work / f"{category}.ipynb"
    job.write_text(
        json.dumps(
            build_notebook(source, args.model, args.pilot_qwen_invalid),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for attempt in range(1, 2):
        before = processed_count(category, args.model)
        if before >= TARGET_PER_CATEGORY:
            print(
                f"SKIP {args.model} {category} processed={before}/"
                f"{TARGET_PER_CATEGORY} model-valid={result_count(category, args.model)}",
                flush=True,
            )
            break
        print(
            f"START {args.model} {category} processed={before}/"
            f"{TARGET_PER_CATEGORY} attempt={attempt}",
            flush=True,
        )
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
        after = processed_count(category, args.model)
        valid = result_count(category, args.model)
        print(
            f"DONE {args.model} {category} processed={after}/"
            f"{TARGET_PER_CATEGORY} model-valid={valid}",
            flush=True,
        )
        if after < TARGET_PER_CATEGORY:
            print(
                f"PARTIAL {args.model} {category} processed={after}/"
                f"{TARGET_PER_CATEGORY}; incomplete rows remain retryable",
                flush=True,
            )
