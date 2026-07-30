from ai.vision.prepare_benchmark_manifest import incident_id_from_asset, source_metadata, validate


def test_incident_id_uses_validated_source_suffix():
    assert incident_id_from_asset("aihub_train_00000080_bb_1_170227_pedestrian_228_22023") == "aihub_source_suffix:228_22023"


def test_source_metadata_keeps_filename_and_label_provenance():
    metadata = source_metadata(
        "aihub_train_00000001_bb_1_161018_pedestrian_112_331",
        "car_vs_pedestrian",
    )

    assert metadata == {
        "viewpoint": "blackbox_unspecified",
        "viewpoint_source": "filename_capture_code:bb",
        "visible_target": "pedestrian",
        "visible_target_source": "dataset_coarse_label",
    }


def test_validate_detects_exact_content_split_leak():
    rows = [
        {
            "incident_id": "content_sha256:same",
            "split": "train",
            "viewpoint": "blackbox_unspecified",
            "lighting": "day",
            "visible_target": "car",
        },
        {
            "incident_id": "content_sha256:same",
            "split": "test",
            "viewpoint": "blackbox_unspecified",
            "lighting": "day",
            "visible_target": "car",
        },
    ]
