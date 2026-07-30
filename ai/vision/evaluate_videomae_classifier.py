"""Evaluate one trained VideoMAE checkpoint on the manifest test split."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from tqdm.auto import tqdm


def _ratio(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def classification_metrics(
    expected: list[int],
    predicted: list[int],
    confidences: list[float],
    labels: list[str],
    confidence_threshold: float,
) -> tuple[dict, list[list[int]]]:
    if not expected or len(expected) != len(predicted) or len(expected) != len(confidences):
        raise ValueError("expected, predicted, and confidences must have the same non-zero length")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be in [0, 1]")

    confusion = [[0 for _ in labels] for _ in labels]
    for truth, guess in zip(expected, predicted):
        confusion[truth][guess] += 1

    per_class = {}
    f1_scores = []
    for index, label in enumerate(labels):
        true_positive = confusion[index][index]
        actual = sum(confusion[index])
        guessed = sum(row[index] for row in confusion)
        precision = true_positive / guessed if guessed else 0.0
        recall = true_positive / actual if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_scores.append(f1)
        per_class[label] = {
            "support": actual,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }

    car_index = labels.index("car_vs_car") if "car_vs_car" in labels else None
    to_car = {}
    if car_index is not None:
        for index, label in enumerate(labels):
            if index != car_index:
                to_car[label] = _ratio(confusion[index][car_index], sum(confusion[index]))

    metrics = {
        "sample_count": len(expected),
        "accuracy": _ratio(sum(a == b for a, b in zip(expected, predicted)), len(expected)),
        "macro_f1": round(sum(f1_scores) / len(f1_scores), 6),
        "confidence_threshold": confidence_threshold,
        "low_confidence_rate": _ratio(sum(value < confidence_threshold for value in confidences), len(confidences)),
        "per_class": per_class,
        "misclassification_to_car_rate": to_car,
    }
    return metrics, confusion


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_confusion_csv(path: Path, labels: list[str], confusion: list[list[int]]) -> None:
    rows = [
        {"expected\\predicted": label, **dict(zip(labels, values))}
        for label, values in zip(labels, confusion)
    ]
    write_csv(path, rows, ["expected\\predicted", *labels])


def write_confusion_png(path: Path, labels: list[str], confusion: list[list[int]]) -> None:
    cell, margin_left, margin_top = 120, 220, 100
    image = np.full((margin_top + cell * len(labels) + 50, margin_left + cell * len(labels), 3), 255, np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    for index, label in enumerate(labels):
        cv2.putText(image, label.replace("car_vs_", ""), (margin_left + index * cell + 8, 55), font, 0.48, (0, 0, 0), 1)
        cv2.putText(image, label.replace("car_vs_", ""), (8, margin_top + index * cell + 65), font, 0.48, (0, 0, 0), 1)
    maximum = max(max(row) for row in confusion) or 1
    for row_index, row in enumerate(confusion):
        for column_index, value in enumerate(row):
            intensity = int(245 - 170 * value / maximum)
            start = (margin_left + column_index * cell, margin_top + row_index * cell)
            end = (start[0] + cell, start[1] + cell)
            cv2.rectangle(image, start, end, (255, intensity, intensity), -1)
            cv2.rectangle(image, start, end, (180, 180, 180), 1)
            cv2.putText(image, str(value), (start[0] + 48, start[1] + 68), font, 0.8, (0, 0, 0), 2)
    cv2.putText(image, "Predicted", (margin_left, 25), font, 0.6, (0, 0, 0), 1)
    cv2.putText(image, "Expected", (8, margin_top - 15), font, 0.6, (0, 0, 0), 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise OSError(f"Failed to write {path}")


def evaluate(args: argparse.Namespace) -> Path:
    import torch
    from torch.utils.data import DataLoader
    from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

    from ai.vision.train_videomae_classifier import VideoDataset, choose_device, filter_rows, read_csv

    checkpoint = args.checkpoint.resolve()
    mapping_path = checkpoint / "class_mapping.json"
    if not mapping_path.is_file():
        raise FileNotFoundError(f"Missing class mapping: {mapping_path}")
    label_to_index = json.loads(mapping_path.read_text(encoding="utf-8"))
    labels = [label for label, _ in sorted(label_to_index.items(), key=lambda item: item[1])]

    rows = filter_rows(read_csv(args.manifest), args.root_dir, args.label_column)
    test_rows = [row for row in rows if row.get("split") == "test"]
    if not test_rows:
        raise ValueError("Manifest does not contain a non-empty test split")

    device = choose_device(args.device)
    processor = VideoMAEImageProcessor.from_pretrained(checkpoint)
    model = VideoMAEForVideoClassification.from_pretrained(checkpoint).to(device).eval()
    dataset = VideoDataset(test_rows, label_to_index, args.label_column, args.frame_count, processor)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)

    expected, predicted, confidences, prediction_rows = [], [], [], []
    total_loss = 0.0
    cursor = 0
    with torch.inference_mode():
        for pixel_values, batch_labels in tqdm(loader, desc="FINAL TEST", unit="batch"):
            pixel_values, batch_labels = pixel_values.to(device), batch_labels.to(device)
            outputs = model(pixel_values=pixel_values, labels=batch_labels)
            probabilities = torch.softmax(outputs.logits, dim=-1)
            batch_confidence, batch_prediction = probabilities.max(dim=1)
            batch_size = batch_labels.size(0)
            total_loss += outputs.loss.item() * batch_size
            for offset in range(batch_size):
                truth = int(batch_labels[offset])
                guess = int(batch_prediction[offset])
                confidence = float(batch_confidence[offset])
                source = test_rows[cursor + offset]
                row = {
                    "asset_id": source.get("asset_id", ""),
                    "video_path": source["resolved_local_path"],
                    "expected_label": labels[truth],
                    "predicted_label": labels[guess],
                    "confidence": round(confidence, 6),
                    "correct": truth == guess,
                }
                row.update({f"probability_{label}": round(float(probabilities[offset, index]), 6) for index, label in enumerate(labels)})
                prediction_rows.append(row)
                expected.append(truth)
                predicted.append(guess)
                confidences.append(confidence)
            cursor += batch_size

    metrics, confusion = classification_metrics(expected, predicted, confidences, labels, args.confidence_threshold)
    metrics.update({
        "loss": round(total_loss / len(test_rows), 6),
        "checkpoint": checkpoint.as_posix(),
        "manifest": args.manifest.as_posix(),
        "frame_count": args.frame_count,
    })
    output_dir = args.output_dir or checkpoint / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "test_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = list(prediction_rows[0])
    write_csv(output_dir / "test_predictions.csv", prediction_rows, fields)
    write_csv(output_dir / "misclassified_videos.csv", [row for row in prediction_rows if not row["correct"]], fields)
    write_confusion_csv(output_dir / "confusion_matrix.csv", labels, confusion)
    write_confusion_png(output_dir / "confusion_matrix.png", labels, confusion)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"output_dir: {output_dir}")
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--label-column", default="coarse_label")
    parser.add_argument("--frame-count", type=int, default=32)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--confidence-threshold", type=float, default=0.5)
    parser.add_argument("--device", default="auto")
    return parser.parse_args()


if __name__ == "__main__":
    evaluate(parse_args())
