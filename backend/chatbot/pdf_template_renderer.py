from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: pdf_template_renderer.py <payload.json> <output.pdf>", file=sys.stderr)
        return 2

    payload_path = Path(argv[1])
    output_path = Path(argv[2])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    template_pdf = Path(str(payload.get("template_pdf") or ""))
    form_data = payload.get("form_data") or {}
    font_file = str(payload.get("font_file") or "").strip() or None

    if not template_pdf.exists():
        print(f"template not found: {template_pdf}", file=sys.stderr)
        return 1

    template_reader = PdfReader(str(template_pdf))
    if not template_reader.pages:
        print("template has no pages", file=sys.stderr)
        return 1

    font_name = "Helvetica"
    try:
        if font_file and Path(font_file).exists():
            font_name = "ReportOverlay"
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, font_file))
    except Exception as exc:
        print(f"font registration failed: {exc}", file=sys.stderr)
        font_name = "Helvetica"

    first_page = template_reader.pages[0]
    page_width = float(first_page.mediabox.width)
    page_height = float(first_page.mediabox.height)

    overlay_stream = BytesIO()
    overlay_canvas = Canvas(overlay_stream, pagesize=(page_width, page_height))
    overlay_canvas.setFillColorRGB(0, 0, 0)

    for page_index in range(len(template_reader.pages)):
        if page_index == 1:
            draw_accident_objection_template_page_2(
                overlay_canvas, page_height=page_height, font_name=font_name, data=form_data
            )
        elif page_index == 2:
            draw_accident_objection_template_page_3(
                overlay_canvas, page_height=page_height, font_name=font_name, data=form_data
            )
        elif page_index == 3:
            draw_accident_objection_template_page_4(
                overlay_canvas, page_height=page_height, font_name=font_name, data=form_data
            )
        elif page_index == 4:
            draw_accident_objection_template_page_5(
                overlay_canvas, page_height=page_height, font_name=font_name, data=form_data
            )
        overlay_canvas.showPage()

    overlay_canvas.save()
    overlay_stream.seek(0)
    overlay_reader = PdfReader(overlay_stream)

    writer = PdfWriter()
    for page_index, template_page in enumerate(template_reader.pages):
        if page_index < len(overlay_reader.pages):
            template_page.merge_page(overlay_reader.pages[page_index])
        writer.add_page(template_page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    return 0


def draw_accident_objection_template_page_2(
    pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]
) -> None:
    draw_text_block(pdf_canvas, data.get("recipient", ""), x=250, top=147, page_height=page_height, width=34, max_lines=1, font_name=font_name, font_size=10)
    draw_text_block(pdf_canvas, data.get("applicant_name", ""), x=126, top=289, page_height=page_height, width=20, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, "", x=428, top=289, page_height=page_height, width=18, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, "", x=126, top=329, page_height=page_height, width=28, max_lines=2, font_name=font_name)
    draw_text_block(pdf_canvas, "", x=428, top=329, page_height=page_height, width=18, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, "", x=126, top=369, page_height=page_height, width=28, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("relationship", ""), x=427, top=369, page_height=page_height, width=24, max_lines=2, font_name=font_name)

    draw_text_block(pdf_canvas, data.get("case_number", ""), x=126, top=482, page_height=page_height, width=26, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("incident_at", ""), x=428, top=482, page_height=page_height, width=22, max_lines=2, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("location", ""), x=126, top=522, page_height=page_height, width=30, max_lines=2, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("police_station", ""), x=428, top=522, page_height=page_height, width=20, max_lines=2, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("investigator", ""), x=126, top=562, page_height=page_height, width=24, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("notice_date", ""), x=428, top=562, page_height=page_height, width=18, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("vehicle_parties", ""), x=126, top=603, page_height=page_height, width=30, max_lines=2, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("insurance_number", ""), x=428, top=603, page_height=page_height, width=20, max_lines=2, font_name=font_name)

    objection_targets = data.get("objection_targets") or []
    draw_text_block(
        pdf_canvas,
        f"\uc120\ud0dd \ucabd\uc810: {', '.join(objection_targets)}",
        x=96,
        top=696,
        page_height=page_height,
        width=94,
        max_lines=2,
        font_name=font_name,
        font_size=9,
        leading=12,
    )
    draw_text_block(pdf_canvas, data.get("purpose", ""), x=96, top=780, page_height=page_height, width=94, max_lines=5, font_name=font_name, leading=14)
    draw_text_block(pdf_canvas, data.get("write_date", ""), x=126, top=927, page_height=page_height, width=20, max_lines=1, font_name=font_name)
    draw_text_block(pdf_canvas, data.get("applicant_name", ""), x=428, top=927, page_height=page_height, width=16, max_lines=1, font_name=font_name)


def draw_accident_objection_template_page_3(
    pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]
) -> None:
    draw_text_block(pdf_canvas, data.get("rebuttal_summary", ""), x=92, top=180, page_height=page_height, width=92, max_lines=3, font_name=font_name, font_size=10, leading=13)

    objection_targets = list(data.get("objection_targets") or [])
    evidence_rows = list(data.get("evidence_rows") or [])
    issue_rows = []
    for target, row in zip(objection_targets[:3], evidence_rows[:3]):
        issue_rows.append({"dispute": target, "claim": data.get("summary", ""), "evidence": row.get("no", "")})

    row_tops = [257, 287, 317]
    for index, row in enumerate(issue_rows[:3]):
        draw_text_block(pdf_canvas, str(index + 1), x=118, top=row_tops[index], page_height=page_height, width=3, max_lines=1, font_name=font_name, font_size=9)
        draw_text_block(pdf_canvas, row["dispute"], x=148, top=row_tops[index], page_height=page_height, width=18, max_lines=2, font_name=font_name, font_size=9, leading=11)
        draw_text_block(pdf_canvas, row["claim"], x=282, top=row_tops[index], page_height=page_height, width=22, max_lines=2, font_name=font_name, font_size=9, leading=11)
        draw_text_block(pdf_canvas, row["evidence"], x=503, top=row_tops[index], page_height=page_height, width=5, max_lines=1, font_name=font_name, font_size=9)

    draw_text_block(pdf_canvas, data.get("summary", ""), x=92, top=410, page_height=page_height, width=94, max_lines=5, font_name=font_name, leading=14)
    draw_text_block(pdf_canvas, data.get("evidence_summary", ""), x=92, top=533, page_height=page_height, width=94, max_lines=4, font_name=font_name, leading=14)
    draw_text_block(pdf_canvas, data.get("action_detail", ""), x=92, top=655, page_height=page_height, width=94, max_lines=3, font_name=font_name, leading=14)


def draw_accident_objection_template_page_4(
    pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]
) -> None:
    evidence_row_tops = [164, 196, 228, 260, 292, 324]
    for index, row in enumerate(list(data.get("evidence_rows") or [])[:6]):
        top = evidence_row_tops[index]
        draw_text_block(pdf_canvas, row.get("name", ""), x=100, top=top, page_height=page_height, width=18, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
        draw_text_block(pdf_canvas, row.get("fact", ""), x=260, top=top, page_height=page_height, width=20, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
        draw_text_block(pdf_canvas, row.get("format", ""), x=425, top=top, page_height=page_height, width=12, max_lines=2, font_name=font_name, font_size=8, leading=9.5)

    draw_text_block(pdf_canvas, data.get("rebuttal_brief", data.get("rebuttal_summary", "")), x=92, top=473, page_height=page_height, width=20, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
    draw_text_block(pdf_canvas, data.get("response_brief", data.get("summary", "")), x=280, top=473, page_height=page_height, width=20, max_lines=2, font_name=font_name, font_size=8, leading=9.5)
    draw_text_block(pdf_canvas, "1-3", x=469, top=473, page_height=page_height, width=6, max_lines=1, font_name=font_name, font_size=8.5)
    draw_text_block(pdf_canvas, "\uc7ac\uc870\uc0ac \uc694\uccad", x=514, top=473, page_height=page_height, width=10, max_lines=2, font_name=font_name, font_size=8.5, leading=10)


def draw_accident_objection_template_page_5(
    pdf_canvas, *, page_height: float, font_name: str, data: dict[str, Any]
) -> None:
    draw_text_block(pdf_canvas, data.get("target_brief", ""), x=372, top=551, page_height=page_height, width=16, max_lines=2, font_name=font_name, font_size=8.5, leading=9.5)
    draw_text_block(pdf_canvas, data.get("reason_detail", ""), x=92, top=657, page_height=page_height, width=90, max_lines=4, font_name=font_name, font_size=8.5, leading=11)


def draw_text_block(
    pdf_canvas,
    text: str,
    *,
    x: float,
    top: float,
    page_height: float,
    width: int,
    max_lines: int,
    font_name: str,
    font_size: float = 10,
    leading: float = 12,
) -> None:
    lines = pdf_block_lines(text, width=width, max_lines=max_lines)
    if not lines:
        return
    pdf_canvas.setFont(font_name, font_size)
    baseline = page_height - top
    for index, line in enumerate(lines):
        pdf_canvas.drawString(x, baseline - (index * leading), line)


def pdf_block_lines(text: str, *, width: int, max_lines: int) -> list[str]:
    value = clean_text(text)
    if not value:
        return []
    lines: list[str] = []
    for raw_line in value.replace("\r", "").split("\n"):
        wrapped = wrap_report_pdf_line(raw_line.strip(), width=width)
        lines.extend(wrapped or [""])
    compact_lines = [line for line in lines if line]
    if not compact_lines:
        return []
    if len(compact_lines) <= max_lines:
        return compact_lines
    truncated = compact_lines[:max_lines]
    if len(truncated[-1]) >= max(width - 3, 1):
        truncated[-1] = truncated[-1][: width - 3].rstrip()
    truncated[-1] = f"{truncated[-1]}..."
    return truncated


def wrap_report_pdf_line(text: str, *, width: int) -> list[str]:
    value = str(text or "")
    if len(value) <= width:
        return [value]
    chunks = []
    current = ""
    for word in value.split(" "):
        if not word:
            continue
        if len(word) > width:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(word[index : index + width] for index in range(0, len(word), width))
            continue
        next_value = f"{current} {word}".strip()
        if len(next_value) > width and current:
            chunks.append(current)
            current = word
        else:
            current = next_value
    if current:
        chunks.append(current)
    return chunks or [value[:width]]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
