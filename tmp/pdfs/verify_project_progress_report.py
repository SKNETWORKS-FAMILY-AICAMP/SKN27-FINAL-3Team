from __future__ import annotations

from pathlib import Path
import re

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "output" / "pdf" / "SKN27-FINAL-3Team_project_progress_report.pdf"
REQUIRED_PHRASES = [
    "프로젝트 대화 및 진행상황 보고서",
    "교통분쟁 AI",
    "마이페이지",
    "과태료",
    "사고 과실비율 분석 리포트",
    "한글 깨짐",
]


def font_descriptor(font_obj):
    descriptor = font_obj.get("/FontDescriptor")
    if descriptor is not None:
        return descriptor.get_object()
    descendants = font_obj.get("/DescendantFonts")
    if descendants:
        descendant = descendants[0].get_object()
        descriptor = descendant.get("/FontDescriptor")
        if descriptor is not None:
            return descriptor.get_object()
    return None


def main() -> None:
    if not PDF.exists():
        raise SystemExit(f"PDF not found: {PDF}")

    reader = PdfReader(str(PDF))
    text_parts: list[str] = []
    with pdfplumber.open(str(PDF)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    extracted = "\n".join(text_parts)

    missing = [phrase for phrase in REQUIRED_PHRASES if phrase not in extracted]
    replacement_count = extracted.count("\ufffd")

    fonts: dict[str, bool] = {}
    used_fonts: dict[str, bool] = {}
    for page in reader.pages:
        resources = page.get("/Resources", {})
        font_refs = resources.get("/Font", {})
        content = ""
        if page.get_contents() is not None:
            content = page.get_contents().get_data().decode("latin1", errors="ignore")
        for resource_name, font_ref in font_refs.items():
            font_obj = font_ref.get_object()
            base_font = str(font_obj.get("/BaseFont", "unknown"))
            descriptor = font_descriptor(font_obj)
            embedded = False
            if descriptor is not None:
                embedded = any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))
            fonts[base_font] = fonts.get(base_font, False) or embedded
            escaped_name = re.escape(str(resource_name))
            text_objects = re.findall(r"BT(.*?)ET", content, flags=re.DOTALL)
            is_used = any(
                re.search(rf"{escaped_name}\s+[-+]?\d+(?:\.\d+)?\s+Tf", block) is not None
                and (" Tj" in block or " TJ" in block)
                for block in text_objects
            )
            used_fonts[base_font] = used_fonts.get(base_font, False) or is_used

    print(f"file={PDF}")
    print(f"size_bytes={PDF.stat().st_size}")
    print(f"pages={len(reader.pages)}")
    print(f"extracted_chars={len(extracted)}")
    print(f"replacement_char_count={replacement_count}")
    print(f"missing_required_phrases={missing}")
    print("fonts=")
    for name, embedded in sorted(fonts.items()):
        print(f"  {name}: embedded={embedded}, used={used_fonts.get(name, False)}")

    if missing:
        raise SystemExit("required Korean phrases were not extracted")
    if replacement_count:
        raise SystemExit("replacement characters found in extracted text")
    used_unembedded = [name for name, embedded in fonts.items() if used_fonts.get(name, False) and not embedded]
    if used_unembedded:
        raise SystemExit(f"one or more used fonts are not embedded: {used_unembedded}")


if __name__ == "__main__":
    main()
