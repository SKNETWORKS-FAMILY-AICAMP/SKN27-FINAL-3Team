from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_report_workspace_is_reachable_from_the_global_rail_and_explains_empty_states() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'id: "reporting"' in shell
    assert 'label: "리포트"' in shell
    assert 'import { deriveReportWorkbenchState } from "./reportWorkbenchState.js";' in shell
    assert "function ReportWorkbenchEmptyState" in shell
    assert "<ReportWorkbenchEmptyState" in shell
    assert "canGenerateReport={hasReportGenerationNode(supervisorState)}" in shell
    assert "async function openReportingWorkspace" in shell
    assert "loadReports({ hydrateLatest: true })" in shell
    assert "setIsReportWorkspaceLoading" in shell
    assert ".report-workbench-empty" in styles


def test_google_login_keeps_authenticated_state_when_post_login_history_refresh_fails() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    start = shell.index("async function saveConversationWithGoogle")
    end = shell.index("async function saveConversationAfterLogin", start)
    save_flow = shell[start:end]

    assert "Google 로그인은 완료됐지만" in save_flow
    assert "내 사건·이력 갱신" in save_flow
    assert "return loginState;" in save_flow
    assert "setStatusMessage(statusMessage);\n    try {\n      let loginState;" in save_flow
