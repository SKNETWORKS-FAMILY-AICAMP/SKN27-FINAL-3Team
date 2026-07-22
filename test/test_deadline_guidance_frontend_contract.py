from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_renders_policy_driven_deadline_guidance_above_case_results() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")

    assert "function isDeadlineGuidance(value)" in shell
    assert "const deadlineGuidance = isDeadlineGuidance(analysisResponse?.deadline_guidance)" in shell
    assert "deadlineGuidance={deadlineGuidance}" in shell
    assert "function DeadlineGuidancePanel({ guidance })" in shell
    assert "<DeadlineGuidancePanel guidance={deadlineGuidance} />" in shell
    assert "{deadlineGuidance && (" in shell
    assert 'role={guidance.status === "normal" ? "status" : "alert"}' in shell
    assert 'deadlineGuidance.status !== "normal"' not in shell
    assert '"Deadline guidance"' not in shell
    assert ".deadline-guidance-panel" in styles
    assert ".deadline-guidance-panel--normal" in styles
