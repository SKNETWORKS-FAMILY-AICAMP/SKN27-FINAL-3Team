from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_DOCS = [
    ROOT / "docs" / "deployment-readiness-review-2026-06-22.md",
    ROOT / "docs" / "ops" / "release-checklist.md",
    ROOT / "docs" / "ops" / "rollback-plan.md",
    ROOT / "docs" / "ops" / "incident-response.md",
    ROOT / "docs" / "ops" / "secret-management.md",
    ROOT / "docs" / "ops" / "backup-and-recovery.md",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_operations_documents_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_DOCS if not path.exists()]
    assert missing == []


def test_deployment_readiness_review_has_required_sections():
    content = read_text(ROOT / "docs" / "deployment-readiness-review-2026-06-22.md")
    required_sections = [
        "## 1. 프로젝트 요약",
        "## 2. 최종 판정",
        "## 4. 즉시 배포 차단 항목",
        "## 6. 영역별 검토 결과",
        "## 8. 최종 추천",
        "## 10. 최종 배포 승인 체크리스트",
    ]
    missing = [section for section in required_sections if section not in content]
    assert missing == []


def test_release_readiness_recommends_standard_operations():
    content = read_text(ROOT / "docs" / "deployment-readiness-review-2026-06-22.md")
    assert "**배포 불가**" in content
    assert "1순위: 표준 운영형" in content
    assert "최소 운영형" in content
    assert "고신뢰 운영형" in content


def test_static_mvp_html_is_utf8_korean_service_screen():
    html = read_text(ROOT / "app" / "screen-design-mvp-flow.html")
    assert '<meta charset="UTF-8">' in html
    assert 'lang="ko"' in html
    assert "교통분쟁 AI" in html


def test_secret_management_document_defines_rotation_and_logging_rules():
    content = read_text(ROOT / "docs" / "ops" / "secret-management.md")
    assert "## 2. 로그 원칙" in content
    assert "## 3. 교체 절차" in content
    assert "Authorization" in content
    assert "Cookie" in content


def test_repository_text_files_do_not_contain_obvious_secret_assignments():
    scanned_suffixes = {".md", ".py", ".html", ".txt", ".yml", ".yaml", ".json"}
    excluded_parts = {".git", ".venv", ".pytest_cache", ".worktrees", "assets"}
    secret_pattern = re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\n]{8,}['\"]"
    )

    matches = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in scanned_suffixes:
            continue
        if any(part in excluded_parts for part in path.parts):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for match in secret_pattern.finditer(content):
            matches.append(f"{path.relative_to(ROOT)}:{match.group(1)}")

    assert matches == []
