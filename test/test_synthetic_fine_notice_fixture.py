from __future__ import annotations

import json
import re
from pathlib import Path


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "fine_notice"
    / "synthetic_fine_notice.json"
)


def test_synthetic_fine_notice_fixture_has_exact_safe_contract() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert set(fixture) == {
        "fixture_version",
        "document_disposition_type",
        "issuing_authority",
        "response_deadline",
        "synthetic_case_number",
    }
    assert fixture == {
        "fixture_version": "synthetic_fine_notice.v1",
        "document_disposition_type": "과태료 사전통지서",
        "issuing_authority": "가상시청",
        "response_deadline": "2026-08-07",
        "synthetic_case_number": "SYN-2026-0001",
    }


def test_synthetic_fine_notice_fixture_contains_no_real_identifier_or_path() -> None:
    serialized = FIXTURE_PATH.read_text(encoding="utf-8")

    forbidden_patterns = (
        r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}",
        r"\d{6}[-\s]?[1-4]\d{6}",
        r"\b\d{2}[-\s]?\d{6}[-\s]?\d{2}\b",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"s3://",
        r"(?:[A-Za-z]:\\|/Users/|/home/)",
        r"[?&](?:X-Amz-|signature=|token=)",
    )
    for pattern in forbidden_patterns:
        assert re.search(pattern, serialized, re.IGNORECASE) is None
