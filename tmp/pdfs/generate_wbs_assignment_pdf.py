from __future__ import annotations

from pathlib import Path

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
    FrameBreak,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "pdf" / "wbs-issue-assignment-2026-06-18.pdf"

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


FONT_REGULAR_PATH = first_existing(FONT_REGULAR_CANDIDATES)
FONT_BOLD_PATH = first_existing(FONT_BOLD_CANDIDATES)
pdfmetrics.registerFont(TTFont("Korean", str(FONT_REGULAR_PATH)))
pdfmetrics.registerFont(TTFont("Korean-Bold", str(FONT_BOLD_PATH)))


styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "TitleKo",
    parent=styles["Title"],
    fontName="Korean-Bold",
    fontSize=20,
    leading=26,
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
    fontSize=8.2,
    leading=12,
    textColor=colors.HexColor("#111827"),
)
BODY_SMALL = ParagraphStyle(
    "BodySmallKo",
    parent=BODY,
    fontSize=7.5,
    leading=10.5,
)
CELL = ParagraphStyle(
    "CellKo",
    parent=BODY_SMALL,
    alignment=TA_LEFT,
)
CELL_CENTER = ParagraphStyle(
    "CellCenterKo",
    parent=CELL,
    alignment=TA_CENTER,
)
HEADER = ParagraphStyle(
    "HeaderKo",
    parent=CELL_CENTER,
    fontName="Korean-Bold",
    textColor=colors.white,
)
NOTE = ParagraphStyle(
    "NoteKo",
    parent=BODY_SMALL,
    textColor=colors.HexColor("#374151"),
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


def table(data, col_widths, repeat_rows=1, font_size=7.5):
    prepared = []
    for row_index, row in enumerate(data):
        prepared.append(
            [
                p(cell, HEADER if row_index < repeat_rows else CELL)
                for cell in row
            ]
        )
    t = Table(prepared, colWidths=col_widths, repeatRows=repeat_rows, hAlign="LEFT")
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
    footer = "SKN27-FINAL-3Team WBS 이슈 담당자 정리 | 기준일 2026-06-18 | page %d" % doc.page
    canvas.drawRightString(286 * mm, 8 * mm, footer)
    canvas.restoreState()


summary_rows = [
    ["담당자", "현재 GitHub assignee", "확정 담당 영역", "관련 이슈"],
    ["hi20260204-maker", "hi20260204-maker", "보험 영상 수집/전처리, DB/Django/AWS 배포, 인증인가, 문서/QA 총괄", "#1, #2, #10-#13, #16-#19, #37, #40-#43"],
    ["LeeJaekang", "leejaegang27", "보험 텍스트 ML/RAG, 과실비율 지식베이스/응답 정책", "#5, #9, #22, #30, #31, #33, #40, #41"],
    ["ohjuheecode", "ohjuheecode", "보험 영상 DL/RAG, Vision/DL POC, 작업 상태 모델", "#7, #15, #22, #36-#39, #40, #41"],
    ["techshin31", "techshin31", "보험 RAG Agent/Front, 홈/챗봇/리포트 화면, DL 결과 검토 연결", "#3, #5, #7, #8, #13, #14, #29, #31-#33, #38, #40, #41"],
    ["kama42kanne", "workzion2", "범칙금 RAG Agent/Front, 보험 텍스트 수집/전처리 파이프라인", "#3, #4, #8, #9, #13, #16-#18, #20-#28, #40, #41"],
]


wbs_rows = [
    ["WBS", "Issue", "이슈명", "담당자", "요구사항/화면", "산출물/메모"],
    ["1. 기획/WBS/범위", "#2", "epic-planning-wbs-scope", "hi20260204-maker", "전체 WBS, 범위, 담당자", "WBS, 범위, 담당자, 화면/프로세스 확정"],
    ["1. 기획/WBS/범위", "#10", "docs-project-scope-and-role-matrix", "hi20260204-maker", "MVP 범위/역할 매트릭스", "전체 역할, MVP 범위, 홈 담당자, 도메인 담당 구분"],
    ["1. 기획/WBS/범위", "#11", "docs-wbs-owner-deliverable-plan", "hi20260204-maker", "화면/API/DB/ETL/AI WBS", "담당자와 산출물 계획 정리"],
    ["1. 기획/WBS/범위", "#12", "docs-mvp-screen-and-process-flows", "hi20260204-maker", "과실비율/합의금/범칙금 플로우", "사용자 플로우 정의"],
    ["1. 기획/WBS/범위", "#13", "docs-requirement-gap-and-risk-log", "전체 담당자", "요구사항-화면설계 충돌", "회의 내용, 요구사항, 화면설계 충돌 정리"],
    ["2. 공통 아키텍처/데이터", "#3", "epic-common-architecture-data-pipeline", "hi20260204-maker, techshin31, ohjuheecode, workzion2", "공통 DB/수집/Job", "공통 DB, 수집 자동화, 증분 수집, Job 구조"],
    ["2. 공통 아키텍처/데이터", "#14", "feat-common-home-entrypoints", "techshin31", "홈 진입점", "범칙금, 과실비율, 합의금, 블랙박스 진입점 구성"],
    ["2. 공통 아키텍처/데이터", "#15", "feat-common-analysis-job-model", "ohjuheecode", "공통 작업 상태 모델", "RAG/DL/문서 생성 공통 작업 상태 모델"],
    ["2. 공통 아키텍처/데이터", "#16", "feat-data-source-registry-schema", "hi20260204-maker, workzion2", "출처/수집일/원문 위치", "데이터 출처 registry schema"],
    ["2. 공통 아키텍처/데이터", "#17", "feat-incremental-ingestion-run-tracking", "hi20260204-maker, workzion2", "증분 수집 실행 이력", "신규 데이터만 수집하는 증분 로직"],
    ["2. 공통 아키텍처/데이터", "#18", "feat-separate-domain-case-schemas", "hi20260204-maker, workzion2", "과실비율/범칙금 도메인 schema", "판례 테이블 및 자동화 프로세스 분리"],
    ["2. 공통 아키텍처/데이터", "#19", "docs-data-governance-retention-policy", "hi20260204-maker", "개인정보/영상/고지서 정책", "보관, 삭제, 마스킹 정책"],
    ["3. 보험 영상 수집/전처리", "#1", "feature-youtube-longforn", "hi20260204-maker", "보험 영상 자막 raw ETL", "한문철TV 공개 자막 수집 가능성 검증"],
    ["3. 보험 영상 수집/전처리", "#37", "feat-dashcam-data-manifest-pipeline", "hi20260204-maker, ohjuheecode", "블랙박스/DL 입력 manifest", "DL 입력 manifest 정리"],
    ["4. 법령/판례 데이터 수집/RAG", "#9", "epic-legal-data-ingestion-and-rag", "leejaegang27, workzion2", "법령/판례/과실비율 RAG", "데이터 수집 및 RAG 색인"],
    ["4. 법령/판례 데이터 수집/RAG", "#20", "feat-law-openapi-collector-poc", "workzion2", "법령/판례 수집", "국가법령정보 API 기반 POC"],
    ["4. 법령/판례 데이터 수집/RAG", "#21", "feat-fault-ratio-source-collector-poc", "workzion2", "과실비율 기준/분심위/상담 사례", "보험 텍스트 수집/전처리 파이프라인"],
    ["4. 법령/판례 데이터 수집/RAG", "#22", "feat-rag-chunk-index-contract", "leejaegang27, workzion2, ohjuheecode", "RAG chunk/metadata/근거 반환", "원문 chunk와 근거 출처 반환 계약"],
    ["5. 범칙금 RAG Agent/Front", "#4", "epic-fine-objection-mvp", "workzion2", "REQ-FINE-001-013, UI-CHAT-001, UI-REPORT-FINE-001", "과태료/범칙금 이의신청 MVP"],
    ["5. 범칙금 RAG Agent/Front", "#23", "feat-fine-case-intake-flow", "workzion2", "REQ-FINE-001-004", "통지일, 납부 여부, 위반 유형, 감경 대상 입력"],
    ["5. 범칙금 RAG Agent/Front", "#24", "feat-fine-rule-engine", "workzion2", "REQ-FINE-005-007", "기한, 납부, 감경 가능성 룰 엔진"],
    ["5. 범칙금 RAG Agent/Front", "#25", "feat-fine-detail-view", "workzion2", "UI-REPORT-FINE-001", "범칙금/과태료 상세 내역 조회 화면"],
    ["5. 범칙금 RAG Agent/Front", "#26", "feat-fine-rag-search-poc", "workzion2", "REQ-FINE-010", "이의신청 근거 RAG 검색 POC"],
    ["5. 범칙금 RAG Agent/Front", "#27", "feat-fine-objection-draft-report", "workzion2", "REQ-FINE-011-013, REQ-REPORT-005-006", "이의신청 가능성 리포트와 신청서 초안"],
    ["5. 범칙금 RAG Agent/Front", "#28", "test-fine-mvp-sample-case-validation", "workzion2", "범칙금 MVP 검증", "샘플 케이스 20개 이상 검증"],
    ["6. 보험 과실비율 RAG/Front", "#5", "epic-fault-ratio-helper-mvp", "leejaegang27, techshin31", "REQ-FAULT-003-008, UI-CHAT-002, UI-REPORT-FAULT-001", "과실비율 RAG/화면 MVP"],
    ["6. 보험 과실비율 RAG/Front", "#29", "feat-fault-ratio-rag-chat-interface", "techshin31", "UI-CHAT-002", "사고경위 입력형 ChatBot RAG 화면"],
    ["6. 보험 과실비율 RAG/Front", "#30", "feat-fault-ratio-knowledge-base", "leejaegang27", "REQ-REPORT-002-004/007", "과실비율 기준/사례 지식베이스"],
    ["6. 보험 과실비율 RAG/Front", "#31", "feat-fault-ratio-structured-question-flow", "leejaegang27, techshin31", "REQ-FAULT-003, UI-CHAT-002", "사고유형 분류 추가 질문 흐름"],
    ["6. 보험 과실비율 RAG/Front", "#32", "feat-fault-ratio-result-range-view", "techshin31", "UI-REPORT-FAULT-001", "과실비율 범위 결과 화면"],
    ["6. 보험 과실비율 RAG/Front", "#33", "feat-fault-response-script-generator", "leejaegang27, techshin31", "REQ-FAULT-008", "보험사 항의/분심위 대응 스크립트"],
    ["7. 합의금 확장", "#6", "epic-settlement-helper-mvp", "기존 광범위 배정 유지", "합의금 항목 체크 확장", "세부 하위 이슈 담당 미확정"],
    ["7. 합의금 확장", "#34", "feat-settlement-checklist-flow", "미배정", "합의금 체크리스트", "치료비, 휴업손해, 위자료 등 누락 체크 - 추후 결정 필요"],
    ["7. 합의금 확장", "#35", "feat-settlement-document-draft", "미배정", "합의금/보험 문서 초안", "생성 방식, 저장/API, 법률 리스크 정책 확정 필요"],
    ["8. 보험 영상 DL/RAG", "#7", "epic-vision-dashcam-poc", "hi20260204-maker, ohjuheecode, techshin31", "Vision/DL/블랙박스 POC", "블랙박스 분석 POC"],
    ["8. 보험 영상 DL/RAG", "#36", "spike-vision-model-use-case-decision", "ohjuheecode", "Vision 적용 범위", "고지서/사고사진/블랙박스 중 범위 결정"],
    ["8. 보험 영상 DL/RAG", "#38", "feat-dashcam-analysis-review-flow", "ohjuheecode, techshin31", "DL 결과 -> RAG 입력", "사용자 검토 후 RAG 연결"],
    ["8. 보험 영상 DL/RAG", "#39", "test-vision-dashcam-poc-validation", "ohjuheecode", "Vision/DL 검증", "POC 결과와 한계 검증"],
    ["9. 통합 QA/최종 데모", "#8", "epic-integration-qa-final-demo", "전체 담당자", "통합 QA/리스크/데모", "통합 QA, 리스크 검증, 최종 데모"],
    ["9. 통합 QA/최종 데모", "#40", "test-cross-mvp-integration-scenarios", "전체 담당자", "MVP 간 통합 시나리오", "통합 시나리오 검증"],
    ["9. 통합 QA/최종 데모", "#41", "test-legal-ai-guardrail-validation", "전체 담당자", "법률 AI guardrail", "법률 판단 금지, 성공 보장 금지, 면책 문구 검증"],
    ["9. 통합 QA/최종 데모", "#42", "docs-final-demo-scenario-and-risk-checklist", "hi20260204-maker", "최종 발표/리스크", "데모 시나리오와 리스크 체크리스트"],
    ["9. 통합 QA/최종 데모", "#43", "chore-final-stabilization-and-release-readiness", "hi20260204-maker", "최종 안정화", "데모 준비, 잔여 이슈 정리"],
]


unassigned_rows = [
    ["Issue", "미배정 사유", "추후 결정사항", "권장 배정안"],
    [
        "#34 feat-settlement-checklist-flow",
        "합의금 항목 체크 기능은 초기 담당 분장의 보험 텍스트 ML/RAG, 보험 RAG Agent/Front, 영상 DL/RAG, 범칙금 RAG Agent/Front, DB/배포/인증 중 하나로 명확히 귀속되지 않는다.",
        "MVP 포함 여부, 체크 방식(정적 체크리스트/RAG/룰 엔진), 입력 항목, 결과 화면 범위, 저장/API 필요 여부 결정",
        "leejaegang27, techshin31 / 저장/API 포함 시 hi20260204-maker 추가",
    ],
    [
        "#35 feat-settlement-document-draft",
        "합의금/보험 문서 초안 생성은 단순 화면인지, RAG 기반 생성인지, PDF/DOCX 저장까지 포함하는지 범위가 미확정이다.",
        "문서 종류, 생성 방식(템플릿/LLM/RAG), 다운로드/저장 범위, 법률 리스크 정책, 면책 문구 결정",
        "leejaegang27, techshin31 / 문서 저장과 다운로드 포함 시 hi20260204-maker 추가",
    ],
]


screen_rows = [
    ["화면/요구사항", "담당 영역", "관련 이슈", "담당자"],
    ["UI-MY-001 / REQ-MY-001-007", "마이페이지, 이력, 생성 문서 수", "#10-#12, #14, #16-#19", "hi20260204-maker, techshin31"],
    ["UI-CHAT-001", "범칙금 RAG 챗봇", "#23-#28", "workzion2"],
    ["UI-CHAT-002", "보험 과실비율 RAG 챗봇", "#29, #31", "techshin31, leejaegang27"],
    ["UI-REPORT-FAULT-001 / REQ-FAULT-003-008", "사고 과실비율 분석 리포트", "#29-#33", "leejaegang27, techshin31"],
    ["UI-REPORT-FINE-001 / REQ-FINE-001-013", "과태료/범칙금 대응 리포트", "#23-#28", "workzion2"],
    ["REQ-REPORT-002-004/007", "과실비율 근거, 핵심 쟁점, 유사 판례", "#22, #30-#33", "leejaegang27, techshin31"],
    ["REQ-REPORT-005-006", "과태료 예상 결과, 문서 액션", "#27", "workzion2"],
]


def build_story():
    story = []
    story.append(Paragraph("SKN27-FINAL-3Team WBS 이슈 담당자 정리", TITLE))
    story.append(
        Paragraph(
            "기준일: 2026-06-18 | 출처: GitHub Issues 43건, 화면설계서 v0.1, 요구사항 정의서 v0.4 매핑 | 상태: 전체 open",
            SUBTITLE,
        )
    )
    story.append(Paragraph("1. 담당자 역할 요약", H1))
    story.append(
        Paragraph(
            "GitHub assignee 기준으로는 kama42kanne 담당자를 assignable 계정인 workzion2로 표기한다.",
            NOTE,
        )
    )
    story.append(Spacer(1, 4))
    story.append(table(summary_rows, [32 * mm, 34 * mm, 98 * mm, 102 * mm]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("2. WBS별 이슈 및 담당자", H1))
    story.append(
        Paragraph(
            "아래 표는 현재 GitHub 이슈 assignee를 기준으로 정리했으며, 각 행은 덮어쓰기 반영 후 상태다.",
            NOTE,
        )
    )
    story.append(Spacer(1, 4))
    story.append(table(wbs_rows, [31 * mm, 14 * mm, 48 * mm, 48 * mm, 55 * mm, 70 * mm]))
    story.append(PageBreak())
    story.append(Paragraph("3. 요구사항/화면 기준 담당 매핑", H1))
    story.append(table(screen_rows, [58 * mm, 70 * mm, 45 * mm, 93 * mm]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("4. 미배정 이슈 메모", H1))
    story.append(
        Paragraph(
            "#34, #35는 합의금 확장 기능으로, 현재 담당 분장에 합의금 전담 축이 없어서 세부 담당을 확정하지 않았다.",
            NOTE,
        )
    )
    story.append(Spacer(1, 4))
    story.append(table(unassigned_rows, [45 * mm, 82 * mm, 92 * mm, 47 * mm]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("5. 검토 메모", H1))
    notes = [
        "모든 이슈는 2026-06-18 현재 open 상태다.",
        "workzion2는 kama42kanne와 같은 담당자로 확인되어 GitHub assignee에는 workzion2를 사용했다.",
        "#34/#35는 미배정 상태이며, MVP 포함 여부와 구현 범위 결정 후 재배정이 필요하다.",
        "인증인가 별도 이슈는 아직 생성되어 있지 않으며, 필요 시 hi20260204-maker 담당 신규 이슈로 분리하는 것이 적절하다.",
    ]
    for item in notes:
        story.append(Paragraph("- " + item, BODY))
    return story


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = doc_template(OUTPUT)
    doc.build(build_story())
    print(OUTPUT)


if __name__ == "__main__":
    main()
