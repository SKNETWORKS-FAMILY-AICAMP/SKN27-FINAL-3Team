"""ASGI config for the demo backend workspace."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from django.core.asgi import get_asgi_application

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.env_loader import load_django_env_file

load_django_env_file(REPO_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()

