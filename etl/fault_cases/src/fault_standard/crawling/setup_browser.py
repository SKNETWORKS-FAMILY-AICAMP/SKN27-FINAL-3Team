"""Install Playwright browser binaries for the fault cases crawler."""

from __future__ import annotations

import argparse
import subprocess
import sys

from playwright.sync_api import sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install Playwright Chromium for the fault cases crawler.")
    parser.add_argument(
        "--with-deps",
        action="store_true",
        help="Also ask Playwright to install OS-level dependencies when supported.",
    )
    return parser


def install_chromium(with_deps: bool = False) -> None:
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    if with_deps:
        command = [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"]
    print("Installing Playwright Chromium browser...")
    subprocess.run(command, check=True)
    print("Playwright Chromium browser is ready.")


def ensure_chromium_installed(with_deps: bool = False) -> None:
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" not in message and "playwright install" not in message:
            raise
        install_chromium(with_deps=with_deps)


def main() -> None:
    args = build_parser().parse_args()
    ensure_chromium_installed(with_deps=args.with_deps)


if __name__ == "__main__":
    main()
