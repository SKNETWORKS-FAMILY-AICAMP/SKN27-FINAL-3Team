from __future__ import annotations

import argparse
import sys

from .general.run import main as run_general
from .seed.run import main as run_seed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run precedent collection.")
    parser.add_argument(
        "--collection-mode", choices=("seed", "general"), required=True
    )
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]
    return run_seed() if args.collection_mode == "seed" else run_general()


if __name__ == "__main__":
    raise SystemExit(main())
