from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from io import BytesIO
from pathlib import Path

import fitz
import pdfplumber
from pypdf import PdfReader

from scripts.build_supervisor_acceptance_fixture import (
    DEFAULT_PDF_PATH,
    DEFAULT_PREVIEW_PATH,
    FIXTURE_FIELDS,
    OPINION_DEADLINE,
    SAFETY_MARKINGS,
    build_fixture_pdf,
    main,
    render_preview,
)


EXPECTED_FIELDS = {
    "문서명": "과태료 부과 사전통지서",
    "처분 유형": "과태료",
    "통지 단계": "사전통지",
    "발급 기관": "테스트구청 교통행정과",
    "사건 번호": "TEST-20260802-001",
    "발급일": "2026-08-02",
    "의견 제출 기한": "2026-08-31",
    "위반 일시": "2026-07-31 10:30",
    "위반 장소": "테스트 도로 구간",
    "위반 내용": "주정차 위반 테스트 데이터",
    "적용 법령": "도로교통법 제32조",
    "과태료 금액": "120,000원",
    "수신인": "테스트 사용자",
    "차량 식별값": "TEST-0000",
}

FORBIDDEN_PATTERNS = (
    r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)",
    r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)",
    r"\b\d{2}[-\s]?\d{6}[-\s]?\d{2}\b",
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    r"(?:[A-Za-z]:\\|/Users/|/home/)",
    r"s3://",
    r"[?&](?:X-Amz-|signature=|token=)",
)


def test_fixture_contract_drives_an_unexpired_synthetic_prior_notice() -> None:
    assert SAFETY_MARKINGS == (
        "테스트 전용 문서",
        "실제 효력 없음",
        "개인정보 없는 운영 검증용 fixture",
    )
    assert {field.label: field.value for field in FIXTURE_FIELDS} == EXPECTED_FIELDS
    assert OPINION_DEADLINE == date(2026, 8, 31)
    assert OPINION_DEADLINE > date(2026, 8, 2)
    assert DEFAULT_PDF_PATH.as_posix() == (
        "output/pdf/"
        "pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf"
    )
    assert DEFAULT_PREVIEW_PATH.as_posix() == (
        "output/pdf/"
        "pilot-fine-notice-prior-notice-valid-through-20260831-v1.png"
    )


def test_fixture_pdf_is_deterministic_one_page_a4_without_active_content() -> None:
    first = build_fixture_pdf()
    second = build_fixture_pdf()

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert len(first) > 1_000

    reader = PdfReader(BytesIO(first))
    root = reader.trailer["/Root"]
    page = reader.pages[0]

    assert len(reader.pages) == 1
    assert abs(float(page.mediabox.width) - 595.28) < 1
    assert abs(float(page.mediabox.height) - 841.89) < 1
    assert "/AcroForm" not in root
    assert "/Names" not in root
    assert "/OpenAction" not in root
    assert "/AA" not in root
    assert "/Annots" not in page

    metadata = {str(key): str(value) for key, value in (reader.metadata or {}).items()}
    serialized_metadata = json.dumps(metadata, ensure_ascii=False)
    assert metadata["/Author"] == "SKN27 Traffic Pilot"
    assert "Playdata" not in serialized_metadata
    assert "C:\\" not in serialized_metadata

    for forbidden_token in (
        b"/JavaScript",
        b"/EmbeddedFile",
        b"/Launch",
        b"file://",
    ):
        assert forbidden_token not in first


def test_fixture_pdf_extracts_every_field_and_contains_no_pii() -> None:
    pdf_bytes = build_fixture_pdf()
    with pdfplumber.open(BytesIO(pdf_bytes)) as document:
        assert len(document.pages) == 1
        extracted = document.pages[0].extract_text() or ""

    for marking in SAFETY_MARKINGS:
        assert marking in extracted
    for label, value in EXPECTED_FIELDS.items():
        assert label in extracted
        assert value in extracted

    reader = PdfReader(BytesIO(pdf_bytes))
    metadata = json.dumps(
        {str(key): str(value) for key, value in (reader.metadata or {}).items()},
        ensure_ascii=False,
    )
    searchable = f"{extracted}\n{metadata}"
    for pattern in FORBIDDEN_PATTERNS:
        assert re.search(pattern, searchable, re.IGNORECASE) is None
    for forbidden_text in ("금천구청", "2025-", "계좌번호", "직인", "서명란", "서명:"):
        assert forbidden_text not in searchable


def test_fixture_preview_is_a_legible_portrait_raster(tmp_path: Path) -> None:
    preview_path = tmp_path / "fixture.png"

    render_preview(build_fixture_pdf(), preview_path)

    assert preview_path.stat().st_size > 10_000
    pixmap = fitz.Pixmap(str(preview_path))
    assert pixmap.width >= 1_100
    assert pixmap.height > pixmap.width
    assert pixmap.alpha == 0


def test_fixture_cli_writes_only_local_artifacts_and_safe_evidence(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    pdf_path = Path("output/pdf/fixture.pdf")
    preview_path = Path("output/pdf/fixture.png")

    exit_code = main(
        [
            "--output",
            str(pdf_path),
            "--preview",
            str(preview_path),
        ]
    )

    assert exit_code == 0
    evidence = json.loads(capsys.readouterr().out)
    pixmap = fitz.Pixmap(str(preview_path))
    assert evidence == {
        "bytes": pdf_path.stat().st_size,
        "contract_version": "supervisor_acceptance_fixture.v1",
        "pages": 1,
        "pdf": pdf_path.as_posix(),
        "preview": preview_path.as_posix(),
        "preview_height": pixmap.height,
        "preview_width": pixmap.width,
        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "status": "generated",
    }
    assert preview_path.exists()
