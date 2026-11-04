"""Liveness and readiness, for Apache, Docker and systemd to probe."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

from core import counters

logger = logging.getLogger(__name__)


def healthz(request):
    """
    Report whether this instance can actually serve, not merely that it started.

    Checks the database, the Django cache and the redirect-hit buffer. The
    endpoint is public, so a failure is reported as a bare "error" and the
    detail (which can name hosts) goes to the log instead.

    ``counters_flushed_ago`` is informational: seconds since the last flush of
    buffered redirect counts, or null if unknown. It never makes the check fail,
    because a stalled scheduler is not a reason to take the resolver out of
    service, but a number far above RESOLUTION_FLUSH_SECONDS means the scheduler
    is not running.
    """
    checks: dict[str, str] = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - the point is to report it
        logger.exception("healthz: database check failed")
        checks["database"] = "error"

    try:
        cache.set("healthz", 1, 10)
        checks["cache"] = "ok" if cache.get("healthz") == 1 else "error"
    except Exception:  # noqa: BLE001
        logger.exception("healthz: cache check failed")
        checks["cache"] = "error"

    try:
        checks["counters"] = "ok" if counters.ping() else "error"
    except Exception:  # noqa: BLE001
        logger.exception("healthz: counter buffer check failed")
        checks["counters"] = "error"

    healthy = all(state == "ok" for state in checks.values())
    return JsonResponse(
        {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "counters_flushed_ago": counters.last_flush_age(),
        },
        status=200 if healthy else 503,
    )
