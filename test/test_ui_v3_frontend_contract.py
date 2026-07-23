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
