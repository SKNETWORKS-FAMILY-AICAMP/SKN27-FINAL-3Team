from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("app", "backend", "ai", "etl", "storage")
EXPLICIT_MOCK_MODULES = {
    "app/api/django_chatbot_mock_views.py",
    "backend/chatbot/mock_views.py",
    "backend/chatbot/mock_urls.py",
    "backend/config/mock_urls.py",
}
LEGACY_COMPATIBILITY_SHIMS = {
    "app/services/analysis_job_mock_service.py",
    "app/services/attachment_mock_service.py",
    "app/services/history_event_mock_service.py",
    "app/services/chatbot_mock_service.py",
}
LOCAL_DEMO_COMMANDS = {
    "backend/chatbot/management/commands/smoke_law_ground_search.py",
    "backend/chatbot/management/commands/smoke_persona_catalog.py",
    "backend/chatbot/management/commands/smoke_supervisor_llm.py",
    "backend/chatbot/management/commands/smoke_text_ml_case_search.py",
}
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


def _production_python_sources() -> list[Path]:
    sources: list[Path] = []
    for root_name in PRODUCTION_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            relative_path = path.relative_to(ROOT).as_posix()
            if _is_excluded(relative_path):
                continue
            sources.append(path)
    return sorted(sources)


def _is_excluded(relative_path: str) -> bool:
    path = Path(relative_path)
    if path.name.startswith("test") or "tests" in path.parts or "migrations" in path.parts:
        return True
    if relative_path.startswith("app/mock_runtime/"):
        return True
    return relative_path in EXPLICIT_MOCK_MODULES | LEGACY_COMPATIBILITY_SHIMS | LOCAL_DEMO_COMMANDS


def _imports_symbols_and_dynamic_paths(path: Path) -> tuple[set[str], set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imported: set[str] = set()
    symbols: set[str] = set()
    dynamic_paths: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            symbols.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            symbols.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORBIDDEN_SYMBOLS:
            symbols.add(node.value)
        elif isinstance(node, ast.Call) and _is_dynamic_import_call(node):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                dynamic_paths.add(node.args[0].value)
        elif isinstance(node, ast.Call) and _is_dynamic_symbol_lookup(node):
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                symbols.add(node.args[1].value)

    return imported, symbols, dynamic_paths


def _is_dynamic_import_call(node: ast.Call) -> bool:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id == "__import__"
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "import_module"
    )


def _is_dynamic_symbol_lookup(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Name) and node.func.id == "getattr"


def _forbidden_modules(modules: set[str]) -> set[str]:
    violations: set[str] = set()
    for module in modules:
        for forbidden in FORBIDDEN_MODULE_PARTS:
            if module == forbidden or module.startswith(f"{forbidden}.") or module.endswith(f".{forbidden}"):
                violations.add(module)
    return violations


def test_production_source_has_no_explicit_mock_import_or_dispatch_dependency() -> None:
    violations: dict[str, dict[str, list[str]]] = {}

    for path in _production_python_sources():
        imported, symbols, dynamic_paths = _imports_symbols_and_dynamic_paths(path)
        forbidden_imports = sorted(_forbidden_modules(imported | dynamic_paths))
        forbidden_symbols = sorted(FORBIDDEN_SYMBOLS & symbols)
        if forbidden_imports or forbidden_symbols:
            violations[path.relative_to(ROOT).as_posix()] = {
                "imports": forbidden_imports,
                "symbols": forbidden_symbols,
            }

    assert violations == {}, f"production source depends on Explicit Mock runtime: {violations}"
