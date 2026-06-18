from __future__ import annotations

import html
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
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
OUTPUT = ROOT / "output" / "pdf" / "SKN27-FINAL-3Team_project_progress_report.pdf"
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


def run_git(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return completed.stdout.strip()
    except Exception as exc:
        return f"확인 실패: {exc}"


def register_korean_font() -> tuple[str, str, str]:
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
            return family, str(regular), str(bold)
    raise RuntimeError("한글 PDF 생성을 위한 Noto Sans KR, Malgun Gothic, Nanum Gothic 폰트를 찾지 못했습니다.")


FONT, FONT_REGULAR_PATH, FONT_BOLD_PATH = register_korean_font()


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "KTitle",
            parent=base["Title"],
            fontName=f"{FONT}-Bold",
            fontSize=22,
            leading=30,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "KSubtitle",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10.5,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=10 * mm,
        ),
        "h1": ParagraphStyle(
            "KH1",
            parent=base["Heading1"],
            fontName=f"{FONT}-Bold",
            fontSize=15,
            leading=22,
            textColor=colors.HexColor("#111827"),
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "KH2",
            parent=base["Heading2"],
            fontName=f"{FONT}-Bold",
            fontSize=12.2,
            leading=18,
            textColor=colors.HexColor("#1f2937"),
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "KBody",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.4,
            leading=15,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#111827"),
            spaceAfter=2.6 * mm,
        ),
        "small": ParagraphStyle(
            "KSmall",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.2,
            leading=12.5,
            textColor=colors.HexColor("#374151"),
            spaceAfter=1.5 * mm,
        ),
        "table_head": ParagraphStyle(
            "KTableHead",
            parent=base["BodyText"],
            fontName=f"{FONT}-Bold",
            fontSize=8.0,
            leading=11,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_body": ParagraphStyle(
            "KTableBody",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=7.6,
            leading=10.7,
            textColor=colors.HexColor("#111827"),
        ),
        "code": ParagraphStyle(
            "KCode",
            parent=base["Code"],
            fontName=FONT,
            fontSize=7.5,
            leading=10.5,
            backColor=colors.HexColor("#f3f4f6"),
            borderPadding=3,
            textColor=colors.HexColor("#111827"),
        ),
    }


STYLES = make_styles()


def text(value: object) -> str:
    return html.escape(str(value)).replace("\n", "<br/>")


def para(value: object, style: str = "body") -> Paragraph:
    return Paragraph(text(value), STYLES[style])


def raw_para(markup: str, style: str = "body") -> Paragraph:
    return Paragraph(markup, STYLES[style])


def heading(title: str, level: int = 1) -> Paragraph:
    return para(title, "h1" if level == 1 else "h2")


def table(
    rows: list[list[object]],
    widths: list[float],
    header: bool = True,
    font_size: str = "table_body",
) -> Table:
    converted: list[list[Paragraph]] = []
    for row_idx, row in enumerate(rows):
        style_name = "table_head" if header and row_idx == 0 else font_size
        converted.append([para(cell, style_name) for cell in row])
    tbl = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb") if header else colors.white),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white if header else colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ]
        )
    )
    return tbl


def bullets(items: list[str]) -> list[Paragraph]:
    return [para(f"- {item}", "body") for item in items]


def image_info() -> list[list[object]]:
    asset_dir = ROOT / "docs" / "assets" / "screen-design"
    rows: list[list[object]] = [["파일", "크기", "용도"]]
    purposes = {
        "mypage-updated.png": "현재 화면설계서의 마이페이지 참조 화면",
        "report-pages-updated.png": "과실비율 리포트와 과태료/범칙금 대응 리포트 참조 화면",
        "mypage_updated.png": "업데이트 전후 비교용으로 보이는 마이페이지 자산",
        "fault_report_updated.png": "과실비율 리포트 개별 화면 자산",
        "fine_report_updated.png": "과태료/범칙금 리포트 개별 화면 자산",
        "final-screen-plan-complete-updated.png": "전체 화면 계획 통합 이미지 자산",
    }
    if not asset_dir.exists():
        rows.append(["docs/assets/screen-design", "없음", "현재 작업 트리에 자산 디렉터리가 없습니다."])
        return rows
    for path in sorted(asset_dir.glob("*.png")):
        try:
            with PILImage.open(path) as img:
                size = f"{img.width} x {img.height}px"
        except Exception:
            size = "확인 실패"
        rows.append([path.name, size, purposes.get(path.name, "화면설계 참조 이미지")])
    return rows


def add_image(story: list, path: Path, caption: str, max_width: float, max_height: float) -> None:
    if not path.exists():
        return
    with PILImage.open(path) as img:
        width, height = img.size
    scale = min(max_width / width, max_height / height)
    story.append(Image(str(path), width=width * scale, height=height * scale))
    story.append(para(caption, "small"))
    story.append(Spacer(1, 4 * mm))


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    footer = "SKN27-FINAL-3Team 프로젝트 대화 및 진행상황 보고서"
    canvas.drawString(doc.leftMargin, 12 * mm, footer)
    canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm, f"{doc.page}")
    canvas.restoreState()


def build_story() -> list:
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    current_branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    status_short = run_git(["status", "--short", "--branch"])
    log = run_git(["log", "--oneline", "--decorate", "-n", "5"])
    branches = run_git(["branch", "-a", "--verbose", "--no-abbrev"])
    remote = run_git(["remote", "-v"])

    story: list = []
    story.append(raw_para("SKN27-FINAL-3Team<br/>프로젝트 대화 및 진행상황 보고서", "title"))
    story.append(
        para(
            f"작성 시각: {now}\n"
            f"작성 위치: {ROOT}\n"
            f"출력 파일: {OUTPUT}\n"
            f"사용 폰트: {FONT} (본문: {FONT_REGULAR_PATH}, 굵게: {FONT_BOLD_PATH})",
            "subtitle",
        )
    )

    story.append(heading("1. 보고서 작성 기준"))
    story += bullets(
        [
            "현재 Codex 스레드에서 확인 가능한 대화와 저장소에 남아 있는 문서, 브랜치, Git 상태만 근거로 작성했다.",
            "현재 스레드는 사용자의 PDF 작성 요청으로 시작되었고, 그 이전의 비공개 대화 원문은 이 환경에서 조회되지 않았다.",
            "따라서 과거 논의 내용은 현재 저장소 산출물과 문서 브랜치에 남아 있는 내용으로만 재구성했다.",
            "사용자가 제공한 AGENTS.md 작업 규칙에 따라 구현 문서를 source of truth로 두고, 불확실한 내용은 확정이 필요한 항목으로 분리했다.",
            "한글 깨짐 방지를 위해 TrueType 한글 폰트를 PDF에 직접 등록해 사용했다.",
        ]
    )

    story.append(heading("2. 현재 대화 요약"))
    story.append(
        table(
            [
                ["순서", "대화/작업", "확인 내용"],
                ["1", "사용자 요청", "현재 프로젝트에서 나눈 대화와 진행상황을 상세히 정리하고, 한글 글씨가 깨지지 않는 PDF 파일로 작성해 달라고 요청했다."],
                ["2", "작업 원칙 적용", "PDF 생성 작업에는 PDF 스킬을 사용하고, 저장소 문서와 Git 상태를 먼저 확인하는 방식으로 진행했다."],
                ["3", "자료 수집", "README, 화면설계서, 브랜치별 문서, Git 상태, 폰트 설치 상태, PDF 라이브러리 설치 상태를 확인했다."],
                ["4", "인코딩 확인", "PowerShell 기본 출력에서는 일부 README 한글이 깨져 보였으나 UTF-8 출력으로 다시 읽었을 때 정상 표시됨을 확인했다."],
                ["5", "작성 범위 결정", "현재 스레드 이전 대화 원문은 조회되지 않아, PDF에는 현재 대화와 저장소 산출물 기준의 프로젝트 진행상황을 구분해서 작성했다."],
            ],
            [18 * mm, 34 * mm, 123 * mm],
        )
    )

    story.append(heading("3. 저장소 현재 상태"))
    story.append(
        table(
            [
                ["항목", "내용"],
                ["작업 디렉터리", str(ROOT)],
                ["현재 브랜치", current_branch],
                ["원격 저장소", remote],
                ["최근 커밋", log],
                ["작업 트리 상태", status_short],
            ],
            [33 * mm, 142 * mm],
        )
    )
    story.append(para("현재 작업 트리에서 확인된 미추적 항목은 `docs/screen-design-specification.md`와 `docs/assets/`이다. 즉, 화면설계서와 화면 이미지 자산은 아직 Git에 커밋되지 않은 진행 중 산출물로 보는 것이 안전하다."))
    story.append(heading("브랜치 상태", 2))
    story.append(raw_para(f"<font name='{FONT}'>{text(branches)}</font>", "code"))

    story.append(heading("4. 프로젝트 구조"))
    story.append(
        table(
            [
                ["경로", "현재 의미", "현재 상태"],
                ["README.md", "프로젝트 루트 문서", "프로젝트명만 존재"],
                ["docs/", "문서 작성 공간", "README와 미추적 화면설계서 및 화면 이미지 자산 존재"],
                ["app/", "웹/앱 서비스 공간", "README만 존재"],
                ["ai/", "머신러닝 또는 딥러닝 파인튜닝/실험 공간", "README만 존재"],
                ["etl/", "데이터 수집 및 처리 공간", "README만 존재"],
                ["storage/", "저장소 정의 공간", "README만 존재"],
                ["test/", "테스트 또는 스터디 공간", "README만 존재"],
            ],
            [31 * mm, 74 * mm, 70 * mm],
        )
    )
    story.append(para("현 시점의 실제 구현 코드는 확인되지 않았고, 저장소는 문서화와 화면 설계 중심의 초기 단계다."))

    story.append(heading("5. 확인 가능한 프로젝트 목표"))
    story += bullets(
        [
            "프로젝트명은 `교통분쟁 AI: 과실비율·범칙금/과태료 분석 및 리포팅 서비스`로 정리되어 있다.",
            "사용자가 교통사고 과실비율 또는 과태료/범칙금 이슈를 입력하거나 자료를 업로드하면, RAG 검색과 AI 분석을 통해 결과, 유사 사례, 관련 기준, 후속 행동, 리포트 또는 이의신청서 초안을 제공하는 것이 목표다.",
            "중간 발표 기준은 2026-07-14, 최종 마무리 기준은 2026-08-04로 문서화되어 있다.",
            "관리자 화면은 MVP 사용자 유형에 포함하지 않고, 일반 사용자/신규 사용자/기존 사용자 중심으로 정의되어 있다.",
            "한글 표시와 UTF-8 인코딩은 기능 요구사항과 비기능 요구사항 모두에서 중요한 기준으로 반복 확인된다.",
        ]
    )

    story.append(heading("6. MVP 및 도메인 범위"))
    story.append(
        table(
            [
                ["구분", "포함 도메인", "현재 문서상 의미"],
                ["Core MVP", "범칙금/과태료 이의신청", "고지 상황 입력, 기한/감경 가능성/이의신청 사유 후보/신청서 초안을 제공하는 핵심 흐름"],
                ["MVP 또는 Beta", "과실비율 RAG", "사고경위와 보험사 제시 비율을 입력받아 과실비율 범위, 근거 사례, 대응 스크립트를 제공하는 흐름"],
                ["확장 Beta", "합의금 체크", "보험사 제시금에서 항목 누락 가능성을 체크하고 문서 초안을 제공하는 확장 흐름"],
                ["Research/POC", "Vision/DL/블랙박스", "영상 또는 라벨 기반으로 사고상황 후보를 구조화하고 사용자 검토 후 RAG 입력으로 넘기는 POC"],
                ["공통 기반", "홈, 분석 Job, 데이터 출처, 증분 수집, RAG 계약, 보관정책", "도메인별 판단 로직과 공통 인프라를 분리하는 기반"],
            ],
            [28 * mm, 45 * mm, 102 * mm],
        )
    )
    story.append(para("주의할 점은 Vision/DL 영역이 과실비율 자동 판정이 아니라 상황 후보 구조화 POC로 제한되어 있다는 점이다. 이 경계는 구현 시 반드시 유지해야 한다."))

    story.append(heading("7. 현재 화면설계서 진행상황"))
    story += bullets(
        [
            "`docs/screen-design-specification.md` 문서가 2026-06-18 기준 v0.1로 작성되어 있다.",
            "작성 기준은 요구사항 정의서 v0.4와 업데이트 화면 이미지 2건으로 명시되어 있다.",
            "문서의 직접 목적은 프론트엔드 구현자가 화면 구조를 추측하지 않고, 마이페이지/과실비율 리포트/과태료·범칙금 대응 리포트를 요구사항 정의서 기준으로 구현할 수 있도록 하는 것이다.",
            "파일 인코딩은 UTF-8, HTML에는 `<meta charset=\"UTF-8\">`, 루트 언어는 `lang=\"ko\"`, 폰트 스택은 Pretendard, Noto Sans KR, Apple SD Gothic Neo, Malgun Gothic, sans-serif 순으로 권장되어 있다.",
        ]
    )
    story.append(
        table(
            [
                ["확인 화면", "요구사항 매핑", "현재 반영 상태", "후속 조치"],
                ["마이페이지", "UI-MY-001, REQ-MY-001~007", "등록 사건, 기한 임박, 생성 문서, 최근 분석 이력 구조가 명확해짐", "화면설계서에 확정 반영"],
                ["사고 과실비율 분석 리포트", "UI-REPORT-002, REQ-REPORT-002~004", "기존 `리포팅 상세 분석` 화면명이 실제 화면에서 구체화됨", "요구사항 정의서 화면명 후속 업데이트 필요"],
                ["과태료·범칙금 대응 리포트", "UI-MY-004, REQ-FINE-001~013, REQ-REPORT-005", "과실비율 리포트와 별도 화면임을 재확인", "API 정의서에서 별도 endpoint 필요"],
            ],
            [37 * mm, 45 * mm, 63 * mm, 30 * mm],
        )
    )

    story.append(heading("8. 화면 목록과 남은 화면설계"))
    story.append(
        table(
            [
                ["Screen ID", "화면명", "MVP 포함", "상태"],
                ["UI-MY-001", "마이페이지", "포함", "화면설계서에 상세 구조 반영"],
                ["UI-HIS-001", "과거 이력", "포함", "필터, 검색, 페이지네이션, 상세 진입 기준 확정 필요"],
                ["UI-REPORT-FAULT-001", "사고 과실비율 분석 리포트", "포함", "사고 개요, 자료 현황, AI 분석 결과, 판단 근거, 핵심 쟁점, 유사 판례, 후속 조치 반영"],
                ["UI-REPORT-FINE-001", "과태료·범칙금 대응 리포트", "포함", "OCR, 처분 결과, 이의제기 가능성, 필요 증거, 법령/판례, 예상 결과, 이의신청서 초안 반영"],
                ["UI-CHAT-001", "범칙금 챗봇", "포함", "별도 화면설계 필요"],
                ["UI-CHAT-002", "보험 챗봇", "포함", "별도 화면설계 필요"],
            ],
            [35 * mm, 45 * mm, 24 * mm, 71 * mm],
        )
    )
    story.append(
        table(
            [
                ["우선순위", "남은 작업"],
                ["높음", "과거 이력 화면의 필터, 검색, 페이지네이션, 상세 진입 기준 확정"],
                ["높음", "진단하기 화면에서 과실비율 진단과 과태료·범칙금 진단 입력 폼 분리 여부 확정"],
                ["보통", "범칙금 챗봇과 보험 챗봇의 대화 UI, 근거 표시, 리포트 이동 버튼 확정"],
                ["보통", "판례/보험사 사례 전체 목록의 검색, 필터, 문서 상세, PDF 다운로드, 원문 보기 UI 확정"],
                ["보통", "공통 오류, 빈 데이터, 권한 없음, OCR 실패, 초안 생성 실패 화면 확정"],
            ],
            [28 * mm, 147 * mm],
        )
    )

    story.append(heading("9. 요구사항 정의서 진행상황"))
    story.append(para("`docs-project-scope-and-role-matrix` 브랜치에는 `docs/traffic_dispute_ai_requirements_definition.md`가 있으며, 문서 버전은 v0.4로 확인된다. 현재 브랜치에는 병합되어 있지 않으므로, PDF에서는 별도 브랜치 산출물로 분리해 기록한다."))
    story.append(
        table(
            [
                ["영역", "주요 요구사항"],
                ["인증/회원가입", "Google 간편로그인, 일반 회원가입 제외, 신규/기존 사용자 분기, 로그아웃, 사용자 기본 정보, 약관 동의 이력"],
                ["마이페이지/과거 이력", "등록 사건 수, 기한 임박 사건, 생성 문서 수, 최근 분석 이력, 유형/기간 필터, 검색, 상세보기, 페이지네이션"],
                ["과실비율", "분석 요약 카드, 정성 결과 표시, 사고 정보, 업로드 자료, AI 분석 요약, 핵심 쟁점, 관련 기준/유사 사례, 후속 행동"],
                ["과태료/범칙금", "OCR 결과, 고지 정보, OCR 상태, 판단 결과, 처분 단계, 이의제기 가능성, 부족 서류, 추가 증거, 법령/판례, 이의신청서 초안"],
                ["챗봇/리포팅", "범칙금 챗봇, 보험 챗봇, 근거 포함 답변, 추천 조치, 리포트 페이지 유형 분리, PDF 저장/출력/공유"],
                ["데이터/RAG/ML/DL/Agent", "범칙금 데이터, 보험 텍스트, 영상 데이터, RAG 저장, 베이스라인 분석, 멀티에이전트 응답 포맷"],
                ["Backend/DB/Ops", "Django API, DB 연동, 파일 저장, 예외 처리, 로그, AWS staging/production, 환경변수 분리, README 작성"],
            ],
            [36 * mm, 139 * mm],
        )
    )

    story.append(heading("10. 일정과 인수 기준"))
    story.append(
        table(
            [
                ["기간", "목표"],
                ["2026-06-16 ~ 2026-06-22", "스키마/API/RAG 구조 고정"],
                ["2026-06-23 ~ 2026-06-29", "데이터 파이프라인 및 RAG 저장 MVP"],
                ["2026-06-30 ~ 2026-07-06", "ML/DL 베이스라인 및 Agent/Front 통합"],
                ["2026-07-07 ~ 2026-07-13", "중간 발표용 MVP 동결 및 AWS staging 배포"],
                ["2026-07-14", "중간 발표"],
                ["2026-07-15 ~ 2026-07-27", "피드백 반영 및 품질 고도화"],
                ["2026-07-28 ~ 2026-08-03", "최종 QA, production 배포, 문서화"],
                ["2026-08-04", "최종 마무리"],
            ],
            [55 * mm, 120 * mm],
        )
    )
    story += bullets(
        [
            "중간 발표 인수 기준은 로그인 진입, 마이페이지, 과거 이력, 과실비율 분석 상세, 리포팅 상세, 과태료/범칙금 상세, 샘플 RAG 검색, Django API와 프론트의 최소 End-to-End 연결, AWS staging 시연 가능 상태다.",
            "최종 인수 기준은 로그인부터 리포트 조회까지의 주요 기능 정상 동작, 데이터 수집/전처리 파이프라인, ML/DL 결과의 RAG 저장 및 Agent 근거 사용, production 배포, README/API/DB/파이프라인/배포 문서 제출이다.",
        ]
    )

    story.append(heading("11. 역할 및 담당 구분"))
    story.append(para("역할/범위 문서에 따르면 홈 화면 직접 이슈는 `#14 feat-common-home-entrypoints`이며 담당자는 `leejaegang27`로 기록되어 있다. 다만 여러 epic이 `전원`으로 배정되어 있어 실무 owner는 하위 이슈 기준으로 추가 확정이 필요하다."))
    story.append(
        table(
            [
                ["영역", "현재 담당 또는 상태"],
                ["역할/범위 문서, WBS/산출물 문서, MVP 화면/프로세스 문서", "hi20260204-maker 담당으로 확인"],
                ["요구사항 Gap/Risk 문서", "leejaegang27, techshin31, hi20260204-maker, ohjuheecode 담당으로 확인"],
                ["홈 진입점", "leejaegang27 담당으로 확인"],
                ["분석 Job 모델", "ohjuheecode 담당으로 확인"],
                ["데이터 출처 저장 구조/증분 수집", "workzion2, hi20260204-maker 담당으로 확인"],
                ["도메인별 case schema 분리", "workzion2 담당으로 확인"],
                ["RAG chunk/index 계약", "leejaegang27, workzion2, ohjuheecode 담당으로 확인"],
                ["범칙금, 과실비율, 합의금, Vision/DL, 법령/과실비율 수집", "실무 owner 확정 필요"],
            ],
            [58 * mm, 117 * mm],
        )
    )

    story.append(heading("12. AI-Hub/Vision-DL POC 진행상황"))
    story += bullets(
        [
            "별도 브랜치의 `Report.md`에는 AI-Hub 승인형 데이터 상세 리포트가 작성되어 있다.",
            "1순위 후보 데이터셋은 `사고위험 환경에서의 운전습관 데이터`로 정리되어 있다.",
            "이 데이터는 운전자 행동 영상, 주행 환경 영상, CAN JSON, 이미지, 자연어 라벨을 포함하므로 주요 장면 추출, 사고 전후 상황 요약, 위험유형 후보 생성, `insurance_video` RAG 저장에 적합하다고 평가되어 있다.",
            "2순위 후보는 `실도로 위험상황 시나리오 기반 시뮬레이션 데이터`이며, 위험상황 taxonomy와 시나리오 기반 테스트 케이스 설계 보조로 정리되어 있다.",
            "금지 범위는 AI-Hub 데이터를 Git에 커밋하는 것, 원본을 승인 없이 공유하는 것, 사용자 영상을 동의 없이 학습에 사용하는 것, DL 결과로 과실비율을 자동 산정하는 것이다.",
        ]
    )

    story.append(heading("13. 화면 자산 현황"))
    story.append(table(image_info(), [57 * mm, 35 * mm, 83 * mm]))
    story.append(PageBreak())
    story.append(heading("14. 참조 화면 미리보기"))
    story.append(para("아래 이미지는 현재 미추적 자산에 포함된 화면설계 참조 이미지다. PDF 본문 텍스트와 별개로, 원본 PNG 자체에 포함된 화면 글자는 이미지 품질에 의존한다."))
    add_image(
        story,
        ROOT / "docs" / "assets" / "screen-design" / "mypage-updated.png",
        "마이페이지 업데이트 화면: `docs/assets/screen-design/mypage-updated.png`",
        max_width=175 * mm,
        max_height=105 * mm,
    )
    add_image(
        story,
        ROOT / "docs" / "assets" / "screen-design" / "report-pages-updated.png",
        "과실비율 리포트 및 과태료·범칙금 대응 리포트 화면: `docs/assets/screen-design/report-pages-updated.png`",
        max_width=175 * mm,
        max_height=105 * mm,
    )

    story.append(heading("15. 현재 리스크와 확정 필요 사항"))
    story.append(
        table(
            [
                ["구분", "내용", "권장 조치"],
                ["대화 원문 제한", "현재 스레드 이전의 대화 원문은 조회되지 않음", "향후 중요한 결정은 문서 또는 이슈에 남겨 source of truth로 관리"],
                ["미추적 산출물", "화면설계서와 이미지 자산이 Git에 커밋되지 않음", "검토 후 커밋 또는 PR로 추적 가능하게 관리"],
                ["브랜치 분산", "요구사항/역할 문서는 별도 브랜치에 있고 현재 브랜치에는 없음", "문서 병합 순서와 충돌 해결 기준 확정"],
                ["MVP 경계", "Core MVP, Beta, POC의 표현과 범위가 팀 합의로 고정되어야 함", "중간 발표 기준에서 반드시 시연할 범위를 명확히 확정"],
                ["API 분리", "과실비율 리포트와 과태료·범칙금 리포트가 별도 endpoint를 필요로 함", "API 정의서에서 리포트 타입과 endpoint 계약 확정"],
                ["OCR/OAuth/ML-DL", "실제 구현 범위와 목업 허용 범위가 일부 오픈 이슈로 남아 있음", "2026-06-22 또는 2026-06-29 이전 결정 필요"],
                ["법적 고지", "AI 분석은 참고용이며 법적 판단 확정으로 보이면 위험함", "모든 결과 화면과 PDF/리포트에 제한 고지 유지"],
            ],
            [29 * mm, 76 * mm, 70 * mm],
        )
    )

    story.append(heading("16. 확인에 사용한 주요 명령"))
    story.append(
        table(
            [
                ["목적", "명령", "결과"],
                ["저장소 상태", "git status --short --branch", "현재 브랜치와 미추적 화면설계서/이미지 자산 확인"],
                ["커밋 이력", "git log --oneline --decorate -n 30", "초기 커밋 수준과 현재 HEAD 확인"],
                ["브랜치 확인", "git branch -a --verbose --no-abbrev", "문서 브랜치와 별도 요구사항 문서 커밋 확인"],
                ["문서 읽기", "Get-Content -Raw -Encoding UTF8 ...", "한글 문서 내용을 UTF-8로 정상 확인"],
                ["브랜치 문서 읽기", "git show docs-project-scope-and-role-matrix:...", "요구사항 정의서, 역할/범위 문서, AI-Hub 리포트 확인"],
                ["폰트 확인", "Get-ChildItem C:\\Windows\\Fonts | Where-Object ...", "Noto Sans KR, Malgun Gothic, Nanum Gothic 설치 확인"],
                ["PDF 라이브러리 확인", "python -c \"import reportlab, pdfplumber, pypdf\"", "PDF 생성/검증 라이브러리 import 성공"],
            ],
            [32 * mm, 78 * mm, 65 * mm],
        )
    )

    story.append(heading("17. 결론"))
    story += bullets(
        [
            "현재 프로젝트는 구현 코드보다 요구사항, 역할, 화면설계, 데이터/POC 검토 문서가 먼저 정리되는 초기 설계 단계다.",
            "현재 브랜치의 핵심 진행물은 화면설계서 v0.1과 화면 이미지 자산이며, 아직 Git에 커밋되지 않았다.",
            "별도 문서 브랜치에는 요구사항 정의서 v0.4, 프로젝트 역할/MVP 범위 문서, AI-Hub 승인형 데이터 리포트가 존재한다.",
            "다음 우선순위는 문서 산출물 병합 기준 확정, 과거 이력/진단하기/챗봇/판례 목록 세부 화면설계 보완, API/DB/RAG 계약 확정, 그리고 OCR/OAuth/ML-DL 목업 허용 범위 확정이다.",
        ]
    )

    return story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title="SKN27-FINAL-3Team 프로젝트 대화 및 진행상황 보고서",
        author="Codex",
        subject="프로젝트 대화 및 진행상황",
    )
    doc.build(build_story(), onFirstPage=on_page, onLaterPages=on_page)
    print(OUTPUT)


if __name__ == "__main__":
    main()
