from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_service_design_documents_docx_only_downloads_and_guest_header_boundary() -> None:
    spec = read_text("docs/service-design-spec-2026-07-21.md")

    for phrase in ("일반 분석 리포트", "교통사고 문서", "과태료 이의신청서", "DOCX 전용"):
        assert phrase in spec
    for obsolete_phrase in ("화면 PDF 저장", "로그인 후 이의신청서 PDF"):
        assert obsolete_phrase not in spec
    for phrase in (
        "X-Guest-Credential",
        "X-Guest-Id",
        "단독으로는 권한 증명이 아니다",
        "request body",
        "query string",
        "auth_context",
        "App JWT",
    ):
        assert phrase in spec


def test_dev_local_preserves_explicit_database_engine_and_gate_builds_frontend() -> None:
    launcher = read_text("dev-local.ps1")
    workflow = read_text(".github/workflows/production-gate.yml")

    assert "if ([string]::IsNullOrWhiteSpace($env:DJANGO_DATABASE_ENGINE))" in launcher
    assert '$env:DJANGO_DATABASE_ENGINE = "sqlite"' in launcher
    assert "`$env:DJANGO_DATABASE_ENGINE='sqlite';" not in launcher

    frontend_build = workflow[workflow.index("name: Frontend production build") :]
    assert "working-directory: app/web" in frontend_build
    assert "npm ci" in frontend_build
    assert "npm run build" in frontend_build
