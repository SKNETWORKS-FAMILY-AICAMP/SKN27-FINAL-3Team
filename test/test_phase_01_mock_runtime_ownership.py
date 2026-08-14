from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MODULES = (
    "app/mock_runtime/analysis_jobs.py",
    "app/mock_runtime/attachments.py",
    "app/mock_runtime/history.py",
    "app/mock_runtime/agent_execution.py",
    "app/mock_runtime/chat.py",
)
LEGACY_SHIMS = (
    "app/services/analysis_job_mock_service.py",
    "app/services/attachment_mock_service.py",
    "app/services/history_event_mock_service.py",
    "app/services/chatbot_mock_service.py",
)
LEGACY_MODULE_PARTS = {
    "analysis_job_mock_service",
    "attachment_mock_service",
    "history_event_mock_service",
    "chatbot_mock_service",
}


def _tree(relative_path: str) -> ast.AST:
    return ast.parse((ROOT / relative_path).read_text(encoding="utf-8-sig"), relative_path)


def _legacy_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            imports.update(alias.name.rsplit(".", 1)[-1] for alias in node.names)
    return imports & LEGACY_MODULE_PARTS


def test_explicit_mock_runtime_owns_its_implementation_without_legacy_imports() -> None:
    violations = {
        relative_path: sorted(_legacy_imports(_tree(relative_path)))
        for relative_path in RUNTIME_MODULES
        if (ROOT / relative_path).exists() and _legacy_imports(_tree(relative_path))
    }

    assert violations == {}, f"Explicit Mock runtime imports legacy implementations: {violations}"


def test_legacy_mock_services_are_thin_reexport_shims() -> None:
    violations: dict[str, list[str]] = {}
    for relative_path in LEGACY_SHIMS:
        tree = _tree(relative_path)
        implementation_nodes = [
            type(node).__name__
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        runtime_imports = [
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("app.mock_runtime")
        ]
        if implementation_nodes or not runtime_imports:
            violations[relative_path] = implementation_nodes or ["missing_app.mock_runtime_reexport"]

    assert violations == {}, f"legacy Mock services are not thin compatibility shims: {violations}"
