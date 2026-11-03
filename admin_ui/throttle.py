"""
Login rate limiting.

Without this the sign-in form accepts unlimited guesses, and an Admin account
is full read/write over every ARK plus the ability to hand out roles. A
deliberately small piece of code rather than a dependency: it counts failures
per (username, client address) in the cache and refuses further attempts for a
while.

The counter lives in the cache, so it is only shared between gunicorn workers
when the cache is (Redis or Valkey in production). With the local-memory fallback a
lockout applies per worker, which still slows an attacker by the worker count
but is not a real limit — production must configure ``REDIS_URL``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

#: Cache key prefix for failed-attempt counters.
PREFIX = "login-failures"


def _limit() -> int:
    return getattr(settings, "LOGIN_MAX_ATTEMPTS", 5)


def _window() -> int:
    return getattr(settings, "LOGIN_LOCKOUT_SECONDS", 15 * 60)


def client_address(request) -> str:
    """
    The address to rate-limit against.

    Behind Apache the peer is always the proxy, so the forwarded address is used
    when the deployment says it is trustworthy. Never trust it otherwise — an
    attacker would just vary the header.
    """
    if getattr(settings, "TRUST_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _key(username: str, address: str) -> str:
    return f"{PREFIX}:{(username or '').strip().lower()}:{address}"


def is_locked_out(request, username: str) -> bool:
    """True when this username and address have failed too often lately."""
    return cache.get(_key(username, client_address(request)), 0) >= _limit()


def record_failure(request, username: str) -> int:
    """Count one failed attempt; returns the running total."""
    key = _key(username, client_address(request))
    try:
        total = cache.incr(key)
    except ValueError:
        # No counter yet: start one. add() rather than set() so two concurrent
        # failures cannot each reset the other to 1.
        cache.add(key, 1, _window())
        total = cache.get(key, 1)
    return total


def clear(request, username: str) -> None:
    """Forget past failures after a successful sign-in."""
    cache.delete(_key(username, client_address(request)))
