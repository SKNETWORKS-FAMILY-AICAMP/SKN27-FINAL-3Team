from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _shell() -> str:
    return (ROOT / "app/web/FrontendAppShell.jsx").read_text(encoding="utf-8")


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
    assert "retrieval.retrieved_at" in shell
