from __future__ import annotations

from collections.abc import Callable

from django.core.cache import cache
from django.db import connections


Probe = Callable[[], None]


def database_probe() -> None:
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def cache_probe() -> None:
    key = "runtime-readiness"
    cache.set(key, "ready", timeout=5)
    if cache.get(key) != "ready":
        raise ConnectionError("cache readiness value was not returned")
    cache.delete(key)


def build_runtime_health(
    *,
    database_probe: Probe = database_probe,
    cache_probe: Probe = cache_probe,
) -> dict[str, object]:
    checks: dict[str, str] = {}
    for name, probe in (("database", database_probe), ("cache", cache_probe)):
        try:
            probe()
        except Exception:
            checks[name] = "unavailable"
        else:
            checks[name] = "ready"

    return {
        "status": "ready" if all(value == "ready" for value in checks.values()) else "not_ready",
        "checks": checks,
    }
