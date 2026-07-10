from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "screen-design-specification.md"
OUTPUT = ROOT / "output" / "pdf" / "화면설계서_27기_3팀_최신화면_Git반영_상세리포팅유지_2026-07-06.pdf"
IMAGE_CACHE_DIR = ROOT / "tmp" / "pdfs" / "optimized-images"
IMAGE_MAX_WIDTH_PX = 1800
IMAGE_JPEG_QUALITY = 76
PAGE_SIZE = landscape(A4)
CONTENT_WIDTH = PAGE_SIZE[0] - 24 * mm
CONTENT_HEIGHT = PAGE_SIZE[1] - 28 * mm


FONT_CANDIDATES = [
    (
        "NotoSansKR",
        Path("C:/Windows/Fonts/NotoSansKR-Regular.ttf"),
        Path("C:/Windows/Fonts/NotoSansKR-Bold.ttf"),
    ),
    (
        "MalgunGothic",
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/malgunbd.ttf"),
    ),
    (
        "NanumGothic",
        Path("C:/Windows/Fonts/NanumGothic.ttf"),
        Path("C:/Windows/Fonts/NanumGothicBold.ttf"),
    ),
]


def register_font() -> str:
    for family, regular, bold in FONT_CANDIDATES:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont(family, str(regular)))
            pdfmetrics.registerFont(TTFont(f"{family}-Bold", str(bold)))
            pdfmetrics.registerFontFamily(
                family,
                normal=family,
                bold=f"{family}-Bold",
                italic=family,
                boldItalic=f"{family}-Bold",
            )
            return family
    raise RuntimeError("한글 PDF 생성을 위한 TTF 폰트를 찾지 못했습니다.")


FONT = register_font()


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    common = {
        "fontName": FONT,
        "wordWrap": "CJK",
        "splitLongWords": True,
    }
    return {
        "title": ParagraphStyle(
            "KTitle",
            parent=base["Title"],
            fontName=f"{FONT}-Bold",
            fontSize=22,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#111827"),
            wordWrap="CJK",
            spaceAfter=7 * mm,
        ),
        "subtitle": ParagraphStyle(
            "KSubtitle",
            parent=base["Normal"],
            **common,
            fontSize=8.5,
            leading=13,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=7 * mm,
        ),
        "h1": ParagraphStyle(
            "KH1",
            parent=base["Heading1"],
            fontName=f"{FONT}-Bold",
            fontSize=14,
            leading=19,
            textColor=colors.HexColor("#111827"),
            wordWrap="CJK",
            spaceBefore=5 * mm,
            spaceAfter=2.5 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "KH2",
            parent=base["Heading2"],
            fontName=f"{FONT}-Bold",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#1f2937"),
            wordWrap="CJK",
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "KH3",
            parent=base["Heading3"],
            fontName=f"{FONT}-Bold",
            fontSize=9.8,
            leading=14,
            textColor=colors.HexColor("#374151"),
            wordWrap="CJK",
            spaceBefore=2.4 * mm,
            spaceAfter=1.5 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "KBody",
            parent=base["BodyText"],
            **common,
            fontSize=8.6,
            leading=13,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#111827"),
            spaceAfter=2.1 * mm,
        ),
        "small": ParagraphStyle(
            "KSmall",
            parent=base["BodyText"],
            **common,
            fontSize=7.2,
            leading=10.5,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=1.4 * mm,
        ),
        "table_head": ParagraphStyle(
            "KTableHead",
            parent=base["BodyText"],
            fontName=f"{FONT}-Bold",
            fontSize=6.8,
            leading=9.5,
            textColor=colors.white,
            alignment=TA_CENTER,
            wordWrap="CJK",
            splitLongWords=True,
        ),
        "table_body": ParagraphStyle(
            "KTableBody",
            parent=base["BodyText"],
            **common,
            fontSize=6.6,
            leading=9.2,
            textColor=colors.HexColor("#111827"),
        ),
        "code": ParagraphStyle(
            "KCode",
            parent=base["Code"],
            fontName=FONT,
            fontSize=6.7,
            leading=9.5,
            textColor=colors.HexColor("#111827"),
            backColor=colors.HexColor("#f3f4f6"),
            borderPadding=4,
            wordWrap="CJK",
            splitLongWords=True,
        ),
    }


STYLES = styles()


def escape(text: str) -> str:
    text = html.escape(text)
    text = text.replace("`", "")
    return text.replace("\n", "<br/>")


def paragraph(text: str, style: str = "body") -> Paragraph:
    return Paragraph(escape(text), STYLES[style])


def inline_text(markdown: str) -> str:
    markdown = markdown.strip()
    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 (\2)", markdown)
    markdown = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", markdown)
    markdown = markdown.replace("<br>", "\n").replace("<br/>", "\n")
    return markdown


def is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    first = lines[index].strip()
    second = lines[index + 1].strip()
    return first.startswith("|") and first.endswith("|") and re.match(r"^\|[\s:\-|\u2014]+\|$", second) is not None


def split_table_row(row: str) -> list[str]:
    row = row.strip().strip("|")
    return [inline_text(cell.strip()) for cell in row.split("|")]


def build_table(rows: list[list[str]]) -> Table:
    if not rows:
        return Table([])
    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    # 첫 행 내용을 기준으로 너무 좁아지지 않도록 폭을 배분한다.
    weights = []
    for col in range(max_cols):
        length = max(6, min(34, max(len(str(row[col])) for row in normalized)))
        weights.append(length)
    total = sum(weights)
    widths = [CONTENT_WIDTH * weight / total for weight in weights]

    converted = []
    for row_index, row in enumerate(normalized):
        style = "table_head" if row_index == 0 else "table_body"
        converted.append([paragraph(cell, style) for cell in row])

    tbl = Table(converted, colWidths=widths, repeatRows=1, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ]
        )
    )
    return tbl


def resolve_image_path(markdown_path: str) -> Path:
    candidate = (SOURCE.parent / markdown_path).resolve()
    if candidate.exists():
        return candidate
    return (ROOT / markdown_path).resolve()


def optimized_image_path(image_path: Path) -> Path:
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    output = IMAGE_CACHE_DIR / f"{image_path.stem}-w{IMAGE_MAX_WIDTH_PX}-q{IMAGE_JPEG_QUALITY}.jpg"
    if output.exists() and output.stat().st_mtime >= image_path.stat().st_mtime:
        return output

    with PILImage.open(image_path) as image:
        if image.mode in ("RGBA", "LA"):
            background = PILImage.new("RGB", image.size, "white")
            alpha = image.getchannel("A") if "A" in image.getbands() else None
            background.paste(image.convert("RGBA"), mask=alpha)
            image = background
        else:
            image = image.convert("RGB")

        if image.width > IMAGE_MAX_WIDTH_PX:
            ratio = IMAGE_MAX_WIDTH_PX / image.width
            image = image.resize((IMAGE_MAX_WIDTH_PX, max(1, int(image.height * ratio))), PILImage.Resampling.LANCZOS)

        image.save(output, "JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True, progressive=True)
    return output


def add_image(
    story: list,
    image_path: Path,
    caption: str,
    max_height: float = 105 * mm,
    add_spacer: bool = True,
) -> None:
    if not image_path.exists():
        story.append(paragraph(f"이미지 파일을 찾을 수 없습니다: {image_path}", "small"))
        return
    pdf_image_path = optimized_image_path(image_path)
    with PILImage.open(pdf_image_path) as img:
        width, height = img.size
    scale = min(CONTENT_WIDTH / width, max_height / height)
    story.append(Image(str(pdf_image_path), width=width * scale, height=height * scale))
    if caption:
        story.append(paragraph(caption, "small"))
    if add_spacer:
        story.append(Spacer(1, 2.5 * mm))


def parse_markdown(markdown: str) -> list:
    lines = markdown.splitlines()
    story: list = []
    index = 0
    in_code = False
    code_lines: list[str] = []

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                story.append(paragraph("\n".join(code_lines), "code"))
                story.append(Spacer(1, 2 * mm))
                code_lines = []
                in_code = False
            else:
                in_code = True
                code_lines = []
            index += 1
            continue

        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            index += 1
            continue

        if stripped == "---":
            story.append(Spacer(1, 2 * mm))
            index += 1
            continue

        if is_table_start(lines, index):
            rows = [split_table_row(lines[index])]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(split_table_row(lines[index]))
                index += 1
            story.append(build_table(rows))
            story.append(Spacer(1, 3 * mm))
            continue

        image_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if image_match:
            alt, path = image_match.groups()
            add_image(story, resolve_image_path(path), alt)
            index += 1
            continue

        if stripped.startswith("# "):
            story.append(paragraph(stripped[2:].strip(), "title"))
            index += 1
            continue
        if stripped.startswith("## "):
            story.append(paragraph(stripped[3:].strip(), "h1"))
            index += 1
            continue
        if stripped.startswith("### "):
            story.append(paragraph(stripped[4:].strip(), "h2"))
            index += 1
            continue
        if stripped.startswith("#### "):
            story.append(paragraph(stripped[5:].strip(), "h3"))
            index += 1
            continue

        if stripped.startswith("- "):
            story.append(paragraph(f"- {inline_text(stripped[2:])}", "body"))
            index += 1
            continue

        # 연속 일반 문단은 하나로 묶는다.
        paragraph_lines = [inline_text(stripped)]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if (
                not candidate
                or candidate.startswith("#")
                or candidate.startswith("|")
                or candidate.startswith("```")
                or candidate == "---"
                or candidate.startswith("![")
            ):
                break
            paragraph_lines.append(inline_text(candidate))
            index += 1
        story.append(paragraph(" ".join(paragraph_lines), "body"))

    return story


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(doc.leftMargin, 8 * mm, "교통분쟁 AI 서비스 화면설계서 v0.5")
    canvas.drawRightString(PAGE_SIZE[0] - doc.rightMargin, 8 * mm, str(doc.page))
    canvas.restoreState()


def build_pdf() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    markdown = SOURCE.read_text(encoding="utf-8")
    story = [
        paragraph("교통분쟁 AI 서비스 화면설계서", "title"),
        paragraph(
            f"원본: {SOURCE}\n생성일: {datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M KST')}\n"
            "한글 폰트는 PDF에 임베딩된다.",
            "subtitle",
        ),
    ]
    story.extend(parse_markdown(markdown))

    # 문서 메타 테이블에서 참조한 통합 화면정의서를 부록으로 포함한다.
    final_screen = ROOT / "docs" / "assets" / "screen-design" / "final-screen-plan-complete-updated.png"
    if final_screen.exists():
        story.append(PageBreak())
        story.append(paragraph("부록. 통합 화면정의서 이미지", "h1"))
        add_image(story, final_screen, str(final_screen), max_height=150 * mm, add_spacer=False)

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=PAGE_SIZE,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=16 * mm,
        title="교통분쟁 AI 서비스 화면설계서 v0.5",
        author="Codex",
        subject="화면설계서 PDF",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
