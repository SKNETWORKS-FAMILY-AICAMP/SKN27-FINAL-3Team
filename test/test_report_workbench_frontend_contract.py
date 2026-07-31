from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_report_workspace_is_reachable_from_the_global_rail_and_explains_empty_states() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'id: "reporting"' in shell
    assert 'label: "리포트 작업대"' in shell
    assert 'import { deriveReportWorkbenchState } from "./reportWorkbenchState.js";' in shell
    assert "function ReportWorkbenchEmptyState" in shell
    assert "<ReportWorkbenchEmptyState" in shell
    assert "canGenerateReport={hasReportGenerationNode(supervisorState)}" in shell
    assert ".report-workbench-empty" in styles
