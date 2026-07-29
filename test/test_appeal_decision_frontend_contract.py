from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "app" / "web" / "FrontendAppShell.jsx"
STYLES = ROOT / "app" / "web" / "styles.css"


def test_frontend_reads_and_prioritizes_appeal_decision_result() -> None:
    shell = SHELL.read_text(encoding="utf-8")

    assert "buildAppealDecisionUi" in shell
    assert "structured_results?.appeal_decision_flow" in shell
    assert "function AppealDecisionPanel(" in shell
    assert "<AppealDecisionPanel" in shell
    assert shell.index("<AppealDecisionPanel") < shell.index("<SafetyGuidancePanel")


def test_risk_acknowledgement_blocks_document_download() -> None:
    shell = SHELL.read_text(encoding="utf-8")

    action_start = shell.index("async function runCurrentReportAction")
    action_end = shell.index("async function streamAssistantMessage", action_start)
    action = shell[action_start:action_end]

    assert "appealRiskAcknowledged" in action
    assert "신원 노출 위험을 확인한 뒤" in action
    assert "requiresAcknowledgement" in action

    assert "function openReportingWorkspace()" in shell
    assert shell.count("onOpenReporting={openReportingWorkspace}") == 1
    assert shell.count("onOpenReport={openReportingWorkspace}") == 1

def test_domain_result_is_not_rendered_as_green_execution_success() -> None:
    shell = SHELL.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "analysisCardTagClass(card)" in shell
    assert "appeal-decision-panel--risky" in styles
    assert "appeal-decision-panel--failed" in styles
    assert "role={ui.risk.status === \"safe\" ? \"status\" : \"alert\"}" in shell
