"""Run all fault standard preprocessing pipelines."""

from __future__ import annotations

import argparse

from .nontypical.main import run as run_nontypical
from .official_2023.main import run as run_official_2023
from .pm_auto.main import run as run_pm_auto
from .roundabout.main import run as run_roundabout


PIPELINES = {
    "official_2023": run_official_2023,
    "nontypical": run_nontypical,
    "pm_auto": run_pm_auto,
    "roundabout": run_roundabout,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fault standard preprocessing pipelines.")
    parser.add_argument(
        "pipelines",
        nargs="*",
        choices=sorted(PIPELINES),
        help="Pipeline names to run. Defaults to all pipelines.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    selected = args.pipelines or list(PIPELINES)
    for name in selected:
        print(f"[preprocess] start: {name}")
        PIPELINES[name]()
        print(f"[preprocess] done: {name}")


if __name__ == "__main__":
    main()
