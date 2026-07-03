"""Fine-tune VideoMAE for coarse accident type classification.

This uses video clips directly from the download manifest. Keep the first run
small; VideoMAE is much heavier than the ResNet18 frame baseline.
"""
from pathlib import Path
import argparse
import csv
import json
import os
import random
from datetime import datetime

import cv2
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from tqdm.auto import tqdm
from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor


DEFAULT_MANIFEST_PATH = Path(
    "storage/vision/datasets/classification/manifests/train_700_download_manifest.csv"
)
DEFAULT_OUTPUT_DIR = Path("storage/vision/models/videomae_classification")
DEFAULT_MODEL_NAME = "MCG-NJU/videomae-base-finetuned-kinetics"
DEFAULT_LABEL_COLUMN = "coarse_label"


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict], output_path: Path, fields: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def set_seed(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def choose_device(device_arg: str) -> torch.device:
    if device_arg != "auto":
        return torch.device(device_arg)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def filter_rows(rows: list[dict], root_dir: Path, label_column: str) -> list[dict]:
    valid = []
    for row in rows:
        label = row.get(label_column)
        local_path = row.get("local_path")
        if not label or not local_path:
            continue
        path = Path(local_path)
        if not path.is_absolute():
            path = root_dir / path
        if path.exists() and path.stat().st_size > 0:
            copied = dict(row)
            copied["resolved_local_path"] = path.as_posix()
            valid.append(copied)
    return valid


def split_rows(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    return (
        [row for row in rows if row.get("split") == "train"],
        [row for row in rows if row.get("split") == "val"],
        [row for row in rows if row.get("split") == "test"],
    )


def build_label_mapping(rows: list[dict], label_column: str) -> dict[str, int]:
    labels = sorted({row[label_column] for row in rows if row.get(label_column)})
    if not labels:
        raise ValueError(f"No labels found in column: {label_column}")
    return {label: index for index, label in enumerate(labels)}


def sample_indices(frame_count: int, target_count: int) -> list[int]:
    if frame_count <= 0:
        return [0] * target_count
    return np.linspace(0, frame_count - 1, target_count).round().astype(int).tolist()


def read_video_frames(path: Path, frame_count: int) -> list[np.ndarray]:
    capture = cv2.VideoCapture(path.as_posix())
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames = []
    for index in sample_indices(total, frame_count):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok:
            continue
        frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    capture.release()

    if not frames:
        frames = [np.zeros((224, 224, 3), dtype=np.uint8)]
    while len(frames) < frame_count:
        frames.append(frames[-1])
    return frames[:frame_count]


class VideoDataset(Dataset):
    def __init__(self, rows: list[dict], label_to_index: dict[str, int], label_column: str, frame_count: int, processor):
        self.rows = rows
        self.label_to_index = label_to_index
        self.label_column = label_column
        self.frame_count = frame_count
        self.processor = processor

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        row = self.rows[index]
        frames = read_video_frames(Path(row["resolved_local_path"]), self.frame_count)
        pixel_values = self.processor(frames, return_tensors="pt")["pixel_values"].squeeze(0)
        label = torch.tensor(self.label_to_index[row[self.label_column]], dtype=torch.long)
        return pixel_values, label


def make_loader(rows, label_to_index, label_column, frame_count, processor, batch_size, num_workers, shuffle):
    if not rows:
        return None
    dataset = VideoDataset(rows, label_to_index, label_column, frame_count, processor)
    return DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)


def run_epoch(model, loader, optimizer, device, train: bool, show_progress: bool) -> tuple[float, float]:
    if loader is None:
        return 0.0, 0.0
    model.train(train)
    total_loss = 0.0
    correct = 0
    total = 0
    batches = tqdm(loader, leave=False) if show_progress else loader

    for pixel_values, labels in batches:
        pixel_values = pixel_values.to(device)
        labels = labels.to(device)
        if train:
            optimizer.zero_grad()
        outputs = model(pixel_values=pixel_values, labels=labels)
        loss = outputs.loss
        if train:
            loss.backward()
            optimizer.step()
        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        correct += (outputs.logits.argmax(dim=1) == labels).sum().item()
        total += batch_size
    return total_loss / max(total, 1), correct / max(total, 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune VideoMAE on downloaded accident videos.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label-column", default=DEFAULT_LABEL_COLUMN)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--frame-count", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--weight-decay", type=float, default=0.05)
    parser.add_argument("--early-stopping-patience", type=int, default=2)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--freeze-backbone", action="store_true")
    parser.add_argument("--show-progress", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    set_seed(args.seed)

    rows = filter_rows(read_csv(args.manifest), args.root_dir, args.label_column)
    if not rows:
        raise ValueError(f"No valid video rows found in {args.manifest}")

    train_rows, val_rows, test_rows = split_rows(rows)
    label_to_index = build_label_mapping(rows, args.label_column)
    id2label = {index: label for label, index in label_to_index.items()}
    label2id = {label: index for label, index in label_to_index.items()}

    device = choose_device(args.device)
    processor = VideoMAEImageProcessor.from_pretrained(args.model_name)
    model = VideoMAEForVideoClassification.from_pretrained(
        args.model_name,
        num_labels=len(label_to_index),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    ).to(device)

    if args.freeze_backbone:
        for parameter in model.videomae.parameters():
            parameter.requires_grad = False

    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )

    train_loader = make_loader(train_rows, label_to_index, args.label_column, args.frame_count, processor, args.batch_size, args.num_workers, True)
    val_loader = make_loader(val_rows, label_to_index, args.label_column, args.frame_count, processor, args.batch_size, args.num_workers, False)
    test_loader = make_loader(test_rows, label_to_index, args.label_column, args.frame_count, processor, args.batch_size, args.num_workers, False)

    run_id = datetime.now().strftime("videomae_cls_%Y%m%d_%H%M%S")
    output_dir = args.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    history = []
    best_val_acc = -1.0
    best_epoch = 0
    epochs_without_improvement = 0
    best_state = None

    print(f"run_id: {run_id}")
    print(f"device: {device}")
    print(f"manifest: {args.manifest}")
    print(f"labels: {label_to_index}")
    print(f"rows: train={len(train_rows)} val={len(val_rows)} test={len(test_rows)}")

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = run_epoch(model, train_loader, optimizer, device, True, args.show_progress)
        with torch.no_grad():
            val_loss, val_acc = run_epoch(model, val_loader, optimizer, device, False, args.show_progress)
            test_loss, test_acc = run_epoch(model, test_loader, optimizer, device, False, args.show_progress)
        row = {
            "epoch": str(epoch),
            "train_loss": f"{train_loss:.6f}",
            "train_accuracy": f"{train_acc:.6f}",
            "val_loss": f"{val_loss:.6f}",
            "val_accuracy": f"{val_acc:.6f}",
            "test_loss": f"{test_loss:.6f}",
            "test_accuracy": f"{test_acc:.6f}",
        }
        history.append(row)
        print(
            f"epoch={epoch} train_loss={row['train_loss']} train_acc={row['train_accuracy']} "
            f"val_loss={row['val_loss']} val_acc={row['val_accuracy']}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_epoch = epoch
            epochs_without_improvement = 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            epochs_without_improvement += 1
            if args.early_stopping_patience > 0 and epochs_without_improvement >= args.early_stopping_patience:
                print(f"early_stopping: epoch={epoch} best_epoch={best_epoch} best_val_acc={best_val_acc:.6f}")
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    model.save_pretrained(output_dir)
    processor.save_pretrained(output_dir)
    (output_dir / "class_mapping.json").write_text(json.dumps(label_to_index, ensure_ascii=False, indent=2), encoding="utf-8")
    config = {
        "run_id": run_id,
        "manifest": args.manifest.as_posix(),
        "label_column": args.label_column,
        "model_name": args.model_name,
        "freeze_backbone": args.freeze_backbone,
        "frame_count": args.frame_count,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "early_stopping_patience": args.early_stopping_patience,
        "best_epoch": best_epoch,
        "best_val_accuracy": best_val_acc,
        "seed": args.seed,
        "device": str(device),
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "test_rows": len(test_rows),
        "model_path": output_dir.as_posix(),
    }
    (output_dir / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(history, output_dir / "training_history.csv", list(history[0].keys()))
    print(f"output_dir: {output_dir}")


if __name__ == "__main__":
    main()
