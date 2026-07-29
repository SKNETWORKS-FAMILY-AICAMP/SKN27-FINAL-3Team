from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _shell() -> str:
    return (ROOT / "app/web/FrontendAppShell.jsx").read_text(encoding="utf-8")


def _styles() -> str:
    return (ROOT / "app/web/styles.css").read_text(encoding="utf-8")


def test_deadline_summary_uses_valid_user_confirmed_received_date() -> None:
    shell = _shell()

    assert "const FINE_NOTICE_DEADLINE_DAYS = 60;" in shell
    assert "function parseISODateOnly(value)" in shell
    assert 'item?.notice_received_source !== "user"' in shell
    assert "const receivedAt = parseISODateOnly(raw);" in shell


def test_assistant_stream_stops_updating_after_shell_unmounts() -> None:
    shell = _shell()

    assert "const isMountedRef = useRef(false);" in shell
    assert "isMountedRef.current = true;" in shell
    assert "isMountedRef.current = false;" in shell
    assert shell.count("if (!isMountedRef.current) return;") >= 2


def test_result_screen_separates_confirmed_facts_from_user_claims() -> None:
    shell = _shell()

    assert "userClaims={analysisResponse?.user_claims || []}" in shell
    assert 'aria-label="사실과 사용자 진술 구분"' in shell
    assert "현재 확인된 사실" in shell
    assert "사용자 진술 · 추가 확인 필요" in shell


def test_follow_up_and_legal_sources_explain_why_and_when() -> None:
    shell = _shell()

    assert "item.reason && <small>{item.reason}</small>" in shell
    assert "Array.isArray(structuredResult.law_provisions)" in shell
    assert "item.effective_date || item.enforce_date" in shell
    assert "qualitySummary?.freshness?.retrieved_at" in shell
    assert "qualitySummary?.freshness?.limitation" in shell


def test_result_screen_always_shows_minimum_quality_summary_and_conditionally_expands_limitations() -> None:
    shell = _shell()

    assert "qualitySummary?.freshness?.effective_at" in shell
    assert "qualitySummary?.freshness?.retrieved_at" in shell
    assert "qualitySummary?.limitation_count" in shell
    assert "qualitySummary?.retrieval?.backend_label" in shell
    assert "qualitySummary?.retrieval?.used_fallback" in shell
    assert '"stale"' in shell
    assert '"fallback"' in shell
    assert "shouldShowQualityDetails" in shell


def test_quick_question_groups_render_without_undefined_legacy_reference() -> None:
    shell = _shell()

    assert "const quickQuestionGroups = [" in shell
    assert "{quickQuestionGroups.map((group) => (" in shell
    assert 'className="quick-examples"' in shell
    assert "{quickQuestions.map((item) => (" not in shell


def test_empty_chat_keeps_the_primary_composer_above_the_desktop_fold() -> None:
    styles = _styles()

    assert "min-height: clamp(220px, 28vh, 300px);" in styles
    assert ".chat-empty-state {\n  min-height: 420px;" not in styles


def test_chat_entry_reuses_the_existing_session_and_guide_has_one_cta() -> None:
    shell = _shell()

    assert shell.count('onOpenChat={() => ensureGuestSession("chatbot")}') >= 3

    guide_start = shell.index("function GuideScreen")
    guide_end = shell.index("function EntryScreenWheelLegacy")
    guide = shell[guide_start:guide_end]
    assert guide.count("onClick={onOpenChat}") == 1
    assert "onClick={onGuestStart}" not in guide


def test_consultation_intake_renders_only_the_selected_case_type_fields() -> None:
    shell = _shell()

    assert "ACCIDENT_TYPE_OPTIONS" in shell
    assert "FINE_NOTICE_FIELDS" in shell
    assert 'selectedType === "fine_notice"' in shell
    assert 'selectedType === "fault_ratio"' in shell
    assert "{isFineNotice && (" in shell
    assert "{isFaultRatio && (" in shell


def test_user_message_and_primary_ctas_have_final_light_theme_overrides() -> None:
    styles = _styles()

    assert ".message.user .bubble p {\n  color: #111844;" in styles
    assert ".service-closing .button.primary,\n.guide-screen__actions .button.primary" in styles
