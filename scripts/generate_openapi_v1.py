"""Generate or verify the OpenAPI v1 shadow contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts.openapi_v1 import render_openapi_yaml  # noqa: E402


DEFAULT_OUTPUT = ROOT / "docs" / "api" / "openapi-v1.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Generated OpenAPI v1 YAML path",
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
    expected = render_openapi_yaml()

    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            print(
                f"OpenAPI v1 is out of date: {output}. "
                "Run scripts/generate_openapi_v1.py.",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI v1 is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Generated OpenAPI v1: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
