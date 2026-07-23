"""Classify canonical image/PDF attachments without returning document contents."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import fitz
import openai

from ai.agents.attachment_document_classification import normalize_classification


SUPPORTED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "application/pdf"}
)
MAX_PDF_PAGES = 10
DOCUMENT_CLASSIFICATION_PROMPT = (
    "Classify the attached traffic/legal-support document only. "
    "Return a JSON object with exactly classification and confidence. "
    "classification must be one of fine_notice, accident_evidence, or unknown. "
    "confidence must be a number from 0 to 1. Do not extract, repeat, or describe document text."
)


def classify_document_bytes(file_bytes: bytes, content_type: str) -> dict[str, Any]:
    """Return a small, safe classification envelope for one image or PDF."""

    normalized_content_type = str(content_type or "").lower().strip()
    if normalized_content_type not in SUPPORTED_CONTENT_TYPES or not file_bytes:
        return _failed_result("unsupported_document_classification_input")
    try:
        raw_result = _request_classification(file_bytes, normalized_content_type)
        structured_result = normalize_classification(raw_result)
    except Exception:
        return _failed_result("document_classification_failed")

    status = "success" if structured_result["requires_confirmation"] else "partial"
    next_action = str(structured_result["next_action"])
    return {
        "status": status,
        "structured_result": structured_result,
        "evidence": [],
        "next_actions": [next_action],
        "limitations": [],
    }


def _request_classification(file_bytes: bytes, content_type: str) -> dict[str, Any]:
    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=96,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": DOCUMENT_CLASSIFICATION_PROMPT},
                    *_image_blocks(file_bytes, content_type),
                ],
            }
        ],
    )
    content = str(response.choices[0].message.content or "").strip()
    return _json_object(content)


def _image_blocks(file_bytes: bytes, content_type: str) -> list[dict[str, Any]]:
    if content_type == "application/pdf":
        return [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
            for encoded, mime in _pdf_to_image_pages(file_bytes)
        ]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    return [
        {
            "type": "image_url",
            "image_url": {"url": f"data:{content_type};base64,{encoded}"},
        }
    ]


def _pdf_to_image_pages(pdf_bytes: bytes) -> list[tuple[str, str]]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if not 1 <= len(document) <= MAX_PDF_PAGES:
            raise ValueError("unsupported_pdf_page_count")
        return [
            (base64.b64encode(page.get_pixmap(dpi=200).tobytes("png")).decode("ascii"), "image/png")
            for page in document
        ]
    finally:
        document.close()


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group())
    if not isinstance(parsed, dict):
        raise ValueError("document_classification_response_must_be_an_object")
    return parsed


def _failed_result(error_code: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "structured_result": {
            "classification": "unknown",
            "confidence_band": "low",
            "requires_confirmation": False,
            "next_action": "retry_upload",
            "error_code": error_code,
        },
        "evidence": [],
        "next_actions": ["retry_upload"],
        "limitations": ["Document classification could not be completed safely."],
    }
