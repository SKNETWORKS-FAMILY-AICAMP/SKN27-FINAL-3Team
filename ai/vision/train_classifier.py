"""Train a frame-level accident type classifier from a manifest CSV.

This script is intentionally small and parameterized for local dry-run first.
Use frame_manifest_dryrun.csv to verify the training loop before paying for GPU time.
"""
from pathlib import Path
import argparse
import csv
import json
import random
from datetime import datetime

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms


DEFAULT_MANIFEST_PATH = Path(
    "storage/vision/datasets/classification/manifests/frame_manifest_dryrun.csv"
)
DEFAULT_OUTPUT_DIR = Path("storage/vision/models/classification")
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


class FrameClassificationDataset(Dataset):
    """Dataset that reads frame paths and labels from the frame-level manifest."""

    def __init__(
        self,
        rows: list[dict],
        root_dir: Path,
        label_to_index: dict[str, int],
        label_column: str,
        transform: transforms.Compose,
    ) -> None:
        self.rows = rows
        self.root_dir = root_dir
        self.label_to_index = label_to_index
        self.label_column = label_column
        self.transform = transform

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        row = self.rows[index]
        frame_path = self.root_dir / row["frame_path"]
        label = row[self.label_column]

        image = Image.open(frame_path).convert("RGB")
        image_tensor = self.transform(image)
        label_tensor = torch.tensor(self.label_to_index[label], dtype=torch.long)
        return image_tensor, label_tensor


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def filter_valid_rows(rows: list[dict], root_dir: Path, label_column: str) -> list[dict]:
    valid_rows = []
    for row in rows:
        frame_path = root_dir / row.get("frame_path", "")
        label = row.get(label_column, "")
        if not label:
            continue
        if row.get("extract_status") and row.get("extract_status") != "extracted":
            continue
        if not frame_path.exists():
            continue
        valid_rows.append(row)
    return valid_rows


def build_label_mapping(rows: list[dict], label_column: str) -> dict[str, int]:
    labels = sorted({row[label_column] for row in rows if row.get(label_column)})
    if not labels:
        raise ValueError(f"No labels found in column: {label_column}")
    return {label: index for index, label in enumerate(labels)}


def split_rows(rows: list[dict], val_ratio: float, seed: int) -> tuple[list[dict], list[dict], list[dict]]:
    train_rows = [row for row in rows if row.get("split") == "train"]
    val_rows = [row for row in rows if row.get("split") == "val"]
    test_rows = [row for row in rows if row.get("split") == "test"]

    if not val_rows and len(train_rows) > 1 and val_ratio > 0:
        rng = random.Random(seed)
        shuffled = list(train_rows)
        rng.shuffle(shuffled)
        val_count = max(1, int(len(shuffled) * val_ratio))
        val_rows = shuffled[:val_count]
        train_rows = shuffled[val_count:]

    return train_rows, val_rows, test_rows


def build_transform(image_size: int, train: bool) -> transforms.Compose:
    if train:
        return transforms.Compose(
            [
                transforms.Resize((image_size, image_size)),
                transforms.RandomHorizontalFlip(p=0.5),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )
    return transforms.Compose(
        [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )


def build_model(model_name: str, num_classes: int, pretrained: bool, freeze_backbone: bool) -> nn.Module:
    if model_name != "resnet18":
        raise ValueError(f"Unsupported model_name for first baseline: {model_name}")

    weights = models.ResNet18_Weights.DEFAULT if pretrained else None
    model = models.resnet18(weights=weights)

    if freeze_backbone:
        for parameter in model.parameters():
            parameter.requires_grad = False

    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, num_classes)
    return model


def choose_device(device_arg: str) -> torch.device:
    if device_arg != "auto":
        return torch.device(device_arg)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def train_one_epoch(
    model: nn.Module,
    dataloader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0

    for images, labels in dataloader:
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        correct += (outputs.argmax(dim=1) == labels).sum().item()
        total += batch_size

    return total_loss / max(total, 1), correct / max(total, 1)


@torch.no_grad()
def evaluate(
    model: nn.Module,
    dataloader: DataLoader | None,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float | None, float | None]:
    if dataloader is None:
        return None, None

    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    for images, labels in dataloader:
        images = images.to(device)
        labels = labels.to(device)
        outputs = model(images)
        loss = criterion(outputs, labels)

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        correct += (outputs.argmax(dim=1) == labels).sum().item()
        total += batch_size

    if total == 0:
        return None, None
    return total_loss / total, correct / total


def make_loader(
    rows: list[dict],
    root_dir: Path,
    label_to_index: dict[str, int],
    label_column: str,
    image_size: int,
    batch_size: int,
    num_workers: int,
    train: bool,
) -> DataLoader | None:
    if not rows:
        return None
    dataset = FrameClassificationDataset(
        rows=rows,
        root_dir=root_dir,
        label_to_index=label_to_index,
        label_column=label_column,
        transform=build_transform(image_size, train=train),
    )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=train,
        num_workers=num_workers,
    )


def save_outputs(
    output_dir: Path,
    model: nn.Module,
    label_to_index: dict[str, int],
    history: list[dict],
    config: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.pt"
    torch.save(model.state_dict(), model_path)

    (output_dir / "class_mapping.json").write_text(
        json.dumps(label_to_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "run_config.json").write_text(
        json.dumps(config | {"model_path": model_path.as_posix()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(
        history,
        output_dir / "training_history.csv",
        [
            "epoch",
            "train_loss",
            "train_accuracy",
            "val_loss",
            "val_accuracy",
            "test_loss",
            "test_accuracy",
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a frame-level Vision classifier baseline.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label-column", default=DEFAULT_LABEL_COLUMN)
    parser.add_argument("--model-name", default="resnet18")
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--val-ratio-if-missing", type=float, default=0.25)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--pretrained", action="store_true")
    parser.add_argument("--freeze-backbone", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    set_seed(args.seed)

    rows = read_csv(args.manifest)
    rows = filter_valid_rows(rows, args.root_dir, args.label_column)
    if not rows:
        raise ValueError(f"No valid frame rows found in {args.manifest}")

    label_to_index = build_label_mapping(rows, args.label_column)
    train_rows, val_rows, test_rows = split_rows(rows, args.val_ratio_if_missing, args.seed)

    device = choose_device(args.device)
    model = build_model(args.model_name, len(label_to_index), args.pretrained, args.freeze_backbone).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=args.learning_rate,
    )

    train_loader = make_loader(
        train_rows,
        args.root_dir,
        label_to_index,
        args.label_column,
        args.image_size,
        args.batch_size,
        args.num_workers,
        train=True,
    )
    val_loader = make_loader(
        val_rows,
        args.root_dir,
        label_to_index,
        args.label_column,
        args.image_size,
        args.batch_size,
        args.num_workers,
        train=False,
    )
    test_loader = make_loader(
        test_rows,
        args.root_dir,
        label_to_index,
        args.label_column,
        args.image_size,
        args.batch_size,
        args.num_workers,
        train=False,
    )

    if train_loader is None:
        raise ValueError("No training rows available after split.")

    run_id = datetime.now().strftime("vision_cls_%Y%m%d_%H%M%S")
    output_dir = args.output_dir / run_id
    history = []

    print(f"run_id: {run_id}")
    print(f"device: {device}")
    print(f"manifest: {args.manifest}")
    print(f"labels: {label_to_index}")
    print(f"rows: train={len(train_rows)} val={len(val_rows)} test={len(test_rows)}")

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)
        test_loss, test_acc = evaluate(model, test_loader, criterion, device)

        history_row = {
            "epoch": str(epoch),
            "train_loss": f"{train_loss:.6f}",
            "train_accuracy": f"{train_acc:.6f}",
            "val_loss": "" if val_loss is None else f"{val_loss:.6f}",
            "val_accuracy": "" if val_acc is None else f"{val_acc:.6f}",
            "test_loss": "" if test_loss is None else f"{test_loss:.6f}",
            "test_accuracy": "" if test_acc is None else f"{test_acc:.6f}",
        }
        history.append(history_row)
        print(
            f"epoch={epoch} "
            f"train_loss={history_row['train_loss']} train_acc={history_row['train_accuracy']} "
            f"val_loss={history_row['val_loss']} val_acc={history_row['val_accuracy']}"
        )

    config = {
        "run_id": run_id,
        "manifest": args.manifest.as_posix(),
        "label_column": args.label_column,
        "model_name": args.model_name,
        "pretrained": args.pretrained,
        "freeze_backbone": args.freeze_backbone,
        "image_size": args.image_size,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "seed": args.seed,
        "device": str(device),
        "num_classes": len(label_to_index),
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "test_rows": len(test_rows),
    }
    save_outputs(output_dir, model, label_to_index, history, config)
    print(f"output_dir: {output_dir}")


if __name__ == "__main__":
    main()

