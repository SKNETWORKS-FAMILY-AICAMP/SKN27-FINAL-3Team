"""Render run_objection_report_generation output into the official
'과태료 처분에 대한 이의신청서' table form (강동구청 양식) as a .docx file.

Resident registration numbers are never auto-filled here (privacy: the cell is
left blank for the applicant to write by hand), matching the masking policy in
app/security/pii_masking.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

_CLOSING_TEXT = (
    "위의 과태료 처분에 대하여 불복하여 이의를 신청하오니 관계 법령에 의하여 "
    "적절한 조치를 하여 주시기 바랍니다."
)


def render_official_objection_docx(agent_output: dict[str, Any], output_path: Path) -> None:
    sr = agent_output["structured_result"]
    applicant = sr["applicant_info"]
    disposition = sr["disposition_details"]

    document = Document()
    _set_default_font(document, "맑은 고딕")

    title_table = document.add_table(rows=1, cols=1)
    title_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(title_table)
    title_cell = title_table.rows[0].cells[0]
    title_paragraph = title_cell.paragraphs[0]
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_paragraph.add_run("과태료 처분에 대한 이의신청서")
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_cell.height = Cm(1.2)

    document.add_paragraph()

    table = document.add_table(rows=6, cols=5)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _set_table_borders(table)
    for column, width in zip(table.columns, (Cm(2.4), Cm(2.6), Cm(4.0), Cm(2.6), Cm(4.0))):
        column.width = width

    # row 0-1: applicant block
    _fill(table, 0, 0, "이 의\n신 청 인", merge_down=1)
    _fill(table, 0, 1, "성명")
    _fill(table, 0, 3, "주민(사업자)\n등 록 번 호")
    _fill(table, 0, 4, "")  # left blank on purpose: never auto-fill a resident ID
    _fill(table, 1, 1, "주소")

    # row 2-4: disposition block
    _fill(table, 2, 0, "과태료 처분내역", merge_down=2)
    _fill(table, 2, 1, "자동차번호")
    _fill(table, 2, 3, "부과기관")
    _fill(table, 3, 1, "고지받은일자")
    _fill(table, 3, 3, "과태료금액")
    _fill(table, 4, 1, "과태료처분사유")
    _fill(table, 4, 3, "납부고지서번호")

    # row 5: free-form content block
    _fill(table, 5, 0, "이의신청내용\n(내용이 많을 때는\n별지로 작성)")
    _fill(table, 5, 1, "", merge_right=3)

    _fill_value(table, 0, 2, applicant["name"])
    _fill_value(table, 1, 2, f"{applicant['address']}   (☎ {applicant['contact']})", merge_right=2)
    _fill_value(table, 2, 2, applicant["vehicle_number"])
    _fill_value(table, 2, 4, sr["recipient_agency"])
    _fill_value(table, 3, 2, disposition.get("violation_datetime") or "확인 필요")
    _fill_value(table, 3, 4, disposition.get("fine_amount") or "확인 필요")
    _fill_value(table, 4, 2, disposition.get("violation_text") or "확인 필요")
    _fill_value(table, 4, 4, disposition.get("case_number") or "확인 필요")

    content_cell = table.cell(5, 1)
    content_cell.text = ""
    content_paragraph = content_cell.paragraphs[0]
    content_paragraph.add_run(f"{sr['petition_purpose']}\n\n{sr['petition_reasons']}")
    content_cell.height = Cm(6)

    document.add_paragraph()
    closing = document.add_paragraph()
    closing.alignment = WD_ALIGN_PARAGRAPH.CENTER
    closing.add_run(_CLOSING_TEXT)

    document.add_paragraph()
    date_line = document.add_paragraph()
    date_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_line.add_run("년        월        일")

    signature_line = document.add_paragraph()
    signature_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    signature_line.add_run(f"신청인:  {applicant['name']}    (서명 또는 인)")

    document.add_paragraph()
    recipient_line = document.add_paragraph()
    recipient_line.add_run(f"{sr['recipient_agency']}  귀하")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))


def _fill(table, row: int, col: int, text: str, *, merge_down: int = 0, merge_right: int = 0) -> None:
    cell = table.cell(row, col)
    cell.text = text
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in paragraph.runs:
            run.font.bold = True
            run.font.size = Pt(10)
    if merge_down:
        cell.merge(table.cell(row + merge_down, col))
    if merge_right:
        cell.merge(table.cell(row, col + merge_right))


def _fill_value(table, row: int, col: int, text: str, *, merge_right: int = 0) -> None:
    cell = table.cell(row, col)
    cell.text = str(text)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.size = Pt(10)
    if merge_right:
        cell.merge(table.cell(row, col + merge_right))


def _set_default_font(document: Document, font_name: str) -> None:
    style = document.styles["Normal"]
    style.font.name = font_name
    style.font.size = Pt(10)
    rpr = style.element.get_or_add_rPr()
    east_asian_font = rpr.find(qn("w:rFonts"))
    if east_asian_font is None:
        east_asian_font = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(east_asian_font)
    east_asian_font.set(qn("w:eastAsia"), font_name)


def _set_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.makeelement(qn("w:tblBorders"), {})
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.makeelement(qn(f"w:{edge}"), {})
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "6")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "000000")
        borders.append(element)
    tbl_pr.append(borders)
