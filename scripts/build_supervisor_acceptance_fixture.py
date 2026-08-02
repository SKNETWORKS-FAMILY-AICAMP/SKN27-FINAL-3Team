from __future__ import annotations

import argparse
import hashlib
import json
from io import BytesIO
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import fitz
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas


@dataclass(frozen=True)
class FixtureField:
    label: str
    value: str


DEFAULT_PDF_PATH = Path(
    "output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.pdf"
)
DEFAULT_PREVIEW_PATH = Path(
    "output/pdf/pilot-fine-notice-prior-notice-valid-through-20260831-v1.png"
)
OPINION_DEADLINE = date(2026, 8, 31)
SAFETY_MARKINGS = (
    "테스트 전용 문서",
    "실제 효력 없음",
    "개인정보 없는 운영 검증용 fixture",
)
FIXTURE_FIELDS = (
    FixtureField("문서명", "과태료 부과 사전통지서"),
    FixtureField("처분 유형", "과태료"),
    FixtureField("통지 단계", "사전통지"),
    FixtureField("발급 기관", "테스트구청 교통행정과"),
    FixtureField("사건 번호", "TEST-20260802-001"),
    FixtureField("발급일", "2026-08-02"),
    FixtureField("의견 제출 기한", "2026-08-31"),
    FixtureField("위반 일시", "2026-07-31 10:30"),
    FixtureField("위반 장소", "테스트 도로 구간"),
    FixtureField("위반 내용", "주정차 위반 테스트 데이터"),
    FixtureField("적용 법령", "도로교통법 제32조"),
    FixtureField("과태료 금액", "120,000원"),
    FixtureField("수신인", "테스트 사용자"),
    FixtureField("차량 식별값", "TEST-0000"),
)

CONTRACT_VERSION = "supervisor_acceptance_fixture.v1"
KOREAN_FONT = "HYSMyeongJo-Medium"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 18 * mm


def _register_korean_font() -> None:
    if KOREAN_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT))


def build_fixture_pdf() -> bytes:
    _register_korean_font()
    output = BytesIO()
    pdf_canvas = Canvas(
        output,
        pagesize=A4,
        pageCompression=1,
        invariant=1,
    )
    pdf_canvas.setTitle("SKN27 테스트 전용 과태료 부과 사전통지서")
    pdf_canvas.setAuthor("SKN27 Traffic Pilot")
    pdf_canvas.setSubject("PII-free operator-reviewed acceptance fixture")
    pdf_canvas.setCreator("SKN27 deterministic acceptance fixture builder v1")
    pdf_canvas.setKeywords("synthetic, pii-free, acceptance-fixture")

    _draw_page(pdf_canvas)
    pdf_canvas.showPage()
    pdf_canvas.save()
    return output.getvalue()


def _draw_page(pdf_canvas: Canvas) -> None:
    content_width = PAGE_WIDTH - (2 * MARGIN)
    banner_height = 16 * mm
    banner_bottom = PAGE_HEIGHT - MARGIN - banner_height

    pdf_canvas.setFillColor(colors.HexColor("#991B1B"))
    pdf_canvas.roundRect(
        MARGIN,
        banner_bottom,
        content_width,
        banner_height,
        3 * mm,
        fill=1,
        stroke=0,
    )
    pdf_canvas.setFillColor(colors.white)
    pdf_canvas.setFont(KOREAN_FONT, 15)
    pdf_canvas.drawCentredString(
        PAGE_WIDTH / 2,
        banner_bottom + 5.2 * mm,
        f"{SAFETY_MARKINGS[0]} · {SAFETY_MARKINGS[1]}",
    )

    title_y = banner_bottom - 14 * mm
    pdf_canvas.setFillColor(colors.HexColor("#172554"))
    pdf_canvas.setFont(KOREAN_FONT, 22)
    pdf_canvas.drawCentredString(PAGE_WIDTH / 2, title_y, "과태료 부과 사전통지서")
    pdf_canvas.setFillColor(colors.HexColor("#475569"))
    pdf_canvas.setFont(KOREAN_FONT, 10.5)
    pdf_canvas.drawCentredString(
        PAGE_WIDTH / 2,
        title_y - 8 * mm,
        SAFETY_MARKINGS[2],
    )

    table_top = title_y - 18 * mm
    column_gap = 4 * mm
    column_width = (content_width - column_gap) / 2
    row_height = 18 * mm
    for index, field in enumerate(FIXTURE_FIELDS):
        row = index // 2
        column = index % 2
        x = MARGIN + (column * (column_width + column_gap))
        top = table_top - (row * row_height)
        bottom = top - row_height + 1.5 * mm

        pdf_canvas.setFillColor(colors.HexColor("#F8FAFC"))
        pdf_canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
        pdf_canvas.roundRect(
            x,
            bottom,
            column_width,
            row_height - 1.5 * mm,
            2 * mm,
            fill=1,
            stroke=1,
        )
        pdf_canvas.setFillColor(colors.HexColor("#64748B"))
        pdf_canvas.setFont(KOREAN_FONT, 9)
        pdf_canvas.drawString(x + 4 * mm, top - 6 * mm, field.label)
        pdf_canvas.setFillColor(colors.HexColor("#0F172A"))
        pdf_canvas.setFont(KOREAN_FONT, 10.5)
        pdf_canvas.drawString(x + 4 * mm, top - 12.5 * mm, field.value)

    footer_height = 25 * mm
    footer_bottom = MARGIN
    pdf_canvas.setFillColor(colors.HexColor("#FFF7ED"))
    pdf_canvas.setStrokeColor(colors.HexColor("#FB923C"))
    pdf_canvas.roundRect(
        MARGIN,
        footer_bottom,
        content_width,
        footer_height,
        2 * mm,
        fill=1,
        stroke=1,
    )
    pdf_canvas.setFillColor(colors.HexColor("#9A3412"))
    pdf_canvas.setFont(KOREAN_FONT, 10.5)
    pdf_canvas.drawString(
        MARGIN + 5 * mm,
        footer_bottom + 16 * mm,
        "이 문서는 운영 검증만을 위한 합성 테스트 자료입니다.",
    )
    pdf_canvas.setFont(KOREAN_FONT, 9.5)
    pdf_canvas.drawString(
        MARGIN + 5 * mm,
        footer_bottom + 9.5 * mm,
        "실제 과태료 부과·납부·의견 제출에 사용할 수 없으며 법적 효력이 없습니다.",
    )
    pdf_canvas.drawString(
        MARGIN + 5 * mm,
        footer_bottom + 4 * mm,
        "모든 이름과 식별값은 개인정보가 아닌 테스트 값입니다.",
    )


def render_preview(pdf_bytes: bytes, output_path: Path) -> None:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        if document.page_count != 1:
            raise ValueError("fixture PDF must contain exactly one page")
        pixmap = document.load_page(0).get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(output_path))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the PII-free SKN27 Supervisor acceptance fixture.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_PDF_PATH)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.output.is_absolute() or args.preview.is_absolute():
        parser.error("artifact paths must be relative")
    if args.output.suffix.lower() != ".pdf" or args.preview.suffix.lower() != ".png":
        parser.error("artifact paths must use .pdf and .png extensions")

    pdf_bytes = build_fixture_pdf()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(pdf_bytes)
    render_preview(pdf_bytes, args.preview)

    reader = PdfReader(BytesIO(pdf_bytes))
    preview = fitz.Pixmap(str(args.preview))
    evidence = {
        "bytes": len(pdf_bytes),
        "contract_version": CONTRACT_VERSION,
        "pages": len(reader.pages),
        "pdf": args.output.as_posix(),
        "preview": args.preview.as_posix(),
        "preview_height": preview.height,
        "preview_width": preview.width,
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "status": "generated",
    }
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
