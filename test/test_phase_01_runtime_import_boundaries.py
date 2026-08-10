from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_MODULES = (
    "backend/chatbot/views.py",
    "backend/chatbot/repositories.py",
    "backend/chatbot/file_scan_service.py",
    "app/services/chat_orchestration_service.py",
    "app/services/agent_node_service.py",
    "app/services/report_query_service.py",
)

FORBIDDEN_MODULE_PARTS = {
    "app.mock_runtime",
    "analysis_job_mock_service",
    "attachment_mock_service",
    "history_event_mock_service",
    "chatbot_mock_service",
}

FORBIDDEN_SYMBOLS = {
    "execute_mock_node",
    "execute_mock_plan",
    "DL_MOCK_NODE_CODES",
}


def _imports_and_symbols(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imported: set[str] = set()
    symbols: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            symbols.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            symbols.add(node.id)

    return imported, symbols


def _forbidden_imports(imported: set[str]) -> set[str]:
    return {
        module
        for module in imported
        if any(
            module == forbidden or module.endswith(f".{forbidden}") or forbidden in module
            for forbidden in FORBIDDEN_MODULE_PARTS
        )
    }


def test_canonical_runtime_has_no_explicit_mock_import_or_dispatch_symbols() -> None:
    violations: dict[str, dict[str, list[str]]] = {}

    for relative_path in CANONICAL_MODULES:
        imported, symbols = _imports_and_symbols(ROOT / relative_path)
        forbidden_imports = sorted(_forbidden_imports(imported))
        forbidden_symbols = sorted(FORBIDDEN_SYMBOLS & symbols)
        if forbidden_imports or forbidden_symbols:
            violations[relative_path] = {
                "imports": forbidden_imports,
                "symbols": forbidden_symbols,
            }

    assert violations == {}, f"canonical runtime imports or dispatches Explicit Mock code: {violations}"
