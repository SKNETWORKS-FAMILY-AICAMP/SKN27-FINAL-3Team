from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_X = 54
MARGIN_TOP = 58
MARGIN_BOTTOM = 56


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: pdf_report_renderer.py <payload.json> <output.pdf>", file=sys.stderr)
        return 2

    payload_path = Path(argv[1])
    output_path = Path(argv[2])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    pdf_bytes = build_pdf(
        report_id=str(payload.get("report_id") or ""),
        title=str(payload.get("title") or "Traffic Dispute AI report"),
        body_text=str(payload.get("body_text") or ""),
        intro=str(payload.get("intro") or ""),
        font_file=str(payload.get("font_file") or "").strip() or None,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)
    return 0


def build_pdf(*, report_id: str, title: str, body_text: str, intro: str, font_file: str | None) -> bytes:
    font_name = register_font(font_file)
    max_width = PAGE_WIDTH - (MARGIN_X * 2)
    output = BytesIO()
    pdf_canvas = Canvas(output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf_canvas.setTitle(title[:120])
    pdf_canvas.setAuthor("Traffic Dispute AI")
    pdf_canvas.setCreator("Traffic Dispute AI")

    y = PAGE_HEIGHT - MARGIN_TOP

    def ensure_page(required_height: float) -> None:
        nonlocal y
        if y - required_height >= MARGIN_BOTTOM:
            return
        pdf_canvas.showPage()
        y = PAGE_HEIGHT - MARGIN_TOP

    def draw_line(text: str, *, size: float = 10.5, leading: float = 16, indent: float = 0) -> None:
        nonlocal y
        ensure_page(leading)
        pdf_canvas.setFont(font_name, size)
        pdf_canvas.drawString(MARGIN_X + indent, y, text)
        y -= leading

    def draw_wrapped(
        text: str,
        *,
        size: float = 10.5,
        leading: float = 16,
        indent: float = 0,
        first_prefix: str = "",
        next_prefix: str = "",
    ) -> None:
        available_width = max_width - indent - pdfmetrics.stringWidth(next_prefix, font_name, size)
        for index, line in enumerate(wrap_line(text, font_name=font_name, font_size=size, max_width=available_width)):
            prefix = first_prefix if index == 0 else next_prefix
            draw_line(f"{prefix}{line}", size=size, leading=leading, indent=indent)

    for line in wrap_line(title or "Traffic Dispute AI report", font_name=font_name, font_size=17, max_width=max_width):
        draw_line(line, size=17, leading=23)
    y -= 4
    if report_id:
        draw_line(f"Report ID: {report_id}", size=9.2, leading=14)
    if intro:
        draw_wrapped(intro, size=9.2, leading=14)
    y -= 12

    for raw_line in str(body_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            y -= 8
            continue
        if line.startswith("# "):
            y -= 6
            draw_wrapped(line[2:], size=15, leading=21)
            y -= 4
            continue
        if line.startswith("## "):
            y -= 8
            draw_wrapped(line[3:], size=13, leading=19)
            y -= 3
            continue
        if line.startswith("### "):
            y -= 5
            draw_wrapped(line[4:], size=11.5, leading=17)
            continue
        if line.startswith("- "):
            draw_wrapped(line[2:], first_prefix="- ", next_prefix="  ", indent=8, size=10.2, leading=15.5)
            continue
        draw_wrapped(line, size=10.2, leading=15.5)

    pdf_canvas.save()
    return output.getvalue()


def register_font(font_file: str | None) -> str:
    if font_file and Path(font_file).exists():
        font_name = "ReportBody"
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, font_file))
        return font_name
    return "Helvetica"


def wrap_line(text: str, *, font_name: str, font_size: float, max_width: float) -> list[str]:
    value = " ".join(str(text or "").split())
    if not value:
        return [""]
    if pdfmetrics.stringWidth(value, font_name, font_size) <= max_width:
        return [value]

    lines: list[str] = []
    current = ""
    for word in value.split(" "):
        candidate = f"{current} {word}".strip()
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            lines.extend(wrap_token(current, font_name=font_name, font_size=font_size, max_width=max_width))
            current = word
            continue
        current = candidate
    if current:
        lines.extend(wrap_token(current, font_name=font_name, font_size=font_size, max_width=max_width))
    return lines or [value]


def wrap_token(text: str, *, font_name: str, font_size: float, max_width: float) -> list[str]:
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return [text]

    chunks: list[str] = []
    current = ""
    for char in text:
        candidate = f"{current}{char}"
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
