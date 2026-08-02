from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_renders_scope_and_partial_result_safe_guidance() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "web" / "styles.css").read_text(encoding="utf-8")

    assert "function SafetyGuidancePanel({ guidance })" in shell
    assert "const serviceScope = analysisResponse?.service_scope || null;" in shell
    assert "const responseNextActions = stringList(analysisResponse?.next_actions);" in shell
    assert "function AssistantLimitationsDisclosure({ guidance })" in shell
    assert "<AssistantLimitationsDisclosure guidance={chatSafetyGuidance} />" in shell
    assert "<summary>한계·주의사항</summary>" in shell
    assert "<SafetyGuidancePanel guidance={resultSafetyGuidance} />" in shell
    assert "function ServiceInformationNotice()" in shell
    assert ".safety-guidance-panel" in styles
    assert ".service-information-notice" in styles


def test_frontend_does_not_expose_internal_next_action_identifiers() -> None:
    shell = (ROOT / "app" / "web" / "FrontendAppShell.jsx").read_text(encoding="utf-8")

    assert "const USER_FACING_NEXT_ACTION_LABELS = {" in shell
    assert 'answer_pending_question: "추가 질문에 답변해 주세요.",' in shell
    assert 'review_verified_results: "확인된 결과와 근거를 검토해 주세요.",' in shell
    assert "function userFacingNextActions(value)" in shell
    assert "return /^[a-z][a-z0-9_]*$/i.test(action) ? [] : [action];" in shell
    assert "const safeNextActions = userFacingNextActions(nextActions);" in shell
    assert "nextActions: safeNextActions," in shell
    assert "nextActions: userFacingNextActions(serviceScope.next_actions)," in shell
    assert "limitations: userFacingLimitations(serviceScope.limitations)," in shell
