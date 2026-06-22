from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path("D:/dev/Project/SKN27-FINAL-3Team")
OUTPUT_DIR = ROOT / "output" / "pdf"
ISSUE_JSON = ROOT / "tmp" / "pdf_wbs_req" / "github_issues_compact.json"
TODAY = "2026-06-22"


def register_fonts() -> tuple[str, str]:
    """Windows 기본 한글 폰트를 등록한다."""
    regular = Path("C:/Windows/Fonts/malgun.ttf")
    bold = Path("C:/Windows/Fonts/malgunbd.ttf")
    if not regular.exists() or not bold.exists():
        raise FileNotFoundError("Malgun Gothic font files were not found.")
    pdfmetrics.registerFont(TTFont("Malgun", str(regular)))
    pdfmetrics.registerFont(TTFont("Malgun-Bold", str(bold)))
    return "Malgun", "Malgun-Bold"


FONT, FONT_BOLD = register_fonts()


def load_issues() -> list[dict]:
    return json.loads(ISSUE_JSON.read_text(encoding="utf-8-sig"))


ISSUES = load_issues()
REAL_ISSUES = [item for item in ISSUES if not item.get("is_pull_request")]
PRS = [item for item in ISSUES if item.get("is_pull_request")]
ISSUE_BY_NO = {int(item["number"]): item for item in ISSUES}


def issue_state(numbers: Iterable[int]) -> str:
    states = []
    for number in numbers:
        item = ISSUE_BY_NO.get(number)
        if item:
            states.append(f"#{number} {item['state']}")
        else:
            states.append(f"#{number} 미확인")
    return ", ".join(states)


def p(text: object, style: ParagraphStyle) -> Paragraph:
    value = "" if text is None else str(text)
    return Paragraph(value.replace("\n", "<br/>"), style)


styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "TitleKo",
    parent=styles["Title"],
    fontName=FONT_BOLD,
    fontSize=17,
    leading=22,
    alignment=TA_CENTER,
    spaceAfter=8,
)
SUBTITLE = ParagraphStyle(
    "SubtitleKo",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=8,
    leading=11,
    alignment=TA_CENTER,
    textColor=colors.HexColor("#555555"),
    spaceAfter=8,
)
SECTION = ParagraphStyle(
    "SectionKo",
    parent=styles["Heading2"],
    fontName=FONT_BOLD,
    fontSize=11,
    leading=14,
    spaceBefore=5,
    spaceAfter=5,
)
BODY = ParagraphStyle(
    "BodyKo",
    parent=styles["Normal"],
    fontName=FONT,
    fontSize=8,
    leading=11,
    alignment=TA_LEFT,
)
BODY_SMALL = ParagraphStyle(
    "BodySmallKo",
    parent=BODY,
    fontSize=7,
    leading=9,
)
HEADER = ParagraphStyle(
    "HeaderKo",
    parent=BODY_SMALL,
    fontName=FONT_BOLD,
    alignment=TA_CENTER,
    textColor=colors.black,
)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(colors.HexColor("#666666"))
    page_text = f"{doc.title} | page {doc.page}"
    canvas.drawRightString(doc.pagesize[0] - 12 * mm, 8 * mm, page_text)
    canvas.restoreState()


def make_table(
    rows: list[list[object]],
    col_widths: list[float],
    *,
    repeat_rows: int = 1,
    header_rows: int = 1,
    small: bool = True,
) -> Table:
    body_style = BODY_SMALL if small else BODY
    converted = []
    for r_idx, row in enumerate(rows):
        style = HEADER if r_idx < header_rows else body_style
        converted.append([p(cell, style) for cell in row])
    table = Table(converted, colWidths=col_widths, repeatRows=repeat_rows, splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), FONT),
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#D9D9D9")),
                ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#4A4A4A")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, header_rows - 1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def build_summary_story(title: str, doc_kind: str) -> list:
    issue_count = len(REAL_ISSUES)
    open_issues = sum(1 for item in REAL_ISSUES if item["state"] == "open")
    closed_issues = issue_count - open_issues
    milestone_counts = Counter(item.get("milestone") or "(없음)" for item in REAL_ISSUES)
    label_counts = Counter(label for item in REAL_ISSUES for label in item.get("labels", []))
    newest = sorted(ISSUES, key=lambda x: x.get("updated_at") or "", reverse=True)[:8]

    story = [
        Paragraph(title, TITLE),
        Paragraph(
            f"작성일 {TODAY} | 기준 저장소: SKNETWORKS-FAMILY-AICAMP/SKN27-FINAL-3Team | 산출물: {doc_kind}",
            SUBTITLE,
        ),
        Paragraph("분석 기준", SECTION),
        make_table(
            [
                ["항목", "내용"],
                ["로컬 기준 브랜치", "docs-wbs-owner-deliverable-plan"],
                ["최신 원격 기준", "origin/dev: PR #46 폴더 스캐폴딩 병합, origin/feat/fine-notice-ocr-intake-flow: #23 구현 초안 진행"],
                ["GitHub 이슈", f"총 {issue_count}개 이슈: open {open_issues}개, closed {closed_issues}개. PR {len(PRS)}개는 별도 집계"],
                ["마일스톤", ", ".join(f"{k} {v}건" for k, v in milestone_counts.items())],
                ["주요 라벨", ", ".join(f"{k} {v}" for k, v in label_counts.most_common(8))],
                ["주의", "Project 보드는 별도 권한 범위라 이 문서는 Issues, PR, branch, local docs 기준으로 작성"],
            ],
            [42 * mm, 230 * mm],
            small=False,
        ),
        Spacer(1, 5 * mm),
        Paragraph("최신 업데이트 상위 항목", SECTION),
        make_table(
            [["No", "제목", "상태", "수정일", "URL"]]
            + [
                [
                    f"#{item['number']}",
                    item["title"],
                    item["state"],
                    item.get("updated_at", "")[:10],
                    item["html_url"],
                ]
                for item in newest
            ],
            [14 * mm, 88 * mm, 18 * mm, 24 * mm, 128 * mm],
        ),
        Spacer(1, 5 * mm),
        Paragraph("프로젝트 구조 판단", SECTION),
        make_table(
            [
                ["영역", "현재 확인 내용", "판단"],
                ["app", "현재 브랜치에는 화면설계 HTML 산출물이 존재, 최신 dev에는 app/api, app/services, app/web 스캐폴딩 존재", "UI 시연물과 실제 API 구현 경계 정리 필요"],
                ["ai", "최신 dev는 supervisor/agents/schemas 뼈대, feature 브랜치는 fine_notice_analysis 일부 구현", "Agent별 패키지 경계는 형성 중"],
                ["etl/storage", "법률, 과실비율, fine_rules, vision_manifest, rag/schema 디렉터리 기준 존재", "데이터 계약과 적재 검증 산출물 필요"],
                ["docs/output/tmp", "WBS, 화면설계, 이슈 분석, PDF/엑셀 산출물이 다수 존재", "문서 산출물은 진행됐으나 dev와 문서 브랜치 병합 전략 필요"],
                ["tests", "feature 브랜치에 OCR 단위 테스트가 존재", "import 경로와 실제 패키지 경로 일치 여부 검증 필요"],
            ],
            [28 * mm, 160 * mm, 84 * mm],
        ),
        PageBreak(),
    ]
    return story


REQUIREMENT_ROWS = [
    ["기능", "기획/관리", "WBS/Issue", "REQ-PLAN-001", "최신 역할 기준으로 WBS, 담당자, milestone을 정리한다.", "2026-07-14 중간, 2026-08-04 최종 기준 반영", issue_state([2, 10, 11, 12, 13])],
    ["기능", "UI/UX", "홈/로그인", "REQ-UI-001", "홈 화면, 로그인 모달, 로그인 후 챗봇 진입 흐름을 제공한다.", "화면설계 문서와 HTML 시연물 기준", issue_state([12, 14])],
    ["기능", "UI/UX", "챗봇", "REQ-UI-002", "챗봇 화면에서 과태료·범칙금, 과실비율, 법률 질문 흐름으로 진입한다.", "Supervisor routing과 연결", issue_state([12, 29])],
    ["기능", "Supervisor", "라우팅", "REQ-SUP-001", "입력 유형에 따라 고지서 OCR, 법률 검색, 텍스트 ML, Vision, 이의신청서 노드를 호출한다.", "추가 질문 조건 포함", issue_state([22, 29, 40])],
    ["기능", "Supervisor", "결과 통합", "REQ-SUP-002", "개별 Agent 결과 envelope을 통합해 최종 답변을 생성한다.", "Agent가 최종 자연어 답변을 확정하지 않음", issue_state([22, 29, 41])],
    ["기능", "과태료", "고지서 OCR", "REQ-FINE-001", "고지서 이미지를 OCR로 구조화 JSON으로 추출한다.", "feature 브랜치에 GPT-4o Vision 기반 초안 존재", issue_state([23])],
    ["기능", "과태료", "OCR 신뢰도", "REQ-FINE-002", "OCR 결과를 success/degraded/partial/failed로 평가하고 fallback을 제공한다.", "critical/important/optional 필드 분리", issue_state([23, 28])],
    ["보안", "개인정보", "마스킹", "REQ-FINE-003", "주민등록번호와 차량번호를 마스킹하고 OCR 완료 후 원본 이미지를 state에서 제거한다.", "프롬프트와 코드 레벨 이중 처리", issue_state([23, 41])],
    ["기능", "과태료", "룰/매핑", "REQ-FINE-004", "과태료·범칙금·벌칙 분석용 룰/매핑 데이터를 구성한다.", "법률 원문 DB와 중복되지 않는 분석용 데이터", issue_state([24])],
    ["기능", "과태료", "상세보기", "REQ-FINE-005", "OCR 결과, 처분 단계, 부족 서류, 필요 증거를 상세 화면/응답 구조로 제공한다.", "사용자 확인 가능한 결과 구조", issue_state([25])],
    ["기능", "과태료", "법률 근거", "REQ-FINE-006", "고지서 분석 결과에 관련 법령/행정 기준 근거를 연결한다.", "법률 검색 input/output 구체화 필요", issue_state([26, 20])],
    ["기능", "이의신청", "가능성 판단", "REQ-OBJ-001", "고지서 단계와 기한을 기준으로 이의제기 가능 여부를 판단한다.", "feature 브랜치에 decision.py 초안 존재", issue_state([27])],
    ["기능", "이의신청", "문서 초안", "REQ-OBJ-002", "분석 결과와 법률 근거를 받아 이의신청서 초안을 생성한다.", "부족 정보는 추가 질문", issue_state([27])],
    ["변경", "이의신청", "재시도", "REQ-OBJ-003", "이의판단 결과 확인 후 retry 요청 시 OCR부터 재시작할 수 있게 한다.", "origin/feat update_require.md의 변경 요구", "검토 필요"],
    ["데이터", "법률", "출처", "REQ-LAW-001", "도로교통법, 시행령, 시행규칙, 고시/행정 기준 출처를 확정한다.", "판례가 아닌 법률 계열 데이터", issue_state([20])],
    ["데이터", "법률", "전처리", "REQ-LAW-002", "조문, 항, 호, 별표, 벌점, 금액, 예외 조건을 구조화한다.", "HTML/중복/깨진 텍스트 제거", issue_state([20])],
    ["데이터", "법률", "DB 적재", "REQ-LAW-003", "법률 데이터를 DB에 적재하고 건수, 실패, 누락, 중복을 검증한다.", "증분 수집 추적과 연결", issue_state([16, 17, 20])],
    ["데이터", "법률", "RAG metadata", "REQ-LAW-004", "law_name, article, effective_date, source_url 등 근거 metadata를 보존한다.", "Supervisor와 과태료 흐름에서 사용", issue_state([22, 26])],
    ["데이터", "과실비율", "유튜브 자막", "REQ-FAULT-001", "유튜브 자막 기반 사고 사례 원문과 metadata를 수집한다.", "공식 근거가 아닌 caption_case로 분리", issue_state([1])],
    ["데이터", "과실비율", "판례/사례", "REQ-FAULT-002", "판례, 유튜브 자막, 과실비율심의사례 데이터를 수집·전처리한다.", "신뢰도별 source_type 구분 필요", issue_state([21])],
    ["기능", "과실비율", "텍스트 처리", "REQ-FAULT-003", "경위서/OCR 결과와 사고 설명을 ML/RAG 입력으로 정규화한다.", "사고 유형, 쟁점, 증거 태그 생성", issue_state([30, 31])],
    ["기능", "과실비율", "ML/RAG", "REQ-FAULT-004", "사고 유형 분류, 요약, 키워드/태그, 유사 사례 추천을 제공한다.", "과실비율 확정이 아닌 근거/추천값", issue_state([30, 33])],
    ["기능", "과실비율", "결과 표시", "REQ-FAULT-005", "과실비율을 단정하지 않고 범위, 쟁점, 유사 사례 중심으로 표시한다.", "법률/책임 단정 금지 guardrail", issue_state([32, 41])],
    ["데이터", "Vision", "데이터셋", "REQ-VISION-001", "이미지/영상 데이터셋 목록과 manifest를 작성한다.", "파일 출처, 사고유형, 개인정보 처리 기준", issue_state([36, 37])],
    ["기능", "Vision", "전처리", "REQ-VISION-002", "영상 frame/key frame 추출과 장면 요약을 수행한다.", "DL/RAG 입력 가능한 구조", issue_state([37, 38])],
    ["기능", "Vision", "분석 Agent", "REQ-VISION-003", "사고 장면 후보, 객체/상황 분석, confidence를 반환한다.", "책임 확정이 아닌 참고 근거", issue_state([38, 39])],
    ["기능", "Vision", "결과 스키마", "REQ-VISION-004", "Vision 결과를 Supervisor가 병합 가능한 text/evidence schema로 제공한다.", "key_frames, scene_summary, limitations 포함", issue_state([22, 38])],
    ["공통", "데이터", "Source registry", "REQ-DATA-001", "데이터 출처 registry와 원천 metadata를 관리한다.", "수집/전처리/적재 추적성", issue_state([16])],
    ["공통", "데이터", "증분 수집", "REQ-DATA-002", "증분 ingestion 실행 이력과 실패 이력을 추적한다.", "run tracking 필요", issue_state([17])],
    ["공통", "데이터", "도메인 스키마", "REQ-DATA-003", "과태료, 법률, 과실비율, Vision 도메인 스키마를 분리한다.", "패키지 경계와 DB 경계 명확화", issue_state([18])],
    ["공통", "분석", "Job 모델", "REQ-JOB-001", "분석 작업 상태를 공통 Job 모델로 관리한다.", "업로드, 분석, 결과 조회 연결", issue_state([15])],
    ["품질", "통합", "Cross-MVP", "REQ-QA-001", "고지서, 사고 설명, 영상/이미지, 리포트 흐름의 통합 시나리오를 검증한다.", "최소 3개 이상 MVP 시나리오 필요", issue_state([40])],
    ["품질", "법률 AI", "Guardrail", "REQ-QA-002", "법률 단정, 과실비율 수치 단정, 제출 성공 보장 표현을 금지한다.", "면책/주의 문구 포함", issue_state([41])],
    ["운영", "배포", "Staging/Release", "REQ-OPS-001", "중간 발표 staging과 최종 release readiness를 준비한다.", "README/API/DB/파이프라인 문서 포함", issue_state([42, 43])],
    ["문서", "거버넌스", "보존 정책", "REQ-DOC-001", "데이터 거버넌스와 보존/삭제 정책을 문서화한다.", "최종 단계 문서", issue_state([19])],
    ["범위", "Scope-out", "합의금", "REQ-SCOPE-001", "합의금 관련 기능은 현재 핵심 MVP에서 제외하고 추적성만 보존한다.", "삭제가 아니라 scope-out", issue_state([6, 34, 35])],
    ["리스크", "브랜치", "병합 전략", "REQ-RISK-001", "문서 브랜치와 최신 dev/feature 브랜치의 산출물 차이를 병합 전 확인한다.", "현재 브랜치와 origin/dev 간 큰 차이 존재", "검증 필요"],
    ["리스크", "테스트", "import 경로", "REQ-RISK-002", "feature 브랜치 테스트 import 경로가 실제 패키지 경로와 일치하는지 검증한다.", "tests/test_ocr.py 일부 patch 경로 검토 필요", "검증 필요"],
    ["변경", "과태료", "fine_type", "REQ-RISK-003", "과태료와 범칙금 이의신청 방법/기한을 구분하는 fine_type 필드를 추가 검토한다.", "update_require.md에서 수정 필요로 명시", "검토 필요"],
]


WBS_ROWS = [
    ["001", "역할/WBS 정리", "최신 회의 기준 역할, 담당자, milestone 재정렬", "hi20260204-maker", "완료", "2026-06-18", "2026-06-21", "높음"],
    ["002", "GitHub Issue 관리", "이슈 #1~#44 재정리, scope-out 항목 종료", "hi20260204-maker", "진행중", "2026-06-18", "2026-06-22", "높음"],
    ["003", "Project 구조", "origin/dev 폴더 스캐폴딩 병합 확인", "hi20260204-maker", "완료", "2026-06-19", "2026-06-22", "높음"],
    ["004", "요구사항 정의", "GitHub 이슈와 문서 기준 요구사항 정의서 PDF 작성", "hi20260204-maker", "완료", "2026-06-22", "2026-06-22", "높음"],
    ["005", "WBS 산출물", "제공 WBS 양식 컬럼 기준 PDF 작성", "hi20260204-maker", "완료", "2026-06-22", "2026-06-22", "높음"],
    ["006", "화면 흐름", "홈, 로그인, 챗봇, 과태료 결과, 과실비율 결과 화면 흐름 정리", "hi20260204-maker", "진행중", "2026-06-18", "2026-07-05", "높음"],
    ["007", "Supervisor 라우팅", "입력 유형별 Agent 호출 조건과 추가 질문 조건 정의", "hi20260204-maker", "진행중", "2026-06-22", "2026-07-05", "높음"],
    ["008", "Agent 결과 계약", "공통 envelope과 노드별 structured_result 정의", "전원", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["009", "고지서 OCR schema", "OCRResult와 critical/important/optional 필드 확정", "workzion2", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["010", "OCR 구현 초안", "GPT-4o Vision OCR, evaluator, masking 구현 초안", "workzion2", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["011", "OCR fallback", "success/degraded/partial/failed별 사용자 입력 fallback", "workzion2", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["012", "개인정보 마스킹", "주민등록번호·차량번호 마스킹 및 이미지 state 제거", "workzion2", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["013", "과태료 룰/매핑", "과태료·범칙금·벌칙 분석용 룰/매핑 데이터 정의", "workzion2", "진행중", "2026-06-22", "2026-07-05", "높음"],
    ["014", "과태료 상세보기", "처분 단계, 부족 서류, 필요 증거 결과 구조", "workzion2", "진행중", "2026-06-29", "2026-07-13", "높음"],
    ["015", "법률 근거 연결", "고지서 위반 유형을 법률 검색 input으로 연결", "workzion2, techshin31", "진행중", "2026-06-29", "2026-07-13", "높음"],
    ["016", "고지서 샘플 검증", "SAMPLE-01~06 일반 분석/법률 근거 포함 분석 비교", "workzion2", "예정", "2026-07-06", "2026-07-13", "높음"],
    ["017", "이의판단", "기한/단계 기준 이의 가능 여부 판단", "hi20260204-maker, workzion2", "진행중", "2026-06-29", "2026-07-13", "높음"],
    ["018", "이의신청서 초안", "분석 결과와 법률 근거 기반 초안 생성 노드", "hi20260204-maker", "예정", "2026-06-29", "2026-07-13", "높음"],
    ["019", "법률 데이터 source", "도로교통법/시행령/시행규칙/고시 출처 확정", "techshin31", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["020", "법률 전처리", "조문/항/호/별표/벌점/금액/예외 조건 구조화", "techshin31", "예정", "2026-06-22", "2026-07-05", "높음"],
    ["021", "법률 DB 적재", "법률 데이터 DB 적재 및 적재 검증 로그", "techshin31", "예정", "2026-06-29", "2026-07-13", "높음"],
    ["022", "법률 RAG metadata", "law_name, article, effective_date, source_url 보존", "techshin31", "예정", "2026-06-29", "2026-07-13", "높음"],
    ["023", "과실비율 자막 데이터", "유튜브 자막 기반 사고 사례 원천/metadata 수집", "leejaegang27", "진행중", "2026-06-22", "2026-07-05", "보통"],
    ["024", "판례/심의사례 데이터", "과실비율 판례와 심의사례 수집·전처리", "leejaegang27", "진행중", "2026-06-22", "2026-07-05", "높음"],
    ["025", "경위서/OCR 텍스트", "사고 설명 텍스트 정제와 ML/RAG 입력 정규화", "leejaegang27", "예정", "2026-06-22", "2026-06-28", "높음"],
    ["026", "텍스트 ML 베이스라인", "사고 유형 분류, 요약, 키워드/태그, 유사 사례 추천", "leejaegang27", "진행중", "2026-06-29", "2026-07-13", "높음"],
    ["027", "판례 Agent schema", "판례/사례 검색 결과 evidence schema 정의", "leejaegang27", "예정", "2026-06-29", "2026-07-13", "높음"],
    ["028", "과실비율 결과 표시", "수치 단정 금지, 범위/쟁점/유사 사례 중심 표시", "leejaegang27, hi20260204-maker", "예정", "2026-06-29", "2026-07-13", "높음"],
    ["029", "Vision 모델 조사", "이미지/영상 후보 모델과 적용 이유 정리", "ohjuheecode", "진행중", "2026-06-22", "2026-06-28", "보통"],
    ["030", "Vision 데이터 manifest", "이미지/영상 파일 출처, 사고유형, metadata 정리", "ohjuheecode", "진행중", "2026-06-22", "2026-06-28", "높음"],
    ["031", "영상/이미지 전처리", "frame 추출, key frame, 장면 요약", "ohjuheecode", "예정", "2026-06-29", "2026-07-05", "높음"],
    ["032", "Vision/DL 베이스라인", "객체/상황 분석과 confidence 반환", "ohjuheecode", "예정", "2026-06-29", "2026-07-13", "높음"],
    ["033", "Vision Agent schema", "Vision 결과를 Supervisor 병합용 evidence로 구조화", "ohjuheecode", "예정", "2026-07-06", "2026-07-13", "높음"],
    ["034", "공통 Job 모델", "분석 요청/진행/완료 상태 관리 모델 정의", "ohjuheecode", "예정", "2026-06-22", "2026-07-05", "보통"],
    ["035", "Source registry", "데이터 출처 registry와 원천 metadata 관리", "전원", "예정", "2026-06-22", "2026-06-28", "높음"],
    ["036", "증분 수집 추적", "ingestion run tracking과 실패 이력 관리", "전원", "예정", "2026-06-22", "2026-07-05", "보통"],
    ["037", "도메인 schema 분리", "fine/law/fault/vision schema 분리", "전원", "예정", "2026-06-22", "2026-07-05", "높음"],
    ["038", "API 초안", "파일 업로드, 챗봇 메시지, 분석 Job, 결과 조회 API 우선순위 정리", "hi20260204-maker", "검증필요", "2026-06-22", "2026-07-05", "높음"],
    ["039", "Cross-MVP 시나리오", "고지서, 사고 설명, 영상/이미지, 리포트 통합 시나리오", "전원", "예정", "2026-07-06", "2026-07-13", "높음"],
    ["040", "Guardrail 검증", "법률 단정, 과실비율 단정, 제출 보장 표현 금지 테스트", "전원", "예정", "2026-07-06", "2026-07-13", "높음"],
    ["041", "중간 발표 MVP", "로그인→챗봇→과태료/과실비율 결과 연결 시연", "전원", "예정", "2026-07-06", "2026-07-14", "높음"],
    ["042", "피드백 반영", "중간 발표 피드백과 RAG/ML/DL 품질 개선", "전원", "예정", "2026-07-15", "2026-07-27", "보통"],
    ["043", "최종 QA", "최종 통합 테스트, 문서, 발표 시나리오 정리", "전원", "예정", "2026-07-28", "2026-08-03", "높음"],
    ["044", "배포 준비", "staging/production 배포와 release readiness 확인", "hi20260204-maker", "예정", "2026-07-28", "2026-08-03", "높음"],
    ["045", "데이터 거버넌스", "보존/삭제/개인정보 처리 정책 문서화", "hi20260204-maker", "예정", "2026-07-15", "2026-08-03", "보통"],
    ["046", "합의금 기능", "합의금 helper/checklist/document draft scope-out 추적", "미배정", "Scope-out", "2026-06-18", "2026-06-18", "낮음"],
    ["047", "브랜치 병합", "문서 브랜치, origin/dev, feature branch 차이 정리", "hi20260204-maker", "검증필요", "2026-06-22", "2026-06-28", "높음"],
    ["048", "테스트 경로 검증", "feature 브랜치 OCR 테스트 import 경로와 패키지 경로 확인", "workzion2", "검증필요", "2026-06-22", "2026-06-28", "높음"],
    ["049", "과태료/범칙금 구분", "fine_type 필드와 과태료/범칙금 이의제기 기한 분기 검토", "workzion2", "검토필요", "2026-06-22", "2026-06-28", "높음"],
]


def build_requirements_pdf(path: Path) -> None:
    story = build_summary_story("요구사항 정의서", "PDF")
    story.append(Paragraph("요구사항 목록", SECTION))
    rows = [
        ["분류", "요구사항명", "", "", "", "추가설명", "비고"],
        ["", "대분류", "중분류", "요구사항 ID", "소분류(기능설명)", "", ""],
    ] + REQUIREMENT_ROWS
    table = make_table(
        rows,
        [16 * mm, 28 * mm, 25 * mm, 24 * mm, 80 * mm, 61 * mm, 39 * mm],
        repeat_rows=2,
        header_rows=2,
    )
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (1, 0), (4, 0)),
                ("SPAN", (0, 0), (0, 1)),
                ("SPAN", (5, 0), (5, 1)),
                ("SPAN", (6, 0), (6, 1)),
                ("ALIGN", (0, 0), (-1, 1), "CENTER"),
            ]
        )
    )
    story.append(table)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=11 * mm,
        bottomMargin=13 * mm,
        title="요구사항 정의서",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_wbs_pdf(path: Path) -> None:
    story = build_summary_story("WBS", "PDF")
    story.append(Paragraph("WBS 목록", SECTION))
    rows = [["Task ID", "주요 업무", "세부 업무", "담당자", "상태", "시작일", "마감일", "우선순위"]] + WBS_ROWS
    story.append(
        make_table(
            rows,
            [15 * mm, 39 * mm, 91 * mm, 38 * mm, 20 * mm, 24 * mm, 24 * mm, 20 * mm],
            repeat_rows=1,
            header_rows=1,
        )
    )
    doc = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=11 * mm,
        bottomMargin=13 * mm,
        title="WBS",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    req_path = OUTPUT_DIR / f"요구사항_정의서_27기_3팀_{TODAY}.pdf"
    wbs_path = OUTPUT_DIR / f"WBS_27기_3팀_{TODAY}.pdf"
    build_requirements_pdf(req_path)
    build_wbs_pdf(wbs_path)
    generated_at = datetime.now(timezone.utc).isoformat()
    print(
        json.dumps(
            {
                "generated_at": generated_at,
                "requirements_pdf": str(req_path),
                "wbs_pdf": str(wbs_path),
                "requirements_rows": len(REQUIREMENT_ROWS),
                "wbs_rows": len(WBS_ROWS),
                "github_items": len(ISSUES),
                "github_issues": len(REAL_ISSUES),
                "github_prs": len(PRS),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
