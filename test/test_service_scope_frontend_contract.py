from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_renders_scope_and_partial_result_safe_guidance() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")

    assert "function SafetyGuidancePanel({ guidance })" in shell
    assert "const serviceScope = analysisResponse?.service_scope || null;" in shell
    assert "const responseNextActions = stringList(analysisResponse?.next_actions);" in shell
    assert "<SafetyGuidancePanel guidance={chatSafetyGuidance} />" in shell
    assert "<SafetyGuidancePanel guidance={resultSafetyGuidance} />" in shell
    assert "function ServiceInformationNotice()" in shell
    assert ".safety-guidance-panel" in styles
    assert ".service-information-notice" in styles
