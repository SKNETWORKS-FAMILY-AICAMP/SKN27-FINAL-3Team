from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL_PATH = ROOT / "app" / "web" / "FrontendAppShell.jsx"


def _shell() -> str:
    return SHELL_PATH.read_text(encoding="utf-8")


def _chat_screen_source() -> str:
    shell = _shell()
    start = shell.index("function ChatScreenV2(")
    end = shell.index("\nfunction ", start + len("function ChatScreenV2("))
    return shell[start:end]


def test_chat_attachment_menu_has_explicit_supported_options() -> None:
    shell = _shell()

    assert "const CHAT_ATTACHMENT_OPTIONS = [" in shell
    assert 'purpose: "fine_notice"' in shell
    assert 'purpose: "accident_scene"' in shell
    assert 'purpose: "blackbox_video"' in shell
    assert "application/pdf" in shell
    assert "video/mp4" in shell


def test_ui_v3_confirms_server_classification_by_attachment_id_only() -> None:
    shell = _shell()

    assert "AttachmentClassificationConfirmationCard" in shell
    assert "attachment_classification_confirmation" in shell
    assert "attachmentClassificationResult?.attachment_id" in shell
    assert "attachmentClassificationResult.classification" not in shell


def test_chat_file_selection_uses_parent_validation_boundary() -> None:
    chat_screen = _chat_screen_source()

    assert (
        'onChange={(event) => onAttachmentFile(event.target.files?.[0] || null)}'
        in chat_screen
    )
    assert "setSelectedUploadFile(" not in chat_screen


def test_attachment_workflow_is_derived_only_from_server_response() -> None:
    shell = _shell()

    assert 'from "./attachmentWorkflowUi.js"' in shell
    assert "buildAttachmentWorkflowUi(analysisResponse?.attachment_workflows)" in shell
    assert "attachmentWorkflowUi={attachmentWorkflowUi}" in shell
    assert "AttachmentWorkflowPanel" in shell


def test_attachment_workflow_state_makes_confirmation_cards_mutually_exclusive() -> None:
    chat_screen = _chat_screen_source()

    assert (
        'activeAttachmentWorkflow?.state === "ocr_needs_confirmation"' in chat_screen
    )
    assert (
        'activeAttachmentWorkflow?.state === "classified_waiting_confirmation"'
        in chat_screen
    )
    assert "attachmentWorkflowUi?.[0] || null" in chat_screen
    assert "activeAttachmentWorkflow && (" in chat_screen
