"""Small opt-in dotenv loader for local Django commands.

Production should inject environment variables through the deployment platform
or secret store. This helper only makes local `manage.py` checks less brittle.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def load_django_env_file(
    repo_root: Path,
    *,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    raw_env_file = env_file or os.environ.get("DJANGO_ENV_FILE")
    should_load = bool(raw_env_file) or _truthy(os.environ.get("DJANGO_LOAD_DOTENV"))
    if not should_load:
        return {"loaded": False, "reason": "disabled"}

    path = Path(raw_env_file) if raw_env_file else repo_root / ".env"
    if not path.is_absolute():
        path = repo_root / path
    if not path.exists():
        return {"loaded": False, "reason": "file_not_found", "path": str(path)}

    loaded_keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded_keys.append(key)

    return {"loaded": True, "path": str(path), "loaded_keys": loaded_keys}


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped.removeprefix("export ").strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None
    return key, _strip_quotes(value.strip())


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
