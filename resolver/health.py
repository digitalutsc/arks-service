"""Liveness and readiness, for Apache and systemd to probe."""

from __future__ import annotations

from django.core.cache import caches
from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """
    Report whether this instance can actually serve, not merely that it started.

    Checks the database and the cache, because a resolver that cannot reach
    either returns 404s and loses counts while looking perfectly alive.
    """
    checks: dict[str, str] = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - the point is to report it
        checks["database"] = f"error: {exc}"[:120]

    try:
        caches["counters"].set("healthz", 1, 10)
        checks["counters"] = "ok" if caches["counters"].get("healthz") == 1 else "error: no value"
    except Exception as exc:  # noqa: BLE001
        checks["counters"] = f"error: {exc}"[:120]

    healthy = all(state == "ok" for state in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
