from __future__ import annotations

import importlib

try:
    adapter = importlib.import_module("app.services.attachment_document_classification_adapter")
except ModuleNotFoundError:
    adapter = None


def test_classify_document_normalizes_only_the_allowed_result_fields(monkeypatch) -> None:
    assert adapter is not None, "attachment document classification adapter must exist"
    monkeypatch.setattr(
        adapter,
        "_request_classification",
        lambda *_args: {
            "classification": "fine_notice",
            "confidence": 0.93,
            "ocr_text": "010-1234-5678 / private text",
            "storage_uri": "s3://private/document.pdf",
        },
    )

    result = adapter.classify_document_bytes(b"image-bytes", "image/png")

    assert result == {
        "status": "success",
        "structured_result": {
            "classification": "fine_notice",
            "confidence_band": "high",
            "requires_confirmation": True,
            "next_action": "confirm_classification",
        },
        "evidence": [],
        "next_actions": ["confirm_classification"],
        "limitations": [],
    }


def test_classify_document_returns_safe_unknown_when_provider_cannot_classify(monkeypatch) -> None:
    assert adapter is not None, "attachment document classification adapter must exist"
    monkeypatch.setattr(
        adapter,
        "_request_classification",
        lambda *_args: {"classification": "other"},
    )

    result = adapter.classify_document_bytes(b"image-bytes", "image/png")

    assert result["status"] == "partial"
    assert result["structured_result"] == {
        "classification": "unknown",
        "confidence_band": "low",
        "requires_confirmation": False,
        "next_action": "change_purpose",
    }
    assert result["next_actions"] == ["change_purpose"]
