from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "app" / "web"


def test_production_frontend_source_does_not_reference_explicit_mock_routes() -> None:
    production_sources = [
        path
        for pattern in ("*.js", "*.jsx")
        for path in FRONTEND_ROOT.rglob(pattern)
        if "node_modules" not in path.parts and "dist" not in path.parts and not path.name.endswith(".test.js")
    ]

    violations = [
        str(path.relative_to(ROOT))
        for path in production_sources
        if "/api/mock/" in path.read_text(encoding="utf-8")
    ]

    assert violations == [], f"production frontend references Explicit Mock routes: {violations}"
