from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "pdf"
OUT.mkdir(parents=True, exist_ok=True)

DOC_DATE = date(2026, 6, 30).isoformat()
PROJECT = "교통분쟁 AI: 과실비율·과태료/범칙금 분석 및 리포팅 서비스"
TEAM = "SKN27-FINAL-3Team"


def register_fonts() -> tuple[str, str]:
    regular = Path("C:/Windows/Fonts/NotoSansKR-Regular.ttf")
    bold = Path("C:/Windows/Fonts/NotoSansKR-Bold.ttf")
    fallback_regular = Path("C:/Windows/Fonts/malgun.ttf")
    fallback_bold = Path("C:/Windows/Fonts/malgunbd.ttf")
    regular = regular if regular.exists() else fallback_regular
    bold = bold if bold.exists() else fallback_bold
    pdfmetrics.registerFont(TTFont("KR", str(regular)))
    pdfmetrics.registerFont(TTFont("KR-Bold", str(bold)))
    return "KR", "KR-Bold"


FONT, FONT_BOLD = register_fonts()


def styles():
    s = getSampleStyleSheet()
    base = ParagraphStyle(
        "KRBase",
        parent=s["Normal"],
        fontName=FONT,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#20242b"),
        wordWrap="CJK",
    )
    return {
        "base": base,
        "title": ParagraphStyle(
            "Title",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=25,
            leading=32,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#123c44"),
            spaceAfter=12,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base,
            fontSize=12,
            leading=18,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#53606f"),
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=16,
            leading=22,
            textColor=colors.HexColor("#14584f"),
            spaceBefore=10,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=12,
            leading=17,
            textColor=colors.HexColor("#285f9f"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base,
            fontSize=7.5,
            leading=10.5,
            textColor=colors.HexColor("#53606f"),
        ),
        "cell": ParagraphStyle(
            "Cell",
            parent=base,
            fontSize=7.8,
            leading=10.8,
            wordWrap="CJK",
        ),
        "cell_small": ParagraphStyle(
            "CellSmall",
            parent=base,
            fontSize=6.8,
            leading=9.2,
            wordWrap="CJK",
        ),
        "th": ParagraphStyle(
            "TH",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=7.6,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "box_title": ParagraphStyle(
            "BoxTitle",
            parent=base,
            fontName=FONT_BOLD,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#123c44"),
            alignment=TA_CENTER,
        ),
    }


ST = styles()


def p(text: str, style: str = "base") -> Paragraph:
    return Paragraph(text.replace("\n", "<br/>"), ST[style])


def bullet(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(p(item, "base"), leftIndent=8) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=14,
    )


def table(rows, widths=None, small=False, repeat=1):
    cell_style = "cell_small" if small else "cell"
    data = []
    for r_idx, row in enumerate(rows):
        cells = []
        for cell in row:
            if isinstance(cell, Flowable):
                cells.append(cell)
            else:
                cells.append(p(str(cell), "th" if r_idx == 0 and repeat else cell_style))
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c8d2dc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if repeat:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f7a6d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafb")]),
        ]
    else:
        commands.append(("BACKGROUND", (0, 0), (-1, -1), colors.white))
    t.setStyle(TableStyle(commands))
    return t


class ProcessDiagram(Flowable):
    def __init__(self, labels: list[str], width=180 * mm, height=28 * mm):
        super().__init__()
        self.labels = labels
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        box_w = (self.width - 12 * (len(self.labels) - 1)) / len(self.labels)
        y = self.height / 2 - 9
        for idx, label in enumerate(self.labels):
            x = idx * (box_w + 12)
            c.setFillColor(colors.HexColor("#e7f4f1"))
            c.setStrokeColor(colors.HexColor("#1f7a6d"))
            c.roundRect(x, y, box_w, 18, 4, stroke=1, fill=1)
            c.setFillColor(colors.HexColor("#123c44"))
            c.setFont(FONT_BOLD, 7)
            c.drawCentredString(x + box_w / 2, y + 6, label)
            if idx < len(self.labels) - 1:
                c.setStrokeColor(colors.HexColor("#647282"))
                c.line(x + box_w + 1, y + 9, x + box_w + 11, y + 9)
                c.line(x + box_w + 11, y + 9, x + box_w + 7, y + 12)
                c.line(x + box_w + 11, y + 9, x + box_w + 7, y + 6)


class MiniWireframe(Flowable):
    def __init__(self, title: str, layout: str, width=76 * mm, height=50 * mm):
        super().__init__()
        self.title = title
        self.layout = layout
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        c.setStrokeColor(colors.HexColor("#9fb0bf"))
        c.setFillColor(colors.HexColor("#f7fafb"))
        c.roundRect(0, 0, self.width, self.height, 5, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#1f7a6d"))
        c.roundRect(0, self.height - 10, self.width, 10, 5, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 6.5)
        c.drawString(5, self.height - 7, self.title)

        if self.layout == "entry":
            self._rect(c, 6, 31, 64, 8, "서비스 안내")
            self._rect(c, 12, 19, 23, 8, "Google")
            self._rect(c, 41, 19, 23, 8, "비회원")
            self._rect(c, 6, 6, 64, 8, "상담 미리보기")
        elif self.layout == "chat":
            self._rect(c, 5, 6, 17, 32, "상담목록")
            self._rect(c, 26, 20, 45, 18, "대화/카드")
            self._rect(c, 26, 6, 45, 9, "입력/첨부")
        elif self.layout == "fine":
            self._rect(c, 5, 29, 66, 9, "고지서 요약")
            self._rect(c, 5, 17, 31, 8, "쟁점")
            self._rect(c, 40, 17, 31, 8, "필요자료")
            self._rect(c, 5, 6, 66, 7, "초안/저장/다운로드")
        elif self.layout == "fault":
            self._rect(c, 5, 29, 31, 9, "사고개요")
            self._rect(c, 40, 29, 31, 9, "자료")
            self._rect(c, 5, 16, 66, 8, "핵심 쟁점/근거")
            self._rect(c, 5, 6, 66, 7, "후속 행동")
        elif self.layout == "my":
            self._rect(c, 5, 29, 66, 9, "사건 요약")
            self._rect(c, 5, 17, 31, 8, "기한 임박")
            self._rect(c, 40, 17, 31, 8, "생성 문서")
            self._rect(c, 5, 6, 66, 7, "최근 이력")
        else:
            self._rect(c, 5, 30, 66, 8, "검색/필터")
            self._rect(c, 5, 17, 66, 8, "리포트 목록")
            self._rect(c, 5, 6, 66, 7, "상세/다운로드")

    def _rect(self, c, x_mm, y_mm, w_mm, h_mm, label):
        x, y, w, h = x_mm * mm, y_mm * mm, w_mm * mm, h_mm * mm
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#b7c3ce"))
        c.roundRect(x, y, w, h, 3, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#20242b"))
        c.setFont(FONT, 5.8)
        c.drawCentredString(x + w / 2, y + h / 2 - 2, label)


class ArchitectureDiagram(Flowable):
    def __init__(self, width=180 * mm, height=76 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        layers = [
            ("Client", ["HTML 화면설계", "React Mock Flow"], "#e9f0fa"),
            ("Django API", ["Auth/Guest", "Chat/File", "Analysis/Report", "History/MyPage"], "#e7f4f1"),
            ("Supervisor/Agents", ["Input Validation", "Fine Notice", "Law/RAG", "Vision", "Report Gen"], "#fff4df"),
            ("Storage", ["PostgreSQL model", "SQLite dev DB", "Mock uploads", "Report URI"], "#fff0ed"),
        ]
        margin = 8
        layer_h = (self.height - margin * (len(layers) + 1)) / len(layers)
        for i, (title, items, fill) in enumerate(layers):
            y = self.height - margin - (i + 1) * layer_h - i * margin
            c.setFillColor(colors.HexColor(fill))
            c.setStrokeColor(colors.HexColor("#9fb0bf"))
            c.roundRect(0, y, self.width, layer_h, 5, stroke=1, fill=1)
            c.setFillColor(colors.HexColor("#123c44"))
            c.setFont(FONT_BOLD, 9)
            c.drawString(8, y + layer_h - 13, title)
            box_w = (self.width - 24 - 8 * (len(items) - 1)) / len(items)
            for j, item in enumerate(items):
                x = 12 + j * (box_w + 8)
                c.setFillColor(colors.white)
                c.setStrokeColor(colors.HexColor("#b7c3ce"))
                c.roundRect(x, y + 7, box_w, 17, 3, stroke=1, fill=1)
                c.setFillColor(colors.HexColor("#20242b"))
                c.setFont(FONT, 6.8)
                c.drawCentredString(x + box_w / 2, y + 13, item)
            if i < len(layers) - 1:
                c.setStrokeColor(colors.HexColor("#647282"))
                x = self.width / 2
                c.line(x, y - 1, x, y - margin + 2)
                c.line(x, y - margin + 2, x - 3, y - margin + 6)
                c.line(x, y - margin + 2, x + 3, y - margin + 6)


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(colors.HexColor("#647282"))
    canvas.drawString(doc.leftMargin, 10 * mm, f"{TEAM} | {PROJECT}")
    canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, f"{doc.page}")
    canvas.restoreState()


def header_footer_landscape(canvas, doc):
    header_footer(canvas, doc)


def cover(title: str, subtitle: str):
    return [
        Spacer(1, 22 * mm),
        p(title, "title"),
        p(subtitle, "subtitle"),
        Spacer(1, 7 * mm),
        table(
            [
                ["항목", "내용"],
                ["프로젝트명", PROJECT],
                ["작성일", DOC_DATE],
                ["작성 기준", "참고 PDF 양식, 저장소 구현/문서, OpenAPI v0, 화면설계 초안"],
                ["작성 범위", "MVP 화면, Django mock/canonical API, Supervisor/Agent 계약, 저장소 경계"],
            ],
            [32 * mm, 112 * mm],
        ),
        PageBreak(),
    ]


def screen_detail(screen_id, name, layout, purpose, components, actions, data, rules):
    return KeepTogether(
        [
            p(f"{screen_id} {name}", "h2"),
            table(
                [
                    [MiniWireframe(name, layout), p(
                        f"<b>화면 목적</b><br/>{purpose}<br/><br/>"
                        f"<b>주요 구성</b><br/>{components}<br/><br/>"
                        f"<b>사용자 액션</b><br/>{actions}",
                        "cell",
                    )],
                ],
                [80 * mm, 100 * mm],
                repeat=0,
            ),
            table(
                [
                    ["표시 데이터", "정책/예외/검증"],
                    [data, rules],
                ],
                [90 * mm, 90 * mm],
                small=True,
            ),
            Spacer(1, 4 * mm),
        ]
    )


def screen_design_pdf():
    story = cover("화면설계서", "UI Specification")
    story += [
        p("1. 문서 개요", "h1"),
        table(
            [
                ["구분", "내용"],
                ["목적", "교통분쟁 AI 서비스의 MVP 화면, 사용자 액션, 표시 데이터, 권한/검증 기준을 개발자가 구현 가능한 수준으로 정의한다."],
                ["대상 사용자", "과태료·범칙금 고지서 또는 교통사고 과실비율 상담이 필요한 비회원/회원 사용자"],
                ["주요 근거", "docs/screen-design-specification.md, docs/screen-design-ui-ux-flow-guide.md, app/screen-design-mvp-flow.html"],
            ],
            [34 * mm, 126 * mm],
        ),
        p("2. 수정 이력 관리", "h1"),
        table(
            [
                ["버전", "일자", "작성/수정자", "수정 내용"],
                ["v0.1", "2026-06-18", "프로젝트 팀", "초기 화면 목록과 요구사항 매핑 작성"],
                ["v0.3", "2026-06-22", "프로젝트 팀", "로그인/챗봇/Supervisor/리포트 흐름 보강"],
                ["v1.0", DOC_DATE, "Codex", "참고 PDF 양식에 맞춘 제출용 PDF 재구성"],
            ],
            [20 * mm, 28 * mm, 32 * mm, 80 * mm],
        ),
        p("3. 메뉴 트리", "h1"),
        table(
            [
                ["1Depth", "2Depth", "주요 화면", "설명"],
                ["서비스 진입", "로그인/서비스 안내", "ENTRY-001", "Google 로그인 또는 비회원 상담 시작"],
                ["AI 상담", "교통 상담 챗봇", "UI-CHAT-001", "고지서, 사고 설명, 사진/영상, 법령 질문 입력"],
                ["분석 결과", "과태료·범칙금 결과", "UI-FINE-001", "OCR 후보, 쟁점, 필요 자료, 이의신청 초안"],
                ["분석 결과", "과실비율 결과", "UI-FAULT-001", "사고 개요, 제출 자료, 핵심 쟁점, 후속 행동"],
                ["내 사건", "마이페이지/이력", "UI-MY-001, UI-HIS-001", "진행 사건, 저장 리포트, 과거 분석 조회"],
                ["리포트", "리포트 목록/상세", "UI-REPORT-*", "과실비율 리포트, 과태료 리포트, 사례 목록"],
            ],
            [27 * mm, 38 * mm, 35 * mm, 60 * mm],
        ),
        p("4. 스크린 리스트", "h1"),
        table(
            [
                ["Screen ID", "화면명", "핵심 컴포넌트", "입력/출력", "상태"],
                ["ENTRY-001", "로그인/서비스 안내", "브랜드, 로그인 CTA, 상담 미리보기", "Google 로그인, 비회원 시작", "MVP 반영"],
                ["UI-CHAT-001", "AI 교통 상담 챗봇", "상담 목록, 대화창, 첨부, 분석 카드", "사용자 텍스트/파일 -> 분석 요청", "MVP 반영"],
                ["UI-FINE-001", "과태료·범칙금 결과", "고지서 요약, 쟁점, 필요 증거, 초안", "분석 결과 -> 리포트 저장/다운로드", "MVP 반영"],
                ["UI-FAULT-001", "사고 과실비율 결과", "사고 정보, 자료, 쟁점, 유사 사례", "사고 설명/자료 -> 후속 대응", "MVP 반영"],
                ["UI-MY-001", "내 사건", "진행 사건, 기한 임박, 생성 문서", "이력 열기, 리포트 저장", "MVP 반영"],
                ["UI-HIS-001", "과거 이력", "검색, 유형/기간 필터, 이력 표", "조회 조건 -> 분석 이력", "MVP 반영"],
                ["UI-REPORT-001", "리포트 목록", "검색, 유형 필터, 목록, 페이지네이션", "리포트 조건 -> 목록/상세", "MVP 반영"],
            ],
            [24 * mm, 31 * mm, 45 * mm, 41 * mm, 20 * mm],
            small=True,
        ),
        PageBreak(),
        p("5. 프로세스 플로우 차트", "h1"),
        ProcessDiagram(["서비스 진입", "인증 선택", "챗봇 입력", "Supervisor 분기", "결과 확인", "리포트 저장", "이력 조회"]),
        Spacer(1, 6 * mm),
        table(
            [
                ["단계", "트리거", "시스템 처리", "다음 화면"],
                ["1", "Google 로그인 또는 비회원 상담 시작", "guest identity 또는 mock bearer subject 생성", "AI 교통 상담"],
                ["2", "사용자 질문/첨부 전송", "chat session/message 생성 및 file metadata 등록", "분석 진행 상태"],
                ["3", "분석 job 생성", "Supervisor가 OCR, 법률/RAG, Vision, 사례검색, 리포트 노드로 분기", "분석 결과"],
                ["4", "리포트 저장/다운로드", "report metadata 저장, mock://report 또는 object storage 후보 반환", "내 사건/리포트 목록"],
            ],
            [16 * mm, 42 * mm, 72 * mm, 30 * mm],
        ),
        p("6. 화면별 와이어프레임 및 상세 설계", "h1"),
    ]
    story += [
        screen_detail(
            "ENTRY-001",
            "로그인/서비스 안내",
            "entry",
            "사용자가 서비스 목적을 이해하고 Google 로그인 또는 비회원 상담으로 즉시 진입한다.",
            "브랜드 영역, 서비스 요약, Google 로그인 버튼, 비회원 상담 시작 버튼, 상담 예시 미리보기",
            "Google로 계속하기, 비회원 상담 시작, 상담 예시 확인",
            "auth_state, guest_id, user_id, session_id, rate_limit preview",
            "비회원 시작 시 guest identity를 발급한다. 로그인 실패 또는 guest 발급 실패 시 상담 시작 버튼을 비활성화하고 재시도 안내를 표시한다.",
        ),
        screen_detail(
            "UI-CHAT-001",
            "AI 교통 상담 챗봇",
            "chat",
            "고지서, 사고 설명, 사진/영상, 법령 질문을 입력받고 분석 job으로 연결한다.",
            "좌측 상담 목록, 중앙 대화 영역, 분석 상태 카드, 추천 질문, 하단 입력창, 파일 첨부 버튼",
            "메시지 전송, 파일 첨부, 분석 결과 열기, 상담 저장, 새 상담 시작",
            "session_id, message_id, user_text, attachments, routing_intent, progress.status, active_node",
            "첨부 파일은 purpose를 fine_notice, accident_scene, evidence 등으로 분류한다. 입력이 부족하면 pending_questions를 표시하고 리포트 액션은 숨긴다.",
        ),
        screen_detail(
            "UI-FINE-001",
            "과태료·범칙금 분석 결과",
            "fine",
            "고지서 OCR 후보와 이의제기 가능 쟁점을 정리하고 의견제출서 초안으로 이어준다.",
            "고지서 요약, 위반 내용, 납부/의견제출 기한, 쟁점 카드, 필요 증거, 이의신청서 초안, 저장/다운로드 버튼",
            "리포트 저장, 초안 다운로드, 사실관계 보완, 내 사건으로 이동",
            "notice_fields, violation_text, agency, due_date, evidence, limitations, report_links",
            "OCR/RAG가 mock 또는 불확실할 경우 한계 문구를 반드시 표시한다. 처분 취소 가능성이나 법률 자문을 확정 표현으로 표시하지 않는다.",
        ),
        screen_detail(
            "UI-FAULT-001",
            "사고 과실비율 분석 결과",
            "fault",
            "사고 설명과 제출 자료를 바탕으로 핵심 쟁점, 유사 사례, 후속 대응 방향을 보여준다.",
            "사고 개요, 제출 자료 목록, AI 분석 요약, 핵심 쟁점, 유사 판례/보험사 사례, 후속 행동 버튼",
            "자료 추가, 보험사 문의 초안 확인, 리포트 저장, 상담으로 돌아가기",
            "accident_summary, uploaded_files, issue_tags, similar_cases, evidence, next_actions",
            "정확한 과실비율을 단정하지 않고 후보 범위와 근거 한계를 함께 표시한다. 영상/이미지 품질이 낮으면 추가 자료 요청 상태로 전환한다.",
        ),
        screen_detail(
            "UI-MY-001 / UI-HIS-001",
            "내 사건·과거 이력",
            "my",
            "진행 중인 상담, 저장 리포트, 기한 임박 사건, 과거 분석 이력을 재조회한다.",
            "사건 요약 카드, 기한 임박 영역, 생성 문서 목록, 최근 분석 이력 표, 유형/기간/검색 필터",
            "사건 열기, 리포트 다운로드, 조건 검색, 이력 상세 보기",
            "case_status, analysis_jobs, reports, history_events, due_date, owner_id",
            "회원/비회원 subject가 소유한 사건만 조회한다. history에는 민감 원문 대신 sanitized metadata와 요약만 표시한다.",
        ),
        screen_detail(
            "UI-REPORT-001",
            "리포트 목록·상세",
            "report",
            "저장된 과태료 리포트와 과실비율 리포트를 검색하고 상세/다운로드로 연결한다.",
            "검색창, 기간 필터, 리포트 유형 필터, 목록 표, 상세 요약, 다운로드/원문 보기 버튼",
            "필터 적용, 상세 열기, PDF 다운로드, 원문 링크 확인",
            "report_id, report_type, title, created_at, storage_uri, download_status, source_refs",
            "다운로드 전 reports.owner_id와 요청 subject를 비교한다. 권한 불일치 시 object_access.v1 403 안내를 표시한다.",
        ),
        p("6.7 화면별 상세 명세", "h2"),
        table(
            [
                ["Screen ID", "화면 목적", "주요 영역/컴포넌트", "필수 표시 데이터"],
                ["UI-ENTRY-001", "서비스 목적을 이해하고 로그인 또는 비회원 상담으로 진입", "서비스 설명, 상담 유형 안내, Google 로그인, 비회원 상담 시작, 상담 미리보기", "auth_state, guest_id, session_id, rate_limit, 서비스 안내 문구"],
                ["UI-AUTH-001", "Google 로그인 후 챗봇 또는 마이페이지로 이동", "Google 인증 버튼, 약관 동의, 신규/기존 사용자 분기, 로그인 실패 안내", "provider, google_sub, email, display_name, auth_session_id, linked_guest_id"],
                ["UI-MY-001", "등록 사건과 최근 분석 현황을 요약 조회", "요약 카드, 기한 임박 사건, 생성 문서, 최근 분석 이력, 상세보기 버튼", "등록 사건 수, 기한 임박 수, 생성 문서 수, 분석 제목, 결과 요약, 상태, 분석 일시"],
                ["UI-Ai-01", "교통사고/과태료/법령 질문을 입력하고 분석 카드 확인", "대화 목록, 챗봇 대화창, 첨부 자료, 추천 키워드, 분석 결과 카드, 입력창", "session_id, message_id, user_text, attachments, routing_intent, progress, cards, pending_questions"],
                ["UI-HIS-001", "과거 분석 이력을 검색/필터 후 상세 진입", "유형 필터, 기간 필터, 검색창, 분석 이력 표, 페이지네이션", "analysis_id, 유형, 제목, 결과 요약, 상태, 분석 일시, 상세 링크"],
                ["UI-MY-003", "과실비율 분석 이력의 상세 요약 확인", "분석 요약, 사고 정보, 업로드 자료, AI 분석 요약, 핵심 쟁점, 후속 행동", "사고 유형, 일시/장소, 제출 자료, 예상 쟁점, 추가 증거, 다음 행동"],
                ["UI-REPORT-001", "생성 리포트 검색 및 상세/다운로드 진입", "검색, 기간 선택, 유형 필터, 리포트 목록 표, 페이지네이션", "report_id, 제목, 유형, 생성일, 상태, 다운로드 가능 여부"],
                ["UI-REPORT-003", "판례/보험사 사례 목록과 선택 상세 확인", "사례 검색, 보험사/판례 필터, 좌측 목록, 우측 상세, PDF 다운로드, 원문 보기", "case_id, 사건 번호, 사고 유형, 주요 내용, 과실비율, 판결/결정, source_ref"],
                ["UI-REPORT-FAULT-001", "사고 과실비율 분석 리포트 제공", "사고 개요, 제출 자료 현황, AI 분석 결과, 판단 근거, 핵심 쟁점, 유사 판례, 후속 조치", "분석 일시, 분석 유형, 예상 과실비율, 신뢰도, 판단 근거, 유사 판례, 후속 조치"],
                ["UI-REPORT-FINE-001", "과태료·범칙금 대응 리포트와 이의신청서 초안 제공", "OCR 문서 분석, 처분 결과, 이의제기 가능성, 필요 증거, 관련 법령/판례, 예상 결과, AI 작성 초안, 문서 액션", "위반 유형, 장소, 일시, 통지일, 납부기한, 관할 기관, OCR 상태, 이의제기 가능성, 초안 본문"],
            ],
            [25 * mm, 42 * mm, 65 * mm, 48 * mm],
            small=True,
        ),
        p("6.8 화면별 액션 및 이동", "h2"),
        table(
            [
                ["화면", "사용자 액션", "처리 결과/이동"],
                ["UI-ENTRY-001", "Google 로그인, 비회원 상담 시작, 상담 예시 확인", "로그인 성공 시 UI-Ai-01 이동, 비회원은 guest identity 발급 후 챗봇 이동"],
                ["UI-AUTH-001", "Google 인증, 약관 동의, 로그인 재시도", "auth_session 생성, 기존 guest session 병합 후보 저장, 실패 시 auth_error.v1 안내"],
                ["UI-MY-001", "기한 임박 사건 상세보기, 최근 분석 상세보기, 과거이력 이동", "사건 유형에 따라 UI-MY-003, UI-REPORT-FINE-001, UI-HIS-001로 이동"],
                ["UI-Ai-01", "대화 선택, 새 대화 시작, 메시지 전송, 파일 첨부, 분석 결과 상세보기, 근거 보기", "POST /api/chat/messages/ 또는 /api/files/ 호출 후 분석 결과/리포트 화면으로 이동"],
                ["UI-HIS-001", "유형 필터, 기간 필터, 키워드 검색, 상세보기, 페이지 이동", "GET /api/history/ 조건 조회 후 해당 분석 상세 또는 리포트 화면으로 이동"],
                ["UI-MY-003", "자료 추가, 리포트 생성, 후속 행동 확인, 보험사 문의 초안 확인", "추가 파일 등록 또는 UI-REPORT-FAULT-001로 이동"],
                ["UI-REPORT-001", "검색/필터 적용, 상세 열기, 다운로드", "리포트 유형에 따라 UI-REPORT-FAULT-001 또는 UI-REPORT-FINE-001 이동"],
                ["UI-REPORT-003", "사례 검색, 필터 적용, 사례 선택, PDF 다운로드, 원문 보기", "선택 사례 상세 표시, 원문 링크 또는 다운로드 권한 확인"],
                ["UI-REPORT-FAULT-001", "더 많은 판례 보기, PDF 저장, 자료 추가, 후속 조치 확인", "UI-REPORT-003 이동, 리포트 다운로드, 상담 화면 복귀"],
                ["UI-REPORT-FINE-001", "관련 법령 더보기, 유사 판례 더보기, 전체 복사, PDF/DOCX 저장, 초안 재생성", "법령/사례 확장, UI-REPORT-003 이동, report artifact 생성"],
            ],
            [35 * mm, 72 * mm, 73 * mm],
            small=True,
        ),
        p("6.9 화면별 상태·예외·빈 데이터", "h2"),
        table(
            [
                ["화면", "상태/예외", "화면 처리"],
                ["공통", "로딩, 빈 데이터, 오류, 권한 없음", "스켈레톤 또는 빈 상태 문구, 재시도 버튼, 로그인 유도, 오류 envelope 요약 표시"],
                ["UI-MY-001", "등록 사건 없음, 기한 임박 없음, 최근 분석 없음", "0건 요약, '기한 임박 사건이 없습니다', '최근 분석 이력이 없습니다', 진단하기 CTA 표시"],
                ["UI-Ai-01", "대화 이력 없음, 파일 업로드 실패, 응답 생성 실패, RAG 근거 부족", "새 대화 시작 CTA, 재업로드/다시 보내기, 근거 부족 안내와 추가 질문 표시"],
                ["UI-HIS-001", "검색 결과 없음, 기간 조건 오류", "조건 초기화 버튼과 빈 결과 안내, 날짜 범위 재선택 안내"],
                ["UI-MY-003", "자료 부족, 분석 신뢰도 낮음, Vision 품질 낮음", "추가 자료 요청, 신뢰도/한계 문구, 영상·사진 재업로드 안내"],
                ["UI-REPORT-001", "리포트 없음, 다운로드 불가", "리포트 생성 안내, object_access.v1 또는 storage 미준비 안내"],
                ["UI-REPORT-003", "사례 수집 중, 원문 링크 없음, 검색 결과 없음", "수집 중 배지, 원문 준비 중 상태, 검색 조건 초기화"],
                ["UI-REPORT-FAULT-001", "정확한 과실비율 단정 불가, 유사 사례 부족", "후보 범위와 판단 근거 한계를 함께 표시, 추가 자료/판례 보기 유도"],
                ["UI-REPORT-FINE-001", "OCR 실패, 법령 근거 부족, 초안 생성 실패", "재업로드/수동 입력, 근거 부족 안내, 초안 재생성 버튼 표시"],
            ],
            [35 * mm, 57 * mm, 88 * mm],
            small=True,
        ),
        p("6.10 API 연결 및 수용 기준", "h2"),
        table(
            [
                ["화면", "연결 API 후보", "수용 기준"],
                ["UI-ENTRY-001 / UI-AUTH-001", "POST /api/auth/guest-session/, POST /api/auth/google-login/, GET /api/auth/me/", "guest/user subject가 발급되고 로그인 실패 시 표준 오류가 표시된다."],
                ["UI-MY-001", "GET /api/mypage/summary/, GET /api/history/", "등록 사건, 기한 임박, 생성 문서 수와 최근 분석 이력이 표시된다."],
                ["UI-Ai-01", "POST /api/chat/sessions/, POST /api/chat/messages/, POST /api/files/, GET /api/analysis/results/{job_id}/", "대화 목록, 메시지, 첨부, 분석 카드, 한계 문구, 리포트 링크가 표시된다."],
                ["UI-HIS-001", "GET /api/history/", "유형/기간/키워드로 이력을 조회하고 상세 이동이 가능하다."],
                ["UI-MY-003", "GET /api/history/{id}/ 또는 과실비율 상세 endpoint", "사고 정보, 업로드 자료, AI 요약, 핵심 쟁점, 후속 행동을 확인할 수 있다."],
                ["UI-REPORT-001", "GET /api/reports/", "리포트 목록 검색/필터와 유형별 상세 이동이 가능하다."],
                ["UI-REPORT-003", "GET /api/reports/{id}/related-cases/ 또는 사례 검색 endpoint", "판례/보험사 사례 목록과 선택 상세, PDF/원문 액션이 동작한다."],
                ["UI-REPORT-FAULT-001", "GET /api/reports/{id}/, GET /api/reports/{id}/download/", "사고 개요, AI 분석 결과, 판단 근거, 유사 판례, 후속 조치를 확인하고 저장할 수 있다."],
                ["UI-REPORT-FINE-001", "GET /api/reports/{id}/, POST /api/reports/, GET /api/reports/{id}/download/", "OCR 결과, 처분 결과, 이의제기 가능성, 법령/판례, 예상 결과, 초안을 확인하고 저장할 수 있다."],
            ],
            [35 * mm, 70 * mm, 75 * mm],
            small=True,
        ),
        p("7. 정책", "h1"),
        table(
            [
                ["정책 영역", "정의"],
                ["인증", "비회원 guest_id와 회원 user_id를 분리한다. Google 로그인은 진입 옵션이며 mock bearer subject로 개발 검증한다."],
                ["사용량 제한", "chat/file/analysis/report 요청은 usage_events로 기록하며 quota 초과 시 rate_limit.v1 429를 반환한다."],
                ["민감정보", "원본 고지서, 사고자료, OCR 원문은 화면에 불필요하게 반복 노출하지 않고 history에는 표준-라이트 이벤트만 저장한다."],
                ["결과 고지", "분석 결과는 법률 자문 또는 처분 취소 보장이 아니며 OCR/RAG/Vision mock 한계가 있을 때 limitations를 표시한다."],
            ],
            [35 * mm, 125 * mm],
        ),
        p("8. 권한 설정", "h1"),
        table(
            [
                ["사용자 유형", "허용 기능", "제한/검증"],
                ["익명", "서비스 안내 확인", "상담 시작 전 guest identity 발급 필요"],
                ["비회원", "챗봇 상담, 파일 메타데이터 등록, mock 분석, 리포트 저장", "TTL, quota, report owner 검증 필요"],
                ["회원", "내 사건/이력 조회, 리포트 다운로드", "mock bearer shape 이후 실제 JWT 서명 검증은 후속 범위"],
                ["운영자", "장애 대응/로그 확인", "개인정보 원문 접근 최소화, secret 관리 문서 준수"],
            ],
            [30 * mm, 75 * mm, 55 * mm],
        ),
        p("9. 검증", "h1"),
        table(
            [
                ["검증 항목", "기준"],
                ["화면 전환", "진입 -> 챗봇 -> 과태료/과실 결과 -> 내 사건/리포트 흐름이 끊기지 않는다."],
                ["반응형", "데스크톱/모바일에서 텍스트 겹침, 버튼 잘림, 표 폭 초과가 없어야 한다."],
                ["API 계약", "OpenAPI v0의 canonical /api/... 응답과 mock alias가 모두 회귀 테스트를 통과해야 한다."],
                ["안전 문구", "법률 성공 보장, 정확한 과실비율 단정, 제출 결과 보장 표현을 사용하지 않는다."],
            ],
            [38 * mm, 122 * mm],
        ),
    ]
    build_pdf("SKN27_화면설계서.pdf", story)


def test_scenario_pdf():
    story = cover("테스트 시나리오", "Test Scenario")
    story += [
        p("1. 테스트 목표", "h1"),
        bullet(
            [
                "사용자가 비회원 또는 회원 상태에서 상담을 시작하고 분석 리포트까지 도달하는 핵심 흐름을 검증한다.",
                "Django canonical API, mock alias, Supervisor/Agent envelope, 저장소 경계를 회귀 테스트로 확인한다.",
                "법률/AI 결과가 mock 또는 제한 상태일 때 사용자에게 한계를 명확히 노출하는지 확인한다.",
            ]
        ),
        p("2. 테스트 범위", "h1"),
        table(
            [
                ["구분", "포함 범위", "제외/후속 범위"],
                ["Frontend", "HTML MVP flow, React ChatbotMockFlow, 상태 라벨/리포트 액션", "실제 배포 UI 빌드 파이프라인"],
                ["Backend API", "Auth, Chat, Files, Analysis Jobs/Results, Agents, Reports, MyPage, History", "운영 JWT 서명 검증"],
                ["AI/Supervisor", "mock_ready/contract_only Agent envelope, plan 실행, validation", "실제 OCR/RAG/Vision/LLM 품질 측정"],
                ["Storage", "Django models, SQLite dev DB, mock uploads/reports, history events", "운영 PostgreSQL/Redis/object storage 전환"],
            ],
            [30 * mm, 76 * mm, 54 * mm],
        ),
        p("3. 테스트 환경", "h1"),
        table(
            [
                ["항목", "값"],
                ["실행 환경", "Windows 개발 환경, Python/Django, pytest"],
                ["API Base", "http://127.0.0.1:8000 또는 상대 경로 /api"],
                ["주요 명령", "python -m pytest test"],
                ["테스트 데이터", "비식별화 mock attachment metadata, mock analysis job/report fixture"],
            ],
            [34 * mm, 126 * mm],
        ),
        p("4. 시나리오 요약", "h1"),
        table(
            [
                ["ID", "시나리오", "우선순위", "관련 테스트/문서"],
                ["TS-001", "비회원 identity 발급 후 챗봇 상담 시작", "상", "test_auth_session_mock_service.py"],
                ["TS-002", "과태료 고지서 메타데이터 등록 및 분석 job 생성", "상", "test_attachment_mock_service.py, test_analysis_job_mock_service.py"],
                ["TS-003", "Supervisor mock plan 실행 및 Agent 결과 envelope 검증", "상", "test_agent_node_service.py"],
                ["TS-004", "분석 결과 display DTO와 리포트 저장/다운로드", "상", "test_chatbot_mock_service.py"],
                ["TS-005", "history_event.v1 저장/조회와 민감정보 sanitizing", "중", "test_history_event_mock_service.py"],
                ["TS-006", "OpenAPI v0 distribution/schema 계약 검증", "중", "test_openapi_v0_distribution.py"],
                ["TS-007", "권한/사용량 제한/다운로드 owner 경계", "상", "auth/quota/history/download 문서"],
            ],
            [18 * mm, 78 * mm, 20 * mm, 44 * mm],
            small=True,
        ),
        PageBreak(),
        p("5. 상세 테스트 케이스", "h1"),
        table(
            [
                ["TC ID", "전제조건", "수행 절차", "기대 결과"],
                ["TC-001-01", "API 서버 실행", "POST /api/auth/guest-session/ 호출", "guest_id, ttl_seconds, subject_id, rate_limit가 반환되고 DB 저장 경계가 동작한다."],
                ["TC-001-02", "mock bearer token 준비", "GET /api/auth/me/ 호출", "authenticated 또는 guest subject가 반환되며 잘못된 bearer는 auth_error.v1 envelope를 반환한다."],
                ["TC-002-01", "guest/session 준비", "POST /api/files/로 fine_notice metadata 등록", "attachment_id, purpose, storage_uri, agent_handoff가 생성된다."],
                ["TC-002-02", "chat session 준비", "POST /api/chat/messages/로 고지서 질문 전송", "routing_intent가 objection_request로 잡히고 결과 카드 후보가 생성된다."],
                ["TC-003-01", "analysis payload 준비", "POST /api/analysis/jobs/ 호출", "analysis_job, node_execution, status_counts, analysis_plan_id가 생성된다."],
                ["TC-003-02", "job_id 존재", "GET /api/analysis/results/{job_id}/ 호출", "assistant_message, progress, cards, evidence, report_links가 화면 DTO로 반환된다."],
                ["TC-004-01", "report action 가능", "POST /api/reports/ 호출", "reports row metadata 또는 mock report action이 생성된다."],
                ["TC-004-02", "report owner 일치", "GET /api/reports/{report_id}/download/ 호출", "권한 확인 후 mock report body 또는 storage metadata 기반 다운로드가 가능하다."],
                ["TC-005-01", "history event 발생", "GET /api/history/ 호출", "history_event.v1 목록이 반환되며 raw prompt/OCR 원문 등 민감 키는 제거된다."],
                ["TC-006-01", "OpenAPI 파일 존재", "pytest OpenAPI distribution 테스트 실행", "canonical path와 schema component가 계약과 일치한다."],
            ],
            [23 * mm, 38 * mm, 49 * mm, 50 * mm],
            small=True,
        ),
        p("6. E2E 대표 흐름", "h1"),
        ProcessDiagram(["Guest 발급", "채팅 생성", "파일 등록", "메시지 전송", "분석 Job", "결과 조회", "리포트 다운로드"]),
        Spacer(1, 5 * mm),
        table(
            [
                ["단계", "입력", "검증 포인트"],
                ["1", "비회원 시작", "guest_id/session_id 분리, quota 기록"],
                ["2", "고지서 이미지 metadata + 질문", "fine_notice purpose, objection_request routing"],
                ["3", "analysis job 생성", "Agent별 success/partial/failed envelope 저장"],
                ["4", "결과 화면 조회", "cards, limitations, pending_questions 표시"],
                ["5", "리포트 저장/다운로드", "owner_id 불일치 403, 일치 시 다운로드 성공"],
            ],
            [18 * mm, 55 * mm, 87 * mm],
        ),
        p("7. 리스크 및 회귀 체크", "h1"),
        table(
            [
                ["리스크", "회귀 체크"],
                ["Mock 결과를 실제 법률 판단처럼 오해", "limitations 문구와 guarantee 금지 문구를 UI/API 모두에서 확인"],
                ["권한 없는 리포트 다운로드", "reports.owner_id와 요청 subject 비교, object_access.v1 403 확인"],
                ["history에 민감 원문 저장", "SENSITIVE_METADATA_KEYS sanitizing 테스트 확인"],
                ["canonical API와 mock alias 불일치", "OpenAPI v0와 pytest 계약 테스트 동시 확인"],
            ],
            [55 * mm, 105 * mm],
        ),
    ]
    build_pdf("SKN27_테스트시나리오.pdf", story)


def architecture_pdf():
    story = cover("시스템 아키텍처", "System Architecture")
    story += [
        p("1. 아키텍처 개요", "h1"),
        table(
            [
                ["구분", "내용"],
                ["아키텍처 유형", "클라이언트-서버 기반의 계층형 구조에 Supervisor/Agent 실행 흐름을 결합한 MVP 아키텍처"],
                ["핵심 목표", "UI, Django API, AI Agent, 저장소 경계를 분리하여 mock 구현에서 운영 구현으로 단계적 전환 가능하게 한다."],
                ["현재 구현 수준", "Django canonical API, mock service, Agent registry/envelope, Django model foundation, history/quota/download 경계 구현"],
            ],
            [34 * mm, 126 * mm],
        ),
        p("2. 전체 구성도", "h1"),
        ArchitectureDiagram(),
        PageBreak(),
        p("3. 레이어별 구성 요소", "h1"),
        table(
            [
                ["레이어", "구성 요소", "역할", "주요 파일/문서"],
                ["Presentation", "HTML MVP, React ChatbotMockFlow", "사용자 진입, 상담, 결과, 내 사건, 리포트 UI 제공", "app/screen-design-mvp-flow.html, app/web/ChatbotMockFlow.jsx"],
                ["API", "Django config/chatbot", "canonical /api 경로와 /api/mock 별칭 제공, 요청 파싱/응답 envelope 처리", "backend/chatbot/views.py, urls.py"],
                ["Application Service", "app/services", "chat, attachment, analysis, auth, history, agent mock service 계약 구현", "app/services/*.py"],
                ["AI Orchestration", "Supervisor + Agent registry", "입력 검증, 고지서 분석, 법률 검색, Vision, 리포트 생성 노드 실행", "app/services/agent_node_service.py"],
                ["Persistence", "Django models, SQLite dev, mock files", "세션, 메시지, 파일, job, result, report, history, quota 저장 경계", "backend/chatbot/models.py, media/mock_*"],
                ["Operations", "Docker, ops docs", "배포 점검, 백업/복구, incident, secret 관리", "Dockerfile, docker-compose.yml, docs/ops/*"],
            ],
            [26 * mm, 39 * mm, 54 * mm, 41 * mm],
            small=True,
        ),
        PageBreak(),
        p("4. 주요 API 흐름", "h1"),
        ProcessDiagram(["Auth", "Chat", "Files", "Analysis", "Agents", "Reports", "History"]),
        Spacer(1, 5 * mm),
        table(
            [
                ["도메인", "Canonical Endpoint", "주요 책임"],
                ["Auth", "POST /api/auth/guest-session/, GET /api/auth/me/", "guest identity, mock bearer subject, session binding"],
                ["Chat", "POST /api/chat/sessions/, POST /api/chat/messages/", "상담 세션 생성, 메시지 등록, routing intent 결정"],
                ["Files", "POST/GET /api/files/", "첨부 metadata, storage_uri, agent_handoff 생성"],
                ["Analysis", "POST /api/analysis/jobs/, GET /api/analysis/results/{job_id}/", "Supervisor plan 실행, display result snapshot 제공"],
                ["Agents", "GET /api/agents/nodes/, POST /api/agents/plans/run/", "Agent registry 조회, mock plan 실행 envelope 반환"],
                ["Reports", "POST /api/reports/, GET /api/reports/{report_id}/download/", "리포트 metadata 저장, owner 권한 확인, 다운로드"],
                ["MyPage/History", "GET /api/mypage/summary/, GET /api/history/", "내 사건 진행도, 표준-라이트 history event 조회"],
            ],
            [28 * mm, 68 * mm, 64 * mm],
            small=True,
        ),
        p("5. 데이터 아키텍처", "h1"),
        table(
            [
                ["테이블/저장소", "주요 데이터", "관계/용도"],
                ["chat_sessions", "session_id, owner_id, status, current_intent", "대화/파일/job/report의 상위 경계"],
                ["chat_messages", "role, content, routing_intent", "사용자 입력과 분석 job trigger 연결"],
                ["uploaded_files", "attachment_id, purpose, storage_uri, privacy_risk", "Agent handoff와 object storage 전환 후보"],
                ["analysis_jobs/events", "job_id, status, active_node, progress", "분석 생명주기와 진행도 복구"],
                ["agent_results", "node_code, summary, structured_result, evidence", "Agent별 실행 결과 추적성"],
                ["analysis_display_results", "cards, report_links, limitations", "화면 표시용 snapshot"],
                ["reports", "report_id, report_type, owner_id, storage_uri", "리포트 저장/다운로드 권한 경계"],
                ["history_events/usage_events", "event_type, sanitized metadata, scope", "이력 조회, quota, 감사 추적"],
            ],
            [42 * mm, 58 * mm, 60 * mm],
            small=True,
        ),
        p("6. 보안 및 권한", "h1"),
        table(
            [
                ["영역", "설계"],
                ["인증", "anonymous, guest:{guest_id}, user:{user_id} subject를 구분한다. 현재 JWT는 mock bearer shape만 검증하며 실제 서명 검증은 후속 범위다."],
                ["인가", "report download는 reports.owner_id와 요청 subject를 비교하고 불일치 시 object_access.v1 403을 반환한다."],
                ["사용량", "canonical chat/file/analysis/report 요청은 usage_events에 기록하고 quota 초과 시 rate_limit.v1 429를 반환한다."],
                ["개인정보", "history에는 원문 prompt, OCR, transcript 등 민감 metadata key를 sanitizing한 표준-라이트 이벤트만 저장한다."],
            ],
            [35 * mm, 125 * mm],
        ),
        p("7. 배포 및 운영 후보", "h1"),
        table(
            [
                ["항목", "현재", "운영 전환 방향"],
                ["Web/API", "Django local server, Dockerfile", "정적 프론트 빌드와 API gateway 또는 Django 배포 경계 확정"],
                ["Database", "SQLite dev DB + PostgreSQL model foundation", "PostgreSQL 연결, migration, backup 정책 적용"],
                ["Cache", "Redis 문서상 후보, 현재 compose 미포함", "analysis progress TTL cache 도입 여부 결정"],
                ["Object Storage", "mock://uploads, mock://reports", "S3/GCS/MinIO adapter와 signed URL 권한 정책 적용"],
                ["AI Runtime", "mock_ready/contract_only Agents", "OCR/RAG/Vision/LLM adapter 교체와 latency/cost/retry 계측"],
            ],
            [32 * mm, 62 * mm, 66 * mm],
            small=True,
        ),
        p("8. 검증 기준", "h1"),
        table(
            [
                ["검증 항목", "완료 기준"],
                ["API 생존성", "/api/health/와 주요 canonical endpoint가 정상 응답한다."],
                ["계약 일관성", "OpenAPI v0와 pytest 계약 테스트가 일치한다."],
                ["추적성", "chat -> file -> job -> agent_result -> display_result -> report 흐름을 DB 또는 metadata로 추적할 수 있다."],
                ["안전성", "권한 없는 다운로드, quota 초과, 인증 실패가 표준 error envelope로 반환된다."],
            ],
            [42 * mm, 118 * mm],
        ),
    ]
    build_pdf("SKN27_시스템_아키텍처.pdf", story)


def build_pdf(filename: str, story, pagesize=A4, landscape_mode=False):
    doc = SimpleDocTemplate(
        str(OUT / filename),
        pagesize=pagesize,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        title=filename,
        author=TEAM,
    )
    footer = header_footer_landscape if landscape_mode else header_footer
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    screen_design_pdf()
    test_scenario_pdf()
    architecture_pdf()
    print(f"generated: {OUT}")


if __name__ == "__main__":
    main()
