"""Generate or verify the frontend Case route catalog."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts.frontend_case_routes import (  # noqa: E402
    render_frontend_case_routes_json,
)


DEFAULT_OUTPUT = ROOT / "app" / "web" / "caseApiRoutes.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Generated frontend Case route JSON path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the generated file is missing or out of date",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    expected = render_frontend_case_routes_json()

    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            print(
                f"Frontend Case route catalog is out of date: {output}. "
                "Run scripts/generate_frontend_case_routes.py.",
                file=sys.stderr,
            )
            return 1
        print(f"Frontend Case route catalog is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Generated frontend Case route catalog: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
