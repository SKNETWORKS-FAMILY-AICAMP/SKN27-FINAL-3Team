from ai.vision.evaluate_videomae_classifier import classification_metrics


def test_classification_metrics_reports_per_class_and_low_confidence():
    metrics, confusion = classification_metrics(
        expected=[0, 0, 1, 1],
        predicted=[0, 1, 1, 1],
        confidences=[0.9, 0.4, 0.8, 0.3],
        labels=["a", "b"],
        confidence_threshold=0.5,
    )

    assert confusion == [[1, 1], [0, 2]]
    assert metrics["accuracy"] == 0.75
    assert metrics["macro_f1"] == 0.733333
    assert metrics["low_confidence_rate"] == 0.5
    assert metrics["per_class"]["a"]["recall"] == 0.5
    assert metrics["per_class"]["b"]["precision"] == 0.666667


def test_training_evaluates_test_split_only_after_best_checkpoint(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import torch

    from ai.vision import train_videomae_classifier as training

    labels = ["car_vs_bicycle", "car_vs_car", "car_vs_motorcycle", "car_vs_pedestrian"]
    rows = [
        {"coarse_label": label, "split": split}
        for label in labels
        for split in ("train", "val", "test")
    ]
    args = SimpleNamespace(
        seed=42,
        manifest=tmp_path / "manifest.csv",
        root_dir=tmp_path,
        output_dir=tmp_path,
        label_column="coarse_label",
        model_name="fake",
        frame_count=32,
        epochs=2,
        batch_size=1,
        learning_rate=1e-5,
        weight_decay=0.0,
        early_stopping_patience=1,
        num_workers=0,
        device="cpu",
        freeze_backbone=False,
        show_progress=False,
    )

    class FakeModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.zeros(1))

        def save_pretrained(self, output_dir):
            output_dir.mkdir(parents=True, exist_ok=True)

    class FakeProcessor:
        def save_pretrained(self, output_dir):
            pass

    class FakeConfig:
        pass

    model = FakeModel()
    phases = []
    validation_scores = iter((0.6, 0.5))

    def fake_run_epoch(_model, _loader, _optimizer, _device, train, _show, phase="", epoch=None):
        phases.append(phase)
        if phase == "validation":
            return 0.5, next(validation_scores)
        if phase == "final test":
            return 0.4, 0.7
        return 0.3, 0.8

    monkeypatch.setattr(training, "parse_args", lambda: args)
    monkeypatch.setattr(training, "set_seed", lambda _seed: None)
    monkeypatch.setattr(training, "read_csv", lambda _path: rows)
    monkeypatch.setattr(training, "filter_rows", lambda *_args: rows)
    monkeypatch.setattr(training, "choose_device", lambda _device: torch.device("cpu"))
    monkeypatch.setattr(training, "make_loader", lambda split_rows, *_args: split_rows)
    monkeypatch.setattr(training, "run_epoch", fake_run_epoch)
    monkeypatch.setattr(training.VideoMAEImageProcessor, "from_pretrained", lambda _name: FakeProcessor())
    monkeypatch.setattr(training.VideoMAEConfig, "from_pretrained", lambda _name: FakeConfig())
    monkeypatch.setattr(
        training.VideoMAEForVideoClassification,
        "from_pretrained",
        lambda *_args, **_kwargs: model,
    )

    training.main()

    assert phases == ["train", "validation", "train", "validation", "final test"]
