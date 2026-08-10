from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "app" / "web"
BUILD_ROOT = FRONTEND_ROOT / "dist"


def test_production_frontend_source_does_not_reference_explicit_mock_routes() -> None:
    production_sources = [
        path
        for pattern in ("*.js", "*.jsx", "*.ts", "*.tsx")
        for path in FRONTEND_ROOT.rglob(pattern)
        if "node_modules" not in path.parts
        and "dist" not in path.parts
        and not any(part in {"__tests__", "tests"} for part in path.parts)
        and ".test." not in path.name
        and ".spec." not in path.name
    ]
    build_outputs = [
        path
        for pattern in ("*.js", "*.css", "*.html")
        for path in BUILD_ROOT.rglob(pattern)
    ] if BUILD_ROOT.exists() else []

    violations = [
        str(path.relative_to(ROOT))
        for path in production_sources + build_outputs
        if "/api/mock/" in path.read_text(encoding="utf-8")
    ]

    assert violations == [], f"production frontend source or build output references Explicit Mock routes: {violations}"
