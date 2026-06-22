from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
TMP_DIR = ROOT / "tmp" / "pdfs"
OUTPUT_DIR = ROOT / "output" / "pdf"
REPORT_BODY = TMP_DIR / "mentor-status-report-body-2026-06-18.pdf"
SCREEN_DESIGN_APPENDIX = OUTPUT_DIR / "screen-design-specification-v0.2-compressed.pdf"
FINAL_OUTPUT = OUTPUT_DIR / "mentor-status-report-2026-06-18.pdf"

FONT_REGULAR_CANDIDATES = [
    Path("C:/Windows/Fonts/NotoSansKR-Regular.ttf"),
    Path("C:/Windows/Fonts/NanumGothic.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
]
FONT_BOLD_CANDIDATES = [
    Path("C:/Windows/Fonts/NotoSansKR-Bold.ttf"),
    Path("C:/Windows/Fonts/NanumGothicBold.ttf"),
    Path("C:/Windows/Fonts/malgunbd.ttf"),
]


def first_existing(paths: list[Path]) -> Path:
    for path in paths:
        if path.exists():
            return path
    raise FileNotFoundError("Korean font file was not found.")


pdfmetrics.registerFont(TTFont("Korean", str(first_existing(FONT_REGULAR_CANDIDATES))))
pdfmetrics.registerFont(TTFont("Korean-Bold", str(first_existing(FONT_BOLD_CANDIDATES))))

styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "TitleKo",
    parent=styles["Title"],
    fontName="Korean-Bold",
    fontSize=21,
    leading=27,
    textColor=colors.HexColor("#111827"),
    alignment=TA_CENTER,
    spaceAfter=8,
)
SUBTITLE = ParagraphStyle(
    "SubtitleKo",
    parent=styles["Normal"],
    fontName="Korean",
    fontSize=9,
    leading=13,
    textColor=colors.HexColor("#4B5563"),
    alignment=TA_CENTER,
    spaceAfter=14,
)
H1 = ParagraphStyle(
    "H1Ko",
    parent=styles["Heading1"],
    fontName="Korean-Bold",
    fontSize=14,
    leading=18,
    textColor=colors.HexColor("#111827"),
    spaceBefore=10,
    spaceAfter=6,
)
H2 = ParagraphStyle(
    "H2Ko",
    parent=styles["Heading2"],
    fontName="Korean-Bold",
    fontSize=11,
    leading=15,
    textColor=colors.HexColor("#1F2937"),
    spaceBefore=8,
    spaceAfter=5,
)
BODY = ParagraphStyle(
    "BodyKo",
    parent=styles["Normal"],
    fontName="Korean",
    fontSize=8.4,
    leading=12.3,
    textColor=colors.HexColor("#111827"),
)
SMALL = ParagraphStyle(
    "SmallKo",
    parent=BODY,
    fontSize=7.4,
    leading=10.2,
)
NOTE = ParagraphStyle(
    "NoteKo",
    parent=SMALL,
    textColor=colors.HexColor("#475569"),
)
CELL = ParagraphStyle(
    "CellKo",
    parent=SMALL,
    alignment=TA_LEFT,
)
HEADER = ParagraphStyle(
    "HeaderKo",
    parent=CELL,
    fontName="Korean-Bold",
    textColor=colors.white,
    alignment=TA_CENTER,
)


def p(text: object, style: ParagraphStyle = CELL) -> Paragraph:
    value = "" if text is None else str(text)
    value = (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(value, style)


def bullet(text: str) -> Paragraph:
    return Paragraph("- " + text, BODY)


def table(data, col_widths, repeat_rows=1, font_size=7.4):
    rows = []
    for idx, row in enumerate(data):
        rows.append([p(cell, HEADER if idx < repeat_rows else CELL) for cell in row])
    t = Table(rows, colWidths=col_widths, repeatRows=repeat_rows, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, repeat_rows - 1), colors.HexColor("#334155")),
                ("TEXTCOLOR", (0, 0), (-1, repeat_rows - 1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Korean"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size + 3),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, repeat_rows), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def doc_template(path: Path) -> BaseDocTemplate:
    page_width, page_height = landscape(A4)
    margin_x = 11 * mm
    margin_y = 10 * mm
    frame = Frame(
        margin_x,
        margin_y + 8 * mm,
        page_width - margin_x * 2,
        page_height - margin_y * 2 - 8 * mm,
        id="main",
    )
    doc = BaseDocTemplate(
        str(path),
        pagesize=landscape(A4),
        leftMargin=margin_x,
        rightMargin=margin_x,
        topMargin=margin_y,
        bottomMargin=margin_y,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=draw_footer)])
    return doc


def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Korean", 7)
    canvas.setFillColor(colors.HexColor("#64748B"))
    footer = "SKN27-FINAL-3Team 멘토 공유용 현황 보고서 | 기준일 2026-06-18 | page %d" % doc.page
    canvas.drawRightString(286 * mm, 8 * mm, footer)
    canvas.restoreState()


def add_image(story, path: Path, max_width_mm: float, max_height_mm: float):
    if not path.exists():
        story.append(Paragraph(f"이미지 없음: {path}", NOTE))
        return
    img = Image(str(path))
    max_w = max_width_mm * mm
    max_h = max_height_mm * mm
    ratio = min(max_w / img.imageWidth, max_h / img.imageHeight)
    img.drawWidth = img.imageWidth * ratio
    img.drawHeight = img.imageHeight * ratio
    story.append(img)


def build_story():
    story = []
    story.append(Paragraph("SKN27-FINAL-3Team 현황 및 WBS 변경 보고", TITLE))
    story.append(
        Paragraph(
            "멘토 공유용 | 기준일 2026-06-18 | 중간 발표 2026-07-14 | 최종 마무리 2026-08-04",
            SUBTITLE,
        )
    )
    story.append(Paragraph("1. 요약", H1))
    for item in [
        "2026-06-18 회의 기준으로 역할, WBS, GitHub Issue, parent/child 구조를 재정렬했다.",
        "최종 답변은 개별 Agent가 아니라 Supervisor가 각 Agent 결과 스키마를 통합해 생성하는 구조로 정리했다.",
        "합의금과 보험 약관은 후순위로 분리했고, 중간 발표 핵심 경로는 과태료/범칙금, 법률 데이터, 과실비율 텍스트/판례, Vision/DL, Supervisor 통합이다.",
        "GitHub Issues #1~#43은 최신 기준으로 제목, 본문, 담당자, 라벨, milestone, 상세 코멘트가 반영되었다.",
    ]:
        story.append(bullet(item))

    story.append(Spacer(1, 6))
    story.append(Paragraph("2. 담당자별 최신 역할", H1))
    story.append(
        table(
            [
                ["담당", "GitHub", "핵심 역할", "중간 발표 산출물"],
                ["요청자/문서·QA", "hi20260204-maker", "WBS/문서, Supervisor, 홈·로그인·챗봇 진입, 이의신청서 생성, 통합 QA", "WBS, 회의록, Supervisor 결과 스키마, 이의신청서 생성 노드"],
                ["재강", "leejaegang27", "경위서/OCR 결과, 텍스트 ML, 과실비율 판례, 유튜브 자막 사례, 과실비율심의사례, 판례 Agent", "텍스트 ML/RAG 입력 데이터, 판례/사례 검색 결과 스키마"],
                ["주희", "ohjuheecode", "차량 사고 이미지·영상, Vision/DL 분석, 영상·이미지 Agent", "비전 데이터셋, key frame, 장면 요약, confidence metadata"],
                ["동혁", "techshin31", "법률 데이터 수집, 전처리, DB 적재, 법률 원문/조문/근거 metadata", "법률 원천 데이터, 전처리 결과, DB 적재 로그"],
                ["필주", "workzion2", "고지서 OCR, 과태료·범칙금·벌칙 분석용 룰/매핑, 과태료·범칙금 분석 흐름", "고지서 OCR 구조화, 처분 단계, 이의제기 가능성, 필요 증거"],
            ],
            [31 * mm, 33 * mm, 120 * mm, 82 * mm],
        )
    )

    story.append(Paragraph("3. 일정과 마일스톤", H1))
    story.append(
        table(
            [
                ["기간", "목표", "주요 산출물"],
                ["2026-06-18 ~ 2026-06-21", "역할/WBS/Issue 재정렬", "WBS 문서, GitHub Issue 재배정, 중간/최종 milestone"],
                ["2026-06-22 ~ 2026-06-28", "데이터·DB·RAG 계약 고정", "법률/과태료/과실비율/영상 데이터 schema, RAG metadata 계약"],
                ["2026-06-29 ~ 2026-07-05", "파이프라인·Agent 골격 연결", "데이터 수집·전처리·적재 MVP, Agent 결과 스키마, Supervisor 분기"],
                ["2026-07-06 ~ 2026-07-13", "중간 발표 MVP 동결", "로그인→챗봇 진입, 과태료·범칙금 흐름, 과실비율 흐름, AWS staging"],
                ["2026-07-14", "중간 발표", "연결된 MVP 시연"],
                ["2026-07-15 ~ 2026-08-03", "피드백 반영, 최종 QA, 배포, 문서화", "RAG/ML/DL 품질 개선, production 배포, 최종 발표자료"],
                ["2026-08-04", "최종 마무리", "최종 제출 상태"],
            ],
            [52 * mm, 78 * mm, 136 * mm],
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("4. GitHub Issue 정리 결과", H1))
    story.append(
        table(
            [
                ["구분", "처리 결과"],
                ["Issue 업데이트", "#1~#43 제목, 본문, 담당자, label, milestone 동기화"],
                ["상세 코멘트", "#1~#43에 회의 반영 상세 코멘트 생성. 마커: wbs-meeting-update-2026-06-18"],
                ["Parent/Child 구조", "#2~#9 epic 아래 child issue 재배치"],
                ["Scope out", "#6, #34, #35 합의금 관련 이슈는 삭제하지 않고 닫힘 처리"],
                ["Project 보드", "현재 토큰 scope가 gist, repo, workflow라 Project 연결 권한 없음"],
                ["Issue Template", ".github/ISSUE_TEMPLATE/wbs-task.md 추가"],
            ],
            [50 * mm, 216 * mm],
        )
    )

    story.append(Paragraph("5. Parent/Child Issue 구조", H1))
    story.append(
        table(
            [
                ["Parent issue", "Child issue"],
                ["#2 epic-planning-wbs-scope", "#10, #11, #12, #13"],
                ["#3 epic-common-architecture-data-pipeline", "#14, #15, #16, #17, #18, #19, #22, #29"],
                ["#4 epic-fine-ocr-penalty-analysis", "#23, #24, #25, #26, #27, #28"],
                ["#5 epic-fault-ratio-precedent-vision-flow", "#30, #31, #32, #33"],
                ["#6 epic-settlement-helper-mvp", "#34, #35 (scope-out)"],
                ["#7 epic-vision-accident-image-video-agent", "#36, #37, #38, #39"],
                ["#8 epic-integration-qa-final-demo", "#40, #41, #42, #43"],
                ["#9 epic-legal-precedent-data-ingestion-and-rag", "#1, #20, #21"],
            ],
            [95 * mm, 171 * mm],
        )
    )

    story.append(Paragraph("6. Supervisor/Agent 구조", H1))
    for item in [
        "Supervisor는 입력 유형과 질문 의도를 분류하고 과태료·범칙금, 과실비율, 법률 근거, 영상/이미지, 이의신청서 생성 흐름으로 분기한다.",
        "개별 Agent는 최종 답변을 확정하지 않고 summary, structured_result, evidence, next_actions, limitations를 반환한다.",
        "필주의 과태료·범칙금 분석과 동혁의 법률 근거는 이의신청서 생성 노드로 연결된다.",
        "재강 텍스트 ML/판례 결과와 주희 Vision/DL 결과는 과실비율 흐름에서 병합된다.",
    ]:
        story.append(bullet(item))

    story.append(Spacer(1, 6))
    story.append(Paragraph("7. 남은 리스크", H1))
    story.append(
        table(
            [
                ["리스크", "상태", "대응"],
                ["GitHub Project 보드", "토큰 scope 부족", "classic token은 project scope, fine-grained token은 Projects Read and write 필요"],
                ["#44 test 업무", "닫힌 테스트 이슈", "영구 삭제는 별도 확인 후 진행"],
                ["보험 약관", "후순위", "중간 발표 핵심 경로에서 제외"],
                ["합의금 기능", "scope-out", "최종 이후 별도 스프린트 후보"],
                ["법률/판례/영상 결과 혼합", "책임 경계 필요", "Supervisor 결과 스키마 기준으로 병합"],
            ],
            [62 * mm, 58 * mm, 146 * mm],
        )
    )

    story.append(PageBreak())
    story.append(Paragraph("8. 화면설계서 포함 요약", H1))
    story.append(Paragraph("아래 요약 뒤에는 화면설계서 PDF 전체를 부록으로 첨부했다.", NOTE))
    story.append(
        table(
            [
                ["화면", "상태 및 주요 내용"],
                ["마이페이지", "등록 사건, 기한 임박, 생성 문서, 최근 분석 이력"],
                ["AI 교통 상담 챗봇", "대화 목록, 챗봇 대화창, 분석 결과 카드, 추천 키워드, 입력창"],
                ["과거 이력", "유형/기간/검색 필터와 분석 이력 상세 진입"],
                ["과실비율 상세/리포트", "사고 개요, 제출 자료, AI 분석 결과, 판단 근거, 유사 판례, 후속 조치"],
                ["과태료·범칙금 리포트", "OCR 문서 분석, 처분 결과, 이의제기 가능성, 필요 증거, 법령/판례, 이의신청서 초안"],
                ["판례/보험사 사례 목록", "사례 목록, 선택 상세, PDF 다운로드, 원문 보기"],
            ],
            [68 * mm, 198 * mm],
        )
    )
    story.append(Spacer(1, 7))
    story.append(Paragraph("주요 화면 이미지", H2))
    image_row = [
        [
            [
                Paragraph("마이페이지", H2),
                Image(str(ROOT / "docs" / "assets" / "screen-design" / "mypage-updated.png"), width=82 * mm, height=46 * mm),
            ],
            [
                Paragraph("리포트 화면", H2),
                Image(str(ROOT / "docs" / "assets" / "screen-design" / "report-pages-updated.png"), width=82 * mm, height=46 * mm),
            ],
            [
                Paragraph("전체 화면 계획", H2),
                Image(str(ROOT / "docs" / "assets" / "screen-design" / "final-screen-plan-complete-updated.png"), width=82 * mm, height=46 * mm),
            ],
        ]
    ]
    story.append(Table(image_row, colWidths=[88 * mm, 88 * mm, 88 * mm]))
    story.append(PageBreak())
    story.append(Paragraph("부록: 화면설계서 v0.2", TITLE))
    story.append(
        Paragraph(
            "다음 페이지부터는 output/pdf/screen-design-specification-v0.2-compressed.pdf 전체를 첨부했다.",
            SUBTITLE,
        )
    )
    return story


def merge_with_appendix():
    writer = PdfWriter()
    for path in [REPORT_BODY, SCREEN_DESIGN_APPENDIX]:
        if not path.exists():
            raise FileNotFoundError(path)
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    with FINAL_OUTPUT.open("wb") as f:
        writer.write(f)


def main():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = doc_template(REPORT_BODY)
    doc.build(build_story())
    merge_with_appendix()
    print(FINAL_OUTPUT)


if __name__ == "__main__":
    main()
