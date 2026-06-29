from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]

CHECKS = [
    (
        ROOT / "output" / "pdf" / "프로젝트_기획서_27기_3팀_2026-06-22.pdf",
        2,
        ["프로젝트 기획서", "교통분쟁 AI", "역할분담"],
    ),
    (
        ROOT / "output" / "pdf" / "수집_데이터_보고서_27기_3팀_2026-06-22.pdf",
        3,
        ["수집 데이터 보고서", "법률 원문 데이터", "데이터 품질"],
    ),
    (
        ROOT / "output" / "pdf" / "화면설계서_27기_3팀_2026-06-22.pdf",
        5,
        ["화면설계서", "UI-Ai-01", "화면 자산"],
    ),
]


def verify(path: Path, expected_pages: int, keywords: list[str]) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size < 10_000:
        raise AssertionError(f"PDF size too small: {path} ({size})")

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    if page_count != expected_pages:
        raise AssertionError(f"{path.name}: expected {expected_pages} pages, got {page_count}")

    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    missing = [keyword for keyword in keywords if keyword not in text]
    if missing:
        raise AssertionError(f"{path.name}: missing extracted keywords {missing}")

    print(f"PASS\t{path.name}\tpages={page_count}\tsize={size}")


def main() -> int:
    for path, expected_pages, keywords in CHECKS:
        verify(path, expected_pages, keywords)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
