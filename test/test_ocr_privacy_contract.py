from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from ai.agents.fine_notice_analysis import agent as fine_notice_agent
from app.security.pii_masking import MASK_TOKEN
from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import (
    agent as traffic_ocr_agent,
)
from etl.fault_cases.src.OCR.traffic_accident_confirmation_ocr import (
    utils as traffic_ocr_utils,
)


PII_PAYLOAD = {
    "applicant_name": "홍길동",
    "phone_number": "010-1234-5678",
    "vehicle_number": "12가3456",
    "home_address": "서울특별시 강남구 테헤란로 123",
    "resident_registration_number": "900101-1234567",
    "driver_license_number": "11-22-123456-78",
    "access_token": "secret-ocr-access-token",
}


def _assert_raw_values_absent(value) -> None:
    serialized = repr(value)
    for raw in PII_PAYLOAD.values():
        assert raw not in serialized


def test_fine_notice_provider_response_is_sanitized_after_json_parsing(monkeypatch) -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(PII_PAYLOAD, ensure_ascii=False)
                )
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response)
        )
    )
    monkeypatch.setattr(fine_notice_agent.openai, "OpenAI", lambda: client)

    result = fine_notice_agent._call_gpt([])

    _assert_raw_values_absent(result)
    assert set(result.values()) == {MASK_TOKEN}


def test_traffic_ocr_json_parser_sanitizes_structured_provider_output() -> None:
    parsed = traffic_ocr_agent._parse_json_response(
        json.dumps({"extracted_fields": PII_PAYLOAD}, ensure_ascii=False)
    )

    _assert_raw_values_absent(parsed)
    assert set(parsed["extracted_fields"].values()) == {MASK_TOKEN}


def test_traffic_ocr_provider_exception_uses_stable_public_detail(monkeypatch) -> None:
    captured = {}

    def raise_private_error(*_args, **_kwargs):
        raise RuntimeError(
            "홍길동 010-1234-5678 900101-1234567 secret provider detail"
        )

    def capture_output(result, **_kwargs):
        captured["result"] = result
        return "captured.json"

    monkeypatch.setattr(traffic_ocr_agent, "_call_gpt_vision", raise_private_error)
    monkeypatch.setattr(traffic_ocr_agent, "save_ocr_output", capture_output)

    result = traffic_ocr_agent.ocr_node(
        {
            "document_image": base64.b64encode(b"image").decode("ascii"),
            "document_mime_type": "image/jpeg",
        }
    )

    serialized = repr({"result": result, "saved": captured["result"]})
    assert "홍길동" not in serialized
    assert "010-1234-5678" not in serialized
    assert "900101-1234567" not in serialized
    assert "secret provider detail" not in serialized
    assert result["limitations"] == ["ocr_provider_error:RuntimeError"]


def test_saved_ocr_json_masks_nested_pii_errors_and_secrets(monkeypatch) -> None:
    writes: list[str] = []
    source = {
        "status": "failed",
        "summary": "성명: 홍길동, 전화: 010-1234-5678 OCR 실패",
        "structured_result": PII_PAYLOAD,
        "limitations": ["provider failed for 900101-1234567"],
        "document_image": "raw-base64-image",
    }

    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda _self, data, **_kwargs: writes.append(data) or len(data),
    )

    traffic_ocr_utils.save_ocr_output(
        source,
        source_filename="notice.jpg",
        output_dir="ignored-output-dir",
    )

    assert writes
    saved = json.loads(writes[0])
    _assert_raw_values_absent(saved)
    assert "document_image" not in saved
    assert "raw-base64-image" not in writes[0]
    assert MASK_TOKEN in writes[0]


def test_saved_ocr_output_omits_raw_text_and_source_filename_pii(tmp_path) -> None:
    source_filename = "홍길동_교통사고사실확인원.jpg"
    source = {
        "status": "success",
        "structured_result": {
            "raw_text_redacted": "홍길동 서울특별시 강남구 테헤란로 123",
        },
    }

    saved_path = Path(
        traffic_ocr_utils.save_ocr_output(
            source,
            source_filename=source_filename,
            output_dir=tmp_path,
        )
    )
    saved = json.loads(saved_path.read_text(encoding="utf-8"))

    assert "raw_text_redacted" not in saved["structured_result"]
    assert "홍길동" not in saved_path.name
    assert "홍길동" not in saved_path.read_text(encoding="utf-8")
