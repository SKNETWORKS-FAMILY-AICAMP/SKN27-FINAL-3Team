#!/usr/bin/env python
"""Django command-line utility for the demo backend workspace."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    backend_dir = Path(__file__).resolve().parent
    repo_root = backend_dir.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

